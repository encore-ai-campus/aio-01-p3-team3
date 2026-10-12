"""위험도 규칙표(정상/주의/경고/위급), 취약도 보정, 원인별 조치안 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 규칙표 첫 구현을 넣음.
#   - 출처: notes/risk_rules.py(폭염·한파 초안)에서 틀만 가져오고, 날씨 단계·쉼터·체감온도 코드는 뺌.
#   - 기준: 계획서 docs/archive/해든-LLM파트-계획서-README반영.md 1·2·3장, 8.2·8.3, 결정 D1~D5·D8.
#   - LLM은 쓰지 않음. 조치안 문장은 agents/emergency.py가 LLM으로 만든다.
# 2026-10-08 해든 (2단계): 실내 극한이면 "실내 온도 이상" 원인을 겹쳐 넣지 않고 바이탈 변화만 근거로 남김.
#   병원 정보는 바이탈 위험 범위(3점)일 때만 붙이도록 VITAL_CAUSES를 좁힘 (heat 시나리오에 병원 안 붙음).
# 2026-10-08 해든 (4단계): 낙상을 바이탈과 따로 보는 "낙상 축"을 넣음 (해든 설계 10/8).
#   - 판정 축 4개(vital / fall / environment / device)를 따로 매기고 최종 위험도는 가장 높은 축 + 취약도 보정.
#     바이탈이 정상이어도 낙상 축만으로 위급이 될 수 있음.
#   - 낙상 상태 5개: none / false_alarm(오탐 가능) / suspected(의심) / confirmed(확인) / critical(위급).
#   - CCTV_FALL 코드를 FALL_DETECTED(강한 CCTV 신호)와 FALL_SUSPECTED(약한 신호)로 나눔.
#   - 워치 버튼 응답·움직임 없는 시간·머리 충격은 care_status["fall_event"]로 받는 확장 입력 (README 시연엔 없음).
#   - 낙상 의심이고 워치 응답을 아직 모르면 watch_check(워치로 괜찮은지 묻기) 조치를 넣음.
#   - 케이스 표: notes/낙상-판정-케이스표.md, 테스트: tests/test_fall_cases.py
# 2026-10-08 해든 (축 정리): 해든 분류 4개로 축을 바꿈 → fall(낙상·보행) / cardio(심뇌) / respiratory(호흡) / environment(환경).
#   - 바이탈 항목을 축에 나눔: 심박·혈압 → cardio, SpO2 → respiratory, 체온 → environment(고체온·저체온), 인덕션도 environment.
#   - 축을 넘는 규칙 3개는 유지: 위험 범위 항목 2개 이상 → 위급, 낙상 의심 + 바이탈 위험 → 위급, 실내 이상 + 바이탈 변화 → 경고.
#   - "이상 행동", "호흡 곤란 정황", "보행 불안정"은 care_status["signs"] / fall_event로 받는 선택 입력. 시연은 수치만으로 판정.
#   - 저온 조치는 HEATING_DEVICE(기본 aircon 난방). 보일러 mock이 생기면 "boiler"로 바꿈.
# 2026-10-08 해든 (승인·119 흐름): "정말 위급하면 119 바로 연결"을 넣음. 흐름 설명은 notes/승인-119-흐름.md.
#   - 119 즉시 자동 연결 2가지: ① 위급 + 워치 확인에 어르신 무응답 ② 바이탈 위험 범위 2개 이상 + 점수 합 7점 이상(최신 측정값).
#     이때 call_119는 needs_approval False, auto True. 보호자에게는 승인 요청이 아니라 "연락했습니다" 알림이 감.
#   - 그 밖의 119는 승인 요청 + GUARDIAN_WAIT_119_SEC 안에 보호자 응답이 없으면 자동 연결 (on_timeout "execute").
#   - 기기 제어는 시간이 지나도 실행하지 않고 다시 알림만 (on_timeout "remind").
#   - notify_guardian에 알림 종류(kind)와 재알림 시간을 붙임. after_guardian_timeout()으로 시간 초과 처리.
# 2026-10-08 해든 (5단계 연결): device_call_args()로 조치안 값을 README control_device(device, action) 인자로 바꿈.
# 2026-10-08 해든 (말투): 스피커 확인 문구를 어르신을 부르는 다정한 말로 바꿈 (SPEAKER_MESSAGE).
# 2026-10-08 해든 (워치 버튼): 스피커 확인을 워치 버튼 확인으로 바꿈 (speaker_check → watch_check, voice_response → watch_response, VOICE_* → WATCH_*).
#   워치에 "괜찮으세요?"를 띄우고 "괜찮아요"(ok) / "도와주세요"(help) / 30초 안에 안 누름(none). 판정 규칙은 그대로.
# 2026-10-08 해든 (시연 시나리오 확정안 반영): 팀 확정안 2장 기준으로 맞춤.
#   - 바이탈 위험 범위(3점)를 확정안 표로 바꿈: 심박 <50·>110, 수축기 <90·>160, 체온 <35.5·>37.5, 산소포화도 <94.
#     위험 범위 안쪽의 1~2점("바이탈 변화")은 NEWS2 점수표를 그대로 씀 (VITAL_DANGER, VITAL_BANDS).
#   - 실내 이상: 30℃ 이상 / 16℃ 이하. 실내 극한(경고)은 확정안에 없어서 끔 (ENABLE_ENV_EXTREME = False).
#   - 기기 상태를 구조 형식 {"state", "minutes", "temperature"}로 읽음 (예전 "on(2h)" 문자열도 읽음). 인덕션 과열 250℃ 이상 추가.
#   - 바이탈만으로 119 바로 연결(VITAL_SEVERE)은 끔: 확정안 critical은 119 승인 장면 (ENABLE_AUTO_119_VITAL = False).
# 2026-10-08 해든 (확정안과 다른 부분 정리): 해든 결정으로 확정안 흐름에 맞춤. 코드는 남기고 설정값으로 끔.
#   - CCTV가 낙상을 의심하면 확신과 상관없이 위급 (확정안 "CCTV 쓰러짐 의심 → 위급", CCTV_SUSPECT_IS_CRITICAL).
#     대신 승인 알림에 CCTV 캡처를 붙여 보호자가 사진을 보고 119를 승인하게 함 (notify_guardian.value.cctv_image).
#     CCTV 판단 불가면 원본 캡처 확인 요청 (확정안 DR-VISION-01).
#   - 워치 확인(ENABLE_WATCH_CHECK)과 119 바로 연결(ENABLE_AUTO_119)은 끔. 확정안은 119를 모두 보호자 승인 뒤에 검.
#   - 위험 범위 안쪽의 작은 바이탈 변화만 있으면 정상 (확정안 판정 순서 4). 변화는 "실내 이상 + 바이탈 변화 → 경고"에만 씀
#     (VITAL_CHANGE_ALONE_RAISES = False). 예: 심박 95만 있으면 예전엔 주의, 그때는 정상. → 아래 main 문서 개정판에서 다시 True.
# 2026-10-08 해든 (main 스키마 연결): main의 schemas.py(CareStatusResult)와 키 이름이 달라 normalize_care_status()를 넣음.
#   - vital.heart_rate/systolic_bp/temperature_c/spo2 → vitals.hr/sbp/temp/spo2, indoor_environment.temperature_c → env.temp
#   - devices.air_conditioner → aircon, induction + induction_minutes(+ induction_temperature) → 구조 {"state","minutes","temperature"}
#   - cctv.status(analyzed/unavailable/failed) → available, 숫자 confidence → "high"/"low", fall_event.voice_response → watch_response
#   - 확정안 형식(vitals/env/구조 기기)으로 오면 그대로 둠. evaluate()와 Emergency Agent 입구에서 한 번 부름.
# 2026-10-08 해든 (두나 님 CCTV 연결): cctv.status가 analyzed가 아니면 항상 판단 불가로 봄. 숫자 confidence는 available 키가 있어도 high/low로 바꿈.
# 2026-10-12 해든 (README 기준으로 119 자동 연결): ENABLE_AUTO_119·ENABLE_AUTO_119_VITAL을 True로 바꿈.
#   critical처럼 바이탈 위험 범위 2개 이상 + 점수 합 7점 이상 + 최신 측정값이면 승인 없이 119 (auto_119 "VITAL_SEVERE").
#   그 밖의 119(낙상 등)는 그대로 보호자 승인 요청.
# 2026-10-12 해든 (에어컨 제어 오류): 에어컨 조치 값에 action(cool/heat)을 넣음. 두나 님 control_device(device, action)는
#   action이 필수라 mode만 있으면 실제 MCP 호출이 실패했음 (heat 시나리오). mode·target은 화면·문구용으로 남김.
# 2026-10-08 해든 (main 문서 docs/scenarios.md 개정판에 맞춤): 팀 문서가 "판정은 risk.py를 따른다"로 바뀌며 NEWS2 기준을 적음.
#   - 위험 범위 = NEWS2 3점 (VITAL_DANGER_FROM_NEWS2 = True, 예전 확정안 범위 VITAL_DANGER는 남겨 둠)
#   - 실내 이상 28℃ 초과 / 20℃ 미만, 실내 극한 31℃ 초과 / 18℃ 미만 → 경고 (ENABLE_ENV_EXTREME = True)
#   - 작은 바이탈 변화(1~2점)도 그 축 주의 (VITAL_CHANGE_ALONE_RAISES = True)
#   - 단, 해든 결정으로 critical도 119는 보호자 승인 (문서 2-4장 VITAL_SEVERE 자동 연결은 끔, ENABLE_AUTO_119 = False). 워치 확인도 계속 끔.
# 2026-10-12 해든 (CCTV 출력 계약, 선택지 B): cctv.status가 "analyzed"면 README 필수 4항목(person_visible, posture,
#   fall_suspected, description)이 모두 있고 자료형이 맞아야 함. cctv_contract_errors()로 검사하고,
#   어기면 normalize_care_status()가 "영상 판단 불가"(status failed)로 바꿔 바이탈 중심으로 판정 (README DR-VISION-01).
#   failed·unavailable은 분석 항목이 없어도 됨. 지혜 님 validation.py, 기화 님 iot.py 재시도 검사에서 같은 함수를 쓰면 됨.
# 2026-10-12 해든 (README 8·9장 최종 맞춤): 남아 있던 README와 다른 설정 2개를 끔.
#   - CCTV_SUSPECT_IS_CRITICAL = False: README 9장대로 fallen + 신뢰도 높음만 위급(FALL_DETECTED),
#     흐린 사진·자세와 플래그 불일치는 낙상 의심(FALL_SUSPECTED) = 경고. 시연 fall.png는 그대로 위급.
#   - ENABLE_TIMEOUT_119 = False: README "그 밖의 119는 모두 보호자 승인". 60초 무응답 자동 연결을 끄고
#     on_timeout을 "remind"(다시 알림)로. 보호자 알림의 "60초 안에 응답이 없으면 119에 자동으로 연락" 문구도 같이 빠짐.
#   - 같은 날 팀 의견으로 60초 무응답 자동 연결은 유지하기로 정해져 ENABLE_TIMEOUT_119 = True로 되돌림 (설정값은 남김).
#
# 모든 수치는 시연용 예시 규칙이며 의학적 기준이 아님. 발표 전 출처(NEWS2, 질병관리청, WHO) 원문 확인.
# 팀원과 겹치는 부분에는 "# [팀 합의] 이름: 설명" 주석을 달았음. 검색: grep -n "팀 합의" risk.py

# ---------- 기준값 (합의되면 여기만 바꾸면 됨) ----------

LEVELS = ["정상", "주의", "경고", "위급"]

# 바이탈 점수표 (NEWS2 기반). 항목마다 (점수, 이 값 이하) 또는 (점수, 이 값 이상) 순서로 본다.
# 3점 = README의 "위험 범위", 1~2점 = "바이탈 변화".
# 체온 40.0℃ 이상을 3점으로 둔 것만 NEWS2 원표와 다름 (질병관리청 열사병 기준).
VITAL_BANDS = {
    "hr":   {"low": [(3, 40), (1, 50)], "high": [(3, 131), (2, 111), (1, 91)]},
    "sbp":  {"low": [(3, 90), (2, 100), (1, 110)], "high": [(3, 220)]},
    "temp": {"low": [(3, 35.0), (1, 36.0)], "high": [(3, 40.0), (2, 39.1), (1, 38.1)]},
    "spo2": {"low": [(3, 91), (2, 93), (1, 95)], "high": []},
}
VITAL_LABEL = {"hr": "심박", "sbp": "수축기 혈압", "temp": "체온", "spo2": "산소포화도"}
# 위험 범위(3점) = 시연 시나리오 확정안 2장 (아래값, 위값). 이 값보다 낮거나 높으면 위험 범위. None이면 그쪽은 보지 않음.
#   VITAL_BANDS의 3점은 이 범위 밖이라 쓰이지 않고, 범위 안쪽은 최대 2점(바이탈 변화)까지만 준다.
VITAL_DANGER = {"hr": (50, 110), "sbp": (90, 160), "temp": (35.5, 37.5), "spo2": (94, None)}
# 10/8 오후 docs/scenarios.md(main) 2-1장: 위험 범위 = NEWS2 3점. True면 위 VITAL_DANGER 대신 NEWS2 점수를 그대로 씀.
VITAL_DANGER_FROM_NEWS2 = True

# 실내 온도. "이상"은 확정안 2장(30℃ 이상 고온, 16℃ 이하 저온). "극한"은 [D4] 해든 안이었지만 확정안에 없어 끔.
INDOOR_HOT, INDOOR_COLD = 28.0, 20.0          # docs/scenarios.md 2-2장: 28℃ 초과 / 20℃ 미만 → 실내 이상
# [팀 합의] 기화 님: 실내 극한을 경고로 올릴지. 켜려면 True로 하고 아래 값을 고온·저온 기준보다 바깥으로 정해 주세요.
ENABLE_ENV_EXTREME = True                      # docs/scenarios.md 2-2장: 실내 극한 → 경고
INDOOR_EXTREME_HOT, INDOOR_EXTREME_COLD = 31.0, 18.0   # 31℃ 초과 / 18℃ 미만

# 에어컨 목표 온도 = 그 달 쾌적 범위 (해든 결정 10/8). 고온이면 상한, 저온이면 하한으로 맞춘다.
COMFORT_SUMMER = (24, 26)   # 4~10월
COMFORT_WINTER = (20, 22)   # 11~3월

# 인덕션 "오래 켜짐"·"과열" 기준 (확정안 2장). 기기 상태는 {"state": "on", "minutes": 120, "temperature": 300}.
INDUCTION_LONG_MIN = 60
INDUCTION_HOT_TEMP = 250

# ---------- 낙상 축 기준값 (시연용 시스템 설정값, 실제 서비스는 의료·응급 전문가 검토 후 정함) ----------

# [팀 합의] 두나 님·지혜 님: 아래 값은 care_status["fall_event"]에 들어오면 쓰고, 없으면 "모름"으로 본다.
#   README 시연 데이터에는 워치 응답·체류 시간이 없어서, 지금은 CCTV 사진 한 장으로만 판정됨.
IMMOBILE_LONG_SEC = 60        # 이 시간 이상 움직임 없음 → 바닥 체류로 봄
WATCH_WAIT_SEC = 30         # 워치 확인 뒤 응답을 기다리는 시간 (해든 설계: 20~30초)
WATCH_MESSAGE = "어르신, 괜찮으세요? '괜찮아요'나 '도와주세요' 버튼을 눌러 주세요."
# [팀 합의] 두나 님: 워치 확인 MCP 도구(예: watch_check(message, wait_seconds) → "ok"/"help"/"none")가 생기기 전에는 False로 두면 조치에서 빠짐.
# [팀 합의] 수언 님: 시연 화면에 워치 버튼 2개("괜찮아요", "도와주세요")와 남은 시간. 30초 안에 안 누르면 "none".
# 해든 10/8: 확정안 fall 조치(119·응급실·알림)에 맞춰 끔. 시연 뒤 확장 기능으로 켤 수 있음.
ENABLE_WATCH_CHECK = False
# 확정안: CCTV 쓰러짐 의심이면 위급. True면 흐린 사진·바닥에 앉음처럼 확신이 낮아도 위급(보호자가 캡처를 보고 승인).
#   False면 예전 해든 설계(확신 낮으면 낙상 의심 = 경고).
# 해든 10/12: README 9장("흐린 사진·자세와 플래그 불일치 = FALL_SUSPECTED 경고")에 맞춰 False.
CCTV_SUSPECT_IS_CRITICAL = False
UPRIGHT = {"standing", "sitting"}

# ---------- 119 자동 연결·승인 대기 (해든 10/8, 시연용 설정값) ----------

# [팀 합의] 기화 님·지혜 님: README 핵심 원칙 ①("119는 보호자 승인 후에만")에 예외를 둠. 합의 전이면 False로 두면 예전과 같음.
# 해든 10/8: 확정안("119는 보호자 승인 후")에 맞춰 끔. 승인 대기 60초 뒤 자동 연결(on_timeout)은 그대로.
# 해든 10/8 오후: docs/scenarios.md 2-4장은 VITAL_SEVERE 자동 연결이지만, 해든 결정으로 119는 모두 보호자 승인 (critical도 승인 요청).
# 해든 10/12: README·docs/scenarios.md대로 다시 켬. critical(VITAL_SEVERE)은 승인 없이 119 자동 연결.
ENABLE_AUTO_119 = True
# 바이탈만으로 바로 연결(VITAL_SEVERE). 해든 10/12: README 응답 3·시연 5·8번에 맞춰 켬. 워치 무응답 바로 연결은 워치 확인이 꺼져 있어 동작 안 함.
ENABLE_AUTO_119_VITAL = True
# 바이탈 4항목 점수 합. NEWS2 원문은 7항목 합 7점 이상이면 "긴급 대응" (출처 확인 필요: RCP NEWS2 2017).
#   여기는 4항목만 있어서 실제보다 낮게 나옴 → 7점이면 꽤 심한 상태.
VITAL_SEVERE_SCORE = 7
# [팀 합의] 지혜 님: 승인 대기 시간. 119 승인 요청에 이 시간 동안 응답이 없으면 119에 자동 연결.
GUARDIAN_WAIT_119_SEC = 60
# 해든 10/12: 팀 의견으로 유지. 119 승인 요청에 GUARDIAN_WAIT_119_SEC 동안 응답이 없으면 자동 연결(on_timeout "execute", decided_by "timeout").
#   False로 바꾸면 시간이 지나도 119를 걸지 않고 다시 알림만 (on_timeout "remind").
# 기화 10/12 (PM 결정): 승인 없는 119는 바이탈 매우 위험(VITAL_SEVERE)일 때만. 60초 무응답 자동 연결은 쓰지 않음 → False.
#   (백엔드에 타이머가 없어 실제로 걸리지는 않았지만, 보호자 안내에 "60초 뒤 자동 연락" 문구가 나가던 것을 막음)
ENABLE_TIMEOUT_119 = False
GUARDIAN_REMIND_SEC = 30      # 승인 요청 뒤 응답이 없으면 한 번 더 알림
AUTO_119_LABEL = {"ELDER_NO_RESPONSE": "어르신 응답 없음", "VITAL_SEVERE": "바이탈 여러 항목 매우 위험"}

# [팀 합의] 지혜 님: 정황 입력 care_status["signs"] = {"abnormal_behavior": bool, "breathing_distress": bool}.
#   보호자 입력, 워치 신호 등에서 옵니다. CCTV LLM이 추측해서 채우지 않음 (진단 금지).
#   보행 불안정은 fall_event["gait_unsteady"]. 없으면 "모름"으로 보고 수치만으로 판정.
# [팀 합의] 두나 님: 보일러 mock 기기와 control_device("boiler", ...)가 생기면 "boiler"로 바꿈. 지금은 README 기기대로 에어컨 난방.
HEATING_DEVICE = "aircon"

# 위험 범위 안쪽의 작은 변화(NEWS2 1~2점)만 있을 때 주의로 올릴지. 확정안 판정 순서에는 없어서 False (해든 10/8).
#   False여도 "실내 고온·저온 + 바이탈 변화 → 경고"(ENV_WITH_VITAL)에는 변화를 씀.
VITAL_CHANGE_ALONE_RAISES = True     # docs/scenarios.md 2-3장: 심박·혈압 등 1~2점 → 그 축 주의
VITAL_CHANGE_CODES = {"CARDIO_CHANGE", "RESP_CHANGE", "BODY_TEMP_CHANGE"}

# 바이탈 항목 → 판정 축
VITAL_AXIS = {"hr": "cardio", "sbp": "cardio", "spo2": "respiratory", "temp": "environment"}

# 원인 코드 → 기본 단계 (계획서 8.2). None은 단계를 바꾸지 않고 근거에만 표시.
CAUSE_LEVEL = {
    # 낙상 축. 신호 코드(WATCH_*, IMMOBILE_LONG, HEAD_IMPACT)는 낙상 신호가 있을 때만 나오고 위급으로 올림.
    "FALL_DETECTED": "위급",       # CCTV가 바닥에 쓰러진 자세를 분명히 봄 (README "쓰러짐 의심 → 위급")
    "FALL_SUSPECTED": "경고",      # 워치만, 흐린 사진, 확인 안 되는 자세 등 약한 신호
    "FALL_WITH_VITAL_DANGER": "위급",
    "WATCH_NO_RESPONSE": "위급",
    "WATCH_HELP": "위급",
    "IMMOBILE_LONG": "위급",
    "HEAD_IMPACT": "위급",
    "FALL_FALSE_ALARM": None,      # 낙상 감지 뒤 서 있거나 앉은 모습·워치 응답 확인 → 기록만
    "WATCH_OK": None,
    "GAIT_UNSTEADY": "주의",            # 낙상·보행: 보행 불안정 정황만 있음
    # 축을 넘는 규칙
    "VITAL_DANGER_MULTI": "위급",       # 위험 범위(3점) 항목 2개 이상 (축이 달라도)
    # 심뇌 (심박·혈압 + 이상 행동)
    "CARDIO_DANGER": "경고",
    "CARDIO_CHANGE": "주의",
    "BEHAVIOR_CHANGE": "주의",          # 이상 행동 정황만 있음
    "CARDIO_WITH_SIGN": "경고",         # 심박·혈압 변화 + 이상 행동
    "CARDIO_DANGER_WITH_SIGN": "위급",  # 심박·혈압 위험 범위 + 이상 행동
    # 호흡 (SpO2 + 호흡 곤란 정황)
    "RESP_DANGER": "경고",
    "RESP_CHANGE": "주의",
    "BREATHING_DISTRESS": "주의",
    "RESP_WITH_SIGN": "경고",
    "RESP_DANGER_WITH_SIGN": "위급",
    # 환경 (실내 온도·체온·가전)
    "BODY_TEMP_DANGER": "경고",
    "BODY_TEMP_CHANGE": "주의",
    "ENV_EXTREME": "경고",         # [팀 합의] 기화 님: README 9장 우선순위 2에 "또는 실내 극한" 추가 필요 [D4]
    "ENV_WITH_VITAL": "경고",
    "ENV_ONLY": "주의",
    "INDUCTION_UNATTENDED": "주의",
    "VITAL_STALE": None,
    "CCTV_UNAVAILABLE": None,
}
CAUSE_LABEL = {
    "FALL_DETECTED": "CCTV 쓰러짐 의심",
    "FALL_SUSPECTED": "낙상 의심(확인 필요)",
    "FALL_WITH_VITAL_DANGER": "낙상 의심 + 바이탈 위험",
    "WATCH_NO_RESPONSE": "워치 확인 무응답",
    "WATCH_HELP": "워치 도움 요청",
    "IMMOBILE_LONG": "오래 움직임 없음",
    "HEAD_IMPACT": "머리 충격 의심",
    "FALL_FALSE_ALARM": "낙상 감지 후 괜찮은 모습 확인",
    "WATCH_OK": "워치 괜찮아요 응답",
    "GAIT_UNSTEADY": "보행 불안정 정황",
    "VITAL_DANGER_MULTI": "위험 범위 항목 2개 이상",
    "CARDIO_DANGER": "심박·혈압 위험 범위",
    "CARDIO_CHANGE": "심박·혈압 변화",
    "BEHAVIOR_CHANGE": "이상 행동 정황",
    "CARDIO_WITH_SIGN": "심박·혈압 변화 + 이상 행동",
    "CARDIO_DANGER_WITH_SIGN": "심박·혈압 위험 + 이상 행동",
    "RESP_DANGER": "산소포화도 위험 범위",
    "RESP_CHANGE": "산소포화도 변화",
    "BREATHING_DISTRESS": "호흡 곤란 정황",
    "RESP_WITH_SIGN": "산소포화도 변화 + 호흡 곤란",
    "RESP_DANGER_WITH_SIGN": "산소포화도 위험 + 호흡 곤란",
    "BODY_TEMP_DANGER": "체온 위험 범위",
    "BODY_TEMP_CHANGE": "체온 변화",
    "ENV_EXTREME": "실내 온도 극한",
    "ENV_WITH_VITAL": "실내 온도 이상(바이탈 변화 동반)",
    "ENV_ONLY": "실내 온도 이상",
    "INDUCTION_UNATTENDED": "사람 없는 곳에서 인덕션 오래 켜짐·과열",
    "VITAL_STALE": "이전 측정값 사용",
    "CCTV_UNAVAILABLE": "영상 판단 불가",
}
# 병원 정보를 붙이는 바이탈 원인 [D8]. 위험 범위(3점)만 셈. 1~2점 변화만으로는 붙이지 않음.
VITAL_CAUSES = {"VITAL_DANGER_MULTI", "CARDIO_DANGER", "RESP_DANGER", "BODY_TEMP_DANGER",
                "CARDIO_DANGER_WITH_SIGN", "RESP_DANGER_WITH_SIGN"}
# 119를 부르는 원인 (낙상 축 위급 말고). 심뇌·호흡 위험 + 정황은 시간이 중요해서 119 승인 버튼을 띄움.
CALL_119_CAUSES = {"VITAL_DANGER_MULTI", "CARDIO_DANGER_WITH_SIGN", "RESP_DANGER_WITH_SIGN"}

# 원인 코드가 어느 판정 축에 속하는지. 축마다 따로 단계를 매긴 뒤 가장 높은 축을 쓴다.
CAUSE_AXIS = {
    "FALL_DETECTED": "fall", "FALL_SUSPECTED": "fall", "FALL_WITH_VITAL_DANGER": "fall",
    "WATCH_NO_RESPONSE": "fall", "WATCH_HELP": "fall", "IMMOBILE_LONG": "fall", "HEAD_IMPACT": "fall",
    "GAIT_UNSTEADY": "fall",
    "CARDIO_DANGER": "cardio", "CARDIO_CHANGE": "cardio", "BEHAVIOR_CHANGE": "cardio",
    "CARDIO_WITH_SIGN": "cardio", "CARDIO_DANGER_WITH_SIGN": "cardio",
    "RESP_DANGER": "respiratory", "RESP_CHANGE": "respiratory", "BREATHING_DISTRESS": "respiratory",
    "RESP_WITH_SIGN": "respiratory", "RESP_DANGER_WITH_SIGN": "respiratory",
    "BODY_TEMP_DANGER": "environment", "BODY_TEMP_CHANGE": "environment",
    "ENV_EXTREME": "environment", "ENV_WITH_VITAL": "environment", "ENV_ONLY": "environment",
    "INDUCTION_UNATTENDED": "environment",
    # VITAL_DANGER_MULTI는 축을 넘는 규칙이라 어느 축에도 넣지 않고, 최종 위험도에서만 셈
}
AXES = ["fall", "cardio", "respiratory", "environment"]


# ---------- 바이탈 ----------

def vital_score(name: str, value: float | None) -> int | None:
    """항목 하나의 0~3점. 값이 없으면 None."""
    if value is None:
        return None
    if VITAL_DANGER_FROM_NEWS2:
        return _news2_score(name, value)
    low, high = VITAL_DANGER[name]
    if (low is not None and value < low) or (high is not None and value > high):
        return 3
    return min(_news2_score(name, value), 2)


def _news2_score(name: str, value: float) -> int:
    bands = VITAL_BANDS[name]
    for score, limit in bands["low"]:
        if value <= limit:
            return score
    for score, limit in bands["high"]:
        if value >= limit:
            return score
    return 0


def vital_scores(vitals: dict | None) -> dict:
    """{"hr": 2, "sbp": 0, ...}. 바이탈이 없으면 모두 None."""
    v = vitals or {}
    return {name: vital_score(name, v.get(name)) for name in VITAL_BANDS}


# ---------- 실내 온도 ----------

def indoor_state(temp: float | None) -> str:
    """normal / hot / cold / extreme_hot / extreme_cold. 값이 없으면 normal (실내 정보 없이 진행)."""
    if temp is None:
        return "normal"
    if ENABLE_ENV_EXTREME and temp > INDOOR_EXTREME_HOT:
        return "extreme_hot"
    if ENABLE_ENV_EXTREME and temp < INDOOR_EXTREME_COLD:
        return "extreme_cold"
    if temp > INDOOR_HOT:
        return "hot"
    if temp < INDOOR_COLD:
        return "cold"
    return "normal"


def comfort_range(month: int) -> tuple[int, int]:
    return COMFORT_WINTER if month in (11, 12, 1, 2, 3) else COMFORT_SUMMER


# ---------- 기기 ----------

# [팀 합의] 두나 님: get_device_status 기기 값은 확정안 형식 {"state": "on", "minutes": 120, "temperature": 300}.
#   예전 문자열("off", "on", "on(2h)", "on(90m)")도 읽는다.
def device_state(value) -> str:
    """"on" / "off" / ""(모름)."""
    if isinstance(value, dict):
        return str(value.get("state") or "")
    return "on" if isinstance(value, str) and value.startswith("on") else (value or "")


def induction_hot(value) -> bool:
    """켜져 있고 표면 온도가 INDUCTION_HOT_TEMP 이상."""
    return isinstance(value, dict) and value.get("state") == "on" and (value.get("temperature") or 0) >= INDUCTION_HOT_TEMP


def induction_on_minutes(status) -> int | None:
    """켜져 있지 않으면 0, 켜졌는데 시간을 모르면 None."""
    if isinstance(status, dict):
        if status.get("state") != "on":
            return 0
        return status.get("minutes")
    if not status or not status.startswith("on"):
        return 0
    inside = status[status.find("(") + 1:status.find(")")] if "(" in status else ""
    try:
        if inside.endswith("h"):
            return int(float(inside[:-1]) * 60)
        if inside.endswith("m"):
            return int(inside[:-1])
    except ValueError:
        pass
    return None


# ---------- 낙상 축 ----------

def detect_fall(care_status: dict, vital_danger: int = 0) -> tuple[list[str], str]:
    """(낙상 원인 코드, 낙상 상태). 상태: none / false_alarm / suspected / confirmed / critical.
    바이탈과 상관없이 판정한다. vital_danger(3점 항목 수)는 "의심 + 바이탈 위험 → 위급"에만 쓴다."""
    cctv = care_status.get("cctv")
    ok = bool(cctv) and cctv.get("available", True)
    event = care_status.get("fall_event") or {}
    posture = cctv.get("posture") if ok else None
    confident = ok and cctv.get("confidence", "high") != "low"
    cctv_flag = ok and bool(cctv.get("fall_suspected"))
    upright = ok and cctv.get("person_visible") is not False and posture in UPRIGHT
    answer = event.get("watch_response")              # "ok" / "help" / "none" / None(모름)
    immobile = event.get("immobile_seconds")
    watch = event.get("watch_fall") is True

    # 1) 낙상 신호의 세기
    if ok and posture == "fallen" and confident:                       # [D2] 자세가 fallen이면 플래그와 상관없이
        base = "FALL_DETECTED"
    elif ok and (posture == "fallen" or cctv_flag) and CCTV_SUSPECT_IS_CRITICAL:   # 확정안: CCTV 의심 → 위급
        base = "FALL_DETECTED"
    elif ok and (posture == "fallen" or cctv_flag):                    # 흐린 사진, 자세와 플래그가 어긋남
        base = "FALL_SUSPECTED"
    elif watch:
        base = "FALL_SUSPECTED"
    elif ok and posture == "lying" and (answer == "none" or (immobile or 0) >= IMMOBILE_LONG_SEC):
        base = "FALL_SUSPECTED"                                        # [D3] lying만으로는 안 올리고, 신호가 더 있을 때만
    else:
        return [], "none"

    # 2) 오탐 가능 → 기록만. 약한 신호이고 바닥 자세가 아니면서,
    #    워치에서 "괜찮아요"를 눌렀거나, CCTV 스스로는 낙상을 의심하지 않는데 서 있거나 앉은 모습일 때.
    #    CCTV가 낙상을 의심했는데 "앉아 있음"이면 바닥에 앉은 것일 수 있어 오탐으로 보지 않는다.
    if base == "FALL_SUSPECTED" and posture != "fallen" and answer != "none" and \
            (answer == "ok" or (upright and not cctv_flag)):
        return ["FALL_FALSE_ALARM"] + (["WATCH_OK"] if answer == "ok" else []), "false_alarm"

    # 3) 추가 신호로 올리기
    codes = [base]
    if answer == "none":
        codes.append("WATCH_NO_RESPONSE")
    elif answer == "help":
        codes.append("WATCH_HELP")
    elif answer == "ok":
        codes.append("WATCH_OK")
    if (immobile or 0) >= IMMOBILE_LONG_SEC:
        codes.append("IMMOBILE_LONG")
    if event.get("head_impact_suspected"):
        codes.append("HEAD_IMPACT")
    if vital_danger >= 1:
        codes.append("FALL_WITH_VITAL_DANGER")

    if {"WATCH_NO_RESPONSE", "HEAD_IMPACT", "FALL_WITH_VITAL_DANGER"} & set(codes):
        state = "critical"
    elif base == "FALL_DETECTED" or {"WATCH_HELP", "IMMOBILE_LONG"} & set(codes):
        state = "confirmed"
    else:
        state = "suspected"
    return codes, state


# ---------- 원인 → 위험도 ----------

# [팀 합의] 지혜 님: care_status는 README 6장 CareStatusResult 형식. 쓰는 키: vitals, env, devices, cctv, vulnerability.
#   CCTV 분석이 실패하면 cctv를 None으로 넘기거나 {"available": false}로 넘겨 주세요.
def detect_causes(care_status: dict) -> list[str]:
    """원인 코드 목록 (계획서 8.2)."""
    vitals = care_status.get("vitals") or {}
    scores = [s for s in vital_scores(vitals).values() if s is not None]
    danger = sum(1 for s in scores if s == 3)
    changed = any(s >= 1 for s in scores)
    indoor = indoor_state((care_status.get("env") or {}).get("temp"))
    cctv = care_status.get("cctv")
    cctv_ok = bool(cctv) and cctv.get("available", True)

    causes, _ = detect_fall(care_status, danger)
    if (care_status.get("fall_event") or {}).get("gait_unsteady") and not causes:
        causes.append("GAIT_UNSTEADY")
    if danger >= 2:
        causes.append("VITAL_DANGER_MULTI")

    # 축별 바이탈: 축 안에서 가장 높은 점수로 위험 범위 / 변화를 고름
    by_axis = {}
    for name, score in vital_scores(vitals).items():
        if score is not None:
            axis = VITAL_AXIS[name]
            by_axis[axis] = max(by_axis.get(axis, 0), score)
    signs = care_status.get("signs") or {}
    causes += _vital_axis_codes("CARDIO", by_axis.get("cardio", 0), signs.get("abnormal_behavior"), "BEHAVIOR_CHANGE")
    causes += _vital_axis_codes("RESP", by_axis.get("respiratory", 0), signs.get("breathing_distress"), "BREATHING_DISTRESS")
    temp_score = by_axis.get("environment", 0)
    if temp_score == 3:
        causes.append("BODY_TEMP_DANGER")
    elif temp_score >= 1:
        causes.append("BODY_TEMP_CHANGE")

    if indoor.startswith("extreme"):
        causes.append("ENV_EXTREME")
    elif indoor != "normal":
        causes.append("ENV_WITH_VITAL" if changed else "ENV_ONLY")

    # 사람이 안 보이는지는 CCTV로만 안다. 켜진 시간을 모르면 위험한 쪽(오래 켜짐)으로 본다.
    induction = (care_status.get("devices") or {}).get("induction")
    minutes = induction_on_minutes(induction)
    if cctv_ok and cctv.get("person_visible") is False and \
            (minutes is None or minutes >= INDUCTION_LONG_MIN or induction_hot(induction)):
        causes.append("INDUCTION_UNATTENDED")

    if vitals.get("source") == "cache":
        causes.append("VITAL_STALE")
    if not cctv_ok:
        causes.append("CCTV_UNAVAILABLE")
    return causes


def cause_level(code: str) -> str | None:
    """원인 코드의 단계. 작은 바이탈 변화는 VITAL_CHANGE_ALONE_RAISES가 False면 단계를 올리지 않음(근거에만 표시)."""
    if code in VITAL_CHANGE_CODES and not VITAL_CHANGE_ALONE_RAISES:
        return None
    return CAUSE_LEVEL.get(code)


def axis_levels(causes: list[str]) -> dict:
    """축별 단계 (취약도 보정 전)."""
    out = {axis: "정상" for axis in AXES}   # 예: {"fall": "위급", "cardio": "주의", "respiratory": "정상", "environment": "정상"}
    for c in causes:
        axis, level = CAUSE_AXIS.get(c), cause_level(c)
        if axis and level and LEVELS.index(level) > LEVELS.index(out[axis]):
            out[axis] = level
    return out


def _vital_axis_codes(prefix: str, score: int, sign: bool | None, sign_code: str) -> list[str]:
    """심뇌·호흡 축 코드. score는 축 안 최고 점수(0~3), sign은 정황(이상 행동·호흡 곤란)."""
    if score == 3:
        return [f"{prefix}_DANGER_WITH_SIGN"] if sign else [f"{prefix}_DANGER"]
    if score >= 1:
        return [f"{prefix}_WITH_SIGN"] if sign else [f"{prefix}_CHANGE"]
    return [sign_code] if sign else []


def risk_level(causes: list[str], vulnerability: str | None) -> str:
    """가장 높은 축의 단계 (final = max(fall, cardio, respiratory, environment, 축을 넘는 규칙)).
    취약도 "상"(또는 없음)이면 한 단계 올림, 정상은 그대로 [D1]."""
    rank = max(LEVELS.index(level) for level in axis_levels(causes).values())
    if "VITAL_DANGER_MULTI" in causes:
        rank = max(rank, LEVELS.index(CAUSE_LEVEL["VITAL_DANGER_MULTI"]))
    if rank > 0 and (vulnerability or "상") == "상":
        rank = min(rank + 1, len(LEVELS) - 1)
    return LEVELS[rank]


REASON_MAX = 60   # llm/prompts.py의 reason 길이 제한과 같음 (템플릿도 검증을 통과해야 함)


def reason_text(causes: list[str]) -> str:
    """LLM이 실패했을 때 쓰는 판정 근거. 높은 단계 원인부터 60자 안에서 이어 붙임.
    예: "CCTV 쓰러짐 의심 + 심박·혈압 변화". 개별 위험 범위가 보이면 "2개 이상" 문구는 생략."""
    shown = [c for c in causes if not (c == "VITAL_DANGER_MULTI" and len(VITAL_CAUSES & set(causes)) > 1)
             and not (c == "FALL_WITH_VITAL_DANGER" and VITAL_CAUSES & set(causes))]   # 낙상 + 개별 위험 범위가 보이면 겹치는 말 생략
    rank = lambda c: LEVELS.index(CAUSE_LEVEL[c]) if CAUSE_LEVEL.get(c) else -1
    text = ""
    for c in sorted(shown, key=rank, reverse=True):     # sorted는 같은 단계끼리 원래 순서를 지킴
        nxt = f"{text} + {CAUSE_LABEL[c]}" if text else CAUSE_LABEL[c]
        if len(nxt) > REASON_MAX:
            break
        text = nxt
    return text or "이상 없음"


# ---------- 원인 → 조치 ----------

# [팀 합의] 지혜 님: evaluate() 결과의 auto_119가 None이 아니면 119를 승인 없이 바로 실행해 주세요.
#   LLM 문장(run_emergency)을 기다리지 말고 먼저 call_119 → emergency_alert_message() 알림 → 그다음 문장 만들기.
# [팀 합의] 상옥 님: 바로 연결한 119가 실패하면(장애 주입) executed에 result "fail"로 넣어 주세요.
#   Summary가 "실패, 직접 조치가 필요합니다"로 보호자에게 알림 (device_fail 상황).
def auto_119_reason(care_status: dict, causes: list[str], level: str) -> str | None:
    """보호자 승인 없이 119에 바로 연결할 이유. 없으면 None.
    ① 위급인데 워치 확인에 어르신이 응답하지 않음 (애플워치 낙상 감지처럼 무응답이면 바로 신고)
    ② 바이탈 위험 범위 2개 이상 + 점수 합 7점 이상. 이전 측정값(캐시)이면 센서 오류일 수 있어 자동 연결하지 않음."""
    if not ENABLE_AUTO_119 or level != "위급":
        return None
    if (care_status.get("fall_event") or {}).get("watch_response") == "none":
        return "ELDER_NO_RESPONSE"
    total = sum(vital_scores(care_status.get("vitals")).values())
    if ENABLE_AUTO_119_VITAL and "VITAL_DANGER_MULTI" in causes and total >= VITAL_SEVERE_SCORE and \
            "VITAL_STALE" not in causes:
        return "VITAL_SEVERE"
    return None


# [팀 합의] 지혜 님: actions 형식은 README EmergencyResult와 같게 {"type", "needs_approval", "value"}에
#   119는 auto·auto_reason 또는 timeout_seconds·on_timeout, 기기는 on_timeout, 보호자 알림은 value.kind가 더 붙음.
#   순서는 119 → 워치 확인 → 기기 제어 → 병원 정보 → 보호자 알림 (README 예시와 순서가 다름, 승인 화면 순서 확인 필요).
# [팀 합의] 두나 님: control_device 값 형식(device, mode, target / action)을 MCP 도구 인자와 맞춰야 함.
#   승인 화면은 notify_guardian.value.kind로 나눔: approval_request(승인 버튼) / emergency_alert(버튼 없이 긴급 알림) / info.
def select_actions(causes: list[str], level: str, month: int, indoor: str = "normal",
                   watch_check: bool = False, auto_119: str | None = None) -> list[dict]:
    """조치 종류는 코드가 정한다. LLM은 더하거나 빼지 못하고 설명만 쓴다 [D6].
    indoor는 indoor_state() 결과. 에어컨을 냉방으로 켤지 난방으로 켤지 정할 때만 쓴다.
    watch_check는 낙상 신호가 있는데 워치 응답을 아직 모를 때 True (evaluate가 정함).
    auto_119는 auto_119_reason() 결과. 있으면 119를 승인 없이 바로 연결한다."""
    if level == "정상":
        return []
    actions = []
    fall_critical = axis_levels(causes)["fall"] == "위급"
    fall_any = bool({"FALL_DETECTED", "FALL_SUSPECTED"} & set(causes))
    # 119: 낙상 축 위급, 바이탈 여러 항목 위험, 또는 최종 위급인데 낙상 신호가 있음 (취약도 보정으로 위급이 된 경우)
    if auto_119:
        actions.append({"type": "call_119", "needs_approval": False, "auto": True, "auto_reason": auto_119})
    elif fall_critical or CALL_119_CAUSES & set(causes) or (level == "위급" and fall_any):
        actions.append({"type": "call_119", "needs_approval": True,
                        "timeout_seconds": GUARDIAN_WAIT_119_SEC,
                        "on_timeout": "execute" if ENABLE_TIMEOUT_119 else "remind"})
    if watch_check and ENABLE_WATCH_CHECK:
        actions.append({"type": "watch_check", "needs_approval": False,
                        "value": {"message": WATCH_MESSAGE, "wait_seconds": WATCH_WAIT_SEC}})

    if {"ENV_EXTREME", "ENV_WITH_VITAL", "ENV_ONLY"} & set(causes):
        # 저온은 HEATING_DEVICE로 난방 (README 기기에 보일러가 없어 기본은 에어컨 난방)
        low, high = comfort_range(month)
        cold = indoor.endswith("cold")
        device = HEATING_DEVICE if cold else "aircon"
        actions.append({"type": "control_device", "needs_approval": True, "on_timeout": "remind",
                        "value": {"device": device, "action": "heat" if cold else "cool", "mode": "heat" if cold else "cool",
                                  "target": low if cold else high}})
    if "INDUCTION_UNATTENDED" in causes:
        actions.append({"type": "control_device", "needs_approval": True, "on_timeout": "remind",
                        "value": {"device": "induction", "action": "off"}})

    # 병원 정보: 119를 부르거나, 바이탈 원인 + 경고 이상일 때 [D8]. 값은 Emergency Agent가 find_hospital로 채운다.
    calls_119 = any(a["type"] == "call_119" for a in actions)
    if calls_119 or (VITAL_CAUSES & set(causes) and LEVELS.index(level) >= LEVELS.index("경고")):
        actions.append({"type": "hospital_info", "needs_approval": False, "value": None})

    # 보호자 알림 종류: 119를 이미 연결함(emergency_alert) / 승인 요청(approval_request) / 알림만(info)
    if auto_119:
        kind = "emergency_alert"
    elif any(a["needs_approval"] for a in actions):
        kind = "approval_request"
    else:
        kind = "info"
    actions.append({"type": "notify_guardian", "needs_approval": False,
                    "value": {"kind": kind, "remind_after_seconds": GUARDIAN_REMIND_SEC if kind == "approval_request" else None}})
    return actions


# [팀 합의] 두나 님·수언 님: 보호자 알림에 CCTV 캡처를 붙이는 경우. notify_guardian.value에
#   cctv_image(이미지 경로)와 cctv_check("fall": 낙상 의심 사진을 보고 판단 / "unavailable": 판단 불가, 원본 확인)가 들어감.
#   승인 화면·휴대폰 알림에 이 사진을 같이 보여 주세요 (확정안 7장 4번 "캡처와 함께 승인 요청", 8번 "원본 캡처 확인 요청").
def attach_cctv(actions: list[dict], care_status: dict, causes: list[str]) -> list[dict]:
    cctv = care_status.get("cctv") or {}
    check = "unavailable" if "CCTV_UNAVAILABLE" in causes else \
        "fall" if {"FALL_DETECTED", "FALL_SUSPECTED"} & set(causes) else None
    if not check or not cctv.get("image_path"):
        return actions
    return [dict(a, value={**a["value"], "cctv_image": cctv["image_path"], "cctv_check": check})
            if a["type"] == "notify_guardian" else a for a in actions]


# [팀 합의] 두나 님: README MCP 도구는 control_device(device, action) 두 인자. 조치안 값을 이 함수로 바꿔 부르면 됨.
#   에어컨: ("aircon", "on", {"mode": "cool", "target": 26}) → control_device("aircon", "on", mode="cool", target=26)
#   인덕션: ("induction", "off", {}) → control_device("induction", "off"). mode·target을 받을 수 있게 도구 인자를 늘려 주세요.
def device_call_args(action: dict) -> tuple[str, str, dict]:
    v = dict(action.get("value") or {})
    device = v.pop("device")
    return device, v.pop("action", "on"), v


# [팀 합의] 지혜 님: 승인 대기 중 시간이 지나면 이 함수로 나눔. execute는 바로 실행, remind는 보호자에게 다시 알림.
def after_guardian_timeout(actions: list[dict]) -> dict:
    """승인이 필요한 조치 중 시간 초과 때 할 일. 119는 실행, 기기 제어는 재알림."""
    waiting = [a for a in actions if a.get("needs_approval")]
    return {"execute": [a for a in waiting if a.get("on_timeout") == "execute"],
            "remind": [a for a in waiting if a.get("on_timeout") != "execute"]}


# ---------- 한 번에 ----------

# [팀 합의] 지혜 님: README EmergencyResult보다 키가 늘어남 → axes(축별 단계), fall_state(낙상 상태), auto_119(바로 연결 이유).
#   CareStatusResult 스키마(schemas.py)에 넣을지, 로그에만 남길지 정해 주세요.
# ---------- main 스키마(CareStatusResult) → 규칙표 입력 ----------

# [팀 합의] 지혜 님: main schemas.py 키(vital, indoor_environment, devices.induction_minutes)를 그대로 넘겨도 되고,
#   확정안 형식(vitals, env, {"state","minutes","temperature"})으로 넘겨도 됨. 둘 다 여기서 같은 모양으로 바꿈.
#   과열(250℃) 판정을 하려면 DeviceStatus에 induction_temperature: int | None 칸이 필요해요 (확정안 6·7번).
#   Scenario에 "critical"도 추가 부탁드려요 (확정안 1번, 시나리오 5개).
SCHEMA_VITAL_KEYS = {"heart_rate": "hr", "systolic_bp": "sbp", "temperature_c": "temp", "spo2": "spo2"}
CCTV_SURE_FROM = 0.6        # 숫자 confidence가 이 값 이상이면 "high"


# ---------- CCTV 출력 계약 (해든 10/12, 선택지 B) ----------

# README 4장 CCTV 필수 키와 자료형. 분석 성공(status "analyzed")일 때만 모두 요구한다.
CCTV_REQUIRED = {"person_visible": bool, "posture": str, "fall_suspected": bool, "description": str}
CCTV_POSTURES = {"standing", "sitting", "lying", "fallen", "none"}     # schemas.CctvAnalysis.posture와 같음
CCTV_FAILED_TEXT = "영상 판단 불가"


# [팀 합의] 지혜 님: validation.py에서 CCTV 결과를 검사할 때 이 함수를 그대로 쓰면 됨 (빈 목록이면 PASS).
# [팀 합의] 기화 님: agents/iot.py _cctv()의 with_healing validate를
#   validate=lambda data: not cctv_contract_errors(data) 로 바꾸면 계약 위반도 재시도(2회) → 끝내 실패하면 status "failed".
# [팀 합의] 전체: description이 빈 문자열이어도 지금은 통과 (README에 정해지지 않음). 금지하려면 아래 한 줄을 켜면 됨.
def cctv_contract_errors(cctv) -> list[str]:
    """CCTV 분석 결과가 출력 계약을 어긴 이유 목록. 빈 목록이면 계약을 지킴.
    status가 analyzed가 아니면(failed·unavailable) 분석 항목이 없어도 됨."""
    cctv = _plain(cctv)
    if not isinstance(cctv, dict):
        return ["cctv 결과가 dict가 아님"]
    status = cctv.get("status", "analyzed" if cctv.get("available", True) else "unavailable")
    if status != "analyzed":
        return []
    errors = []
    for key, kind in CCTV_REQUIRED.items():
        value = cctv.get(key)
        if value is None:
            errors.append(f"{key} 없음")
        elif not isinstance(value, kind):
            errors.append(f"{key} 자료형 오류({kind.__name__})")
    if isinstance(cctv.get("posture"), str) and cctv["posture"] not in CCTV_POSTURES:
        errors.append(f"posture 값 오류({cctv['posture']!r})")
    # if isinstance(cctv.get("description"), str) and not cctv["description"].strip(): errors.append("description 빈 문자열")
    return errors


def _plain(value):
    """Pydantic 모델이면 dict로."""
    return value.model_dump() if hasattr(value, "model_dump") else value


def normalize_care_status(care_status) -> dict:
    """main 스키마 형식이든 확정안 형식이든 규칙표가 읽는 형식(vitals, env, 구조 기기)으로 바꾼다. 여러 번 불러도 같음."""
    cs = dict(_plain(care_status) or {})

    if not cs.get("vitals") and cs.get("vital"):
        vital = _plain(cs["vital"])
        vitals = {short: vital.get(long) for long, short in SCHEMA_VITAL_KEYS.items()}
        vitals["measured_at"] = vital.get("measured_at")
        if cs.get("source") == "cache":
            vitals["source"] = "cache"
        cs["vitals"] = vitals

    if not cs.get("env") and cs.get("indoor_environment"):
        indoor = _plain(cs["indoor_environment"])
        cs["env"] = {"temp": indoor.get("temperature_c"), "humidity": indoor.get("humidity_percent")}

    devices = dict(_plain(cs.get("devices")) or {})
    if "air_conditioner" in devices and "aircon" not in devices:
        devices["aircon"] = {"state": devices.pop("air_conditioner")}
    induction = devices.get("induction")
    if isinstance(induction, str) and not induction.startswith("on("):
        devices["induction"] = {"state": induction,
                                "minutes": devices.pop("induction_minutes", None),
                                "temperature": devices.pop("induction_temperature", None)}
    if devices:
        cs["devices"] = devices

    cctv = _plain(cs.get("cctv"))
    if isinstance(cctv, dict):
        cctv = dict(cctv)
        if "status" in cctv and "available" not in cctv:
            cctv["available"] = cctv["status"] == "analyzed"      # unavailable·failed는 판단 불가
        conf = cctv.get("confidence")
        if isinstance(conf, (int, float)) and not isinstance(conf, bool):
            cctv["confidence"] = "high" if conf >= CCTV_SURE_FROM else "low"
        if not cctv.get("description"):
            cctv["description"] = cctv.get("summary")
        # 해든 10/12 (선택지 B): 분석 성공이라면서 필수 4항목이 빠지거나 자료형이 틀리면 믿지 않고 "영상 판단 불가"로 본다.
        #   → 낙상 축은 CCTV_UNAVAILABLE(보호자에게 원본 캡처 확인 요청), 위험도는 바이탈 중심. 캡처 경로(image_path)는 그대로 둠.
        #   계약 검사는 main 스키마 형식(status 키가 있을 때)에만 한다. 예전 확정안 형식(status 없음)은 그대로.
        if cctv.get("status") == "analyzed":
            problems = cctv_contract_errors(cctv)
            if problems:
                cctv.update(status="failed", available=False, description=CCTV_FAILED_TEXT, contract_errors=problems)
        cs["cctv"] = cctv

    event = _plain(cs.get("fall_event"))
    if isinstance(event, dict) and event.get("watch_response") is None and event.get("voice_response") is not None:
        cs["fall_event"] = dict(event, watch_response=event["voice_response"])

    if cs.get("signs") is not None:
        cs["signs"] = _plain(cs["signs"])
    return cs


def evaluate(care_status: dict, month: int) -> dict:
    """CareStatusResult → 위험도, 원인, 조치 목록. Emergency Agent가 이 결과에 병원·문장을 붙인다."""
    care_status = normalize_care_status(care_status)
    causes = detect_causes(care_status)
    level = risk_level(causes, care_status.get("vulnerability"))
    indoor = indoor_state((care_status.get("env") or {}).get("temp"))
    danger = sum(1 for s in vital_scores(care_status.get("vitals")).values() if s == 3)
    _, fall_state = detect_fall(care_status, danger)
    answer_unknown = (care_status.get("fall_event") or {}).get("watch_response") is None
    ask_watch = fall_state in ("suspected", "confirmed", "critical") and answer_unknown
    auto = auto_119_reason(care_status, causes, level)
    return {
        "risk_level": level,
        "axes": axis_levels(causes),
        "fall_state": fall_state,
        "reason_codes": causes,
        "reason": reason_text(causes),
        "vital_scores": vital_scores(care_status.get("vitals")),
        "auto_119": auto,
        "actions": attach_cctv(select_actions(causes, level, month, indoor, ask_watch, auto), care_status, causes),
    }
