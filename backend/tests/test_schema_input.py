"""main schemas.py(CareStatusResult) 형식으로 들어와도 확정안 형식과 같은 판정이 나오는지 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 지혜 님 main 스키마(vital.heart_rate, indoor_environment, devices.induction_minutes)와
#   확정안 형식(vitals.hr, env, 구조 기기)이 달라 rules.risk.normalize_care_status()를 넣고 같은 결과인지 확인.

import pytest

from src.agents.emergency import run_emergency
from src.rules.risk import evaluate, normalize_care_status
from src.schemas import CareStatusResult
from tests.test_risk_rules import PROFILES, SCENARIOS, types
from src.agents.profile import vulnerability


def to_schema(name: str, vuln: str, cctv_ok: bool = True) -> dict:
    """확정안 시나리오 값 → main CareStatusResult(model_dump). critical은 Scenario에 아직 없어 fall로 둠."""
    s = SCENARIOS[name]
    v, d = s["vitals"], s["devices"]
    cctv = s["cctv"]
    data = CareStatusResult(
        run_id="run-1", profile_id="profile-01", scenario=name if name != "critical" else "fall",
        vital={"heart_rate": v["hr"], "systolic_bp": v["sbp"], "diastolic_bp": 80,
               "temperature_c": v["temp"], "spo2": v["spo2"]},
        indoor_environment={"temperature_c": s["env"]["temp"], "humidity_percent": s["env"]["humidity"]},
        devices={"air_conditioner": d["aircon"]["state"], "induction": d["induction"]["state"],
                 "induction_minutes": d["induction"]["minutes"] or None},
        cctv=({"image_path": "assets/cctv/x.jpg", "person_visible": cctv.get("person_visible"),
               "posture": cctv.get("posture"), "fall_suspected": cctv.get("fall_suspected"),
               "confidence": 0.9, "description": cctv.get("description"), "status": "analyzed"}
              if cctv_ok else {"status": "failed"}),
        vulnerability=vuln, area="서울 강남구",
    )
    return data.model_dump()


@pytest.mark.parametrize("name, profile", [
    ("normal", "profile-01"), ("heat", "profile-02"), ("heat", "profile-01"), ("induction", "profile-03"),
    ("induction", "profile-01"), ("fall", "profile-03"), ("fall", "profile-01"), ("critical", "profile-01"),
])
def test_schema_input_matches_plan_format(name, profile):
    vuln = vulnerability(PROFILES[profile])
    plan = evaluate({**SCENARIOS[name], "vulnerability": vuln}, month=8)
    schema = evaluate(to_schema(name, vuln), month=8)
    assert schema["risk_level"] == plan["risk_level"]
    assert schema["reason_codes"] == plan["reason_codes"]
    assert types(schema) == types(plan)


def test_schema_cctv_failure_is_unavailable():
    c = normalize_care_status(to_schema("fall", "하", cctv_ok=False))
    assert c["cctv"]["available"] is False
    assert evaluate(c, month=8)["risk_level"] == "경고"     # 확정안: CCTV 실패 → 바이탈 1개로 경고


def test_schema_induction_temperature_when_added():
    """지혜 님이 induction_temperature 칸을 넣으면 과열도 판정 (켜진 시간 몰라도)."""
    c = to_schema("induction", "하")
    c["devices"].update(induction_minutes=None, induction_temperature=300)
    assert normalize_care_status(c)["devices"]["induction"] == {"state": "on", "minutes": None, "temperature": 300}
    assert "INDUCTION_UNATTENDED" in evaluate(c, month=8)["reason_codes"]


def test_normalize_keeps_plan_format_and_is_idempotent():
    plan = {**SCENARIOS["heat"], "vulnerability": "중"}
    once = normalize_care_status(plan)
    assert once["vitals"] == plan["vitals"] and once["devices"] == plan["devices"]
    assert normalize_care_status(once) == once


def test_schema_voice_response_and_cache_source():
    c = to_schema("fall", "하")
    c["fall_event"] = {"voice_response": "help"}
    c["source"] = "cache"
    n = normalize_care_status(c)
    assert n["fall_event"]["watch_response"] == "help"
    assert n["vitals"]["source"] == "cache"


def test_emergency_agent_reads_schema_and_area():
    asked = []
    out = run_emergency(to_schema("heat", "중"), find_hospital=lambda area: asked.append(area) or "○○병원 응급실 (1.2km)")
    assert out["risk_level"] == "경고"
    assert asked == ["서울 강남구"]
    assert out["hospital"] == "○○병원 응급실 (1.2km)"
