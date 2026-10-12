"""위험도 배너 — 기화 (첫 화면 맨 위에 크게)

보호자가 처음 보는 화면에서 "지금 어떤 상황인지"를 한눈에 알 수 있게
위험도(정상·주의·경고·위급)를 크게, 판정 근거를 실제 측정값과 함께 보여 준다.
  예) ⚠️ 경고 — 실내 극한 고온(33℃) + 심박·혈압 변화(심박 105회/분 · 혈압 140mmHg)
위험도와 근거는 백엔드 규칙(risk.py)이 정한 값을 그대로 쓰고, 화면은 측정값만 덧붙인다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

import streamlit as st

RISK_STYLE = {   # 위험도 → (아이콘, 글자·테두리 색, 배경색)
    "정상": ("✅", "#1e7e34", "#e6f4ea"),
    "주의": ("🔔", "#9a6700", "#fff4d6"),
    "경고": ("⚠️", "#c25400", "#ffe9d6"),
    "위급": ("🚨", "#c5221f", "#fde4e2"),
}
# 원인이 아니라 참고 사항인 근거 (제목 줄에는 넣지 않고 아래 목록에만 표시)
NOTE_REASONS = ("영상 판단 불가", "이전 측정값 사용")
# 제목 줄에 먼저 올릴 근거 순서 (심각한 것 먼저)
REASON_PRIORITY = ("쓰러짐", "위험 범위", "극한", "인덕션", "이상", "변화")


def _num(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def reason_with_values(reason: str, care_status: Mapping | None) -> str:
    """판정 근거 문구에 해당하는 실제 측정값을 덧붙인다. 값이 없으면 문구 그대로."""
    cs = care_status or {}
    vital = cs.get("vital") or {}
    env = cs.get("indoor_environment") or {}
    devices = cs.get("devices") or {}
    temp = env.get("temperature_c")

    if reason.startswith("실내 온도") and temp is not None:
        hot = temp >= 25
        if "극한" in reason:
            return f"실내 극한 {'고온' if hot else '저온'}({_num(temp)}℃)"
        return f"실내 {'고온' if hot else '저온'}({_num(temp)}℃)"
    if reason.startswith("심박·혈압"):
        parts = [f"심박 {_num(vital['heart_rate'])}회/분" if vital.get("heart_rate") is not None else None,
                 f"혈압 {_num(vital['systolic_bp'])}mmHg" if vital.get("systolic_bp") is not None else None]
        parts = [p for p in parts if p]
        return f"{reason}({' · '.join(parts)})" if parts else reason
    if reason.startswith("산소포화도") and vital.get("spo2") is not None:
        return f"{reason}(SpO₂ {_num(vital['spo2'])}%)"
    if reason.startswith("체온") and vital.get("temperature_c") is not None:
        return f"{reason}({_num(vital['temperature_c'])}℃)"
    if "인덕션" in reason:
        parts = [f"{devices['induction_minutes']}분" if devices.get("induction_minutes") is not None else None,
                 f"{devices['induction_temperature']}℃" if devices.get("induction_temperature") is not None else None]
        parts = [p for p in parts if p]
        return f"{reason}({' · '.join(parts)})" if parts else reason
    return reason


def _priority(reason: str) -> int:
    return next((i for i, key in enumerate(REASON_PRIORITY) if key in reason), len(REASON_PRIORITY))


def headline(reasons: Sequence[str], care_status: Mapping | None, limit: int = 2) -> str:
    """제목 줄: 참고 사항을 뺀 근거 중 심각한 것부터 최대 2개를 측정값과 함께."""
    causes = sorted((r for r in reasons if r not in NOTE_REASONS), key=_priority)
    return " + ".join(reason_with_values(r, care_status) for r in causes[:limit])


def render_risk_banner(emergency: Mapping | None, care_status: Mapping | None = None) -> None:
    if not isinstance(emergency, Mapping):
        return
    level = str(emergency.get("risk_level") or "정상")
    icon, color, background = RISK_STYLE.get(level, RISK_STYLE["주의"])
    reasons = [str(r) for r in emergency.get("reasons") or []]
    title = headline(reasons, care_status) or ("현재 확인된 이상 징후가 없습니다." if level == "정상" else "")

    items = "".join(f"<li>{escape(reason_with_values(r, care_status))}</li>" for r in sorted(reasons, key=_priority))
    st.markdown(
        f'<div class="care-risk" style="border:2px solid {color};border-left-width:10px;background:{background};'
        f'border-radius:16px;padding:20px 26px;margin:6px 0 18px;">'
        f'<div style="color:{color};font-size:15px;font-weight:700;">위험도</div>'
        f'<div style="color:{color};font-size:44px;font-weight:800;line-height:1.15;">{icon} {escape(level)}</div>'
        f'<div style="color:#1f2d3a;font-size:22px;font-weight:700;margin-top:8px;line-height:1.5;">{escape(title)}</div>'
        + (f'<div style="color:#3c4a57;font-size:15px;margin-top:10px;">판정 근거</div>'
           f'<ul style="color:#3c4a57;font-size:16px;margin:4px 0 0 0;">{items}</ul>' if items else "")
        + "</div>",
        unsafe_allow_html=True,
    )
