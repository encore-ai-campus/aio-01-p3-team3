"""
LLM 파트 → AutoHealing 전달용 계약 (초안)

상옥 님의 AutoHealing.llm()이 감싸서 쓰는 함수들입니다.
- call_writer / call_summary: LLM 호출. errors를 넘기면 JSON 교정 지시를 붙여 재요청합니다.
- validate_writer / validate_summary: (파싱된 dict 또는 None, 오류 목록)을 반환합니다.
- fallback_writer / fallback_summary: 재요청까지 실패했을 때 쓰는 템플릿 출력입니다.
  템플릿 출력도 validate_*를 통과합니다.

llm 인자는 프롬프트 문자열을 받아 응답 문자열을 돌려주는 함수입니다.
(OpenAI·Gemini 중 무엇을 쓰든 이 모양으로 감싸서 넘기면 됩니다.)

팀원과 겹치는 부분에는 "# [팀 합의] 이름: 설명" 주석을 달았습니다.

ctx (risk_rules.build_ctx가 만드는 입력):
{
  "hazard": "heat" | "cold",
  "risk_level": "주의" | "경고" | "위험",      # 관심은 HandoffGuard에서 이미 종료
  "stage_label": "한파주의보 수준",
  "vulnerability": "상" | "중" | "하",
  "max_temp": -4.0, "min_temp": -13.0, "feels_like": -20.3, "wind_ms": 4.0,
  "shelter": {"name": "OO 경로당", "distance_m": 320, "open": "09:00-18:00", "open_now": False} | None,
}
"""

import json
import re
from typing import Callable

# [팀 합의] 상옥 님: AutoHealing.llm()이 넘겨줄 LLM 호출 함수 모양. 프롬프트 문자열 → 응답 문자열.
#   호출당 시간 제한 10초(해든 결정)는 이 함수 안이나 AutoHealing 쪽 중 어디에 둘지 정해야 한다.
LLM = Callable[[str], str]

# [팀 합의] 상옥 님: 요청한 "필수 키·자료형". 이 키가 없으면 검증 실패로 보고 재요청한다.
# 필수 키와 자료형
WRITER_SCHEMA = {"actions": list, "reason": str}    # actions: 문자열 정확히 3개, 각 20자 이하
SUMMARY_SCHEMA = {"elder_message": str, "guardian_message": str}  # elder_message 90자 이하

ACTION_MAX = 20
ELDER_MAX = 90
# [팀 합의] 수언 님: 위험도 값은 한글. 프런트 COLORS 키와 같아야 한다.
CALL_LEVELS = {"경고", "위험"}  # 보호자에게 안부 전화를 권하는 위험도
MEDICAL_WORDS = ["진단", "복용", "처방", "치료", "투약", "약을", "약물"]
PLACE_WORDS = ["경로당", "주민센터", "복지관", "쉼터"]

HAZARD_GUIDE = {
    "heat": "더위 대비 행동만 쓴다 (물 마시기, 그늘·시원한 실내, 한낮 외출 줄이기).",
    "cold": "추위 대비 행동만 쓴다 (보온, 난방, 새벽·이른 아침 외출 줄이기, 빙판길 조심).",
}
HAZARD_EXAMPLE = {
    "heat": '{"actions": ["물을 자주 드세요", "한낮 외출을 줄이세요", "시원한 곳에서 쉬세요"], "reason": "폭염경보 수준 더위와 높은 취약도가 확인되었습니다."}',
    "cold": '{"actions": ["새벽 외출을 줄이세요", "모자와 장갑을 하세요", "난방을 꼭 켜 두세요"], "reason": "한파주의보 수준 추위와 중간 취약도가 확인되었습니다."}',
}
JSON_FIX = (
    "\n\n[교정 요청] 앞선 답이 형식 검사를 통과하지 못했습니다. 문제: {errors}\n"
    "설명이나 코드블록 없이 위 형식의 JSON 객체 하나만 다시 답하세요."
)


# ---------- 프롬프트와 호출 ----------

def _shelter_text(ctx: dict) -> str:
    s = ctx.get("shelter")
    if not s:
        return "없음 (쉼터를 언급하지 않는다)"
    state = "지금 운영 중" if s.get("open_now") else "지금은 운영 전 (실내에 머무르기를 먼저 안내)"
    return f"{s['name']} ({s['distance_m']}m, {s['open']}, {state})"


def writer_prompt(ctx: dict) -> str:
    return f"""너는 어르신 안전 안내문을 쓰는 도우미다. 아래 정보만 사용해 행동요령 3가지를 만든다.

[정보]
위험 종류: {"폭염" if ctx["hazard"] == "heat" else "한파"} / 위험도: {ctx["risk_level"]} ({ctx["stage_label"]})
취약도: {ctx["vulnerability"]}
최고기온: {ctx["max_temp"]}℃ / 최저기온: {ctx["min_temp"]}℃ / 체감온도: {ctx["feels_like"]}℃ / 풍속: {ctx["wind_ms"]}m/s
추천 쉼터: {_shelter_text(ctx)}

[규칙]
- 행동요령은 정확히 3개, 각 {ACTION_MAX}자 이내, 어르신이 바로 할 수 있는 행동
- {HAZARD_GUIDE[ctx["hazard"]]}
- 정보에 없는 장소나 수치는 쓰지 않는다
- 질병 진단, 약, 치료에 대한 조언은 하지 않는다
- 위험도를 바꾸거나 다시 판단하지 않는다
- reason은 위 위험도와 취약도를 근거로 한 문장으로 쓴다
- 아래 형식의 JSON 객체 하나로만 답한다. 예시는 형식만 참고하고 문장을 그대로 쓰지 않는다

[예시]
{HAZARD_EXAMPLE[ctx["hazard"]]}"""


def summary_prompt(ctx: dict, writer_out: dict) -> str:
    s = ctx.get("shelter")
    shelter = f"{s['name']} (약 {s['distance_m']}m, {s['open']})" if s else "없음 (쉼터를 언급하지 않는다)"
    call_rule = "- 보호자에게 어르신께 안부 전화를 드리라고 권한다 (\"안부 전화\"라는 말을 넣는다)" if ctx["risk_level"] in CALL_LEVELS else "- 보호자에게 어르신 상태를 한 번 확인하라고 권한다"
    return f"""아래 안전 정보를 어르신과 보호자에게 맞게 다시 쓴다.

[정보]
위험 종류: {"폭염" if ctx["hazard"] == "heat" else "한파"} / 위험도: {ctx["risk_level"]} / 근거: {ctx["stage_label"]}
행동요령: {", ".join(writer_out["actions"])}
추천 쉼터: {shelter}

[어르신용 elder_message 규칙]
- {ELDER_MAX}자 이내, 존댓말, 쉬운 말, 숫자는 최소화
- 가장 중요한 행동 하나만 강조

[보호자용 guardian_message 규칙]
- 위험도 단어("{ctx["risk_level"]}")와 근거를 포함한다
- 쉼터가 있으면 쉼터 이름을 포함한다
{call_rule}

입력에 없는 사실은 쓰지 않는다. 아래 형식의 JSON 객체 하나로만 답한다.
{{"elder_message": "...", "guardian_message": "..."}}"""


# [팀 합의] 상옥 님: 요청한 "JSON 교정 지시를 붙이는 호출 함수". 재요청 1회는 AutoHealing.llm()이 담당.
def call_writer(ctx: dict, llm: LLM, errors: list[str] | None = None) -> str:
    """첫 호출은 errors=None, 재요청은 직전 validate_writer의 오류 목록을 넘긴다."""
    prompt = writer_prompt(ctx)
    if errors:
        prompt += JSON_FIX.format(errors="; ".join(errors))
    return llm(prompt)


def call_summary(ctx: dict, writer_out: dict, llm: LLM, errors: list[str] | None = None) -> str:
    prompt = summary_prompt(ctx, writer_out)
    if errors:
        prompt += JSON_FIX.format(errors="; ".join(errors))
    return llm(prompt)


# ---------- 검증 ----------

def _parse(raw: str, schema: dict) -> tuple[dict | None, list[str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, ["JSON 파싱 실패"]
    if not isinstance(data, dict):
        return None, ["JSON 객체가 아님"]
    errors = [f"{k} 누락 또는 자료형 오류({t.__name__})" for k, t in schema.items() if not isinstance(data.get(k), t)]
    return (None, errors) if errors else (data, [])


def _allowed_numbers(ctx: dict) -> set[float]:
    nums = {ctx.get("max_temp"), ctx.get("min_temp"), ctx.get("feels_like"), ctx.get("wind_ms")}
    if ctx.get("shelter"):
        nums.add(ctx["shelter"]["distance_m"])
    allowed = set()
    for n in nums:
        if n is None:
            continue
        # "영하 13도"처럼 부호 없이 쓰거나 "-20도"처럼 반올림해 써도 입력 수치로 인정한다.
        for v in (float(n), round(float(n))):
            allowed |= {round(v, 1), round(abs(v), 1)}
    return allowed


def _content_errors(text: str, ctx: dict) -> list[str]:
    errors = []
    medical = [w for w in MEDICAL_WORDS if w in text]
    if medical:
        errors.append(f"의료 표현 사용: {medical}")
    # 숫자 검사는 기온(℃, 도)과 거리(m)에만 적용한다. 시간대 표현은 허용.
    allowed = _allowed_numbers(ctx)
    for n in re.findall(r"(-?\d+(?:\.\d+)?)\s*(?:℃|도|m|미터)", text):
        if round(float(n), 1) not in allowed:
            errors.append(f"입력에 없는 수치: {n}")
    if not ctx.get("shelter") and any(w in text for w in PLACE_WORDS[:3]):
        errors.append("쉼터 정보가 없는데 장소를 언급함")
    return errors


# [팀 합의] 상옥 님: 반환값 (결과 dict 또는 None, 오류 목록). 오류 목록은 재요청 때 call_writer(errors=...)로 넘긴다.
def validate_writer(raw: str, ctx: dict) -> tuple[dict | None, list[str]]:
    data, errors = _parse(raw, WRITER_SCHEMA)
    if data is None:
        return None, errors
    actions = data["actions"]
    if len(actions) != 3 or not all(isinstance(a, str) and a.strip() for a in actions):
        errors.append("actions는 비어 있지 않은 문자열 3개여야 함")
    else:
        errors += [f"행동요령 {ACTION_MAX}자 초과: {a}" for a in actions if len(a) > ACTION_MAX]
    if not data["reason"].strip():
        errors.append("reason이 비어 있음")
    errors += _content_errors(" ".join(map(str, actions)) + " " + data["reason"], ctx)
    return (None, errors) if errors else (data, [])


def validate_summary(raw: str, ctx: dict) -> tuple[dict | None, list[str]]:
    data, errors = _parse(raw, SUMMARY_SCHEMA)
    if data is None:
        return None, errors
    elder, guardian = data["elder_message"], data["guardian_message"]
    if not elder.strip() or len(elder) > ELDER_MAX:
        errors.append(f"elder_message는 1~{ELDER_MAX}자여야 함 (현재 {len(elder)}자)")
    if ctx["risk_level"] not in guardian:
        errors.append("guardian_message에 위험도 없음")
    if ctx.get("shelter") and ctx["shelter"]["name"] not in guardian:
        errors.append("guardian_message에 쉼터 이름 없음")
    if ctx["risk_level"] in CALL_LEVELS and "안부 전화" not in guardian:
        errors.append("경고·위험인데 안부 전화 권고 없음")
    errors += _content_errors(elder + " " + guardian, ctx)
    return (None, errors) if errors else (data, [])


# ---------- 대체 출력 (재요청까지 실패했을 때) ----------
# [팀 합의] 상옥 님: 요청한 "여름/겨울 대체 JSON". 위험도·hazard·실제 쉼터 정보와 쉼터 없음 문구를 반영.
#   이 출력을 쓰면 fallback_used = true (재요청으로 정상 회복하면 false).
# [팀 합의] 지혜 님: 날씨 캐시·쉼터 CSV 사용까지 fallback_used에 포함할지는 아직 미정.

FALLBACK_ACTIONS = {
    "heat": ["물을 자주 드세요", "한낮 외출을 줄이세요"],
    "cold": ["새벽 외출을 줄이세요", "모자와 장갑을 하세요"],
}
FALLBACK_THIRD = {  # 셋째 행동: 쉼터 상태에 따라
    ("heat", "open"): "가까운 쉼터에서 쉬세요",
    ("heat", "closed"): "시원한 실내에 계세요",
    ("heat", "none"): "시원한 실내에 계세요",
    ("cold", "open"): "가까운 쉼터에서 쉬세요",
    ("cold", "closed"): "난방을 꼭 켜 두세요",
    ("cold", "none"): "난방을 꼭 켜 두세요",
}
FALLBACK_ELDER_HEAD = {
    ("heat", False): "오늘은 더위에 주의하세요.",
    ("heat", True): "오늘은 더위가 위험합니다.",
    ("cold", False): "오늘은 추위에 주의하세요.",
    ("cold", True): "오늘은 추위가 위험합니다.",
}
FALLBACK_ELDER_TAIL = {
    ("heat", "open"): " {name}에서 쉬세요.",
    ("heat", "closed"): " 무리하지 마시고 시원한 실내에 계세요.",
    ("heat", "none"): " 무리하지 마시고 시원한 실내에 계세요.",
    ("cold", "open"): " 따뜻하게 입으시고 {name}에서 몸을 녹이세요.",
    ("cold", "closed"): " 따뜻하게 입으시고 실내에 계세요.",
    ("cold", "none"): " 따뜻하게 입으시고 실내에 계세요.",
}


def _shelter_state(ctx: dict) -> str:
    s = ctx.get("shelter")
    if not s:
        return "none"
    return "open" if s.get("open_now") else "closed"


def fallback_writer(ctx: dict) -> dict:
    hazard, state = ctx["hazard"], _shelter_state(ctx)
    return {
        "actions": FALLBACK_ACTIONS[hazard] + [FALLBACK_THIRD[(hazard, state)]],
        "reason": f"{ctx['stage_label']}, 취약도 {ctx['vulnerability']} 기준으로 위험도 {ctx['risk_level']}입니다.",
    }


def fallback_summary(ctx: dict) -> dict:
    hazard, state, s = ctx["hazard"], _shelter_state(ctx), ctx.get("shelter")
    elder = FALLBACK_ELDER_HEAD[(hazard, ctx["risk_level"] in CALL_LEVELS)]
    elder += FALLBACK_ELDER_TAIL[(hazard, state)].format(name=s["name"] if s else "")
    if len(elder) > ELDER_MAX:  # 쉼터 이름이 아주 길 때
        elder = FALLBACK_ELDER_HEAD[(hazard, ctx["risk_level"] in CALL_LEVELS)] + FALLBACK_ELDER_TAIL[(hazard, "none")]

    guardian = f"위험도 {ctx['risk_level']} ({ctx['stage_label']})."
    if state == "open":
        guardian += f" 추천 쉼터: {s['name']} (약 {s['distance_m']}m, {s['open']})."
    elif state == "closed":
        guardian += f" 추천 쉼터: {s['name']} (약 {s['distance_m']}m, {s['open']}), 지금은 운영 전입니다."
    else:
        guardian += " 근처 쉼터 정보를 찾지 못했습니다."
    guardian += " 어르신께 안부 전화를 드려 주세요." if ctx["risk_level"] in CALL_LEVELS else " 어르신 상태를 한 번 확인해 주세요."
    return {"elder_message": elder, "guardian_message": guardian}
