"""화면 토글용 기기 제어 API: /devices/{profile_id}, /devices/control."""
from fastapi.testclient import TestClient

from src import main
from src.db.database import Database
from src.db.device_states import DeviceStates
from src.db.seed import seed_profiles


def make_client(tmp_path, monkeypatch, behavior=None):
    db = Database(tmp_path / "devices.db")
    seed_profiles(db)
    calls = []

    async def fake_call_tool(name, arguments=None, *, url=None):
        calls.append((name, arguments))
        if behavior:
            behavior()
        return {"tool": name, "status": "success", "message": "Mock 실행", "recovery": None}

    monkeypatch.setattr(main.mcp_client, "call_tool", fake_call_tool)
    main.app.dependency_overrides[main.get_db] = lambda: db
    return TestClient(main.app), db, calls


def teardown_function():
    main.app.dependency_overrides.pop(main.get_db, None)


def test_states_start_empty_and_unknown_profile_is_404(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path, monkeypatch)

    assert client.get("/devices/profile-01").json() == {"profile_id": "profile-01", "devices": {}}
    assert client.get("/devices/profile-99").status_code == 404


def test_toggle_calls_mcp_with_the_right_action_and_saves_the_state(tmp_path, monkeypatch):
    client, _, calls = make_client(tmp_path, monkeypatch)
    expected = [("aircon", "on", "cool"), ("aircon", "off", "off"), ("induction", "on", "on"), ("induction", "off", "off")]

    for device, state, action in expected:
        response = client.post("/devices/control", json={"profile_id": "profile-03", "device": device, "state": state})
        assert response.status_code == 200, response.text
        assert response.json()["state"] == state and response.json()["message"] == "Mock 실행"
        assert calls[-1] == ("control_device", {"device": device, "action": action})

    assert client.get("/devices/profile-03").json()["devices"] == {"aircon": "off", "induction": "off"}


def test_states_are_kept_per_profile(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path, monkeypatch)
    client.post("/devices/control", json={"profile_id": "profile-01", "device": "aircon", "state": "on"})

    assert client.get("/devices/profile-01").json()["devices"] == {"aircon": "on"}
    assert client.get("/devices/profile-02").json()["devices"] == {}


def test_mcp_failures_do_not_change_the_saved_state(tmp_path, monkeypatch):
    client, db, _ = make_client(tmp_path, monkeypatch)

    async def down(name, arguments=None, *, url=None):
        raise main.mcp_client.McpConnectionError("MCP 연결 실패")

    monkeypatch.setattr(main.mcp_client, "call_tool", down)
    response = client.post("/devices/control", json={"profile_id": "profile-01", "device": "aircon", "state": "on"})
    assert response.status_code == 503
    assert DeviceStates(db).all("profile-01") == {}

    async def tool_error(name, arguments=None, *, url=None):
        raise main.mcp_client.McpToolError(name, "fail")

    monkeypatch.setattr(main.mcp_client, "call_tool", tool_error)
    response = client.post("/devices/control", json={"profile_id": "profile-01", "device": "aircon", "state": "on"})
    assert response.status_code == 502
    assert DeviceStates(db).all("profile-01") == {}


def test_rejects_unknown_profile_device_and_state(tmp_path, monkeypatch):
    client, _, calls = make_client(tmp_path, monkeypatch)

    for body in (
        {"profile_id": "profile-99", "device": "aircon", "state": "on"},
        {"profile_id": "profile-01", "device": "heater", "state": "on"},
        {"profile_id": "profile-01", "device": "aircon", "state": "cool"},
        {"profile_id": "", "device": "aircon", "state": "on"},
    ):
        assert client.post("/devices/control", json=body).status_code in (404, 422), body
    assert calls == []


def test_a_new_care_run_resets_the_toggled_states(tmp_path, monkeypatch):
    client, db, _ = make_client(tmp_path, monkeypatch)
    client.post("/devices/control", json={"profile_id": "profile-03", "device": "induction", "state": "off"})
    client.post("/devices/control", json={"profile_id": "profile-02", "device": "aircon", "state": "on"})

    async def fake_run_care(request, *, db):
        return {"run_id": "run-1", "status": "no_issue", "current_step": "완료", "message": "이상 없음"}

    monkeypatch.setattr(main, "run_care", fake_run_care)
    client.post("/care/run", json={"profile_id": "profile-03", "scenario": "induction", "fault": []})

    assert DeviceStates(db).all("profile-03") == {}                 # 확인한 어르신만 초기화
    assert DeviceStates(db).all("profile-02") == {"aircon": "on"}
