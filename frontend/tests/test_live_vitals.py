"""실시간 바이탈 카드 (src/components/live_vitals.py)와 최근 바이탈 API 호출."""

import pytest
import requests
from streamlit.testing.v1 import AppTest

from src import api_client
from src.components import live_vitals
from src.components.live_vitals import REFRESH_SECONDS, age_text, live_caption, live_values

READING = {
    "status": "ok", "profile_id": "profile-02", "scenario": "heat",
    "heart_rate": 105, "systolic_bp": 140, "temperature_c": 37.8, "spo2": 96,
    "measured_at": "2026-10-12T14:03:45+09:00", "age_seconds": 7.0,
    "history": [{"measured_at": "t1", "heart_rate": 101}, {"measured_at": "t2", "heart_rate": 103},
                {"measured_at": "t3", "heart_rate": 105}],
}
RUN_VITAL = {"heart_rate": 80, "systolic_bp": 130, "temperature_c": 36.6, "spo2": 97,
             "measured_at": "2026-10-12T14:00:00+09:00"}
CARD_APP = """
from src.components.live_vitals import render_live_vital_card
render_live_vital_card("http://backend.test", "profile-02", "heat", {care})
"""


def run_card(monkeypatch, *, reading=None, error=None, care=None):
    def fake_latest(backend_url, profile_id, scenario, *, limit):
        assert (backend_url, profile_id, scenario, limit) == ("http://backend.test", "profile-02", "heat", 1)
        if error:
            raise api_client.BackendAPIError(error)
        return reading

    monkeypatch.setattr(live_vitals, "request_latest_vital", fake_latest)
    app = AppTest.from_string(CARD_APP.format(care=repr(care))).run()
    assert not app.exception
    return app


@pytest.mark.parametrize(("age", "expected"), [(None, ""), (0, "방금 전"), (4.9, "방금 전"), (7, "7초 전"), (59, "59초 전"), (125, "2분 전")])
def test_age_text(age, expected):
    assert age_text(age) == expected


def test_values_and_caption():
    assert live_values(READING) == [("심박", "105 bpm"), ("수축기 혈압", "140 mmHg"), ("체온", "37.8 ℃"), ("산소포화도", "96 %")]
    assert live_values({"heart_rate": 70})[1] == ("수축기 혈압", "—")
    caption = live_caption(READING)
    assert "14:03:45" in caption and "7초 전" in caption and "수신 지연" not in caption
    stale = live_caption({**READING, "age_seconds": 100.0})
    assert "수신 지연" in stale and "새 측정값이 들어오지 않고" in stale


def test_card_shows_live_metrics_and_caption(monkeypatch):
    app = run_card(monkeypatch, reading=READING)

    assert {m.label: m.value for m in app.metric} == dict(live_values(READING))
    assert not any("<svg" in item.value for item in app.markdown)      # 그래프는 그리지 않는다
    assert any(f"{REFRESH_SECONDS}초마다 갱신" in item.value for item in app.caption)
    assert any("실시간 바이탈" in item.value for item in app.markdown)


def test_card_keeps_source_of_this_runs_value_when_not_live(monkeypatch):
    care = {"vital": RUN_VITAL, "source": "cache"}
    app = run_card(monkeypatch, reading=READING, care=care)

    assert {m.label: m.value for m in app.metric}["심박"] == "105 bpm"      # 표시는 실시간 값
    assert any("이번 확인 결과" in item.value and "이전 측정값" in item.value for item in app.caption)


def test_card_falls_back_to_this_runs_vital_when_live_is_unavailable(monkeypatch):
    care = {"vital": RUN_VITAL, "source": "live"}
    for kwargs in ({"error": "연결 끊김"}, {"reading": {"status": "no_data"}}):
        app = run_card(monkeypatch, care=care, **kwargs)
        assert {m.label: m.value for m in app.metric}["심박"] == "80 bpm"
        assert any("실시간 값을 받지 못해" in item.value for item in app.caption)


def test_card_empty_and_error_states_without_a_run(monkeypatch):
    app = run_card(monkeypatch, reading={"status": "no_data"})
    assert [m.label for m in app.metric] == [] and any("아직 수신된 측정값이 없습니다" in i.value for i in app.info)

    app = run_card(monkeypatch, error="연결할 수 없습니다")
    assert [m.label for m in app.metric] == [] and any("바이탈을 불러오지 못했습니다" in w.value for w in app.warning)


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload, self.ok, self.status_code, self.text = payload, ok, 200 if ok else 500, ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_request_latest_vital_sends_profile_scenario_and_limit():
    session = FakeSession(FakeResponse(READING))
    result = api_client.request_latest_vital("http://backend.test/", "profile-02", "heat", limit=10, session=session)

    assert result["heart_rate"] == 105
    url, kwargs = session.calls[0]
    assert url == "http://backend.test/vitals/latest"
    assert kwargs["params"] == {"profile_id": "profile-02", "scenario": "heat", "limit": 10}


def test_request_latest_vital_reports_connection_and_input_errors():
    with pytest.raises(api_client.BackendAPIError, match="연결할 수 없습니다"):
        api_client.request_latest_vital("http://backend.test", "profile-02", "heat",
                                        session=FakeSession(error=requests.ConnectionError("down")))
    with pytest.raises(ValueError):
        api_client.request_latest_vital("http://backend.test", "profile-02", "storm")
    with pytest.raises(ValueError):
        api_client.request_latest_vital("http://backend.test", " ", "heat")
