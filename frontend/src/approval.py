"""보호자 승인 화면과 승인 대기 세션 상태 관리 — 두나."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Literal

import streamlit as st

from .api_client import (
    BackendAPIError,
    fetch_cctv_image,
    request_care_run,
    submit_care_decision,
)


TOOL_LABELS = {
    "control_device": "기기 제어",
    "notify_guardian": "보호자 알림",
    "call_119": "119 호출",
    "find_hospital": "가까운 병원 조회",
}
RISK_LABELS = {
    "정상": "정상",
    "주의": "주의",
    "경고": "경고",
    "위급": "위급",
}
PROFILE_LABELS = {
    "profile-01": "어르신 A (취약도 상)",
    "profile-02": "어르신 B (취약도 중)",
    "profile-03": "어르신 C (취약도 하)",
}
SCENARIO_LABELS = {
    "normal": "정상",
    "heat": "폭염",
    "induction": "인덕션 방치",
    "fall": "낙상",
    "critical": "바이탈 위급",
}
FAULT_LABELS = {
    "vital": "바이탈 장애",
    "iot": "IoT 장애",
    "vision": "CCTV 분석 장애",
    "llm": "LLM 장애",
}


def store_pending_approval(
    run_response: Mapping[str, object],
    session_state: MutableMapping[str, object],
) -> None:
    """승인 대기 응답을 Streamlit 재실행 후에도 유지한다."""

    if run_response.get("status") != "pending_approval":
        return

    run_id = run_response.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("pending_approval 응답에는 run_id가 필요합니다.")

    previous_run_id = session_state.get("run_id")
    session_state["run_id"] = run_id
    session_state["care_status"] = run_response.get("care_status")
    session_state["emergency"] = run_response.get("emergency")

    if previous_run_id != run_id:
        session_state.pop("approval_result", None)


def get_approval_actions(emergency: Mapping[str, object] | None) -> list[dict[str, object]]:
    """제안 조치 중 보호자 승인이 필요한 항목만 반환한다."""

    if not emergency:
        return []
    if emergency.get("requires_approval") is False:
        return []
    raw_actions = emergency.get("proposed_actions")
    if not isinstance(raw_actions, list):
        return []

    return [
        action
        for action in raw_actions
        if isinstance(action, dict) and action.get("needs_approval") is True
    ]


def _render_risk(emergency: Mapping[str, object]) -> None:
    risk_level = str(emergency.get("risk_level", "정상"))
    label = RISK_LABELS.get(risk_level, risk_level)
    message = f"위험도: {label}"

    if risk_level == "위급":
        st.error(message)
    elif risk_level == "경고":
        st.warning(message)
    elif risk_level == "주의":
        st.warning(message)
    else:
        st.info(message)

    reasons = emergency.get("reasons")
    if isinstance(reasons, list) and reasons:
        st.markdown("**판정 근거**")
        for reason in reasons:
            st.write(f"- {reason}")


def _render_actions(emergency: Mapping[str, object]) -> None:
    raw_actions = emergency.get("proposed_actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        st.info("제안된 조치가 없습니다.")
        return

    st.markdown("**제안된 조치**")
    for index, action in enumerate(raw_actions, start=1):
        if not isinstance(action, dict):
            continue
        tool = str(action.get("tool", "unknown"))
        description = str(action.get("description") or "상세 설명이 없습니다.")
        approval_text = "승인 필요" if action.get("needs_approval") is True else "승인 불필요"
        with st.container(border=True):
            st.markdown(
                f"**{index}. {TOOL_LABELS.get(tool, tool)}** · {approval_text}"
            )
            st.write(description)
            arguments = action.get("arguments")
            if isinstance(arguments, dict) and arguments:
                st.caption(f"실행 인자: {arguments}")


def _cctv_values(
    care_status: Mapping[str, object] | None,
    emergency: Mapping[str, object] | None,
) -> tuple[str | None, str | None]:
    cctv: Mapping[str, object] = {}
    if care_status:
        raw_cctv = care_status.get("cctv")
        if isinstance(raw_cctv, dict):
            cctv = raw_cctv

    image_path = cctv.get("image_path")
    summary = (
        cctv.get("summary")
        or cctv.get("description")
        or (emergency.get("cctv_summary") if emergency else None)
    )
    return (
        str(image_path) if image_path else None,
        str(summary) if summary else None,
    )


def _render_cctv(
    care_status: Mapping[str, object] | None,
    emergency: Mapping[str, object] | None,
    backend_url: str,
) -> None:
    image_path, summary = _cctv_values(care_status, emergency)
    if not image_path and not summary:
        return

    st.markdown("**CCTV 확인**")
    if image_path:
        try:
            image_bytes = fetch_cctv_image(backend_url, image_path)
        except (BackendAPIError, ValueError) as exc:
            st.warning(f"CCTV 이미지를 표시할 수 없습니다: {exc}")
        else:
            st.image(image_bytes, caption="상황 확인용 CCTV 캡처")
    if summary:
        st.caption(summary)


def render_approval_result(result: Mapping[str, object]) -> None:
    """승인 또는 거절 처리 결과를 보호자에게 표시한다."""

    status = str(result.get("status", "fail"))
    if status == "done":
        decided_by = result.get("decided_by")
        if decided_by == "auto":
            st.success("자동 긴급 조치를 실행했습니다.")
        elif decided_by == "timeout":
            st.warning("승인 응답이 없어 정해진 시간 뒤 자동으로 조치를 실행했습니다.")
        else:
            st.success("승인된 조치를 실행했습니다.")
    elif status == "rejected":
        st.info("보호자가 조치를 거절했습니다. 실행 없이 기록했습니다.")
    else:
        st.error("조치 처리 중 문제가 발생했습니다.")

    current_step = result.get("current_step")
    if current_step:
        st.caption(f"현재 단계: {current_step}")

    actions = result.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            tool = str(action.get("tool", "조치"))
            action_status = str(action.get("status", "failed"))
            message = str(action.get("message") or "결과 메시지가 없습니다.")
            st.write(f"- {TOOL_LABELS.get(tool, tool)} · {action_status}: {message}")
            recovery = action.get("recovery")
            if recovery:
                st.caption(f"복구 결과: {recovery}")

    guardian_message = result.get("guardian_message")
    if guardian_message:
        st.markdown("**보호자 안내**")
        st.write(str(guardian_message))

    elder_message = result.get("elder_message")
    if elder_message:
        st.markdown("**어르신 안내**")
        st.write(str(elder_message))


def _submit_decision(
    backend_url: str,
    run_id: str,
    decision: Literal["approve", "reject"],
) -> None:
    try:
        with st.spinner("승인 결과를 처리하고 있습니다..."):
            result = submit_care_decision(backend_url, run_id, decision)
    except (BackendAPIError, ValueError) as exc:
        st.error(str(exc))
        return

    st.session_state["approval_result"] = result
    render_approval_result(result)


def render_care_workflow(backend_url: str) -> None:
    """실제 ``/care/run``과 ``/care/approve``를 연결한 보호자 흐름을 그린다."""

    with st.sidebar:
        st.header("상태 확인 설정")
        profile_id = st.selectbox(
            "어르신",
            options=list(PROFILE_LABELS),
            format_func=PROFILE_LABELS.__getitem__,
        )
        scenario = st.selectbox(
            "시연 시나리오",
            options=list(SCENARIO_LABELS),
            format_func=SCENARIO_LABELS.__getitem__,
        )
        fault = st.multiselect(
            "장애 주입",
            options=list(FAULT_LABELS),
            format_func=FAULT_LABELS.__getitem__,
        )
        run_clicked = st.button(
            "상태 확인하기",
            type="primary",
            use_container_width=True,
        )

    if run_clicked:
        for key in (
            "run_response",
            "run_id",
            "care_status",
            "emergency",
            "approval_result",
        ):
            st.session_state.pop(key, None)
        try:
            with st.spinner("바이탈·IoT·CCTV 상태를 확인하고 있습니다..."):
                response = request_care_run(
                    backend_url,
                    profile_id,
                    scenario,
                    list(fault),
                )
        except (BackendAPIError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state["run_response"] = response

    response = st.session_state.get("run_response")
    if isinstance(response, dict):
        render_approval_panel(response, backend_url)
    else:
        st.info("왼쪽에서 어르신과 시나리오를 선택한 뒤 상태를 확인해 주세요.")


def render_approval_panel(
    run_response: Mapping[str, object],
    backend_url: str,
) -> None:
    """위험 정보와 조치안을 보여주고 보호자 결정을 전송한다."""

    if not run_response:
        st.info("아직 실행 결과가 없습니다.")
        return

    status = str(run_response.get("status", "fail"))
    current_step = run_response.get("current_step")
    if current_step:
        st.caption(f"현재 단계: {current_step}")

    if status == "no_issue":
        st.success(str(run_response.get("message") or "현재 확인된 이상 징후가 없습니다."))
        return
    if status == "fail":
        st.error(str(run_response.get("message") or "돌봄 실행에 실패했습니다."))
        return

    if status in {"done", "rejected"}:
        emergency = run_response.get("emergency")
        emergency_mapping = emergency if isinstance(emergency, dict) else None
        care_status = run_response.get("care_status")
        care_mapping = care_status if isinstance(care_status, dict) else None

        if emergency_mapping:
            _render_risk(emergency_mapping)
            _render_actions(emergency_mapping)
        _render_cctv(care_mapping, emergency_mapping, backend_url)

        if run_response.get("decided_by") == "auto":
            st.error(
                str(
                    run_response.get("message")
                    or "바이탈이 매우 위험해 보호자 승인 없이 119에 연락했습니다."
                )
            )
        render_approval_result(run_response)
        return

    if status != "pending_approval":
        return

    try:
        store_pending_approval(run_response, st.session_state)
    except ValueError as exc:
        st.error(str(exc))
        return

    run_id = str(st.session_state["run_id"])
    care_status = st.session_state.get("care_status")
    emergency = st.session_state.get("emergency")
    care_mapping = care_status if isinstance(care_status, dict) else None
    emergency_mapping = emergency if isinstance(emergency, dict) else None

    st.subheader("보호자 조치 승인")
    if emergency_mapping:
        _render_risk(emergency_mapping)
        remaining = emergency_mapping.get("remaining_seconds")
        if isinstance(remaining, (int, float)):
            st.metric("승인 남은 시간", f"{max(0, int(remaining))}초")
        _render_actions(emergency_mapping)
    else:
        st.warning("위험·조치 정보를 불러오지 못했습니다.")

    _render_cctv(care_mapping, emergency_mapping, backend_url)

    previous_result = st.session_state.get("approval_result")
    if isinstance(previous_result, dict):
        render_approval_result(previous_result)
        return

    approval_actions = get_approval_actions(emergency_mapping)
    if not approval_actions:
        st.info("추가 승인이 필요한 조치는 없습니다.")
        return

    st.caption("승인을 선택하면 위에 표시된 승인 필요 조치가 실행됩니다.")
    approve_column, reject_column = st.columns(2)
    with approve_column:
        approve_clicked = st.button(
            "조치 승인 및 실행",
            type="primary",
            use_container_width=True,
            key=f"approve_{run_id}",
        )
    with reject_column:
        reject_clicked = st.button(
            "조치 거절",
            use_container_width=True,
            key=f"reject_{run_id}",
        )

    if approve_clicked:
        _submit_decision(backend_url, run_id, "approve")
    elif reject_clicked:
        _submit_decision(backend_url, run_id, "reject")
