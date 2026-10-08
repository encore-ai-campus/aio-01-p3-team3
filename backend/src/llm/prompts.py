"""Emergency 조치안, Summary 프롬프트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 프롬프트, 입력(ctx) 만들기, 검증 함수를 넣음.
#   - 출처: notes/llm_contract.py의 틀(프롬프트 → 검증 → JSON 교정 재요청 → 템플릿)을 그대로 쓰고 내용을 바꿈.
#     writer → emergency, 날씨·쉼터 → 바이탈·실내·CCTV·병원, 숫자 단위 ℃·m → 회/분·mmHg·℃·%·km.
#   - 기준: 계획서 4장, 8.4 Emergency 프롬프트, 8.5 Summary 프롬프트, 8.7 검증 표, 결정 D6·D7.
#   - CCTV 분석 프롬프트는 여기가 아니라 mcp_server/src/vision/prompt.py에 둠 (4단계).
#   - LLM 호출은 llm/client.py(3단계). 여기 함수는 문자열을 만들고 검사만 함.
# 2026-10-08 해든 (4단계): 낙상 상태(의심/확인/위급)를 프롬프트에 넣고, "관찰 사실만 전달" 규칙과
#   골절·뇌진탕 같은 진단 단어 금지를 추가함.
# 2026-10-08 해든 (실제 호출 점검): gpt-4.1-mini로 시나리오 5개를 실제 호출해 보니 검증은 다 통과했지만 내용 문제 3개가 보여 막음.
#   ① 승인이 필요 없는 조치 설명에 "승인", "동의"를 씀 → 조치 목록에 [승인 필요]/[승인 없음]을 붙이고 검증
#   ② 일어나지 않은 일을 씀("이송 중", "병원으로 이동 중") → 금지 표현 검사 (UNDONE_WORDS)
#   ③ 거절을 "조치를 시도했으나 실패"라고 씀 → 거절이면 "거절"을 쓰고 "실패", "시도"를 못 쓰게 함
# 2026-10-08 해든 (승인·119 흐름): 조치 목록에 [자동 실행]/[승인 필요, N초 응답 없으면 자동 연결] 표시.
#   Summary 상황 auto_119·timeout_119·info(승인할 조치 없음) 추가. 실행 결과 조치 이름에 냉방·난방·목표 온도를 다시 붙임. 이때 "승인하신"처럼 보호자가 승인한 것처럼 쓰지 못하게 검증.
# 2026-10-08 해든 (말투): 어르신 문장은 다정한 간호사 말투("어르신,"으로 시작, 챙기는 한 마디), 위급은 단호하게.
#   검증 추가: 어르신 문장에 "어르신"·겁주는 말 금지·119면 "움직이지 말고" 같은 지시, 위급 보호자 문장에 흐린 말 금지.
# 2026-10-08 해든 (현실 상황 20개 실제 점검): 실제 문장에서 나온 문제를 막음. 결과: notes/llm_realistic_check_result.md
#   ① 보호자에게 "병원으로 이동 준비하세요"처럼 추측한 할 일 → 보호자 할 일(next_step)을 코드가 정하고 그대로 쓰게 함
#   ② 음성 응답이 없는데 "낙상 의심과 무응답" (프롬프트 예시를 베낌) → 예시 바꾸고, 무응답 코드가 없으면 "무응답" 금지
#   ③ 보호자에게 "보호자에게 알렸습니다", 스피커로 말만 걸었는데 "상태 확인 성공·안정적" → 알림은 실행 결과에서 빼고 스피커는 "말을 걸었음(응답 모름)"
#   ④ 기기 실패인데 어르신께 "시원하게 해 드릴게요" (지키지 못할 약속) → 솔직하게 말하고 직접 하실 일(창문·담요·인덕션 끄기) 안내
#   ⑤ 거절이면 어르신께 아무 말도 안 감 → "보호자분께 알려 드렸어요, 곧 연락드릴 거예요" (ELDER_MESSAGE_ON_REJECT)
# 2026-10-08 해든 (워치 버튼): 스피커로 말 걸기 대신 워치에 "괜찮으세요?"를 띄우고 버튼으로 응답 받음 (watch_check, watch_response).
# 2026-10-08 해든 (현실 상황 2차 점검): ① 조치가 많은 위급 거절(S15)에서 보호자 문장이 120자를 넘어 템플릿으로 감
#   → 프롬프트에 next_step을 뺀 앞부분 글자 수와 "수치는 2개까지"를 알려 줌.
#   ② 체온 39.3℃인데 어르신께 열 이야기가 없음(S19) → 체온 원인이면 어르신이 하실 일(ELDER_CARE_TIP)을 넣고 검증.
# 2026-10-08 해든 (시연 시나리오 확정안): 기기 상태 구조 형식을 "켜짐 120분 300℃"로 프롬프트에 넣고, 그 숫자를 허용 수치에 넣음.
#
# 팀원과 겹치는 부분에는 "# [팀 합의] 이름: 설명" 주석을 달았음.

import json
import re

from src.llm.fallback import DEVICE_LABEL, ELDER_MESSAGE_ON_REJECT, action_label
from src.rules.risk import CAUSE_LABEL, VITAL_LABEL

REASON_MAX = 60          # Emergency 판정 근거
ACTION_TEXT_MAX = 30     # Emergency 조치 설명 하나
GUARDIAN_MAX = 120       # Summary 보호자용
# [팀 합의] 수언 님: 화면 문장 길이. 어르신 문장이 40 → 60자로 늘어남 (다정한 말투에 한 마디 더). 카드 줄바꿈 확인 부탁.
ELDER_MAX = 60           # Summary 어르신용

# 진단명·약·확진 표현. 판단은 "의심" 수준으로만 쓴다 (README 8장).
MEDICAL_WORDS = ["진단", "처방", "복용", "투약", "약을", "약물", "치료",
                 "뇌졸중", "심근경색", "심정지", "골절", "뇌진탕", "뇌출혈", "열사병", "저체온증", "폐렴"]
CONFIRM_WORDS = ["쓰러졌", "사망", "의식 없", "의식이 없", "숨을 쉬지"]
CCTV_WORDS = ["CCTV", "영상", "카메라", "화면"]
# 실행 결과에 없는 일을 이미 일어난 것처럼 쓰는 표현 (119에 연락한 것과 구급차가 이송 중인 것은 다름)
UNDONE_WORDS = ["이송", "이동 중", "이동하고", "도착했", "출동했", "병원에 도착", "입원", "진료를 받"]
APPROVAL_WORDS = ["승인", "동의"]
# 보호자에게 보내는 글에서 쓰지 않는 말: 자기 자신에게 알렸다는 말, 확인 안 된 추측
GUARDIAN_SELF_WORDS = ["보호자에게", "보호자께", "보호자님께"]
GUARDIAN_GUESS_WORDS = ["병원으로", "병원 도착", "안정적", "이상 없"]
NO_RESPONSE_WORDS = ["무응답", "응답하지 않", "대답이 없", "대답하지 않"]
# 기기 제어가 실패했는데 어르신께 하면 안 되는 말 (지키지 못할 약속, 된 것처럼)
DEVICE_FAIL_PROMISE_WORDS = ["해 드릴게요", "켜 두었", "꺼 두었", "껐어요", "켰어요"]
# 기기 제어가 실패했을 때 어르신이 직접 하실 일 (안내 문장, 꼭 들어갈 단어)
ELDER_TIP = {
    "cool": ("에어컨이 켜지지 않았어요. 창문을 열고 물을 자주 드세요.", ["창문", "물"]),
    "heat": ("난방이 켜지지 않았어요. 옷을 겹쳐 입고 담요를 덮으세요.", ["옷", "담요"]),
    "induction": ("인덕션이 아직 켜져 있어요. 주방에 가시면 꼭 꺼 주세요.", ["꺼"]),
}
# 체온 원인일 때 어르신이 하실 일 (알림만 가거나 조치가 끝났을 때). 진단·약 이야기는 하지 않음.
ELDER_CARE_TIP = {
    "fever": ("열이 조금 있어요. 물을 자주 드시고 시원하게 누워 쉬세요.", ["물", "쉬"]),
    "cold_body": ("몸이 차가워요. 담요를 덮고 따뜻한 물을 천천히 드세요.", ["담요", "따뜻"]),
}
FEVER_FROM, COLD_BODY_TO = 37.5, 35.9      # 체온 원인일 때 열·저체온 안내를 고르는 기준


def next_step(situation: str, level: str, called_119: bool) -> str:
    """보호자가 지금 할 일. LLM이 추측하지 않게 코드가 정하고 문장 끝에 그대로 쓰게 한다."""
    urgent = level in ("위급", "경고")
    if called_119 or (situation == "done" and level == "위급"):
        return "지금 바로 어르신께 전화해 상태를 확인하세요."
    if situation == "rejected":
        return "지금 바로 어르신께 직접 연락해 상태를 확인하세요." if level == "위급" else "어르신께 직접 연락해 상태를 확인해 주세요."
    if situation == "device_fail":
        return "지금 바로 어르신께 연락하세요." if urgent else "어르신께 연락해 주세요."
    if situation == "info":
        return "지금 바로 어르신께 전화해 상태를 확인하세요." if urgent else "어르신께 안부 전화로 상태를 확인해 주세요."
    return "잠시 뒤 어르신 상태를 한 번 더 확인해 주세요."

# 숫자 검사를 하는 단위. "119" 같은 단위 없는 숫자는 검사하지 않는다.
NUMBER_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:회/분|회|mmHg|℃|도|%|km|m(?![a-zA-Z]))")

JSON_FIX = (
    "\n\n[교정 요청] 앞선 답이 형식 검사를 통과하지 못했습니다. 문제: {errors}\n"
    "설명이나 코드블록 없이 위 형식의 JSON 객체 하나만 다시 답하세요."
)

# [팀 합의] 상옥 님: 필수 키와 자료형. 이 키가 없거나 형식이 다르면 검증 실패로 보고 재요청 1회.
# llm/client.py가 구조화 출력(strict)에 쓰는 스키마와 같은 키.
EMERGENCY_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "action_texts": {"type": "array", "items": {"type": "string"}}},
    "required": ["reason", "action_texts"],
    "additionalProperties": False,
}
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"guardian_message": {"type": "string"}, "elder_message": {"type": "string"}},
    "required": ["guardian_message", "elder_message"],
    "additionalProperties": False,
}


# ---------- 입력(ctx) 만들기 ----------

# [팀 합의] 지혜 님: care_status = CareStatusResult, decision = rules.risk.evaluate() 결과,
#   hospital = find_hospital 결과 문자열 (예: "○○병원 응급실 (1.2km)") 또는 None.
def build_emergency_ctx(care_status: dict, decision: dict, hospital: str | None = None) -> dict:
    vitals = care_status.get("vitals") or {}
    cctv = care_status.get("cctv") or {}
    actions = [dict(a, value=hospital) if a["type"] == "hospital_info" else a for a in decision["actions"]]
    if not any(a["type"] == "hospital_info" for a in actions):
        hospital = None     # 병원 조치가 없으면 프롬프트에도 넣지 않음 (입력에 없는 장소 금지)
    return {
        "risk_level": decision["risk_level"],
        "fall_state": decision.get("fall_state", "none"),
        "reason_codes": decision["reason_codes"],
        "code_reason": decision["reason"],
        "vitals": {k: vitals.get(k) for k in VITAL_LABEL},
        "measured_at": vitals.get("measured_at"),
        "stale": vitals.get("source") == "cache",
        "env_temp": (care_status.get("env") or {}).get("temp"),
        "devices": care_status.get("devices") or {},
        "cctv_description": cctv.get("description") if cctv.get("available", True) else None,
        "vulnerability": care_status.get("vulnerability") or "상",
        "actions": actions,
        "hospital": hospital,
    }


# [팀 합의] 지혜 님: executed 형식은 README 응답 2와 같게 [{"action": "call_119", "result": "success"}].
#   기기 제어는 어떤 기기였는지 알아야 하므로 {"action": "control_device", "device": "aircon", ...}처럼 device를 넣어 주세요.
def build_summary_ctx(emergency_ctx: dict, approved: bool, executed: list[dict] | None,
                      decided_by: str = "guardian") -> dict:
    """decided_by: guardian(보호자 승인·거절) / auto(119 바로 연결) / timeout(보호자 무응답으로 자동 연결)."""
    planned = emergency_ctx.get("actions", [])
    # 보호자 알림은 이 안내문 자체라서 실행 결과에 넣지 않음 ("보호자에게 알렸습니다"를 보호자에게 쓰지 않게)
    executed = [e for e in executed or [] if e.get("action") != "notify_guardian"]
    labels, values = [], []
    for e in executed:
        # 조치안에 있던 같은 조치의 값(냉방·난방, 목표 온도)을 가져와 "에어컨 난방 20℃로 켜기"처럼 씀
        same = next((a for a in planned if a["type"] == e["action"] and
                     (a.get("value") or {}).get("device") == e.get("device")), None) if e.get("device") else None
        value = dict(same["value"]) if same else ({"device": e.get("device")} if e.get("device") else {})
        if e["action"] == "control_device" and e.get("device") == "induction":
            value["action"] = "off"
        labels.append(action_label({"type": e["action"], "value": value}))
        values.append(value)
    ok = [(e, l) for e, l in zip(executed, labels) if e.get("result") == "success"]
    failed = [l for e, l in zip(executed, labels) if e.get("result") != "success"]
    auto_119 = next((a for a in emergency_ctx.get("actions", []) if a["type"] == "call_119" and a.get("auto")), None)
    called = any(e["action"] == "call_119" for e, _ in ok)
    if decided_by == "timeout" and called and not failed:
        situation = "timeout_119"
    elif (decided_by == "auto" or auto_119) and called and not failed:
        situation = "auto_119"      # 조치안에 119 바로 연결이 있었으면 decided_by를 안 넘겨도 auto로 봄
    elif failed:
        situation = "device_fail"
    elif not approved:
        situation = "rejected"
    elif not any(a.get("needs_approval") for a in planned):
        situation = "info"      # 승인할 조치가 없었음 (알림·워치 확인만)
    else:
        situation = "done"
    tip = None
    if situation == "device_fail":
        for e, v in zip(executed, values):
            if e.get("result") != "success" and e["action"] == "control_device":
                key = "induction" if v.get("device") == "induction" else v.get("mode", "cool")
                tip = ELDER_TIP.get(key)
                break
    care = None
    temp = (emergency_ctx.get("vitals") or {}).get("temp")
    # 119·기기 제어를 한 경우는 그 안내(움직이지 마세요, 에어컨 켰어요)가 우선이라 넣지 않음
    acted = any(e["action"] in ("call_119", "control_device") for e, _ in ok)
    if situation in ("info", "done") and not acted and temp is not None and \
            any(c.startswith("BODY_TEMP") for c in emergency_ctx.get("reason_codes", [])):
        care = ELDER_CARE_TIP["fever"] if temp >= FEVER_FROM else ELDER_CARE_TIP["cold_body"] if temp <= COLD_BODY_TO else None
    return {
        "situation": situation,
        "auto_reason": "GUARDIAN_TIMEOUT" if situation == "timeout_119" else
                       ((auto_119 or {}).get("auto_reason") if situation == "auto_119" else None),
        "risk_level": emergency_ctx["risk_level"],
        "reason": emergency_ctx.get("reason") or emergency_ctx["code_reason"],
        "executed": [_executed_text(e, l) for e, l in zip(executed, labels)],
        "reason_codes": emergency_ctx.get("reason_codes", []),
        "next_step": next_step(situation, emergency_ctx["risk_level"], called and not failed),
        "elder_tip": tip,
        "elder_care": care,
        "succeeded_types": [e["action"] for e, _ in ok],
        "succeeded_labels": [l for _, l in ok],
        "failed_labels": failed,
        "hospital": emergency_ctx.get("hospital"),
        "cctv_description": emergency_ctx.get("cctv_description"),
        "allowed_numbers": _allowed_numbers(emergency_ctx),
    }


def _executed_text(e: dict, label: str) -> str:
    if e.get("result") != "success":
        return f"{label}: 실패"
    if e["action"] == "watch_check":     # 말을 건 것이지 어르신이 괜찮다는 뜻이 아님
        return "워치로 괜찮은지 묻기: 했음 (어르신 응답은 아직 모름)"
    return f"{label}: 성공"


# ---------- 프롬프트 ----------

def _vital_text(ctx: dict) -> str:
    v = ctx["vitals"]
    unit = {"hr": "회/분", "sbp": "mmHg", "temp": "℃", "spo2": "%"}
    parts = [f"{VITAL_LABEL[k]} {v[k]}{unit[k]}" if v[k] is not None else f"{VITAL_LABEL[k]} 없음" for k in VITAL_LABEL]
    note = f" ({ctx['measured_at']} 측정, 이전 측정값)" if ctx["stale"] else ""
    return ", ".join(parts) + note


FALL_STATE_TEXT = {"none": "낙상 신호 없음", "false_alarm": "낙상 감지 후 괜찮은 모습 확인(오탐 가능)",
                   "suspected": "낙상 의심(아직 확인 안 됨)", "confirmed": "쓰러짐 의심이 분명함",
                   "critical": "쓰러짐 의심 + 위급 신호"}


def _approval_tag(a: dict) -> str:
    if a.get("auto"):
        return "승인 없음, 이미 바로 연결함"
    if not a.get("needs_approval"):
        return "승인 없음, 바로 실행"
    if a.get("on_timeout") == "execute":
        return f"승인 필요, {a['timeout_seconds']}초 응답 없으면 자동 연결"
    return "승인 필요"


def _device_text(value) -> str:
    """{"state": "on", "minutes": 120, "temperature": 300} → "켜짐 120분 300℃". 예전 문자열은 그대로."""
    if not isinstance(value, dict):
        return str(value)
    text = {"on": "켜짐", "off": "꺼짐"}.get(value.get("state"), "상태 모름")
    if value.get("state") == "on":
        text += f" {value['minutes']}분" if value.get("minutes") else ""
        text += f" {value['temperature']}℃" if value.get("temperature") else ""
    return text


def emergency_prompt(ctx: dict, errors: list[str] | None = None) -> str:
    """첫 호출은 errors=None, 재요청은 직전 validate_emergency의 오류 목록을 넘긴다."""
    causes = ", ".join(CAUSE_LABEL[c] for c in ctx["reason_codes"]) or "없음"
    devices = ", ".join(f"{DEVICE_LABEL.get(k, k)} {_device_text(v)}" for k, v in ctx["devices"].items()) or "정보 없음"
    actions = "\n".join(f"{i}. {action_label(a)} [{_approval_tag(a)}]" for i, a in enumerate(ctx["actions"], 1))
    prompt = f"""너는 떨어져 사는 보호자에게 어르신 상황을 설명하는 도우미다.
위험도와 조치 목록은 이미 정해졌다. 바꾸거나 더하거나 빼지 않는다.

[입력]
위험도: {ctx["risk_level"]}
낙상 판정: {FALL_STATE_TEXT[ctx.get("fall_state", "none")]}
판정 원인: {causes}
바이탈: {_vital_text(ctx)}
실내 온도: {ctx["env_temp"] if ctx["env_temp"] is not None else "정보 없음"}℃ / 기기: {devices}
CCTV: {ctx["cctv_description"] or "영상 판단 불가"}
취약도: {ctx["vulnerability"]}
조치 목록:
{actions}
병원: {ctx["hospital"] or "없음"}

[규칙]
- reason: 판정 근거 한 문장, {REASON_MAX}자 이내. 입력에 있는 수치만 쓴다.
- action_texts: 조치 목록과 같은 개수({len(ctx["actions"])}개), 같은 순서. 각 {ACTION_TEXT_MAX}자 이내로 보호자가 승인할지 판단할 수 있게 쓴다.
  [승인 없음] 조치에는 "승인", "동의"를 쓰지 않는다. 무엇을 하는지만 쓴다.
- 진단명, 약, 확진 표현("쓰러졌다")을 쓰지 않는다. CCTV 내용은 "~로 보입니다", "의심"으로 쓴다.
- 골절, 뇌진탕, 의식 상태처럼 사진으로 알 수 없는 것은 추측하지 않는다. "CCTV에서 바닥에 누운 모습이 보여 낙상이 의심됩니다"처럼 관찰 사실만 쓴다.
  판정 원인에 "워치 확인 무응답"이 없으면 "무응답"이라고 쓰지 않는다.
{TONE_RULE}
- JSON으로만 답한다: {{"reason": "...", "action_texts": ["..."]}}"""
    return prompt + (JSON_FIX.format(errors="; ".join(errors)) if errors else "")


SITUATION_TEXT = {"done": "보호자가 승인했고 조치를 실행함", "device_fail": "보호자가 승인했지만 일부 조치가 실패함",
                  "rejected": "보호자가 조치를 거절함",
                  "info": "승인이 필요한 조치는 없었고, 보호자 알림·워치 확인만 함",
                  "auto_119": "보호자 승인을 기다리지 않고 119에 바로 연락함",
                  "timeout_119": "보호자가 정해진 시간 안에 응답하지 않아 119에 자동으로 연락함"}
AUTO_WHY_TEXT = {"ELDER_NO_RESPONSE": "어르신이 워치 확인에 응답하지 않음",
                 "VITAL_SEVERE": "바이탈 여러 항목이 매우 위험함", "GUARDIAN_TIMEOUT": "보호자 응답 없음"}
# 어르신께 겁을 주는 말 (혼자 계신 분)
ELDER_FEAR_WORDS = ["위험", "위급", "쓰러", "낙상", "사고", "응급"]
# 119에 연락했을 때 어르신께 꼭 줄 지시
ELDER_STAY_WORDS = ["움직이지", "그대로 계세요", "기다려"]
# 위급할 때 보호자 문장에 쓰지 않는 흐린 말
HEDGE_WORDS = ["좋겠습니다", "것 같습니다", "것 같아요", "혹시", "가능하면", "여유"]
TONE_RULE = """- 말투: 위험도가 위급이면 단호하고 짧게 쓴다. 무슨 일인지 먼저, 보호자가 할 일은 "지금 바로 ~하세요"로 분명히 쓴다.
  "~면 좋겠습니다", "~것 같습니다", "혹시", "가능하면" 같은 흐린 말을 쓰지 않는다. 주의·경고면 차분하고 정중하게 쓴다."""
# 보호자가 승인하지 않았는데 승인한 것처럼 쓰는 표현
APPROVED_WORDS = ["승인하신", "승인 후", "승인하에", "승인대로", "승인에 따라", "승인해 주셔서"]


def summary_prompt(ctx: dict, errors: list[str] | None = None) -> str:
    elder_rule = _elder_rule(ctx)
    prompt = f"""너는 조치 결과를 보호자와 어르신에게 알리는 도우미다.

[입력]
상황: {SITUATION_TEXT[ctx["situation"]]}{(" (이유: " + AUTO_WHY_TEXT.get(ctx.get("auto_reason"), "") + ")") if ctx.get("auto_reason") else ""}
위험도: {ctx["risk_level"]}, 판정 근거: {ctx["reason"]}
실행 결과: {", ".join(ctx["executed"]) or "없음"}
병원: {ctx["hospital"] or "없음"}, CCTV 설명: {ctx["cctv_description"] or "없음"}

[규칙]
- guardian_message: {GUARDIAN_MAX}자 이내. 떨어져 사는 보호자에게 보내는 글이다. 무슨 일인지와 한 일을 쓰고,
  마지막 문장은 반드시 이 문장을 그대로 쓴다: "{ctx["next_step"]}"
  그 앞부분은 {GUARDIAN_MAX - len(ctx["next_step"]) - 1}자 이내로 쓴다. 수치는 가장 중요한 것 2개까지만 쓴다.
  실패한 조치는 "실패"라고 쓰고 "직접 조치가 필요합니다"를 넣는다. 성공하지 않은 조치를 완료라고 쓰지 않는다.
  실행 결과에 없는 일(구급차 이송, 병원 이동·도착, 진료)과 추측("안정적", "병원으로 가세요")을 쓰지 않는다. 119는 "연락했습니다"까지만 쓴다.
  "보호자에게 알렸습니다"처럼 보호자 자신에게 알렸다는 말을 쓰지 않는다.
  워치는 "괜찮은지 물었다"까지만 쓴다. 어르신이 괜찮은지는 아직 모른다.
  CCTV 내용은 "~로 보입니다"로 쓰고 "확인했다"고 쓰지 않는다.
  판정 근거에 워치 무응답이 없으면 "무응답"이라고 쓰지 않는다.
  거절이면 "보호자 거절"로 조치하지 않았다고 쓴다. 거절을 "시도", "실패"로 쓰지 않는다.
  승인할 조치가 없었으면(알림·워치 확인만) "승인"이라는 말을 쓰지 않는다.
  119에 바로·자동으로 연락했으면 그 이유(어르신 응답 없음 등)를 쓰고 "119에 연락했습니다"를 넣는다. 보호자가 승인한 것처럼 쓰지 않는다.
{TONE_RULE}
{elder_rule}
- 입력에 없는 사실과 수치는 쓰지 않는다. 진단명, 약은 쓰지 않는다.
- JSON으로만 답한다: {{"guardian_message": "...", "elder_message": "..."}}"""
    return prompt + (JSON_FIX.format(errors="; ".join(errors)) if errors else "")


def _elder_rule(ctx: dict) -> str:
    if ctx["situation"] == "rejected" and not ELDER_MESSAGE_ON_REJECT:
        return '- elder_message: 빈 문자열 "" (거절이라 어르신께 보내지 않는다).'
    common = f"""- elder_message: {ELDER_MAX}자 이내. 혼자 계신 어르신이 듣거나 읽는다.
  다정한 간호사가 챙기듯 "어르신,"으로 시작하고 부드러운 존댓말로 쓴다.
  수치·CCTV·영상·병명과 "위험", "위급", "쓰러", "낙상", "사고", "응급"을 쓰지 않는다."""
    if ctx["situation"] == "rejected":
        return common + """
  보호자분께 알려 드렸고 곧 연락드릴 거라고 안심시킨다. 조치 이야기는 하지 않는다.
  예: "어르신, 보호자분께 상황을 알려 드렸어요. 곧 연락드릴 거예요.\""""
    if "call_119" in ctx["succeeded_types"]:
        return common + """
  119에 연락했으니 짧고 분명하게, 움직이지 말고 기다리시라고 한다.
  예: "어르신, 구급대가 오고 있어요. 보호자분께도 알렸어요. 움직이지 말고 그대로 계세요.\""""
    if ctx.get("elder_tip"):
        return common + f"""
  기기가 켜지거나 꺼지지 않았다. 된 것처럼 쓰거나 "~해 드릴게요"처럼 약속하지 않는다. 솔직하게 말하고 이렇게 하시라고 안내한다:
  "{ctx["elder_tip"][0]}\""""
    if ctx.get("elder_care"):
        return common + f"""
  지금 하실 일로 이 내용을 다정하게 안내한다: "{ctx["elder_care"][0]}\""""
    return common + """
  한 일과 지금 하실 일 하나를 쓴다. 예: "어르신, 시원하게 에어컨을 켜 두었어요. 물 한 잔 천천히 드세요.\""""


# ---------- 검증 ----------

def _parse(raw: str, keys: dict) -> tuple[dict | None, list[str]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, ["JSON 파싱 실패"]
    if not isinstance(data, dict):
        return None, ["JSON 객체가 아님"]
    errors = [f"{k} 누락 또는 자료형 오류({t.__name__})" for k, t in keys.items() if not isinstance(data.get(k), t)]
    return (None, errors) if errors else (data, [])


def _allowed_numbers(ctx: dict) -> set[float]:
    """입력에 있는 수치. 반올림해 써도 인정한다."""
    nums = [v for v in ctx.get("vitals", {}).values() if v is not None]
    if ctx.get("env_temp") is not None:
        nums.append(ctx["env_temp"])
    for d in (ctx.get("devices") or {}).values():      # 인덕션 120분·300℃ 같은 기기 값
        if isinstance(d, dict):
            nums += [d[k] for k in ("minutes", "temperature") if isinstance(d.get(k), (int, float))]
    for a in ctx.get("actions", []):
        if isinstance(a.get("value"), dict) and a["value"].get("target") is not None:
            nums.append(a["value"]["target"])
    nums += [float(n) for n in re.findall(r"\d+(?:\.\d+)?", ctx.get("hospital") or "")]
    return {round(x, 1) for n in nums for x in (float(n), round(float(n)))}


def _no_response_errors(text: str, codes: list[str], auto_reason: str | None = None) -> list[str]:
    """워치 무응답이 판정에 없는데 "무응답"이라고 쓰면 오류 (보호자 무응답 문장은 제외)."""
    if "WATCH_NO_RESPONSE" in codes or auto_reason == "ELDER_NO_RESPONSE":
        return []
    found = [w for w in NO_RESPONSE_WORDS if w in text.replace("보호자 응답", "")]
    return [f"어르신 워치 무응답이 판정에 없는데 씀: {found}"] if found else []


def _content_errors(text: str, allowed: set[float]) -> list[str]:
    errors = []
    medical = [w for w in MEDICAL_WORDS if w in text]
    if medical:
        errors.append(f"진단·약 표현 사용: {medical}")
    confirm = [w for w in CONFIRM_WORDS if w in text]
    if confirm:
        errors.append(f"확진 표현 사용: {confirm} (\"의심\", \"~로 보입니다\"로 쓸 것)")
    for n in NUMBER_UNIT.findall(text):
        if round(float(n), 1) not in allowed:
            errors.append(f"입력에 없는 수치: {n}")
    return errors


# [팀 합의] 상옥 님: 반환값 (결과 dict 또는 None, 오류 목록). 오류 목록은 재요청 때 emergency_prompt(errors=...)로 넘긴다.
def validate_emergency(raw: str, ctx: dict) -> tuple[dict | None, list[str]]:
    data, errors = _parse(raw, {"reason": str, "action_texts": list})
    if data is None:
        return None, errors
    reason, texts = data["reason"].strip(), data["action_texts"]
    if not reason or len(reason) > REASON_MAX:
        errors.append(f"reason은 1~{REASON_MAX}자여야 함 (현재 {len(reason)}자)")
    if len(texts) != len(ctx["actions"]):
        errors.append(f"action_texts는 조치 개수와 같은 {len(ctx['actions'])}개여야 함 (현재 {len(texts)}개)")
    for t in texts:
        if not isinstance(t, str) or not t.strip() or len(t) > ACTION_TEXT_MAX:
            errors.append(f"조치 설명은 1~{ACTION_TEXT_MAX}자 문자열이어야 함: {t!r}")
    for a, t in zip(ctx["actions"], texts):
        if not a.get("needs_approval") and isinstance(t, str) and any(w in t for w in APPROVAL_WORDS):
            errors.append(f'승인이 필요 없는 조치({action_label(a)})에 "승인·동의"를 씀: {t!r}')
    errors += _no_response_errors(reason + " " + " ".join(map(str, texts)), ctx.get("reason_codes", []))
    if ctx["risk_level"] == "위급":
        hedge = [w for w in HEDGE_WORDS if w in reason + " ".join(map(str, texts))]
        if hedge:
            errors.append(f"위급인데 흐린 말을 씀: {hedge} (단호하게)")
    errors += _content_errors(reason + " " + " ".join(map(str, texts)), _allowed_numbers(ctx))
    return (None, errors) if errors else (data, [])


def validate_summary(raw: str, ctx: dict) -> tuple[dict | None, list[str]]:
    data, errors = _parse(raw, {"guardian_message": str, "elder_message": str})
    if data is None:
        return None, errors
    guardian, elder = data["guardian_message"].strip(), data["elder_message"].strip()
    if not guardian or len(guardian) > GUARDIAN_MAX:
        errors.append(f"guardian_message는 1~{GUARDIAN_MAX}자여야 함 (현재 {len(guardian)}자)")
    if ctx["situation"] == "rejected" and not ELDER_MESSAGE_ON_REJECT:
        if elder:
            errors.append("거절이면 elder_message는 빈 문자열이어야 함")
    else:
        if not elder or len(elder) > ELDER_MAX:
            errors.append(f"elder_message는 1~{ELDER_MAX}자여야 함 (현재 {len(elder)}자)")
        if re.search(r"\d", elder) and "119" not in elder:
            errors.append("elder_message에 수치를 쓰지 않음")
        if any(w in elder for w in CCTV_WORDS):
            errors.append("elder_message에 CCTV·영상을 언급하지 않음")
        if "어르신" not in elder:
            errors.append('elder_message는 "어르신,"으로 부르며 시작')
        fear = [w for w in ELDER_FEAR_WORDS if w in elder]
        if fear:
            errors.append(f"elder_message에 겁주는 말을 씀: {fear}")
        if "call_119" in ctx["succeeded_types"] and not any(w in elder for w in ELDER_STAY_WORDS):
            errors.append('119에 연락했으면 elder_message에 "움직이지 말고 그대로 계세요"처럼 지시를 넣음')
        if ctx.get("elder_tip"):
            promise = [w for w in DEVICE_FAIL_PROMISE_WORDS if w in elder]
            if promise:
                errors.append(f"기기 제어가 실패했는데 어르신께 된 것처럼·약속처럼 씀: {promise}")
            if not any(w in elder for w in ctx["elder_tip"][1]):
                errors.append(f'기기 제어가 실패했으면 어르신이 하실 일을 안내: "{ctx["elder_tip"][0]}"')
        if ctx.get("elder_care") and not any(w in elder for w in ctx["elder_care"][1]):
            errors.append(f'체온 원인이면 어르신이 하실 일을 안내: "{ctx["elder_care"][0]}"')
    if ctx.get("next_step") and ctx["next_step"] not in guardian:
        errors.append(f'guardian_message 마지막에 "{ctx["next_step"]}"를 그대로 넣어야 함')
    for words, what in ((GUARDIAN_SELF_WORDS, "보호자 자신에게 알렸다는 말"), (GUARDIAN_GUESS_WORDS, "확인 안 된 추측")):
        found = [w for w in words if w in guardian]
        if found:
            errors.append(f"guardian_message에 {what}을 씀: {found}")
    errors += _no_response_errors(guardian, ctx.get("reason_codes", []), ctx.get("auto_reason"))
    undone = [w for w in UNDONE_WORDS if w in guardian + " " + elder]
    if undone:
        errors.append(f"실행 결과에 없는 일을 씀: {undone} (119는 \"연락했습니다\"까지만)")
    if ctx["situation"] == "rejected":
        if "거절" not in guardian:
            errors.append('거절이면 guardian_message에 "거절"을 넣어야 함')
        if "실패" in guardian or "시도" in guardian:
            errors.append('거절을 "시도", "실패"로 쓰지 않음')
    if ctx["risk_level"] == "위급":
        hedge = [w for w in HEDGE_WORDS if w in guardian]
        if hedge:
            errors.append(f"위급인데 guardian_message에 흐린 말을 씀: {hedge} (단호하게)")
        if "지금" not in guardian and "바로" not in guardian:
            errors.append('위급이면 guardian_message에 "지금 바로 ~하세요"처럼 할 일을 분명히 씀')
    if ctx["situation"] == "info" and "승인" in guardian:
        errors.append('승인할 조치가 없었는데 "승인"을 씀')
    if ctx["situation"] in ("auto_119", "timeout_119"):
        if "119" not in guardian or "연락" not in guardian:
            errors.append('119 자동 연결이면 guardian_message에 "119"와 "연락"을 넣어야 함')
        said = [w for w in APPROVED_WORDS if w in guardian]
        if said:
            errors.append(f"보호자가 승인하지 않았는데 승인한 것처럼 씀: {said}")
    if ctx["failed_labels"] and not ("실패" in guardian and "직접 조치" in guardian):
        errors.append('실패한 조치가 있으면 guardian_message에 "실패"와 "직접 조치가 필요합니다"를 넣어야 함')
    errors += _content_errors(guardian + " " + elder, ctx["allowed_numbers"])
    return (None, errors) if errors else (data, [])
