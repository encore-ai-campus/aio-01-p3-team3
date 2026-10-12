"""main schemas.py(CareStatusResult) 형식으로 들어와도 확정안 형식과 같은 판정이 나오는지 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 지혜 님 main 스키마(vital.heart_rate, indoor_environment, devices.induction_minutes)와
#   확정안 형식(vitals.hr, env, 구조 기기)이 달라 rules.risk.normalize_care_status()를 넣고 같은 결과인지 확인.
# 2026-10-08 해든 (두나 님 CCTV 연결): status·숫자 confidence 테스트 추가.
# 2026-10-08 해든 (main 문서 개정판): 스키마에 critical·induction_temperature가 들어가 그대로 씀, 기대값을 docs/scenarios.md 8장으로.
# 2026-10-12 해든 (CCTV 출력 계약, 선택지 B): analyzed인데 필수 4항목이 빠지면 영상 판단 불가로 보는지 테스트 추가.

import pytest

from src.agents.emergency import run_emergency
from src.rules.risk import cctv_contract_errors, evaluate, normalize_care_status
from src.schemas import CareStatusResult
from tests.test_risk_rules import PROFILES, SCENARIOS, types
from src.agents.profile import vulnerability


def to_schema(name: str, vuln: str, cctv_ok: bool = True) -> dict:
    """확정안 시나리오 값 → main CareStatusResult(model_dump)."""
    s = SCENARIOS[name]
    v, d = s["vitals"], s["devices"]
    cctv = s["cctv"]
    data = CareStatusResult(
        run_id="run-1", profile_id="profile-01", scenario=name,
        vital={"heart_rate": v["hr"], "systolic_bp": v["sbp"],
               "temperature_c": v["temp"], "spo2": v["spo2"]},
        indoor_environment={"temperature_c": s["env"]["temp"], "humidity_percent": s["env"]["humidity"]},
        devices={"air_conditioner": d["aircon"]["state"], "induction": d["induction"]["state"],
                 "induction_minutes": d["induction"]["minutes"] or None,
                 "induction_temperature": d["induction"]["temperature"] or None},
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
    assert evaluate(c, month=8)["risk_level"] == "주의"     # docs/scenarios.md 8장: CCTV 실패 → 심박 변화만


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
    out = run_emergency(to_schema("fall", "중"), find_hospital=lambda area: asked.append(area) or "○○병원 응급실 (1.2km)")
    assert out["risk_level"] == "위급"
    assert asked == ["서울 강남구"]
    assert out["hospital"] == "○○병원 응급실 (1.2km)"


def test_cctv_status_and_numeric_confidence_from_analyzer():
    """두나 님 analyze_cctv 결과(status, 0~1 confidence)를 그대로 넘겨도 판단 불가·확신 낮음을 바로 읽음."""
    off = normalize_care_status({"cctv": {"status": "unavailable", "available": False, "person_visible": False, "posture": "none"}})
    assert off["cctv"]["available"] is False
    low = normalize_care_status({"cctv": {"status": "analyzed", "available": True, "posture": "fallen", "confidence": 0.4}})
    assert low["cctv"]["confidence"] == "low"


# ---------- CCTV 출력 계약 (해든 10/12, 선택지 B) ----------

FALL_CCTV = {"image_path": "assets/cctv/fall.jpg", "status": "analyzed", "person_visible": True,
             "posture": "fallen", "fall_suspected": True, "confidence": 0.9, "description": "바닥에 누워 계신 것으로 보입니다."}


def test_contract_passes_full_analyzed_and_failed_without_fields():
    assert cctv_contract_errors(FALL_CCTV) == []
    assert cctv_contract_errors({"status": "failed", "image_path": "assets/cctv/fall.jpg"}) == []
    assert cctv_contract_errors({"status": "unavailable"}) == []


@pytest.mark.parametrize("missing", ["person_visible", "posture", "fall_suspected", "description"])
def test_analyzed_without_required_field_becomes_unjudgeable(missing):
    """분석 성공이라면서 필수 항목이 빠지면 믿지 않고 영상 판단 불가 → 원본 캡처 확인 요청, 바이탈 중심 판정."""
    cctv = {k: v for k, v in FALL_CCTV.items() if k != missing}
    if missing == "description":
        cctv["summary"] = None
    assert cctv_contract_errors(cctv)
    data = to_schema("normal", "하")
    data["cctv"] = cctv
    cs = normalize_care_status(data)
    assert cs["cctv"]["available"] is False and cs["cctv"]["status"] == "failed"
    assert cs["cctv"]["image_path"] == "assets/cctv/fall.jpg"          # 원본 캡처 경로는 남김
    r = evaluate(data, month=8)
    assert "CCTV_UNAVAILABLE" in r["reason_codes"] and r["fall_state"] != "confirmed"


def test_analyzed_with_summary_only_still_passes():
    """두나 님 도구는 summary도 같이 줌. description이 비어 있어도 summary로 채운 뒤 검사한다."""
    data = to_schema("normal", "하")
    data["cctv"] = {**FALL_CCTV, "description": None, "summary": "바닥에 누워 계신 것으로 보입니다."}
    assert evaluate(data, month=8)["fall_state"] == "confirmed"
