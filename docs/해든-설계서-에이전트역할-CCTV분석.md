# 설계서: 에이전트 역할 · CCTV 분석 (해든 담당 부분)

기준: main (2026-10-12). README 12장 산출물 "설계서 중 에이전트 역할·CCTV 분석 부분". 지혜 님 설계서에 이 내용을 그대로 옮겨 쓰면 됩니다.
모든 수치는 시연용 예시 규칙이며 의학적 기준이 아닙니다.

## 1. 원칙

- **코드가 판정하고, LLM은 설명만 씁니다.** 위험도, 원인, 조치 목록은 규칙표(`backend/src/rules/risk.py`)가 정합니다. LLM은 조치를 더하거나 빼지 못하고, 근거 문장과 안내문만 씁니다.
- **LLM이 실패해도 판정은 나옵니다.** 문장 LLM이 실패하면 고정 템플릿 문구로 대신합니다 (DR-LLM-01).
- **CCTV는 보이는 사실만 묻습니다.** 비전 LLM은 사실 4개만 답하고, 자세와 낙상 의심은 코드 표가 정합니다.
- **119는 보호자 승인 후 실행합니다.** 예외는 바이탈 매우 위험(VITAL_SEVERE)일 때 한 가지뿐이고, 보호자가 응답하지 않아도 119에 자동 연결하지 않습니다.

## 2. 에이전트 역할

| 에이전트 | 입력 | 하는 일 | 출력 | 실패하면 | 코드 |
| --- | --- | --- | --- | --- | --- |
| Profile Agent | 테스트 프로필 (SQLite) | 75세 이상·독거·지병 유무·거동 불편 중 3개 이상이면 상, 2개면 중, 그 밖은 하 | `vulnerability` | 프로필 없음 → "상" | `backend/src/agents/profile.py` |
| Emergency Agent | CareStatusResult | ① 규칙표로 위험도·원인 판정 ② 원인별 조치 선택 ③ 바이탈 원인 + 경고 이상이면 병원 조회 ④ 근거·조치 설명 문장 LLM | EmergencyResult (`risk_level`, `reason`, `reason_codes`, `actions`, `hospital`) | 문장 LLM 실패 → 템플릿. 병원 조회 실패 → 병원 없이 진행 | `backend/src/agents/emergency.py`, `backend/src/rules/risk.py` |
| Summary Agent | EmergencyResult, 승인/거절, 실행 결과(`executed`) | 보호자용 결과 보고, 어르신용 짧은 안내 LLM | `guardian_message`, `elder_message` | 템플릿. 거절이면 어르신용은 빈 문자열 | `backend/src/agents/summary.py` |
| CCTV 분석 (IoT Agent 도구) | 캡처 이미지 경로 (png) | 비전 LLM에 사실 4개 질문 → 코드 표로 자세·낙상 판정 → 결과 계약 검사 | `person_visible`, `posture`, `fall_suspected`, `description`, `confidence`, `status` | "영상 판단 불가" (`status: "failed"`) → 바이탈 기준 판정 | `mcp_server/src/vision/analyzer.py`, `prompt.py` |

### 위험도 판정 순서 (Emergency Agent 안)

1. 바이탈 4항목(심박, 수축기 혈압, 체온, 산소포화도)을 NEWS2 방식으로 0~3점 매깁니다.
2. 실내 온도를 봅니다. 28℃ 초과·20℃ 미만은 이상(주의), 31℃ 초과·18℃ 미만은 극한(경고)입니다.
3. 원인 코드를 모으고, 4개 축(낙상, 심혈관, 호흡, 환경)별 단계 중 가장 높은 것이 위험도입니다.
4. 취약도 "상"이면 한 단계 올립니다. 정상은 그대로 둡니다.
5. 정상이면 "이상 없음"으로 끝냅니다 (Handoff Guard).
6. 원인별 조치를 고릅니다. 기기 제어와 119는 승인 필요, 보호자 알림은 승인 불필요입니다.

### 문장 LLM 검증

| 검사 | Emergency | Summary |
| --- | --- | --- |
| JSON 형식·필수 키 | `reason`, `action_texts` | `guardian_message`, `elder_message` |
| 조치 설명 개수 = 조치 개수 (설명 하나 30자) | ✅ | — |
| 입력에 없는 수치, 진단·약·확진 표현 금지 | ✅ | ✅ |
| 실패한 조치를 "완료"로 쓰지 않음 | — | ✅ |
| 길이 | `reason` 60자 | 보호자 120자, 어르신 60자 |

검사에 걸리면 한 번 교정 재요청하고, 그래도 안 되면 템플릿을 씁니다 (1회 호출 제한 10초, 최대 2회).

## 3. CCTV 분석

### 흐름

1. backend IoT Agent가 MCP `analyze_cctv(image_path)`를 부릅니다.
2. 분석기가 이미지를 비전 LLM(gpt-4.1-mini)에 넣고 사실 4개를 받습니다: `person_visible`, `body_support`(floor/furniture/unclear/none), `body_shape`(upright/seated/horizontal/unclear/none), `image_clear`, 그리고 보호자용 `description`.
3. 코드 표 `FACT_RULES`가 자세(`posture`)와 낙상 의심(`fall_suspected`)을 정합니다. 예: 누움 + 바닥 → fallen, 낙상 의심. 누움 + 침대 → lying, 정상.
4. 사진이 흐리거나 답에 unclear가 있으면 신뢰도 0.4, 아니면 0.9입니다.
5. 분석 성공(`status: "analyzed"`)이면 4항목(`person_visible`, `posture`, `fall_suspected`, `description`)이 모두 있어야 합니다. 어기면 재시도하고, 끝내 실패하면 "영상 판단 불가"입니다.

### 판정에 쓰는 법

- fallen + 신뢰도 높음 → 낙상 축 **위급** (FALL_DETECTED).
- 흐린 사진, 자세와 플래그가 어긋남, 바닥에 주저앉음 → 낙상 의심 **경고** (FALL_SUSPECTED). 낙상 의심에 바이탈 위험 항목이 겹치면 위급.
- 낙상 의심 이상이면 보호자 알림에 캡처 사진과 한 문장 설명을 붙입니다.
- "영상 판단 불가"면 바이탈만으로 판정하고, 보호자에게 원본 캡처로 직접 확인을 요청합니다 (DR-VISION-01).

### 재시도와 제한 시간

CCTV 분석은 두 단계로 나뉘며, 각 단계의 시간 제한을 따로 둡니다.

| 단계 | 시도 횟수 (최초 포함) | 1회 호출 제한 시간 | 코드 위치 |
| --- | --- | --- | --- |
| 백엔드 → MCP `analyze_cctv` 호출 | 2회 | 60초 | `backend/src/agents/iot.py` `VISION_POLICY` |
| 분석 1번 안의 비전 LLM 호출 | 3회 (첫 호출 + 교정 재요청 2회) | 15초 | `mcp_server/src/vision/analyzer.py` `TIMEOUT_SECONDS`, `RETRIES` |

- 비전 LLM 3회는 재시도 사이 대기가 없어 길어야 약 45초이고, 백엔드 제한(60초)보다 먼저 끝납니다.
- LLM 3회가 모두 실패하면 분석기는 "판단 불가"(`status: "failed"`)를 정상 결과로 돌려주고, 백엔드는 다시 시도하지 않습니다.
- 백엔드 2번째 시도는 MCP 연결 오류, 60초 초과, CCTV 계약 위반일 때만 일어납니다.
- 이 값들은 보호자 승인 대기와 관계없는 내부 값입니다.

## 4. 시험 결과

- 자동 테스트: backend 471개, mcp_server 140개 통과 (main, 2026-10-12).
- 실제 LLM: 가짜 CCTV 이미지 8장 8/8 정답 (2026-10-08, gpt-4.1-mini, `notes/cctv_check_result.md`). 시연 png 4장 실제 점검은 `python notes/cctv_check.py --repeat 3`으로 발표 전 확인.
