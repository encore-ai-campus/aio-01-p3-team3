"""/care/run 전체 흐름 — 기화 (README 3장)

Orchestration 1(모니터링) → Join Guard → Emergency(판정·조치안) → Handoff Guard → Approval Gate(승인 대기 저장)
조치 실행과 Summary(/care/approve)는 ⑤ 지혜 님.
"""

import uuid

from src import mcp_client
from src.healing.faults import Faults
from src.orchestrator import guards
from src.orchestrator.approval import pending
from src.orchestrator.emergency import run_emergency_step
from src.orchestrator.monitoring import run_monitoring
from src.schemas import CareRunRequest, CareRunResponse

STEP_MONITOR = "바이탈 확인 → IoT·CCTV 확인"


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:8]}"


async def _notify_guardian(message: str) -> None:
    """승인이 필요 없는 보호자 알림. 실패해도 흐름을 멈추지 않는다 (응답 message로도 전달됨)."""
    try:
        await mcp_client.call_tool("notify_guardian", {"message": message})
    except (mcp_client.McpConnectionError, mcp_client.McpToolError):
        pass


async def run_care(request: CareRunRequest, *, db, run_id: str | None = None) -> CareRunResponse:
    run_id = run_id or new_run_id()
    fault = Faults(request.fault)

    care_status = await run_monitoring(db=db, run_id=run_id, profile_id=request.profile_id,
                                       scenario=request.scenario, fault=fault)

    stop_message = guards.join_guard(care_status)
    if stop_message:
        await _notify_guardian(stop_message)
        return CareRunResponse(run_id=run_id, status="fail", care_status=care_status, message=stop_message,
                               current_step=f"{STEP_MONITOR} → 바이탈 조회 실패 → 안전 종료 (보호자에게 센서 확인 요청)")

    raw, emergency = await run_emergency_step(db=db, run_id=run_id, care_status=care_status, fault=fault)

    if not guards.handoff_guard(emergency.risk_level):
        return CareRunResponse(run_id=run_id, status="no_issue", care_status=care_status, emergency=emergency,
                               message="이상 없음", current_step=f"{STEP_MONITOR} → 위험 판정: 이상 없음 → 종료")

    # TODO(⑤ 지혜): emergency.requires_approval이 False(보호자 알림·병원 정보만)면 승인 없이 바로 실행하고
    #   Summary까지 진행. 다섯 시연 시나리오에는 이런 경우가 없다 (위험이 있으면 항상 기기 제어나 119가 포함됨).
    pending.save(run_id, care_status=care_status.model_dump(), emergency=emergency.model_dump(), raw=raw)
    return CareRunResponse(run_id=run_id, status="pending_approval", care_status=care_status, emergency=emergency,
                           message=raw["reason"],
                           current_step=f"{STEP_MONITOR} → 위험 판정 완료({emergency.risk_level}) → 보호자 승인 대기")
