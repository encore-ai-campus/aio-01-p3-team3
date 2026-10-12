"""첫 화면 오른쪽 CCTV 패널: 위는 캡처, 아래는 백엔드를 거쳐 받은 영상 (src/components/cards.py)."""

import pytest
import requests
from streamlit.testing.v1 import AppTest

from src import api_client
from src.components import cards
from src.components.cards import cctv_video_name

CARE_STATUS = {
    "vital": {"heart_rate": 118, "systolic_bp": 120, "temperature_c": 36.4, "spo2": 96},
    "source": "live",
    "indoor_environment": {"temperature_c": 25.0, "humidity_percent": 50.0},
    "devices": {"air_conditioner": "off", "induction": "off", "induction_minutes": None, "induction_temperature": None},
    "cctv": {"status": "unavailable", "description": "영상 판단 불가", "image_path": "assets/cctv/lying.png"},
}
PANEL = """
from src.components.cards import render_cctv_panel
render_cctv_panel({run}, "http://backend.test", "{scenario}")
"""
MP4 = b"\x00\x00\x00\x18ftypmp42"


@pytest.fixture(autouse=True)
def fresh_video_cache():
    cards._load_video.clear()
    yield
    cards._load_video.clear()


def install_video(monkeypatch, *, data=MP4, error=None):
    requested = []

    def fake_fetch(backend_url, name, **kwargs):
        requested.append((backend_url, name))
        if error:
            raise error
        return data

    monkeypatch.setattr(cards, "fetch_cctv_video", fake_fetch)
    return requested


def run_panel(run="None", scenario="heat"):
    app = AppTest.from_string(PANEL.format(run=run, scenario=scenario)).run()
    assert not app.exception
    return app


@pytest.mark.parametrize(("scenario", "expected"), [
    ("fall", "fall.mp4"), ("heat", "normal.mp4"), ("induction", "kitchen_empty.mp4"),
    ("critical", "lying.mp4"), ("normal", "normal.mp4"),
])
def test_video_name_follows_the_scenario_scene_before_a_run(scenario, expected):
    assert cctv_video_name(None, scenario) == expected


def test_video_name_prefers_the_image_of_this_run():
    assert cctv_video_name({"cctv": {"image_path": "assets/cctv/kitchen_empty.png"}}, "heat") == "kitchen_empty.mp4"
    assert cctv_video_name({"cctv": {"image_path": "C:\\x\\fall.png"}}, None) == "fall.mp4"
    assert cctv_video_name(None, "storm") is None and cctv_video_name(None, None) is None


def test_panel_before_a_run_has_capture_placeholder_and_plays_the_scene_video(monkeypatch):
    requested = install_video(monkeypatch)
    app = run_panel("None", "induction")

    texts = [item.value for item in app.markdown]
    assert any("CCTV · 거실" in text and "확인 전" in text for text in texts)          # 위: 캡처 칸
    assert any("상태 확인 후 캡처가 표시됩니다" in text for text in texts)
    assert any("CCTV 영상 · 거실" in text and "재생 가능" in text for text in texts)    # 아래: 영상 칸
    assert len(app.get("video")) == 1
    assert requested == [("http://backend.test", "kitchen_empty.mp4")]


def test_panel_after_a_run_uses_the_video_of_that_runs_image(monkeypatch):
    requested = install_video(monkeypatch)
    app = run_panel(repr({"care_status": CARE_STATUS}), "heat")

    assert requested == [("http://backend.test", "lying.mp4")]
    assert len(app.get("video")) == 1
    assert any("영상 판단 불가" in item.value for item in app.markdown)


def test_panel_shows_placeholder_when_the_video_is_not_there(monkeypatch):
    install_video(monkeypatch, error=api_client.BackendAPIError("CCTV 영상 조회 실패: 404"))
    app = run_panel("None", "fall")

    assert not app.get("video")
    assert any("영상 준비 중" in item.value for item in app.markdown)


def test_missing_video_is_not_cached_so_a_later_upload_shows_up(monkeypatch):
    install_video(monkeypatch, error=api_client.BackendAPIError("404"))
    assert not run_panel("None", "fall").get("video")

    install_video(monkeypatch)
    assert len(run_panel("None", "fall").get("video")) == 1


def test_home_card_no_longer_contains_the_cctv_capture():
    app = AppTest.from_string(
        f"""
from src.components.cards import render_home_card
render_home_card({CARE_STATUS!r}, "http://backend.test")
"""
    ).run()

    assert not app.exception
    assert not any("CCTV · 거실" in item.value for item in app.markdown)
    assert {m.label for m in app.metric} == {"실내 온도", "습도"}


class FakeResponse:
    def __init__(self, content=b"", ok=True, status_code=200, payload=None):
        self.content, self.ok, self.status_code, self._payload, self.text = content, ok, status_code, payload, ""

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


def test_fetch_cctv_video_calls_the_backend_video_route():
    session = FakeSession(FakeResponse(MP4))
    assert api_client.fetch_cctv_video("http://backend.test/", "assets/video/lying.mp4", session=session) == MP4
    assert session.calls[0][0] == "http://backend.test/video/lying.mp4"


def test_fetch_cctv_video_reports_errors():
    with pytest.raises(api_client.BackendAPIError, match="조회 실패"):
        api_client.fetch_cctv_video("http://backend.test", "fall.mp4",
                                    session=FakeSession(FakeResponse(ok=False, status_code=404, payload={"detail": "없음"})))
    with pytest.raises(api_client.BackendAPIError, match="가져올 수 없습니다"):
        api_client.fetch_cctv_video("http://backend.test", "fall.mp4",
                                    session=FakeSession(error=requests.ConnectionError("down")))
    with pytest.raises(ValueError):
        api_client.fetch_cctv_video("http://backend.test", "")
