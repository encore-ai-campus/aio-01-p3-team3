"""POST /care/run 통합 테스트: 다섯 시나리오가 docs/scenarios.md 5장 기대 결과대로 나오는지. — 기화

가짜 MCP(시나리오별 mock 값) + 임시 SQLite. LLM 키는 지워서 템플릿 문장으로 진행한다.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from src import main as backend_app
from src import mcp_client
from src.db.database import Database
from src.db.seed import seed_profiles
from src.orchestrator.approval import pending

OFF = {"air_conditioner": "off", "induction": "off", "induction_minutes": None, "induction_temperature": None}
SCENARIOS = {   # docs/scenarios.md 4-1장 (두나 님 mock_data.py와 같은 값)
    "normal":    ({"heart_rate": 72, "systolic_bp": 125, "temperature_c": 36.5, "spo2": 98}, (24.0, 50.0), OFF, "normal.jpg"),
    "heat":      ({"heart_rate": 105, "systolic_bp": 140, "temperature_c": 37.8, "spo2": 96}, (33.0, 75.0), OFF, "normal.jpg"),
    "induction": ({"heart_rate": 80, "systolic_bp": 130, "temperature_c": 36.6, "spo2": 97}, (26.0, 55.0),
                  {"air_conditioner": "off", "induction": "on", "induction_minutes": 120, "induction_temperature": 300},
                  "kitchen_empty.jpg"),
    "fall":      ({"heart_rate": 118, "systolic_bp": 120, "temperature_c": 36.4, "spo2": 96}, (25.0, 50.0), OFF, "fall.jpg"),
    "critical":  ({"heart_rate": 140, "systolic_bp": 85, "temperature_c": 36.0, "spo2": 88}, (25.0, 50.0), OFF, "lying.jpg"),
}
ANALYSIS = {   # docs/scenarios.md 4-3장 기대 분석 결과
    "normal.jpg": (True, "sitting", False), "kitchen_empty.jpg": (False, "none", False),
    "fall.jpg": (True, "fallen", True), "lying.jpg": (True, "lying", False),
}


def fake_tools():
    def scenario(args):
        return SCENARIOS[args["scenario"]]

    def analyze(args):
        name = args["image_path"].rsplit("/", 1)[-1]
        visible, posture, fall = ANALYSIS[name]
        return {"image_path": args["image_path"], "available": True, "person_visible": visible,
                "posture": posture, "fall_suspected": fall, "confidence": "high", "description": f"{name} 장면"}

    return {
        "get_vitals": lambda a: dict(scenario(a)[0]),
        "get_indoor_env": lambda a: {"temperature_c": scenario(a)[1][0], "humidity_percent": scenario(a)[1][1]},
        "get_device_status": lambda a: dict(scenario(a)[2]),
        "capture_cctv": lambda a: {"image_path": f"assets/cctv/{scenario(a)[3]}"},
        "analyze_cctv": analyze,
        "find_hospital": lambda a: {"name": "강남안심병원", "distance_km": 1.2, "type": "응급실"},
        "notify_guardian": lambda a: {"tool": "notify_guardian", "status": "success"},
    }


@pytest.fixture(autouse=True)
def no_llm_no_wait(monkeypatch):
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda delay, *a, **k: real_sleep(0))


@pytest.fixture
def mcp(monkeypatch):
    tools, calls = fake_tools(), []

    async def fake_call_tool(name, arguments=None, *, url=None):
        calls.append(name)
        return tools[name](arguments or {})

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    return {"tools": tools, "calls": calls}


@pytest.fixture
def client(tmp_path, mcp):
    db = Database(tmp_path / "app.db")
    seed_profiles(db)
    backend_app.app.dependency_overrides[backend_app.get_db] = lambda: db
    yield TestClient(backend_app.app), db
    backend_app.app.dependency_overrides.clear()


def care_run(client, scenario, profile_id, fault=()):
    response = client.post("/care/run", json={"profile_id": profile_id, "scenario": scenario, "fault": list(fault)})
    assert response.status_code == 200, response.text
    return response.json()


def tools_of(body):
    return {a["tool"]: a for a in body["emergency"]["proposed_actions"]}


def test_normal_ends_with_no_issue(client):
    body = care_run(client[0], "normal", "profile-01")
    assert body["status"] == "no_issue"
    assert body["emergency"]["risk_level"] == "정상"     # 취약도 "상"이어도 정상은 올리지 않음
    assert pending.get(body["run_id"]) is None


def test_heat_asks_approval_for_aircon(client):
    body = care_run(client[0], "heat", "profile-02")
    assert body["status"] == "pending_approval"
    assert body["emergency"]["risk_level"] == "경고"
    assert body["emergency"]["axes"]["environment"] == "경고"
    aircon = tools_of(body)["control_device"]
    assert aircon["needs_approval"] is True
    assert aircon["arguments"]["device"] == "aircon" and aircon["arguments"]["mode"] == "cool"
    assert "call_119" not in tools_of(body)


def test_induction_asks_approval_to_turn_off(client):
    body = care_run(client[0], "induction", "profile-03")
    assert body["status"] == "pending_approval"
    assert body["emergency"]["risk_level"] == "주의"
    assert tools_of(body)["control_device"]["arguments"] == {"device": "induction", "action": "off"}


def test_fall_is_critical_from_cctv_and_119_needs_approval(client):
    body = care_run(client[0], "fall", "profile-01")
    assert body["emergency"]["risk_level"] == "위급"
    assert body["emergency"]["fall_state"] == "confirmed"
    assert body["emergency"]["axes"]["fall"] == "위급"
    assert tools_of(body)["call_119"]["needs_approval"] is True
    assert body["emergency"]["cctv_summary"] == "fall.jpg 장면"


def test_critical_119_is_approval_request_not_auto(client):
    body = care_run(client[0], "critical", "profile-01")
    assert body["status"] == "pending_approval"
    assert body["emergency"]["risk_level"] == "위급"
    assert body["emergency"]["auto_119"] is None          # 해든 님 결정: 자동 119 꺼짐
    assert tools_of(body)["call_119"]["needs_approval"] is True


def test_pending_approval_is_saved_for_approve_step(client):
    body = care_run(client[0], "fall", "profile-01")
    saved = pending.get(body["run_id"])
    assert saved["emergency"]["risk_level"] == "위급"
    assert saved["raw"]["context"] is not None             # ⑤ Summary Agent가 다시 받는 값


def test_vital_total_failure_stops_safely_and_notifies(client, mcp):
    def down(args):
        raise mcp_client.McpConnectionError("MCP 연결 실패")
    mcp["tools"]["get_vitals"] = down
    body = care_run(client[0], "fall", "profile-01", fault=["vital"])
    assert body["status"] == "fail"
    assert "센서" in body["message"]
    assert "notify_guardian" in mcp["calls"]
    assert body["emergency"] is None


def test_llm_fault_uses_template_and_is_logged(client):
    test_client, db = client
    body = care_run(test_client, "fall", "profile-01", fault=["llm"])
    assert body["status"] == "pending_approval"
    assert body["emergency"]["risk_level"] == "위급"       # 판정은 코드라 LLM 장애와 무관
    llm_logs = [(log["status"], log["recovery"]) for log in db.logs(body["run_id"]) if log["step"] == "llm"]
    assert ("fallback", "template") in llm_logs
    assert any(status == "retry" for status, _ in llm_logs)


def test_vision_fault_judges_by_vitals_only(client):
    body = care_run(client[0], "critical", "profile-01", fault=["vision"])
    assert body["emergency"]["risk_level"] == "위급"       # 바이탈 위험 범위 3개
    assert body["care_status"]["cctv"]["status"] == "failed"
    assert body["care_status"]["cctv"]["image_path"] == "assets/cctv/lying.jpg"


def test_bad_request_is_rejected(client):
    response = client[0].post("/care/run", json={"profile_id": "profile-01", "scenario": "weather"})
    assert response.status_code == 422
