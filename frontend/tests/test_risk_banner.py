"""첫 화면 위험도 배너 테스트 — 기화"""

from streamlit.testing.v1 import AppTest

from src.components.risk_banner import headline, reason_with_values

HEAT = {
    "vital": {"heart_rate": 105, "systolic_bp": 140, "temperature_c": 37.8, "spo2": 96},
    "indoor_environment": {"temperature_c": 33.0, "humidity_percent": 75.0},
    "devices": {"air_conditioner": "off", "induction": "off"},
}


def test_heat_headline_shows_hot_room_and_heart_rate_change_with_values():
    """README 14장 2번: 실내 극한 고온(33℃) + 심박 변화. 백엔드 근거 순서와 상관없이 심각한 것 먼저."""
    reasons = ["심박·혈압 변화", "실내 온도 극한", "영상 판단 불가"]
    assert headline(reasons, HEAT) == "실내 극한 고온(33℃) + 심박·혈압 변화(심박 105회/분 · 혈압 140mmHg)"


def test_note_reasons_are_not_in_headline():
    assert headline(["영상 판단 불가"], HEAT) == ""
    assert reason_with_values("영상 판단 불가", HEAT) == "영상 판단 불가"


def test_other_scenarios_get_their_values():
    induction = {"devices": {"induction": "on", "induction_minutes": 120, "induction_temperature": 300}}
    assert reason_with_values("사람 없는 곳에서 인덕션 오래 켜짐·과열", induction) == \
        "사람 없는 곳에서 인덕션 오래 켜짐·과열(120분 · 300℃)"
    critical = {"vital": {"heart_rate": 140, "systolic_bp": 85, "temperature_c": 36.0, "spo2": 88}}
    assert reason_with_values("산소포화도 위험 범위", critical) == "산소포화도 위험 범위(SpO₂ 88%)"
    assert headline(["CCTV 쓰러짐 의심", "심박·혈압 변화"], {"vital": {"heart_rate": 118}}) == \
        "CCTV 쓰러짐 의심 + 심박·혈압 변화(심박 118회/분)"


def test_missing_values_keep_plain_reason():
    assert reason_with_values("실내 온도 극한", {}) == "실내 온도 극한"
    assert reason_with_values("심박·혈압 변화", None) == "심박·혈압 변화"


def test_banner_is_large_and_above_actions_in_pending_screen():
    """승인 대기 화면에서 배너(위험도)가 '보호자 조치 승인'과 조치안보다 먼저 나온다."""
    app = AppTest.from_string(
        """
from src.approval import render_approval_panel
render_approval_panel(
    {"run_id": "run-h", "status": "pending_approval", "current_step": "위험 판정 완료(경고) → 보호자 승인 대기",
     "care_status": {"run_id": "run-h", "vital": {"heart_rate": 105, "systolic_bp": 140},
                     "indoor_environment": {"temperature_c": 33.0}},
     "emergency": {"run_id": "run-h", "risk_level": "경고", "reasons": ["심박·혈압 변화", "실내 온도 극한"],
                   "proposed_actions": [{"tool": "control_device", "description": "에어컨 냉방 26℃로 켜기",
                                         "arguments": {"device": "aircon", "action": "cool"}, "needs_approval": True}]}},
    "http://backend.test",
)
""", default_timeout=30).run()

    assert not app.exception
    banner = next(m for m in app.markdown if "care-risk" in m.value)
    assert "경고" in banner.value and "실내 극한 고온(33℃)" in banner.value and "심박 105회/분" in banner.value
    order = [el.value for el in app.main if hasattr(el, "value") and isinstance(el.value, str)]
    banner_at = next(i for i, v in enumerate(order) if "care-risk" in v)
    subheader_at = next(i for i, v in enumerate(order) if v == "보호자 조치 승인")
    assert banner_at < subheader_at
    assert not any(c.value.startswith("현재 단계") for c in app.caption)   # 진행 표시와 중복된 줄 제거
    assert [b.label for b in app.button] == ["조치 승인 및 실행", "조치 거절"]
