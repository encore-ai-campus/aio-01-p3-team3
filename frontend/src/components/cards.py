"""바이탈 카드, 실내·기기 카드 — 기화 (README 10장)

/care/run 응답의 care_status(vital, indoor_environment, devices, source)를 보여 준다.
위험 판정은 백엔드 규칙(risk.py)이 하므로 화면은 값만 보여 주고 판단하지 않는다.
CCTV 캡처·영상은 첫 화면 오른쪽(위험 판정 카드 옆)에 위아래로 보인다 (render_cctv_panel).
[팀 합의] 10/12 해든: 수언 님 시안(index-2.html) 모양으로 타일·기기 줄을 바꿈. 값 계산 함수는 그대로.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from html import escape
from pathlib import PurePath

import streamlit as st

from src.api_client import BackendAPIError, control_device, fetch_cctv_image, fetch_cctv_video, fetch_device_states
from src.components.live_vitals import render_live_vital_card
from src.components.theme import COLORS, card_header

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


SOURCE_BADGES = {   # 카드 오른쪽 위 배지 (글자, 글자색, 배경색)
    "live": ("LIVE", COLORS["green"], COLORS["mint"]),
    "cache": ("이전 값", COLORS["amber"], COLORS["amber_soft"]),
    "mixed": ("일부 이전 값", COLORS["amber"], COLORS["amber_soft"]),
    "mock": ("시뮬레이션", COLORS["muted"], COLORS["gray_soft"]),
}
DEVICE_ICONS = {"에어컨": "❄", "인덕션": "♨"}


def _source_badge(source: str | None) -> tuple[str, tuple[str, str] | None]:
    text, fg, bg = SOURCE_BADGES.get(str(source), ("", COLORS["muted"], COLORS["gray_soft"]))
    return text, (fg, bg)


def _tile(key: str, label: str, value: str) -> None:
    """숫자 타일 하나. 값이 없으면 붉은 타일 + "센서 응답 없음" (판단이 아니라 값이 없다는 표시)."""
    missing = value == "—"
    with st.container(key=f"tile_missing_{key}" if missing else f"tile_ok_{key}"):
        st.metric(label, value)
        if missing:
            st.markdown(f'<p class="ok-tile-note" style="color:{COLORS["red"]};">센서 응답 없음</p>',
                        unsafe_allow_html=True)


def _device_row(name: str, state_text: str, is_on: bool) -> str:
    return (f'<div class="ok-device"><div class="ok-device-icon">{DEVICE_ICONS.get(name, "⌂")}</div>'
            f'<div><div class="ok-device-name">{escape(name)}</div>'
            f'<div class="ok-device-state">{escape(state_text)}</div></div>'
            f'<div class="ok-switch{" on" if is_on else ""}" title="{"켜짐" if is_on else "꺼짐"}"></div></div>')


def render_vital_card(care_status: Mapping) -> None:
    with st.container(key="vital_card"):
        badge, colors = _source_badge(care_status.get("source"))
        caption = measured_text(care_status.get("vital"), care_status.get("source"))
        card_header("실시간 바이탈 사인", "Vital Agent" + (f" · {caption}" if caption else ""), badge, colors)
        vital = care_status.get("vital")
        if not vital:
            st.warning("바이탈을 불러오지 못했습니다. 센서 상태를 확인해 주세요.")
            return
        for column, (index, (label, value)) in zip(st.columns(4), enumerate(vital_values(vital))):
            with column:
                _tile(f"vital_{index}", label, value)


CCTV_STATUS = {"analyzed": "분석 완료", "unavailable": "판단 불가", "failed": "분석 실패"}

# CCTV 영상은 CCTV 캡처와 같은 길로 받는다: MCP assets/video/<이미지 이름>.mp4 → 백엔드 /video → 여기.
# 이름은 상태 확인 결과의 image_path에서 얻고(normal.png → normal.mp4), 상태 확인 전에는 시나리오별 기본 장면으로 정한다.
SCENARIO_CCTV_STEM = {"normal": "normal", "heat": "normal", "induction": "kitchen_empty", "fall": "fall", "critical": "lying"}


def cctv_video_name(care_status: Mapping | None, scenario: str | None) -> str | None:
    image_path = ((care_status or {}).get("cctv") or {}).get("image_path")
    stem = PurePath(str(image_path).replace("\\", "/")).stem if image_path else SCENARIO_CCTV_STEM.get(scenario or "")
    return f"{stem}.mp4" if stem else None


@st.cache_data(show_spinner=False, ttl=3600, max_entries=8)
def _load_video(backend_url: str, name: str) -> bytes:
    return fetch_cctv_video(backend_url, name)   # 실패하면 예외가 나서 캐시되지 않는다 (영상을 나중에 넣어도 바로 보인다)


def _cctv_head(title: str, status: str) -> None:
    st.markdown(f'<div class="ok-cctv-head"><span><i></i>{escape(title)}</span><span>{escape(status)}</span></div>',
                unsafe_allow_html=True)


def render_cctv(care_status: Mapping | None, backend_url: str | None) -> None:
    """오른쪽 위: CCTV 캡처와 한 줄 설명 (두나 님 #43 코드를 시안의 어두운 화면 틀로 옮김). 결과가 없으면 자리만."""
    cctv = (care_status or {}).get("cctv") or {}
    status = CCTV_STATUS.get(str(cctv.get("status")), "확인 전")
    with st.container(key="cctv_frame"):
        _cctv_head("CCTV · 거실", status)
        if care_status is None:
            st.markdown('<div class="care-video-empty">상태 확인 후 캡처가 표시됩니다</div>', unsafe_allow_html=True)
            return
        path = cctv.get("image_path")
        if backend_url and path:
            try:
                picture = fetch_cctv_image(backend_url, str(path))
            except (BackendAPIError, ValueError):
                st.warning("캡처를 불러오지 못했습니다.")
            else:
                st.image(picture, caption="보호자 확인용 캡처", use_container_width=True)
        st.write(cctv.get("description") or cctv.get("summary") or "영상 판단 불가")


def render_cctv_video(care_status: Mapping | None, backend_url: str | None, scenario: str | None) -> None:
    """오른쪽 아래: CCTV 영상. 받아 오면 재생하고, 없으면 자리만 보여 준다."""
    name = cctv_video_name(care_status, scenario)
    video = None
    if backend_url and name:
        try:
            video = _load_video(backend_url, name)
        except (BackendAPIError, ValueError):
            video = None
    with st.container(key="cctv_video_frame"):
        _cctv_head("CCTV 영상 · 거실", "재생 가능" if video else "영상 준비 중")
        if video:
            st.video(video, format="video/mp4")
        else:
            st.markdown('<div class="care-video-empty"><span>▶</span>영상 준비 중</div>', unsafe_allow_html=True)


def render_cctv_panel(run_response: Mapping | None, backend_url: str | None = None, scenario: str | None = None) -> None:
    """첫 화면 오른쪽 열: 위 CCTV 캡처, 아래 CCTV 영상."""
    care_status = run_response.get("care_status") if isinstance(run_response, Mapping) else None
    care_status = care_status if isinstance(care_status, Mapping) else None
    render_cctv(care_status, backend_url)
    render_cctv_video(care_status, backend_url, scenario)


DEVICE_TOGGLES = (("aircon", "에어컨", "❄"), ("induction", "인덕션", "♨"))
DEVICE_NOTICE_KEY = "device_notice"


def _on_device_toggle(backend_url: str, profile_id: str, device: str, widget_key: str, label: str) -> None:
    """토글을 누르면 백엔드로 제어를 보낸다. 실패하면 화면은 저장된 값으로 돌아가고 이유를 알려 준다."""
    wanted = "on" if st.session_state.get(widget_key) else "off"
    try:
        control_device(backend_url, profile_id, device, wanted)
    except (BackendAPIError, ValueError) as exc:
        st.session_state[DEVICE_NOTICE_KEY] = ("error", f"{label} 제어에 실패했습니다: {exc}")
    else:
        st.session_state[DEVICE_NOTICE_KEY] = ("ok", f"{label}을 {'켰' if wanted == 'on' else '껐'}습니다. (Mock 제어)")


def render_device_toggles(devices: Mapping, backend_url: str, profile_id: str) -> None:
    """에어컨·인덕션 켜짐/꺼짐 토글. 표시는 항상 저장된 값(토글로 바꾼 값, 없으면 시나리오 기본값)을 따른다."""
    try:
        saved = fetch_device_states(backend_url, profile_id)
    except (BackendAPIError, ValueError):
        saved = {}
    baseline = {"aircon": devices.get("air_conditioner") == "on", "induction": devices.get("induction") == "on"}

    for device, label, icon in DEVICE_TOGGLES:
        is_on = (saved[device] == "on") if device in saved else baseline[device]
        widget_key = f"device_toggle_{profile_id}_{device}"
        st.session_state[widget_key] = is_on          # 위젯 값을 저장된 값에 맞춘다 (눌렀지만 실패한 경우 되돌림)
        st.toggle(
            f"{icon} {label}",
            key=widget_key,
            on_change=_on_device_toggle,
            args=(backend_url, profile_id, device, widget_key, label),
        )
        if device == "induction" and is_on and device not in saved:
            detail = induction_text(devices)             # 시나리오가 알려 준 가동 시간·온도
        else:
            detail = "켜짐" if is_on else "꺼짐"
        st.caption(detail)

    notice = st.session_state.pop(DEVICE_NOTICE_KEY, None)
    if notice:
        (st.success if notice[0] == "ok" else st.warning)(notice[1])


def render_home_card(care_status: Mapping, backend_url: str | None = None, profile_id: str | None = None) -> None:
    with st.container(key="home_card"):
        card_header("주거 환경", "IoT Agent · 기기 제어는 보호자 승인 후 실행 (CCTV는 오른쪽 위)")
        env_column, device_column = st.columns(2, gap="medium")
        with env_column:
            env = care_status.get("indoor_environment")
            if env:
                left, right = st.columns(2)
                with left:
                    _tile("indoor_temp", "실내 온도", _number(env.get("temperature_c"), " ℃", 1))
                with right:
                    _tile("humidity", "습도", _number(env.get("humidity_percent"), " %"))
            else:
                st.warning("실내 온습도를 확인할 수 없습니다.")

        with device_column:
            devices = care_status.get("devices")
            if devices and backend_url and profile_id:
                render_device_toggles(devices, backend_url, profile_id)
            elif devices:
                aircon = str(devices.get("air_conditioner"))
                st.markdown(
                    _device_row("에어컨", DEVICE_STATE.get(aircon, "알 수 없음"), aircon == "on")
                    + _device_row("인덕션", induction_text(devices), devices.get("induction") == "on"),
                    unsafe_allow_html=True,
                )
            else:
                st.warning("기기 상태를 확인할 수 없습니다.")


def render_status_cards(
    run_response: Mapping | None,
    backend_url: str | None = None,
    *,
    profile_id: str | None = None,
    scenario: str | None = None,
) -> None:
    """바이탈 카드와 주거 환경 카드를 그린다 (CCTV는 오른쪽 위 render_cctv_panel).

    profile_id·scenario를 주면 바이탈 카드가 3초마다 갱신되는 실시간 값이 된다 (상태 확인 전에도 보인다).
    """
    care_status = run_response.get("care_status") if isinstance(run_response, Mapping) else None
    live = bool(backend_url and profile_id and scenario)
    if not isinstance(care_status, Mapping):
        if live:
            render_live_vital_card(backend_url, profile_id, scenario, None)
        st.markdown('<div class="care-empty">아직 측정 결과가 없습니다. 왼쪽에서 \'상태 확인하기\'를 눌러 주세요.</div>',
                    unsafe_allow_html=True)
        return
    if live:
        render_live_vital_card(backend_url, profile_id, scenario, care_status)
    else:
        render_vital_card(care_status)
    render_home_card(care_status, backend_url, profile_id if live else None)
