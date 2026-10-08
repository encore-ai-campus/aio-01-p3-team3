# 해든 LLM 파트 계획서 (새 README 반영, 10/8)

기준: 팀 README "바이탈·IoT·긴급대응 멀티 에이전트 기반 노인 케어 시스템"(10/8)과 해든 결정(월별 실내 기준, NEWS2 바이탈, 코드가 판정하고 LLM은 전달만).
모든 수치는 **시연용 예시 규칙이며 의학적 기준이 아님**. 출처(NEWS2 RCP 2017, 질병관리청, ASHRAE 55, WHO)는 발표 전 원문 확인.

## 담당 범위 (해든 확정 10/8, 해든이 직접 구현)

**구조도에서 맡는 에이전트 4개**

| 에이전트 | 입력 | 하는 일 | 출력 | 실패 시 |
|---|---|---|---|---|
| Profile Agent | 테스트 프로필 (SQLite) | 취약도 함수로 상/중/하 계산 | `vulnerability` | 프로필 없음 → "상" |
| Emergency Agent | CareStatusResult | ① 규칙표로 위험도 판정(코드) ② 원인별 조치 종류 선택(코드) ③ 위급·경고면 `find_hospital` ④ 조치안 문장 LLM 호출 | EmergencyResult (`risk_level`, `reason`, `actions`) | LLM 실패 → 템플릿. 판정은 코드라 LLM이 실패해도 위험도는 나옴 |
| Summary Agent | 승인/거절, 실행 결과(executed), EmergencyResult | 보호자용·어르신용 안내문 LLM 호출 | `guardian_message`, `elder_message` | 템플릿 |
| CCTV 분석 | 캡처 이미지 경로 | 이미지를 비전 LLM에 넣고 결과 JSON 검증 | `person_visible`, `posture`, `fall_suspected`, `description` | 2회 재시도 → "영상 판단 불가" |

**개인 산출물 4개**: ① 취약도 함수(3장) ② 위험도 규칙표(1~3장) ③ Emergency·Summary 프롬프트(4장) ④ 템플릿 문구(4장)

**상옥 님과 맞추는 부분**: Emergency Agent의 규칙표 연결, 조치안 프롬프트, LLM 호출. LLM 호출 함수는 해든이 만들고, 상옥 님 AutoHealing이 그 함수를 감싸 재요청·템플릿 대체·로그를 맡는 구조를 추천(6장).

**해든 담당이 아닌 것**: 에이전트 호출 순서와 응답 JSON 조립(지혜), MCP 도구 등록(두나), 재시도·캐시·장애 주입 실행(상옥), 화면(수언, 두나).

### 파일 구성 (추천)

| 파일 | 내용 |
|---|---|
| `backend/src/agents/profile_agent.py` | `vulnerability(p)`, `run_profile(person_id)` |
| `backend/src/agents/risk_rules.py` | 바이탈 점수, 실내 기준, `risk_level`, `select_actions` |
| `backend/src/agents/emergency_agent.py` | `run_emergency(care_status) -> EmergencyResult` |
| `backend/src/agents/summary_agent.py` | `run_summary(emergency, approved, executed) -> dict` |
| `backend/src/agents/prompts.py` | Emergency·Summary·CCTV 프롬프트, 검증 함수, 템플릿 |
| `mcp_server/src/vision.py` | `analyze_cctv_image(image_path) -> dict` (두나 님이 `analyze_cctv` 도구로 등록) |

---

## 0. README 기준으로 바뀐 점 (현재 확정)

- 위험도는 README의 **정상/주의/경고/위급**을 씀. 프런트 색상(초록/노랑/주황/빨강)과 같음.
- 에어컨·인덕션 제어와 119는 **보호자 승인 후에만** 실행함.
- 바이탈은 **심박, 수축기 혈압, 체온, 산소포화도** 4개를 NEWS2 점수로 판정함(1장). 쓰러짐은 CCTV가 맡음.
- 실내 온도는 해든 결정(월별 쾌적 범위 + 위험 한계)을 README 9장 단계에 맞춤(2장).
- 취약도는 README 함수(나이, 독거, 지병 유무, 거동 불편)를 씀.
- 코드가 위험도와 조치 종류를 정하고, LLM은 근거·설명 문장과 안내문만 씀.
- 증상 질문(KTAS 방식)은 README에 어르신 입력 경로가 없어 **확장 기능으로 보류**함.

**팀 합의가 남은 것**: 119 무응답 처리(자동 호출 없이 보호자 재알림 추천), 실내 극한 → 경고 추가, 시연 모델.

---

## 1. 바이탈 판정 (NEWS2 점수를 README 규칙에 맞춤)

항목마다 0~3점. **3점 = README의 "위험 범위"**, 1~2점 = "바이탈 변화".

| 항목 | 0점 | 1점 | 2점 | 3점 (위험 범위) |
|---|---|---|---|---|
| 심박(회/분) | 51~90 | 41~50, 91~110 | 111~130 | ≤40, ≥131 |
| 수축기 혈압(mmHg) | 111~219 | 101~110 | 91~100 | ≤90, ≥220 |
| 체온(℃) | 36.1~38.0 | 35.1~36.0, 38.1~39.0 | 39.1~39.9 | ≤35.0(저체온), ≥40.0(열사병 의심, 질병관리청) |
| 산소포화도(%) | ≥96 | 94~95 | 92~93 | ≤91 |

체온 40℃ 이상을 3점으로 둔 것만 NEWS2 원표(39.1 이상 2점)와 다름.

README mock 값 검산:

| 시나리오 | 점수(심박/혈압/체온/SpO2) | 결과 |
|---|---|---|
| normal | 0/0/0/0 | 정상 |
| heat | 1/0/0/0 + 실내 33℃ | 경고 (실내 고온 + 바이탈 변화) |
| induction | 0/0/0/0 + 사람 없음·인덕션 2시간 | 주의 |
| fall | 2/2/0/2 + CCTV 쓰러짐 | 위급 (CCTV) |
| critical | 3/3/1/3 | 위급 (위험 범위 3개) |

## 2. 실내 온도 기준 (해든 결정 10/8을 README 단계에 맞춤)

| 쓰임 | 값 |
|---|---|
| 에어컨 목표 온도 (조치안에 넣는 값) | 6~9월 24~26℃, 11~3월 20~22℃, 4·5·10월 24~26℃ |
| README "실내 환경 이상" (주의) | 28℃ 초과 또는 20℃ 미만 |
| 실내 극한 | 31℃ 초과 또는 18℃ 미만 (WHO 실내 최저 18℃) |

- 쾌적 범위를 벗어났지만 20~28℃ 안이면 **정상**으로 둠. README Handoff Guard의 "알림 피로 줄이기"와 맞춤.
- 제안 (팀): 실내 극한은 바이탈 변화가 없어도 **경고**로 올리기. README 9장 우선순위 2에 "또는 실내 극한"을 한 줄 추가.
- 저온일 때 조치는 "에어컨 난방 모드 켜기"로 씀. README 기기에 보일러가 없기 때문.

## 3. 취약도 함수와 위험도 판정 순서

취약도 함수(산출물 ①)는 README 4장 함수를 그대로 씀: 75세 이상, 독거, 지병 유무, 거동 불편 중 3개 이상이면 상, 2개면 중, 그 밖에는 하. 값이 없으면 위험한 쪽으로 셈. 지병명은 받지 않고 유무만 받음.


```
1. CCTV fall_suspected 또는 바이탈 3점 항목 2개 이상          → 위급
2. 바이탈 3점 항목 1개, 또는 실내 이상 + 바이탈 1점 이상
   (제안: 또는 실내 극한)                                     → 경고
3. 실내 이상만, 또는 사람 없음 + 인덕션 켜짐 1시간 이상        → 주의
4. 그 외                                                     → 정상 (Handoff Guard에서 종료)
취약도 "상"이면 한 단계 올림 (최대 위급)
정보 누락: 바이탈 FAIL → 안전 종료(지혜 Join Guard), CCTV 판단 불가 → 바이탈만으로 판정, 프로필 없음 → 취약도 "상"
```
- 인덕션 "오래 켜짐" 기준 1시간은 제 제안값. (팀) 두나 mock의 `on(2h)` 표기와 함께 확인.
- 조치 종류 선택(코드): README 9장 "위험 원인별 조치안" 표 그대로. 원인 → `control_device`(승인), `notify_guardian`(승인 없음), `call_119`(승인), `find_hospital`(정보).

## 4. LLM이 쓰는 곳 3군데

| 단계 | 입력 | 출력(JSON, 구조화 출력 strict) | 검증 | 실패 시 |
|---|---|---|---|---|
| ① CCTV 분석 (IoT Agent 도구) | 캡처 이미지 | `person_visible`, `posture`(standing/sitting/lying/fallen/none), `fall_suspected`, `description` | 필수 키, posture 값 목록, description 1문장·60자 이하, "의심" 표현(확진 단어 금지) | 2회 재시도 → "영상 판단 불가" (DR-VISION-01) |
| ② Emergency 조치안 문장 | 위험도, 원인 목록, 코드가 고른 조치 목록, 바이탈 수치, 취약도, CCTV 설명, 병원 | `reason`(판정 근거 1문장), `action_texts`(조치별 승인 화면용 설명, 조치 개수와 같아야 함) | 개수 일치, 입력에 없는 수치·장소 금지, 진단·약 표현 금지 | JSON 1회 재요청 → 템플릿 (DR-LLM-01) |
| ③ Summary | 승인/거절 결과, 실행 결과(executed), 위험도, 근거, 병원, CCTV 설명 | `guardian_message`, `elder_message` | 어르신용에 CCTV·수치 언급 금지, 길이 제한, 실패한 조치를 "완료"라고 쓰지 않기 | 같음 |

- 기존 llm_contract.py의 틀(프롬프트 → 검증 → JSON 교정 재요청 → 템플릿)을 그대로 쓰고 내용만 바꿈.
- 숫자 검사 단위를 ℃·m에서 **회/분, mmHg, ℃, %**로 바꿈.
- 거절이면 `elder_message`는 비우고 보호자용 기록 문구만 만듦(README 5장 "거절 → 보호자용 기록만").
- IoT 제어 최종 실패(DR-IOT-01)면 guardian_message에 "직접 조치 필요"가 반드시 들어가야 함. 템플릿 고정 권장.

### 템플릿 (README FALLBACK을 상황별로 나눔)
| 상황 | guardian_message | elder_message |
|---|---|---|
| 승인 대기 | 어르신 상태 확인이 필요합니다. 위험도 {risk_level}. 판정 근거: {reason}. 화면에서 조치를 승인해 주세요. | — |
| 승인·실행 성공 | 승인하신 조치({actions})를 실행했습니다. 위험도 {risk_level}. | 보호자에게 연락했어요. 편하게 계시고 무리하지 마세요. |
| 119 실행 | 승인하신 대로 119에 연락했습니다. 가까운 응급실: {hospital}. | 곧 도움이 도착해요. 움직이지 말고 기다려 주세요. |
| 기기 제어 실패 | {device} 제어에 실패했습니다. 직접 조치가 필요합니다. | 보호자에게 연락했어요. 편하게 계세요. |
| 거절 | 보호자 거절로 조치 없이 기록했습니다. 위험도 {risk_level}. | — |

## 5. 기존 초안 코드 재사용

| 기존 파일 | 새 위치 | 처리 |
|---|---|---|
| risk_rules.py | agents/risk_rules.py, profile_agent.py | 날씨 단계·쉼터 코드 제거, 취약도 함수는 README 함수로 교체 |
| llm_contract.py | agents/prompts.py | 틀(프롬프트 → 검증 → JSON 교정 재요청 → 템플릿) 유지, 내용 교체, CCTV 프롬프트·검증 추가 |
| openai_llm.py | 호출 함수 | 스키마 3개(cctv, emergency, summary)와 이미지 입력 추가, SDK 재시도는 끈 채 유지 |
| alert_response.py | — | 응답 조립은 지혜 님 몫이라 쓰지 않음 |
| test_risk_rules.py | tests/ | README 시나리오 5개(1장 검산표)와 장애 `vision`·`llm` 테스트로 다시 씀 |

## 6. 팀원과 다시 맞출 것

### 상옥 님 (가장 중요)
| 맞출 것 | 제 추천 |
|---|---|
| 재요청을 누가 하나 | 해든의 호출 함수는 실패하면 예외만 던지고, 1회 재요청·템플릿 대체는 상옥 님 AutoHealing이 함. 둘 다 재시도하면 횟수가 두 배가 됨 |
| 넘길 함수 | 단계마다 `build_prompt(ctx)`, `call_llm(prompt)`, `validate(raw, ctx)`, `fallback(ctx)` 4개 |
| `llm`·`vision` 장애 주입 위치 | AutoHealing 쪽에서 `call_llm` 대신 깨진 문자열을 돌려줌. 해든 코드에는 장애 주입을 넣지 않음 |
| 필수 키 | Emergency: `reason`, `action_texts` / Summary: `guardian_message`, `elder_message` / CCTV: `person_visible`, `posture`, `fall_suspected`, `description` |
| 로그 값 | `llm` / `llm_retry` / `template` (CCTV는 `vision_fail`) |
| 프로필 테이블 컬럼 | `age`, `lives_alone`, `has_condition`, `mobility_limited` (SQLite가 상옥 님 담당) |

### 지혜 님
| 맞출 것 | 제 추천 |
|---|---|
| 에이전트 함수 입출력 | `run_profile`, `run_emergency(care_status)`, `run_summary(emergency, approved, executed)` 세 함수를 오케스트레이터가 부름 |
| Summary 입력 `executed` 형식 | README 응답 2의 `[{action, result}]` 그대로 |
| 119 무응답 처리 (0장) | 자동 호출 없이 보호자 재알림 + 승인 대기 유지 |
| 거절일 때 | Summary는 보호자용 기록 문구만, `elder_message`는 빈 값 |

### 두나 님
| 맞출 것 | 제 추천 |
|---|---|
| CCTV 함수 위치·이름 | `mcp_server/src/vision.py`의 `analyze_cctv_image(image_path)`. 두나 님은 도구 등록만 |
| `find_hospital` 반환 형식 | `{"name", "distance_km", "type"}`. 조치안·안내문이 이 값만 인용함 |
| 인덕션 켜짐 시간 표기 | mock `on(2h)` 대신 `{"state": "on", "minutes": 120}`처럼 숫자로. 규칙표가 "1시간 이상"을 계산해야 함 |

### 기화 님 (PM)
| 맞출 것 | 제 추천 |
|---|---|
| README 9장 표에 확정값 기록 | 1~3장 값을 보내 드리고 README에 반영 요청 |
| 시나리오 5개 기대 결과 | 1장 검산표대로 나오는지 확인 |
| CCTV 이미지 4장 일정 | 이미지가 있어야 CCTV 프롬프트를 실제로 시험할 수 있음 |
| 실내 극한 → 경고 추가 (2장) | 추가 추천 |

### 수언 님
| 맞출 것 | 제 추천 |
|---|---|
| 카드에 들어갈 문장 길이 | `reason` 60자, CCTV `description` 60자, `elder_message` 40자 이내 |

### 전체
| 맞출 것 | 제 추천 |
|---|---|
| 시연 모델·키 | OpenAI gpt-4.1-mini(이미지 입력 지원). backend와 mcp_server 두 곳에 키가 필요 |

## 7. 작업 순서 (발표 10/13)
1. 취약도 함수, 위험도 규칙표 + 시나리오 테스트 (키 없이 가능)
2. Emergency·Summary 프롬프트, 템플릿, 검증 함수
3. 상옥 님과 호출 함수 모양을 맞춘 뒤 Emergency·Summary Agent 연결
4. CCTV 분석 함수와 프롬프트 (기화 님 이미지 받으면 실제 호출 시험)
5. 지혜·두나 님과 함수 이름·형식을 맞춰 연결

---

## 8. 세부 설계

**해든 확정 10/8** (본문의 [D번호]와 같음)

| # | 결정 |
|---|---|
| D1 | 취약도 "상"이어도 정상은 정상으로 둠 (주의 이상만 한 단계 올림) |
| D2 | CCTV posture가 fallen이면 fall_suspected를 true로 고침 |
| D3 | lying만으로는 단계를 올리지 않음 |
| D4 | 실내 31℃ 초과·18℃ 미만은 바이탈이 정상이어도 경고 (팀 합의 필요) |
| D5 | 습도는 MVP에서 쓰지 않음 |
| D6 | LLM은 조치를 더하거나 빼지 못하고 설명만 씀 |
| D7 | 어르신 안내는 승인·실행 뒤에만 보냄 |
| D8 | 병원 정보는 바이탈 원인 + 경고 이상일 때 붙임 |
| D9 | 이미지 분석과 문장 작성에 같은 모델 하나 사용, gpt-4.1-mini (팀 합의 필요) |

### 8.1 Emergency Agent 내부 순서

```
run_emergency(care_status):
  1. scores = vital_scores(vitals)              # 항목별 0~3점, 값 없으면 None
  2. indoor = indoor_state(env.temp, month)     # normal / abnormal_hot / abnormal_cold / extreme_hot / extreme_cold
  3. causes = detect_causes(scores, indoor, devices, cctv)   # 원인 코드 목록
  4. level  = risk_level(causes, vulnerability)              # 정상/주의/경고/위급
  5. if level == 정상: return no_issue                        # Handoff Guard와 같은 결과
  6. actions = select_actions(causes, level, month)          # 조치 목록(코드)
  7. if 병원 필요: hospital = find_hospital(area)             # [D8]
  8. texts = LLM 조치안 문장(ctx) → 실패 시 템플릿
  9. return EmergencyResult(risk_level, reason, reason_codes, actions, hospital)
```

### 8.2 원인 코드 (detect_causes)

| 코드 | 조건 | 기본 단계 |
|---|---|---|
| `CCTV_FALL` | `fall_suspected` true (또는 [D2] posture가 fallen) | 위급 |
| `VITAL_DANGER_MULTI` | 3점 항목 2개 이상 | 위급 |
| `VITAL_DANGER_ONE` | 3점 항목 1개 | 경고 |
| `ENV_EXTREME` | 31℃ 초과 / 18℃ 미만 | 경고 [D4] |
| `ENV_WITH_VITAL` | 실내 이상 + 바이탈 1점 이상 항목 있음 | 경고 |
| `ENV_ONLY` | 실내 이상(28℃ 초과 / 20℃ 미만)만 | 주의 |
| `INDUCTION_UNATTENDED` | `person_visible` false + 인덕션 켜짐 60분 이상 | 주의 |
| `VITAL_CHANGE` | 1~2점 항목만 있음 (실내 정상) | 주의 [D1] |
| `VITAL_STALE` | `source` = cache | 단계 변화 없음, 근거에 "n분 전 측정값" 표시 |
| `CCTV_UNAVAILABLE` | 영상 판단 불가 | 단계 변화 없음, 근거에 표시 |

최종 단계 = 원인 중 가장 높은 단계 → 취약도 "상"이면 한 단계 올림(최대 위급, [D1] 정상은 그대로).

### 8.3 원인 → 조치 (select_actions)

| 원인 | 조치 | 값 | 승인 |
|---|---|---|---|
| 실내 고온 | `control_device` | `{"device": "aircon", "mode": "cool", "target": 그 달 쾌적 범위 상한}` (예: 9월 26℃) | 필요 |
| 실내 저온 | `control_device` | `{"device": "aircon", "mode": "heat", "target": 그 달 쾌적 범위 하한}` (예: 1월 20℃) | 필요 |
| `INDUCTION_UNATTENDED` | `control_device` | `{"device": "induction", "action": "off"}` | 필요 |
| 단계 주의 이상 | `notify_guardian` | — | 불필요 (항상 포함) |
| `CCTV_FALL`, `VITAL_DANGER_MULTI` | `call_119` | — | 필요 |
| 바이탈 원인이 있고 경고 이상 [D8] | `hospital_info` | `find_hospital` 결과 | 정보 |

- 같은 기기 조치는 한 번만 넣음. 순서: 119 → 기기 제어 → 병원 정보 → 보호자 알림.
- LLM은 이 목록에 조치를 더하거나 빼지 못함 [D6].

### 8.4 Emergency 조치안 프롬프트 (초안)

```
너는 떨어져 사는 보호자에게 어르신 상황을 설명하는 도우미다.
위험도와 조치 목록은 이미 정해졌다. 바꾸거나 더하지 않는다.
[입력]
위험도: {risk_level}
판정 원인: {reason_codes를 한국어로}
바이탈: 심박 {hr}회/분, 혈압 {sbp}mmHg, 체온 {temp}℃, 산소포화도 {spo2}% ({measured_note})
실내: {env_temp}℃ / 기기: {devices}
CCTV: {cctv_description 또는 "영상 판단 불가"}
취약도: {vulnerability}
조치 목록: {actions 번호 목록}
병원: {hospital 또는 "없음"}
[규칙]
- reason: 판정 근거 한 문장, 60자 이내. 입력에 있는 수치만 쓴다.
- action_texts: 조치 목록과 같은 개수, 같은 순서. 각 30자 이내로 보호자가 승인할지 판단할 수 있게 쓴다.
- 진단명, 약, 확진 표현("쓰러졌다")을 쓰지 않는다. CCTV는 "~로 보입니다", "의심"으로 쓴다.
- JSON으로만 답한다: {"reason": "...", "action_texts": ["..."]}
```

### 8.5 Summary 프롬프트 (초안)

```
너는 조치 결과를 보호자와 어르신에게 알리는 도우미다.
[입력]
상황: {done / rejected / device_fail}
위험도: {risk_level}, 판정 근거: {reason}
실행 결과: {executed: 조치별 success / fail}
병원: {hospital 또는 "없음"}, CCTV 설명: {cctv_description 또는 "없음"}
[규칙]
- guardian_message: 120자 이내. 실행한 조치와 결과, 다음에 할 일을 쓴다.
  실패한 조치는 "실패"라고 쓰고 "직접 조치가 필요합니다"를 넣는다. 성공하지 않은 조치를 완료라고 쓰지 않는다.
- elder_message: 40자 이내, 존댓말, 쉬운 말. 수치·CCTV·병명을 쓰지 않는다. 상황이 rejected면 빈 문자열.
- JSON으로만 답한다: {"guardian_message": "...", "elder_message": "..."}
```

### 8.6 CCTV 분석 (README 프롬프트에 더할 것)

| 항목 | 설계 |
|---|---|
| 이미지 전달 | 파일을 읽어 base64 data URL로 비전 모델에 넣음. 긴 변 1024px로 줄여 비용·시간을 줄임 |
| 출력 고정 | 구조화 출력 strict, `posture`는 5개 값 enum |
| 검증 | 필수 키 4개, `description` 60자 이내·한 문장, "쓰러졌다/사망/의식 없음" 같은 확진 표현 금지 |
| 모순 처리 [D2] | posture가 fallen인데 fall_suspected false면 true로 고침 (보수적 판단, README 원칙 ③) |
| lying 처리 [D3] | 사진 한 장으로는 움직임을 알 수 없으니 lying만으로는 단계를 올리지 않음 |
| 사람 없음 | `person_visible` false면 posture는 none으로 고정 |

### 8.7 검증 함수가 막는 것 (공통)

| 검사 | Emergency | Summary | CCTV |
|---|---|---|---|
| JSON 파싱·필수 키 | ✅ | ✅ | ✅ |
| 개수 일치 (action_texts = actions) | ✅ | — | — |
| 입력에 없는 수치 (회/분, mmHg, ℃, %, km) | ✅ | ✅ | — |
| 진단·약·확진 표현 | ✅ | ✅ | ✅ |
| 실패 조치를 성공처럼 씀 | — | ✅ | — |
| 어르신용에 수치·CCTV | — | ✅ | — |
| 길이 | 60/30자 | 120/40자 | 60자 |

### 8.8 해든 테스트 목록

1. README 시나리오 5개가 1장 검산표 단계로 나옴
2. 취약도: 값 없음 → 상, 4가지 조합
3. 경계값: 심박 90/91, SpO2 95/96, 실내 28/28.1, 18/17.9
4. 조치 선택: heat → 에어컨 cool 26℃, induction → 인덕션 off, fall → 119 + 병원
5. 검증: 지어낸 수치·확진 표현·개수 불일치가 걸러짐
6. 템플릿 5종이 모두 검증을 통과
7. CCTV 모순 응답(fallen + false)이 true로 고쳐짐
