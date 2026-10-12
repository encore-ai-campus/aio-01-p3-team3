"""GET /vitals/latest: 화면의 실시간 심박수가 쓰는 최근 측정값 조회."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src import main
from src.db.database import Database


def _reading(profile, scenario, heart_rate, measured_at, **extra):
    return {"profile_id": profile, "scenario": scenario, "heart_rate": heart_rate,
            "systolic_bp": 120, "temperature_c": 36.5, "spo2": 97,
            "measured_at": measured_at.isoformat(timespec="seconds"), **extra}


def _client(db):
    main.app.dependency_overrides[main.get_db] = lambda: db
    return TestClient(main.app)


def test_no_data_is_ok_not_an_error(tmp_path):
    db = Database(tmp_path / "live.db")
    try:
        response = _client(db).get("/vitals/latest", params={"profile_id": "profile-02", "scenario": "heat"})
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_data" and body["heart_rate"] is None and body["history"] == []


def test_returns_newest_value_and_history_oldest_first(tmp_path):
    db = Database(tmp_path / "live.db")
    now = datetime.now(timezone.utc)
    try:
        client = _client(db)
        for seconds_ago, heart_rate in ((45, 101), (30, 103), (15, 105), (5, 107)):
            stored = client.post("/vitals/readings", json=_reading(
                "profile-02", "heat", heart_rate, now - timedelta(seconds=seconds_ago)))
            assert stored.status_code == 200
        response = client.get("/vitals/latest", params={"profile_id": "profile-02", "scenario": "heat", "limit": 3})
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)

    body = response.json()
    assert body["status"] == "ok" and body["heart_rate"] == 107
    assert [point["heart_rate"] for point in body["history"]] == [103, 105, 107]
    assert 0 <= body["age_seconds"] < 60


def test_other_profile_scenario_and_stale_values_are_not_mixed_in(tmp_path):
    db = Database(tmp_path / "live.db")
    now = datetime.now(timezone.utc)
    try:
        client = _client(db)
        client.post("/vitals/readings", json=_reading("profile-02", "heat", 105, now - timedelta(seconds=5)))
        client.post("/vitals/readings", json=_reading("profile-01", "fall", 118, now - timedelta(seconds=5)))
        client.post("/vitals/readings", json=_reading("profile-03", "induction", 80, now - timedelta(seconds=900)))
        mixed = client.get("/vitals/latest", params={"profile_id": "profile-02", "scenario": "fall"}).json()
        stale = client.get("/vitals/latest", params={"profile_id": "profile-03", "scenario": "induction"}).json()
        own = client.get("/vitals/latest", params={"profile_id": "profile-01", "scenario": "fall"}).json()
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)

    assert mixed["status"] == "no_data"      # 다른 시나리오 값은 섞이지 않는다
    assert stale["status"] == "no_data"      # 오래된 값(기본 120초 초과)은 쓰지 않는다
    assert own["status"] == "ok" and own["heart_rate"] == 118


def test_rejects_unknown_scenario_and_empty_profile(tmp_path):
    db = Database(tmp_path / "live.db")
    try:
        client = _client(db)
        assert client.get("/vitals/latest", params={"profile_id": "profile-01", "scenario": "storm"}).status_code == 422
        assert client.get("/vitals/latest", params={"profile_id": ""}).status_code == 422
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
