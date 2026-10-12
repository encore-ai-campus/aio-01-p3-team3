"""한 줄 진행 표시 — 기화 (README 10장)

/care/run·/care/approve 응답의 current_step("바이탈 확인 → IoT·CCTV 확인 → 위험 판정 완료(경고) → 보호자 승인 대기")을
단계별 칩으로 나눠 보여 준다. 마지막 단계가 지금 위치다.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

import streamlit as st

DEFAULT_STEPS = ["상태 확인", "위험 판정", "보호자 승인", "조치 실행", "결과 안내"]
STATUS_STYLE = {   # 응답 status → (칩 색, 한 줄 설명)
    "no_issue": ("#1e8e3e", "이상 없음"),
    "pending_approval": ("#e37400", "보호자 승인 대기"),
    "done": ("#1a73e8", "처리 완료"),
    "rejected": ("#5f6368", "보호자 거절"),
    "fail": ("#d93025", "확인 필요"),
}


def split_steps(current_step: str | None) -> list[str]:
    if not current_step:
        return []
    return [step.strip() for step in current_step.split("→") if step.strip()]


def latest_progress(run_response: Mapping | None, approval_result: Mapping | None) -> tuple[list[str], str | None]:
    """승인 결과가 있으면 그쪽 진행 상황이 더 최신이다. → (단계 목록, status)"""
    for response in (approval_result, run_response):
        if isinstance(response, Mapping) and response.get("current_step"):
            return split_steps(str(response["current_step"])), response.get("status")
    return [], None


def render_progress(run_response: Mapping | None, approval_result: Mapping | None = None) -> None:
    steps, status = latest_progress(run_response, approval_result)
    color, label = STATUS_STYLE.get(str(status), ("#1a73e8", ""))
    if not steps:          # 아직 실행 전: 전체 흐름을 회색으로 보여 준다
        steps, color, label = DEFAULT_STEPS, None, "상태 확인 전"

    chips = []
    for index, step in enumerate(steps):
        current = color is not None and index == len(steps) - 1
        style = (f"background:{color};color:#fff;font-weight:600;" if current
                 else "background:#f1f3f4;color:#3c4043;")
        chips.append(f'<span style="{style}padding:4px 10px;border-radius:14px;white-space:nowrap;">'
                     f"{escape(step)}</span>")
    arrow = '<span style="color:#9aa0a6;margin:0 4px;">→</span>'
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 0;margin:4px 0 2px;">'
        f'<span style="color:#5f6368;margin-right:8px;">진행</span>{arrow.join(chips)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="care-progress-label">{escape(label)}</div>', unsafe_allow_html=True)
