"""보호자 결정 처리: 승인 Action 실행 → Summary → 최종 응답."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from src import mcp_client
from src.agents.summary import run_summary
from src.healing.retry import InvalidResult, RecoveryError, RetryPolicy, with_healing
from src.llm.client import make_llm
from src.orchestrator.approval import pending
from src.schemas import ActionResult, CareApprovalRequest, CareApprovalResponse


ACTION_POLICY = RetryPolicy(max_attempts=3, timeout_s=10, delay_s=0.5)
BROKEN_LLM_OUTPUT = "{이건 JSON이 아님"


class PendingApprovalNotFound(LookupError):
    """run_id가 없거나 이미 승인·거절 처리된 경우."""


def _validate_action_result(payload: object) -> None:
    if not isinstance(payload, dict):
        raise InvalidResult("Action result must be an object")
    status = payload.get("status") or payload.get("result")
    if status != "success":
        raise InvalidResult("Action did not succeed")


async def _execute_action(
    *,
    db,
    run_id: str,
    tool: str,
    arguments: Mapping[str, object],
    fault: list[str],
) -> ActionResult:
    async def fetch() -> dict:
        return await mcp_client.call_tool(tool, dict(arguments))

    injected_fault = fault if tool == "control_device" else []
    try:
        healed = await with_healing(
            db=db,
            run_id=run_id,
            step=f"action:{tool}",
            fetch=fetch,
            validate=_validate_action_result,
            policy=ACTION_POLICY,
            fault=injected_fault,
            fault_target="iot",
            use_cache=False,
            retryable=(
                TimeoutError,
                ConnectionError,
                InvalidResult,
                mcp_client.McpConnectionError,
                mcp_client.McpToolError,
            ),
        )
    except RecoveryError as exc:
        return ActionResult(
            tool=tool,
            status="failed",
            message=f"{tool} Mock 실행에 실패했습니다.",
            recovery=f"{exc.attempts}회 시도 후 실패",
        )

    payload = healed["data"]
    message = payload.get("message") if isinstance(payload, dict) else None
    return ActionResult(
        tool=tool,
        status="success",
        message=str(message or f"{tool} Mock 실행을 완료했습니다."),
        recovery="재시도 후 성공" if healed["attempts"] > 1 else None,
    )


def _summary_llm(fault: list[str]):
    if "llm" in fault:
        return lambda _prompt: BROKEN_LLM_OUTPUT
    try:
        return make_llm("summary")
    except RuntimeError:
        return None


def _log_summary(db, run_id: str, log: dict | None) -> None:
    if not log:
        return
    for attempt, _error in enumerate(log.get("errors", []), start=1):
        db.log(run_id, "summary", attempt, "retry", error="LLMOutputError")
    attempts = max(int(log.get("attempts", 0)), 1)
    if log.get("fallback_used"):
        db.log(run_id, "summary", attempts, "fallback", recovery="template")
    else:
        db.log(
            run_id,
            "summary",
            attempts,
            "success",
            recovery="retry" if attempts > 1 else None,
        )


def _executed(action: ActionResult, arguments: Mapping[str, object]) -> dict[str, str]:
    result = {
        "action": action.tool,
        "result": action.status,
    }
    device = arguments.get("device")
    if device:
        result["device"] = str(device)
    return result


async def process_care_approval(
    request: CareApprovalRequest,
    *,
    db,
) -> CareApprovalResponse:
    """승인 대기 건을 한 번만 처리하고 최종 안내를 반환한다."""

    saved = pending.pop(request.run_id)
    if saved is None:
        raise PendingApprovalNotFound(request.run_id)

    approved = request.decision == "approve"
    emergency = saved["emergency"]
    fault = list(saved.get("fault") or [])
    action_results: list[ActionResult] = []
    executed: list[dict[str, str]] = []

    if approved:
        for action in emergency.get("proposed_actions", []):
            if not action.get("needs_approval"):
                continue
            arguments = action.get("arguments") or {}
            result = await _execute_action(
                db=db,
                run_id=request.run_id,
                tool=action["tool"],
                arguments=arguments,
                fault=fault,
            )
            action_results.append(result)
            executed.append(_executed(result, arguments))

    summary = await asyncio.to_thread(
        run_summary,
        saved["raw"],
        approved,
        executed,
        _summary_llm(fault),
        "guardian",
    )
    _log_summary(db, request.run_id, summary.get("llm_log"))

    if approved and summary.get("guardian_message"):
        notification = await _execute_action(
            db=db,
            run_id=request.run_id,
            tool="notify_guardian",
            arguments={"message": summary["guardian_message"]},
            fault=[],
        )
        action_results.append(notification)

    status = "done" if approved else "rejected"
    db.log(
        request.run_id,
        "approval",
        1,
        "success",
        recovery="approved" if approved else "rejected",
    )
    return CareApprovalResponse(
        run_id=request.run_id,
        status=status,
        current_step=(
            "보호자 승인 → Action 실행 → Summary 안내 완료"
            if approved
            else "보호자 거절 → 조치 미실행 → Summary 기록 완료"
        ),
        actions=action_results,
        guardian_message=summary.get("guardian_message"),
        elder_message=summary.get("elder_message"),
        approved=approved,
        decided_by="guardian",
    )
