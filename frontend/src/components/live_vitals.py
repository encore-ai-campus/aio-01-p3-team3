"""실시간 바이탈 카드 — '오늘의 돌봄 상태'의 바이탈 칸. 5초마다 백엔드의 최근 측정값을 받아 보여 준다.

위험 판정은 백엔드 규칙(risk.py)이 하므로 이 카드는 값만 보여 주고 판단(색·경고)을 하지 않는다.
시뮬레이터(mcp_server vital_sender)가 보내는 값을 보여 주므로, 숫자는 시뮬레이터가 보낼 때마다 바뀐다. 그래프는 그리지 않고 숫자만 보여 준다.
실시간 값을 받지 못하면 이번 "상태 확인하기" 결과의 바이탈을 대신 보여 준다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

import streamlit as st
from src.api_client import BackendAPIError, request_latest_vital

REFRESH_SECONDS = 3   # 전송기(시연용 compose)가 3초마다 보내므로 화면도 3초마다 확인한다
STALE_AFTER_SECONDS = 45   # 이 시간 동안 새 값이 없으면 지연으로 안내 (backend FRESHNESS_SECONDS와 같다)


def age_text(age_seconds: float | None) -> str:
    if age_seconds is None:
        return ""
    seconds = max(int(age_seconds), 0)
    if seconds < 5:
        return "방금 전"
    if seconds < 60:
        return f"{seconds}초 전"
    return f"{seconds // 60}분 전"


def _clock(stamp) -> str:
    try:
        return datetime.fromisoformat(str(stamp)).strftime("%H:%M:%S")
    except ValueError:
        return str(stamp)


def live_values(reading: Mapping) -> list[tuple[str, str]]:
    """[(항목, 표시값)]. 값이 없으면 "—"."""
    def show(value, unit, digits=0):
        return "—" if value is None else f"{value:.{digits}f}{unit}"

    return [
        ("심박", show(reading.get("heart_rate"), " bpm")),
        ("수축기 혈압", show(reading.get("systolic_bp"), " mmHg")),
        ("체온", show(reading.get("temperature_c"), " ℃", 1)),
        ("산소포화도", show(reading.get("spo2"), " %")),
    ]


def live_caption(reading: Mapping) -> str:
    age = reading.get("age_seconds")
    text = f"● {REFRESH_SECONDS}초마다 갱신 · 측정 {_clock(reading.get('measured_at'))} · {age_text(age)}"
    if isinstance(age, (int, float)) and age > STALE_AFTER_SECONDS:
        text = f"● 수신 지연 · 측정 {_clock(reading.get('measured_at'))} · {age_text(age)} · 새 측정값이 들어오지 않고 있습니다"
    return text


def _draw_tiles(rows: Sequence[tuple[str, str]]) -> None:
    from src.components.cards import _tile   # cards가 이 모듈을 쓰므로 순환을 피해 안에서 가져온다

    for column, (index, (label, value)) in zip(st.columns(4), enumerate(rows)):
        with column:
            _tile(f"vital_{index}", label, value)


def draw_vital_card(reading: Mapping | None, error: str | None, care_status: Mapping | None) -> None:
    """카드 한 장(새 디자인의 바이탈 카드 자리). reading은 /vitals/latest 응답, care_status는 이번 상태 확인 결과(없을 수 있음)."""
    from src.components.cards import measured_text, vital_values
    from src.components.theme import COLORS, card_header

    run_vital = (care_status or {}).get("vital")
    run_source = (care_status or {}).get("source")
    with st.container(key="vital_card"):
        if reading and reading.get("status") == "ok":
            age = reading.get("age_seconds")
            stale = isinstance(age, (int, float)) and age > STALE_AFTER_SECONDS
            badge, colors = ("수신 지연", (COLORS["amber"], COLORS["amber_soft"])) if stale else ("LIVE", (COLORS["green"], COLORS["mint"]))
            card_header("실시간 바이탈 사인", f"Vital Agent · {REFRESH_SECONDS}초마다 갱신", badge, colors)
            _draw_tiles(live_values(reading))
            st.caption(live_caption(reading))
            if run_vital and run_source and run_source != "live":
                # 바이탈 장애 시연 등: 이번 확인에서 실제로 쓴 값의 출처(캐시·시뮬레이션)를 남겨 둔다
                st.caption(f"이번 확인 결과: {measured_text(run_vital, run_source)}")
            return

        card_header("실시간 바이탈 사인", "Vital Agent")
        if run_vital:   # 실시간 값을 못 받았으면 이번 확인 결과를 보여 준다
            _draw_tiles(vital_values(run_vital))
            caption = measured_text(run_vital, run_source)
            st.caption(f"{caption} · 실시간 값을 받지 못해 이번 확인 결과를 보여 줍니다" if caption else "실시간 값을 받지 못했습니다")
        elif error:
            st.warning("실시간 바이탈을 불러오지 못했습니다. 센서 상태를 확인해 주세요.")
        else:
            st.info("아직 수신된 측정값이 없습니다. 측정기(시뮬레이터)가 켜져 있는지 확인해 주세요.")


@st.fragment(run_every=REFRESH_SECONDS)
def render_live_vital_card(backend_url: str, profile_id: str, scenario: str, care_status: Mapping | None = None) -> None:
    """이 칸만 5초마다 다시 그린다 (페이지 전체나 돌봄 실행 흐름은 건드리지 않는다)."""
    reading = error = None
    try:
        reading = request_latest_vital(backend_url, profile_id, scenario, limit=1)
    except (BackendAPIError, ValueError) as exc:
        error = str(exc)
    draw_vital_card(reading, error, care_status)
