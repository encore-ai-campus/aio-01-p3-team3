"""119 자동 연결 (auto_119 "VITAL_SEVERE") — 해든 (README 3장 Approval Gate 예외, 6장 응답 3)

# [변경 기록]
# 2026-10-12 해든: 새 파일. README대로 바이탈이 매우 위험하면 승인 대기 없이 /care/run 한 번에
#   119 호출(mock) → 보호자 긴급 알림 → Summary 안내까지 끝낸다. care.py가 emergency.auto_119를 보고 부른다.
#   조치 실행은 두나 님 approval_flow._execute_action(재시도·로그 포함)을 그대로 쓴다.
"""

import asyncio

from src.agents.summary import run_summary
from src.llm.fallback import emergency_alert_message
from src.orchestrator.approval_flow import _execute_action, _executed, _log_summary, _summary_llm
from src.schemas import CareRunResponse, CareStatusResult, EmergencyResult

STEP = "바이탈 확인 → 위험 판정(바이탈 매우 위험) → 119 자동 연결(mock) → 보호자 긴급 알림"


async def run_auto_119(*, db, run_id: str, care_status: CareStatusResult, emergency: EmergencyResult,
                       raw: dict, fault: list[str]) -> CareRunResponse:
    """승인 없이 바로 실행하는 조치(119)를 실행하고 보호자에게 바로 알린 뒤 Summary까지 만든다."""
    results, executed = [], []
    for action in emergency.proposed_actions:
        if action.needs_approval or action.tool != "call_119":
            continue                      # 병원 정보는 알림 문구에, 보호자 알림은 아래에서 따로 보냄
        result = await _execute_action(db=db, run_id=run_id, tool=action.tool,
                                       arguments=action.arguments, fault=fault)
        results.append(result)
        executed.append(_executed(result, action.arguments))

    # 119를 부른 직후 보호자에게 긴급 알림 (LLM을 기다리지 않는 고정 문구, 원본 캡처 확인 안내 포함)
    alert = emergency_alert_message(raw["reason"], emergency.auto_119, raw.get("hospital"), raw["actions"])
    results.append(await _execute_action(db=db, run_id=run_id, tool="notify_guardian",
                                         arguments={"message": alert}, fault=[]))

    summary = await asyncio.to_thread(run_summary, raw, False, executed, _summary_llm(fault), "auto")
    _log_summary(db, run_id, summary.get("llm_log"))
    db.log(run_id, "approval", 1, "success", recovery="auto_119")

    called = any(r.tool == "call_119" and r.status == "success" for r in results)
    return CareRunResponse(
        run_id=run_id,
        status="done",
        care_status=care_status,
        emergency=emergency,
        message=alert if called else summary.get("guardian_message"),
        current_step=STEP if called else STEP.replace("119 자동 연결(mock)", "119 자동 연결 실패"),
        actions=results,
        guardian_message=summary.get("guardian_message"),
        elder_message=summary.get("elder_message") or None,
        approved=None,
        decided_by="auto",
    )
