# 해든 LLM 파트 전달서 (2026-10-08)

> 팀원용 요약입니다. 해든이 만든 것, 각자 연결할 곳, 정해야 할 것을 한 파일에 모았습니다.
> 코드 안에서는 `grep -rn "팀 합의" backend/src mcp_server/src`로 같은 내용을 찾을 수 있습니다.
> 모든 기준값은 **시연용 예시**이며 의학적 기준이 아닙니다.

## 1. 한 줄 요약

**위험도와 조치는 코드가 정하고, LLM은 문장만 씁니다.** LLM이 실패해도 템플릿 문장으로 끝까지 돌아갑니다 (키 없이도 시연 가능).

```
CareStatusResult ─▶ rules/risk.py evaluate()      위험도·4축·조치 (코드)
                 ─▶ agents/emergency.py            조치안 문장 (LLM, 실패 시 템플릿)
                 ─▶ [승인 대기 / 119 바로 연결]     ← 지혜 님 approval.py, 두나 님 승인 화면
                 ─▶ agents/summary.py              보호자·어르신 안내 (LLM, 실패 시 템플릿)
CCTV 이미지      ─▶ mcp_server vision/analyzer.py  자세·낙상 의심 JSON (비전 LLM)
```

## 2. 해든이 만든 파일

| 파일 | 하는 일 |
|---|---|
| `backend/src/rules/risk.py` | 위험도 정상/주의/경고/위급, 판정 축 4개(낙상·심뇌·호흡·환경), 낙상 상태 5개, 조치 목록, 119 바로 연결 |
| `backend/src/agents/profile.py` | 취약도 상/중/하 (README 기준) |
| `backend/src/agents/emergency.py` | `run_emergency(care_status, llm, find_hospital)` → EmergencyResult |
| `backend/src/agents/summary.py` | `run_summary(emergency_result, approved, executed, llm, decided_by)` → 보호자·어르신 문장 |
| `backend/src/llm/client.py` | OpenAI(우선)·Gemini 호출, `generate()`는 실패하면 예외만, `generate_or_template()`은 임시 재시도 |
| `backend/src/llm/prompts.py` | 프롬프트, 검증(수치 지어내기·진단·말투·"승인" 오용 등) |
| `backend/src/llm/fallback.py` | 템플릿 문장, 보호자 휴대폰 알림 문구 |
| `mcp_server/src/vision/` | CCTV 프롬프트·분석·검증 |
| 테스트 | `backend/tests/` 265개, `mcp_server/tests/test_vision.py` 23개 (키 없이 돌아감) |
| 설명서 | `notes/낙상-판정-케이스표.md`, `notes/승인-119-흐름.md` |

## 3. 위험도 판정

- 4축을 따로 매기고 **가장 높은 축**이 최종 위험도. 취약도 "상"이면 한 단계 올림(정상은 그대로).
- 위험 범위 바이탈이 2개 이상이면 축이 달라도 위급.
- 낙상은 바이탈과 따로 봅니다. 바이탈이 정상이어도 CCTV가 바닥 자세를 분명히 보면 위급.

| 축 | 보는 것 |
|---|---|
| 낙상 `fall` | CCTV 자세·확신도, 워치 낙상, 스피커 응답, 움직임 없는 시간, 머리 충격 |
| 심뇌 `cardio` | 심박·혈압 + 이상 행동 |
| 호흡 `respiratory` | 산소포화도 + 호흡 곤란 정황 |
| 환경 `environment` | 실내 온도(월별 쾌적 범위), 체온, 인덕션 |

## 4. 승인 알림과 119 (자세한 건 `notes/승인-119-흐름.md`)

| 상황 | 시스템 행동 |
|---|---|
| 승인할 조치 없음 (낙상 의심 등) | 📱 상태 알림 + 스피커 확인 |
| 기기 제어 | 📱 승인 요청 → 30초 무응답이면 다시 알림 → 시간이 지나도 실행 안 함 |
| 119 (위급) | 📱 승인 요청 → 30초 다시 알림 → **60초 무응답이면 119 자동 연결** |
| 정말 위급 | **승인 없이 119 바로 연결** → 📱 "[긴급] 119에 바로 연락했습니다" |

"정말 위급" = 위급이면서 ① 스피커 확인에 어르신 무응답, 또는 ② 바이탈 위험 범위 2개 이상 + 점수 합 7점 이상(최신 측정값).

## 5. 말투

| 누구에게 | 말투 | 예 |
|---|---|---|
| 어르신 (스피커) | 다정한 간호사. "어르신,"으로 부르고 한 일 + 지금 하실 일 하나 | "어르신, 시원하게 에어컨을 켜 두었어요. 물 한 잔 천천히 드세요." |
| 어르신 (119) | 짧고 분명하게 | "어르신, 구급대에 연락했어요. 움직이지 말고 그대로 계세요." |
| 보호자 (주의·경고) | 차분하고 정중하게 | "잠시 뒤 어르신 상태를 한 번 더 확인해 주세요." |
| 보호자 (위급) | 단호하게, "지금 바로 ~하세요" | "[긴급] 어르신이 위급합니다. … 지금 바로 화면에서 조치를 승인하세요." |
| 어르신 (보호자 거절) | 혼자 남지 않게 짧게 | "어르신, 보호자분께 상황을 알려 드렸어요. 곧 연락드릴 거예요." |
| 어르신 (기기 실패) | 솔직하게 + 직접 하실 일 | "어르신, 에어컨이 켜지지 않았어요. 창문을 열고 물을 자주 드세요." |

보호자 결과 안내의 마지막 문장(보호자가 할 일)은 LLM이 추측하지 않게 코드(`prompts.next_step()`)가 정합니다.
예: 119 연락 → "지금 바로 어르신께 전화해 상태를 확인하세요."

검증이 막는 것 (실제 호출 25번 + 현실 상황 20개 점검에서 나온 문제):
- 어르신 문장: 수치·CCTV·"위험/위급/쓰러/낙상/사고/응급", 기기 실패인데 "해 드릴게요"·"켜 두었어요"
- 보호자 문장: 위급인데 "혹시·~면 좋겠습니다·가능하면", "병원으로 이동하세요"·"안정적" 같은 추측, "보호자에게 알렸습니다"
- 공통: 일어나지 않은 일("이송 중"), 승인 안 한 조치에 "승인", 음성 응답이 없는데 "무응답"

## 6. 팀원별로 연결할 것

### 지혜 님 (오케스트레이터)
- `run_emergency(care_status, llm=make_llm("emergency"), find_hospital=...)` 결과를 task_id로 승인 대기에 저장. `context`도 함께 저장(Summary가 다시 씀).
- `evaluate()` 결과에 `axes`, `fall_state`, `auto_119`가 새로 생김. `auto_119`가 있으면 **LLM 문장보다 먼저** 119 실행.
- 승인 대기 타이머: 30초 다시 알림(`reminder_guardian_message`), 60초 뒤 `after_guardian_timeout(actions)` → `execute`는 실행, `remind`는 다시 알림.
- `run_summary(..., decided_by="guardian" | "auto" | "timeout")`. 보호자 알림(notify_guardian)은 executed에 넣어도 안내문에서는 빠집니다. executed 형식 `[{"action": "control_device", "device": "aircon", "result": "success"}]`.
- CareStatusResult에 선택 키 `fall_event`(watch_fall, voice_response ok/help/none, immobile_seconds, head_impact_suspected), `signs`(abnormal_behavior, breathing_distress), cctv에 `confidence`.

### 두나 님 (데이터·MCP·승인 화면)
- `tools/cctv.py`의 `analyze_cctv(image_path)`에서 `analyze_cctv_or_unavailable(image_path)` 호출.
- `find_hospital(area)` 결과: `"○○병원 응급실 (1.2km)"` 또는 `{"name", "distance_km"}`.
- `control_device` 값 형식: 에어컨 `{"device": "aircon", "mode": "cool"/"heat", "target": 26}`, 인덕션 `{"device": "induction", "action": "off"}`.
- 스피커 mock 도구 `speaker_check(message, wait_seconds)` 추가 여부 (없으면 `ENABLE_SPEAKER_CHECK = False`).
- 승인 화면: 남은 시간 표시, `notify_guardian.value.kind`(approval_request / emergency_alert / info), 긴급 알림은 승인 버튼 없이.
- `mcp_server/requirements`에 `openai>=1.66`, `pillow`. `.env.example`에 `OPENAI_API_KEY`.

### 상옥 님 (AutoHealing)
- `generate(step, ctx, llm)`과 `analyze_cctv_image()`를 감싸 주세요. 실패하면 예외만 던집니다. 재요청까지 실패하면 `template(step, ctx)` + `fallback_used = true`.
- LLM 시간 제한 10초(비전 15초), SDK 재시도는 꺼 둠. CCTV 3번 실패면 "영상 판단 불가".
- 119 자동 연결이 실패하면 보호자에게 "직접 조치가 필요합니다" (지금 `device_fail` 상황으로 감).

### 기화 님 (PM)
- README 핵심 원칙 ① "119는 보호자 승인 후에만"에 예외 2개를 둘지 (안 두면 `rules/risk.py`의 `ENABLE_AUTO_119 = False`).
- README 5장 "거절 → 보호자용 기록만"을 "어르신께도 짧게 안내"로 바꿀지 (안 바꾸면 `llm/fallback.py`의 `ELDER_MESSAGE_ON_REJECT = False`).
- README 7장 FALLBACK 승인 대기 문구를 새 말투로 바꿀지.
- README 9장: 낙상 우선순위를 "CCTV가 바닥 자세를 분명히 봄"으로, 낙상 의심(경고) 단계 추가, 실내 극한을 경고로.
- 발표 전 출처 원문 확인: NEWS2(RCP 2017), 질병관리청 실내 온도, NICE 낙상 가이드라인.

### 수언 님 (프런트)
- 어르신 문장 최대 60자, 보호자 120자, 판정 근거 60자. 화면 줄바꿈 확인 부탁드려요.

## 7. 연결 예시 (5단계)

`backend/tests/test_integration.py`에 README 도구 이름·인자 그대로 만든 가짜 MCP(`FakeTools`)와
오케스트레이터 흐름 예시(`care_run` = `/care/run`, `care_approve` = `/care/approve`)가 있습니다.
README 시나리오 5개, 승인·거절·60초 무응답·119 바로 연결·119 실패·기기 실패가 끝까지 도는 것을 확인했습니다 (키 없이).
지혜 님은 이 순서를 그대로 옮기면 되고, 두나 님은 `FakeTools`와 실제 도구 형식이 같은지만 봐 주세요.

README 형식과 아직 안 맞는 곳:

| # | 누구 | 내용 | 지금 해든 코드 |
|---|---|---|---|
| 1 | 두나 | `control_device(device, action)`에 냉방·난방, 목표 온도를 넘길 자리가 없음 | `device_call_args()`가 `("aircon", "on", {"mode": "cool", "target": 26})`로 바꿔 줌. 도구에 `mode`, `target` 인자 추가 부탁 |
| 2 | 지혜 | CareStatusResult에 `area`(병원 찾기용)가 없음 | `care_status["area"]`를 읽고, 없으면 `find_hospital(None)` |
| 3 | 지혜 | `analyze_cctv` 결과에 `available`, `confidence`가 더 붙음 | 없으면 `available` true, `confidence` "high"로 봄 |
| 4 | 지혜 | EmergencyResult에 `axes`, `fall_state`, `auto_119`, 조치별 `label`·`text`, Summary용 `context`가 더 있음 | `schemas.py`에 넣을지 정해 주세요 |
| 5 | 지혜 | 119 바로 연결은 승인 대기 없이 끝나서 README `status`에 맞는 값이 없음 | 예시는 `status: "done"`, `approved: null` |
| 6 | 지혜 | 60초 무응답 처리 (`/care/approve`에 `approved: null`로 들어오는 경우) | `after_guardian_timeout()` → `decided_by="timeout"` |
| 7 | 두나 | 스피커 확인 도구가 README 9개 도구에 없음 | 없으면 `ENABLE_SPEAKER_CHECK = False` |
| 8 | 지혜·두나 | 취약도용 프로필(나이·혼자 사는지·지병·거동)을 어디서 읽을지 | `run_profile(profile)`에 dict만 넘기면 됨 |
| 9 | 기화 | 실제 프로필(82세, 혼자, 지병)이면 heat 시나리오가 경고 → 위급으로 올라감 (취약도 보정) | 시연 대본의 위험도 확인 |

## 8. 직접 돌려보기

```bash
# 테스트 (키 없이)
cd backend && python -m pytest -q
cd mcp_server && python -m pytest -q

# 실제 LLM (키 필요: backend/config/.env 또는 mcp_server/config/.env에 OPENAI_API_KEY)
pip install "openai>=1.66"
python notes/llm_live_check.py          # README 시나리오 5개
python notes/llm_realistic_check.py     # 현실 상황 20개 + 어르신·보호자 입장 평가
```

결과는 `notes/llm_realistic_check_result.md`에 저장됩니다 (VS Code에서 Ctrl+Shift+V로 미리보기).
