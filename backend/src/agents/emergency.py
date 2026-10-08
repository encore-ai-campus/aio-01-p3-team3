"""Emergency Agent: rules/risk.py로 위험도 판정(코드) + 조치안 문장(LLM) + 병원 정보 첨부 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 run_emergency()를 넣음. 계획서 8.1 순서 그대로.
#   판정(rules/risk.py) → 병원 조회 → 조치안 문장(LLM, 실패 시 템플릿) → EmergencyResult.
#   위험도와 조치 종류는 코드가 정하고, LLM은 설명 문장만 바꿀 수 있음 [D6].
# 2026-10-08 해든 (main 스키마 연결): 입구에서 normalize_care_status()로 main schemas.py 키도 읽게 함.

from datetime import datetime
from typing import Callable

from src.llm.client import LLM, generate_or_template
from src.llm.fallback import action_label
from src.llm.prompts import build_emergency_ctx
from src.rules.risk import evaluate, normalize_care_status

NO_ISSUE = {"risk_level": "정상", "reason": "이상 없음", "reason_codes": [], "actions": []}


def _hospital_text(found) -> str | None:
    """find_hospital 결과를 "○○병원 응급실 (1.2km)" 한 줄로. 문자열이면 그대로."""
    if not found:
        return None
    if isinstance(found, list):
        found = found[0]
    if isinstance(found, dict):
        name, km = found.get("name"), found.get("distance_km")
        return f"{name} ({km}km)" if name and km is not None else name
    return str(found)


# [팀 합의] 지혜 님: 오케스트레이터가 CareStatusResult를 넘기고, 이 결과를 승인 대기(approval.py)에 task_id로 저장.
#   "context"는 화면에 안 쓰고 Summary Agent가 다시 받는 값이라 함께 저장해 주세요.
# [팀 합의] 두나 님: find_hospital(area) 결과 형식. 문자열 "○○병원 응급실 (1.2km)" 또는
#   {"name": ..., "distance_km": ...} (목록이면 첫 번째)를 읽는다. area는 care_status["area"]에서 가져온다.
def run_emergency(care_status: dict, llm: LLM | None = None,
                  find_hospital: Callable[[str | None], object] | None = None,
                  month: int | None = None) -> dict:
    """CareStatusResult → EmergencyResult. llm이 None이면 템플릿 문장으로 끝까지 돈다 (키 없이 시연 가능)."""
    care_status = normalize_care_status(care_status)    # main 스키마 키도 읽음
    decision = evaluate(care_status, month or datetime.now().month)
    if decision["risk_level"] == "정상":
        return dict(NO_ISSUE, context=None, fallback_used=False, llm_log=None)

    hospital = None
    if find_hospital and any(a["type"] == "hospital_info" for a in decision["actions"]):
        try:
            hospital = _hospital_text(find_hospital(care_status.get("area")))
        except Exception:      # 병원 조회 실패는 판정에 영향 없음. 병원 정보 없이 진행
            hospital = None
    if hospital is None:       # 병원을 못 찾으면 빈 병원 조치를 화면에 내보내지 않음
        decision["actions"] = [a for a in decision["actions"] if a["type"] != "hospital_info"]

    ctx = build_emergency_ctx(care_status, decision, hospital)
    out, log = generate_or_template("emergency", ctx, llm)
    actions = [dict(a, label=action_label(a), text=text) for a, text in zip(ctx["actions"], out["action_texts"])]
    return {
        "risk_level": decision["risk_level"],
        "reason": out["reason"],
        "reason_codes": decision["reason_codes"],
        "actions": actions,
        "hospital": hospital,
        "context": dict(ctx, reason=out["reason"]),
        "fallback_used": log["fallback_used"],
        "llm_log": log,
    }
