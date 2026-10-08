"""Orchestration 1 테스트: Vital·IoT·Profile → CareStatusResult. 가짜 MCP + 임시 SQLite. — 기화"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src import mcp_client
from src.db.database import Database
from src.db.seed import seed_profiles
from src.db.vital_service import VitalService
from src.orchestrator.monitoring import run_monitoring

MOCK_VITAL = {"heart_rate": 118, "systolic_bp": 120, "temperature_c": 36.4, "spo2": 96}
FALL_ANALYSIS = {"image_path": "assets/cctv/fall.jpg", "available": True, "person_visible": True,
                 "posture": "fallen", "fall_suspected": True, "confidence": "high",
                 "description": "거실 바닥에 사람이 쓰러져 있는 것으로 보입니다."}
TOOLS = {
    "get_vitals": lambda args: MOCK_VITAL,
    "get_indoor_env": lambda args: {"temperature_c": 25.0, "humidity_percent": 50.0},
    "get_device_status": lambda args: {"air_conditioner": "off", "induction": "off",
                                       "induction_minutes": None, "induction_temperature": None},
    "capture_cctv": lambda args: {"image_path": "assets/cctv/fall.jpg"},
    "analyze_cctv": lambda args: FALL_ANALYSIS,
}


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda delay, *a, **k: real_sleep(0))


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "app.db")
    seed_profiles(database)
    return database


@pytest.fixture
def mcp(monkeypatch):
    """도구 이름 → 처리 함수. 테스트에서 바꿔 끼워 장애를 만든다."""
    tools = dict(TOOLS)
    calls = []

    async def fake_call_tool(name, arguments=None, *, url=None):
        calls.append(name)
        return tools[name](arguments or {})

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    return {"tools": tools, "calls": calls}


def run(db, scenario="fall", profile_id="profile-01", fault=()):
    return asyncio.run(run_monitoring(db=db, run_id="run-1", profile_id=profile_id,
                                      scenario=scenario, fault=fault))


def simulator_reading(db, heart_rate=90):
    VitalService(db).save_vital_reading(dict(
        reading_id=f"r-{heart_rate}", profile_id="profile-01", scenario="fall",
        heart_rate=heart_rate, systolic_bp=120, temperature_c=36.4, spo2=96,
        # 1초 전으로: datetime.now()와 DB의 time.time()이 수 ms 어긋나면 "미래 측정값"으로 거절됨
        measured_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))


def test_without_simulator_uses_mcp_mock(db, mcp):
    result = run(db)
    assert result.vital.heart_rate == 118
    assert result.source == "mock"
    assert result.indoor_environment.temperature_c == 25.0
    assert result.devices.induction == "off"
    assert result.cctv.status == "analyzed" and result.cctv.fall_suspected is True
    assert result.cctv.confidence == 0.9
    assert result.vulnerability == "상"          # profile-01 = 84세, 독거, 지병, 거동 불편
    assert result.errors == []


def test_fresh_simulator_reading_is_live(db, mcp):
    simulator_reading(db, heart_rate=90)
    result = run(db)
    assert result.vital.heart_rate == 90
    assert result.source == "live"
    assert "get_vitals" not in mcp["calls"]


def test_vital_fault_falls_back_to_cache(db, mcp):
    simulator_reading(db, heart_rate=90)
    run(db)                                      # 정상 실행으로 캐시를 채움
    result = run(db, fault=["vital"])
    assert result.vital.heart_rate == 90
    assert result.source == "cache"


def test_vision_fault_keeps_image_for_guardian(db, mcp):
    result = run(db, fault=["vision"])
    assert result.cctv.status == "failed"
    assert result.cctv.image_path == "assets/cctv/fall.jpg"
    assert result.cctv.description == "영상 판단 불가"
    assert "cctv_failed" in result.errors
    assert result.vital is not None              # 바이탈은 그대로 진행


def test_mcp_down_gives_empty_values_not_exception(db, mcp):
    def down(args):
        raise mcp_client.McpConnectionError("MCP 연결 실패")
    for name in mcp["tools"]:
        mcp["tools"][name] = down
    result = run(db)
    assert result.vital is None and result.indoor_environment is None and result.devices is None
    assert result.cctv.status == "failed"
    assert set(result.errors) == {"vital_unavailable", "indoor_environment_unavailable",
                                  "devices_unavailable", "cctv_failed"}


def test_unknown_profile_is_treated_as_high_vulnerability(db, mcp):
    result = run(db, profile_id="profile-99")
    assert result.vulnerability == "상"
    assert "profile_missing" in result.errors


def test_retries_are_logged(db, mcp):
    run(db, fault=["vision"])
    steps = [(log["step"], log["status"]) for log in db.logs("run-1")]
    assert ("vision", "retry") in steps and ("vision", "fail") in steps
