"""바이탈 카드, 실내·기기 카드 — 기화 (README 10장)

/care/run 응답의 care_status(vital, indoor_environment, devices, source)를 보여 준다.
위험 판정은 백엔드 규칙(risk.py)이 하므로 화면은 값만 보여 주고 판단하지 않는다.
CCTV 카드는 두나 님 승인 화면(approval.py)에 이미 있어 여기서는 다루지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import streamlit as st

SOURCE_LABELS = {
    "live": "🟢 실시간 측정값",
    "cache": "🟡 이전 측정값 (캐시)",
    "mock": "⚪ 시뮬레이션 값",
    "mixed": "🟡 일부 이전 측정값",
}
DEVICE_STATE = {"on": "켜짐", "off": "꺼짐", "unknown": "알 수 없음"}


def _number(value, unit: str, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}{unit}" if isinstance(value, (int, float)) else f"{value}{unit}"


def vital_values(vital: Mapping | None) -> list[tuple[str, str]]:
    """[(항목, 표시값)]. 값이 없으면 "—"."""
    vital = vital or {}
    return [
        ("심박", _number(vital.get("heart_rate"), " bpm")),
        ("수축기 혈압", _number(vital.get("systolic_bp"), " mmHg")),
        ("체온", _number(vital.get("temperature_c"), " ℃", 1)),
        ("산소포화도", _number(vital.get("spo2"), " %")),
    ]


def measured_text(vital: Mapping | None, source: str | None) -> str:
    parts = [SOURCE_LABELS.get(str(source), str(source))] if source else []
    stamp = (vital or {}).get("measured_at")
    if stamp:
        try:
            parts.append(f"측정 {datetime.fromisoformat(str(stamp)).strftime('%H:%M:%S')}")
        except ValueError:
            parts.append(f"측정 {stamp}")
    return " · ".join(parts)


def induction_text(devices: Mapping) -> str:
    state = DEVICE_STATE.get(str(devices.get("induction")), "알 수 없음")
    details = [f"{devices['induction_minutes']}분" if devices.get("induction_minutes") is not None else None,
               f"{devices['induction_temperature']}℃" if devices.get("induction_temperature") is not None else None]
    details = [d for d in details if d]
    return state + (f" · {' · '.join(details)}" if details and devices.get("induction") == "on" else "")


def render_vital_card(care_status: Mapping) -> None:
    with st.container(border=True):
        st.markdown("**❤️ 바이탈**")
        vital = care_status.get("vital")
        if not vital:
            st.warning("바이탈을 불러오지 못했습니다. 센서 상태를 확인해 주세요.")
            return
        left, right = st.columns(2)
        for index, (label, value) in enumerate(vital_values(vital)):
            (left if index % 2 == 0 else right).metric(label, value)
        caption = measured_text(vital, care_status.get("source"))
        if caption:
            st.caption(caption)


def render_home_card(care_status: Mapping) -> None:
    with st.container(border=True):
        st.markdown("**🏠 실내·기기**")
        env = care_status.get("indoor_environment")
        left, right = st.columns(2)
        if env:
            left.metric("실내 온도", _number(env.get("temperature_c"), " ℃", 1))
            right.metric("습도", _number(env.get("humidity_percent"), " %"))
        else:
            st.warning("실내 온습도를 확인할 수 없습니다.")

        devices = care_status.get("devices")
        if devices:
            st.markdown(f"에어컨: **{DEVICE_STATE.get(str(devices.get('air_conditioner')), '알 수 없음')}**  \n"
                        f"인덕션: **{induction_text(devices)}**")
        else:
            st.warning("기기 상태를 확인할 수 없습니다.")


def render_status_cards(run_response: Mapping | None) -> None:
    care_status = run_response.get("care_status") if isinstance(run_response, Mapping) else None
    if not isinstance(care_status, Mapping):
        return
    vital_column, home_column = st.columns(2)
    with vital_column:
        render_vital_card(care_status)
    with home_column:
        render_home_card(care_status)
