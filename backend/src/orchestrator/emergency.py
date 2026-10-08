"""Orchestration 2 (앞부분): Emergency Agent → 스키마 EmergencyResult 변환 — 기화
(Approval Gate 이후 Action 실행 → Summary는 ⑤ 지혜 님)

해든 님 run_emergency()가 위험도·조치 종류(코드)와 문장(LLM, 실패 시 템플릿)을 만든다.
이 파일은 ① 병원 정보를 MCP로 미리 받아 넘기고 ② LLM 장애 주입과 로그를 붙이고
③ 결과를 schemas.py의 EmergencyResult 형식으로 바꾼다.
"""

import asyncio
from datetime import datetime

from src import mcp_client
from src.agents.emergency import run_emergency
from src.healing.faults import Faults
from src.llm.client import make_llm
from src.rules.risk import CAUSE_LABEL, evaluate, normalize_care_status
from src.schemas import CareStatusResult, EmergencyResult, ProposedAction

# 해든 님 조치 종류 → MCP 도구 이름 (schemas.ActionTool)
ACTION_TOOL = {"call_119": "call_119", "control_device": "control_device",
               "notify_guardian": "notify_guardian", "hospital_info": "find_hospital"}
BROKEN_LLM_OUTPUT = "{이건 JSON이 아님"   # llm 장애 주입: 깨진 응답 (README 7장)


def _llm(fault: Faults):
    """llm 장애면 깨진 문자열을 돌려주는 가짜 LLM. 키가 없으면 None → 해든 님 코드가 템플릿으로 진행."""
    if "llm" in fault.values:
        return lambda prompt: BROKEN_LLM_OUTPUT
    try:
        return make_llm("emergency")
    except RuntimeError:
        return None


async def _hospital(area: str | None):
    """병원 정보를 미리 받는다. run_emergency는 동기 함수라 MCP(비동기)를 직접 못 부르기 때문."""
    if not area:
        return None
    try:
        return await mcp_client.call_tool("find_hospital", {"area": area})
    except (mcp_client.McpConnectionError, mcp_client.McpToolError):
        return None   # 병원 조회 실패는 판정에 영향 없음


def _log_llm(db, run_id: str, log: dict | None) -> None:
    """해든 님 generate_or_template 기록 → run_logs (AutoHealing 로그 화면용)."""
    if not log:
        return
    for attempt, _ in enumerate(log["errors"], start=1):
        db.log(run_id, "llm", attempt, "retry", error="LLMOutputError")
    if log["fallback_used"]:
        db.log(run_id, "llm", max(log["attempts"], 1), "fallback", recovery="template")
    else:
        db.log(run_id, "llm", log["attempts"], "success",
               recovery="retry" if log["attempts"] > 1 else None)


def _arguments(action: dict, reason: str, area: str | None) -> dict[str, str]:
    """ProposedAction.arguments = 해당 MCP 함수의 매개변수 (승인 후 ⑤에서 그대로 호출)."""
    kind = action["type"]
    if kind == "control_device":
        return {key: str(value) for key, value in (action.get("value") or {}).items()}
    if kind == "hospital_info":
        return {"area": area or ""}
    return {"message": reason}


def to_emergency_result(run_id: str, raw: dict, decision: dict, care_status: CareStatusResult) -> EmergencyResult:
    """해든 님 run_emergency() 결과 → schemas.EmergencyResult."""
    actions = [
        ProposedAction(tool=ACTION_TOOL[a["type"]],
                       description=a.get("text") or a.get("label") or a["type"],
                       arguments=_arguments(a, raw["reason"], care_status.area),
                       needs_approval=a["needs_approval"])
        for a in raw["actions"] if a["type"] in ACTION_TOOL   # 워치 확인 등 꺼진 조치는 제외
    ]
    return EmergencyResult(
        run_id=run_id,
        risk_level=raw["risk_level"],
        reasons=[CAUSE_LABEL.get(code, code) for code in raw["reason_codes"]],
        axes=decision["axes"],
        fall_state=decision["fall_state"],
        auto_119=decision["auto_119"],
        proposed_actions=actions,
        requires_approval=any(a.needs_approval for a in actions),
        cctv_summary=care_status.cctv.description if care_status.cctv else None,
    )


async def run_emergency_step(*, db, run_id: str, care_status: CareStatusResult, fault=()) -> tuple[dict, EmergencyResult]:
    """→ (해든 님 원본 결과, 스키마 EmergencyResult). 원본은 승인 대기 저장과 Summary에 다시 쓴다."""
    fault = fault if isinstance(fault, Faults) else Faults(fault)
    month = datetime.now().month
    cs = care_status.model_dump()
    hospital = await _hospital(care_status.area)
    raw = await asyncio.to_thread(run_emergency, cs, _llm(fault), lambda area: hospital, month)
    _log_llm(db, run_id, raw.get("llm_log"))
    decision = evaluate(normalize_care_status(cs), month)   # axes·fall_state·auto_119 (규칙표, LLM 없음)
    return raw, to_emergency_result(run_id, raw, decision, care_status)
