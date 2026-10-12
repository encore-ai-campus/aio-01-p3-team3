"""에어컨·인덕션 토글 (src/components/cards.py render_device_toggles)과 기기 제어 API 호출."""

import pytest
import requests
from streamlit.testing.v1 import AppTest

from src import api_client
from src.components import cards

CARE_STATUS = {
    "vital": {"heart_rate": 80, "systolic_bp": 130, "temperature_c": 36.6, "spo2": 97},
    "source": "live",
    "indoor_environment": {"temperature_c": 26.0, "humidity_percent": 55.0},
    "devices": {"air_conditioner": "off", "induction": "on", "induction_minutes": 120, "induction_temperature": 300},
    "cctv": {"status": "unavailable"},
}
APP = """
from src.components.cards import render_home_card
render_home_card({care}, "http://backend.test", "profile-03")
"""


class FakeBackend:
    """저장된 기기 상태를 흉내 낸다 (백엔드 /devices)."""

    def __init__(self, saved=None, fail=False):
        self.saved, self.fail, self.calls = dict(saved or {}), fail, []

    def install(self, monkeypatch):
        monkeypatch.setattr(cards, "fetch_device_states", lambda url, profile_id, **kw: dict(self.saved))
        monkeypatch.setattr(cards, "control_device", self.control)

    def control(self, url, profile_id, device, state, **kw):
        self.calls.append((url, profile_id, device, state))
        if self.fail:
            raise api_client.BackendAPIError("기기 제어 실패: HTTP 503")
        self.saved[device] = state
        return {"status": "success"}


def open_card(care=CARE_STATUS):
    app = AppTest.from_string(APP.format(care=repr(care))).run()
    assert not app.exception
    return app


def toggles(app):
    return {t.label: t.value for t in app.toggle}


def test_toggles_start_from_the_scenario_devices(monkeypatch):
    FakeBackend().install(monkeypatch)
    app = open_card()

    assert toggles(app) == {"❄ 에어컨": False, "♨ 인덕션": True}
    assert any("120분" in c.value and "300" in c.value for c in app.caption)     # 인덕션 가동 시간·온도


def test_saved_state_wins_over_the_scenario(monkeypatch):
    FakeBackend(saved={"induction": "off", "aircon": "on"}).install(monkeypatch)

    assert toggles(open_card()) == {"❄ 에어컨": True, "♨ 인덕션": False}


def test_pressing_a_toggle_sends_the_control_and_shows_the_new_state(monkeypatch):
    backend = FakeBackend()
    backend.install(monkeypatch)
    app = open_card()

    app = next(t for t in app.toggle if t.label == "❄ 에어컨").set_value(True).run()

    assert backend.calls == [("http://backend.test", "profile-03", "aircon", "on")]
    assert toggles(app)["❄ 에어컨"] is True
    assert any("에어컨을 켰습니다" in s.value for s in app.success)

    app = next(t for t in app.toggle if t.label == "♨ 인덕션").set_value(False).run()
    assert backend.calls[-1] == ("http://backend.test", "profile-03", "induction", "off")
    assert toggles(app) == {"❄ 에어컨": True, "♨ 인덕션": False}


def test_failed_control_reverts_the_toggle_and_tells_why(monkeypatch):
    backend = FakeBackend(fail=True)
    backend.install(monkeypatch)
    app = open_card()

    app = next(t for t in app.toggle if t.label == "❄ 에어컨").set_value(True).run()

    assert toggles(app)["❄ 에어컨"] is False                     # 저장된 값(꺼짐)으로 되돌아간다
    assert any("제어에 실패했습니다" in w.value for w in app.warning)


def test_without_backend_profile_the_card_keeps_the_static_rows():
    app = AppTest.from_string(
        f"""
from src.components.cards import render_home_card
render_home_card({CARE_STATUS!r})
"""
    ).run()

    assert not app.exception
    assert len(app.toggle) == 0


class FakeResponse:
    def __init__(self, payload=None, ok=True, status_code=200):
        self._payload, self.ok, self.status_code, self.text = payload, ok, status_code, ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_fetch_device_states_reads_saved_states():
    session = FakeSession(FakeResponse({"profile_id": "profile-03", "devices": {"induction": "off"}}))

    assert api_client.fetch_device_states("http://backend.test/", "profile-03", session=session) == {"induction": "off"}
    assert session.calls[0][1] == "http://backend.test/devices/profile-03"


def test_control_device_posts_profile_device_and_state():
    session = FakeSession(FakeResponse({"status": "success", "state": "on"}))

    result = api_client.control_device("http://backend.test", "profile-03", "aircon", "on", session=session)

    assert result["state"] == "on"
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", "http://backend.test/devices/control")
    assert kwargs["json"] == {"profile_id": "profile-03", "device": "aircon", "state": "on"}


def test_device_api_reports_errors():
    with pytest.raises(api_client.BackendAPIError, match="기기 제어 실패"):
        api_client.control_device("http://backend.test", "profile-03", "aircon", "on",
                                  session=FakeSession(FakeResponse({"detail": "MCP"}, ok=False, status_code=503)))
    with pytest.raises(api_client.BackendAPIError, match="제어할 수 없습니다"):
        api_client.control_device("http://backend.test", "profile-03", "aircon", "on",
                                  session=FakeSession(error=requests.ConnectionError("down")))
    for args in (("", "aircon", "on"), ("profile-03", "heater", "on"), ("profile-03", "aircon", "cool")):
        with pytest.raises(ValueError):
            api_client.control_device("http://backend.test", *args)
