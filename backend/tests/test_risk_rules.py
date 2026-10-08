"""위험도 규칙표·취약도 계산 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 테스트를 넣음. 계획서 8.8 테스트 목록 1~4번과 결정 D1·D2.
#   - notes/_지난파일/test_risk_rules.py(폭염·한파)는 쓰지 않고 README 시나리오 기준으로 새로 씀.
#   - 시나리오 값은 README 6장 mock_data.py와 같음. mock 값이 바뀌면 여기도 같이 바꿔야 함.
# 2026-10-08 해든 (4단계): 낙상 축 도입으로 CCTV_FALL → FALL_DETECTED, fall 조치에 speaker_check 추가.
#   낙상 케이스는 tests/test_fall_cases.py에 따로 모음.
# 2026-10-08 해든 (축 정리): 근거 문장이 축별 원인(심박·혈압 / 산소포화도 / 체온)으로 바뀜. 축 테스트는 tests/test_axes.py.
# 2026-10-08 해든 (2단계): heat 근거 문장 테스트 추가. tests/test_llm_contract.py가 SCENARIOS·care()를 가져다 씀.

import pytest

from src.agents.profile import run_profile, vulnerability
from src.rules.risk import (
    detect_causes,
    evaluate,
    indoor_state,
    induction_on_minutes,
    risk_level,
    vital_score,
)

CCTV_NORMAL = {"person_visible": True, "posture": "sitting", "fall_suspected": False, "description": "앉아 있음"}
CCTV_EMPTY = {"person_visible": False, "posture": "none", "fall_suspected": False, "description": "사람 없음"}
CCTV_FALL = {"person_visible": True, "posture": "fallen", "fall_suspected": True, "description": "쓰러짐 의심"}
CCTV_LYING = {"person_visible": True, "posture": "lying", "fall_suspected": False, "description": "누워 있음"}

SCENARIOS = {
    "normal": {"vitals": {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98},
               "env": {"temp": 24}, "devices": {"aircon": "off", "induction": "off"}, "cctv": CCTV_NORMAL},
    "heat": {"vitals": {"hr": 105, "sbp": 140, "temp": 37.8, "spo2": 96},
             "env": {"temp": 33}, "devices": {"aircon": "off", "induction": "off"}, "cctv": CCTV_NORMAL},
    "induction": {"vitals": {"hr": 80, "sbp": 130, "temp": 36.6, "spo2": 97},
                  "env": {"temp": 26}, "devices": {"aircon": "off", "induction": "on(2h)"}, "cctv": CCTV_EMPTY},
    "fall": {"vitals": {"hr": 118, "sbp": 100, "temp": 36.3, "spo2": 93},
             "env": {"temp": 25}, "devices": {"aircon": "off", "induction": "off"}, "cctv": CCTV_FALL},
    "critical": {"vitals": {"hr": 140, "sbp": 85, "temp": 36.0, "spo2": 88},
                 "env": {"temp": 25}, "devices": {"aircon": "off", "induction": "off"}, "cctv": CCTV_LYING},
}


def care(name, vulnerability="중", **override):
    return {**SCENARIOS[name], "vulnerability": vulnerability, **override}


def types(result):
    return [a["type"] for a in result["actions"]]


# 1. README 시나리오 5개 (계획서 1장 검산표, 취약도 중 기준)
@pytest.mark.parametrize("name, level", [
    ("normal", "정상"), ("heat", "경고"), ("induction", "주의"), ("fall", "위급"), ("critical", "위급"),
])
def test_scenarios(name, level):
    assert evaluate(care(name), month=8)["risk_level"] == level


def test_normal_has_no_actions():
    assert evaluate(care("normal", "상"), month=8)["actions"] == []    # [D1] 상이어도 정상은 정상


def test_vulnerability_high_raises_one_step():
    assert evaluate(care("induction", "상"), month=8)["risk_level"] == "경고"
    assert evaluate(care("heat", "상"), month=8)["risk_level"] == "위급"
    assert evaluate(care("fall", "상"), month=8)["risk_level"] == "위급"    # 최대 위급


def test_missing_vulnerability_counts_as_high():
    assert evaluate(care("induction", None), month=8)["risk_level"] == "경고"


# 2. 취약도
@pytest.mark.parametrize("profile, expected", [
    (None, "상"),
    ({}, "상"),
    ({"age": 70, "lives_alone": False, "has_condition": False, "mobility_limited": False}, "하"),
    ({"age": 80, "lives_alone": False, "has_condition": False, "mobility_limited": False}, "하"),
    ({"age": 80, "lives_alone": True, "has_condition": False, "mobility_limited": False}, "중"),
    ({"age": 80, "lives_alone": True, "has_condition": True, "mobility_limited": False}, "상"),
    ({"age": 70, "lives_alone": False}, "중"),     # 지병·거동 값 없음 → 위험한 쪽으로 셈
])
def test_vulnerability(profile, expected):
    assert vulnerability(profile) == expected


def test_run_profile_returns_level_only():
    out = run_profile({"age": 82, "condition_name": "고혈압"})
    assert out == {"vulnerability": "상"}


# 3. 경계값
@pytest.mark.parametrize("name, value, score", [
    ("hr", 90, 0), ("hr", 91, 1), ("hr", 110, 1), ("hr", 111, 2), ("hr", 131, 3), ("hr", 40, 3), ("hr", 41, 1),
    ("spo2", 96, 0), ("spo2", 95, 1), ("spo2", 93, 2), ("spo2", 91, 3),
    ("sbp", 111, 0), ("sbp", 110, 1), ("sbp", 90, 3), ("sbp", 220, 3),
    ("temp", 38.0, 0), ("temp", 38.1, 1), ("temp", 39.1, 2), ("temp", 40.0, 3), ("temp", 35.0, 3), ("temp", 35.1, 1),
    ("hr", None, None),
])
def test_vital_score_boundaries(name, value, score):
    assert vital_score(name, value) == score


@pytest.mark.parametrize("temp, state", [
    (28, "normal"), (28.1, "hot"), (31, "hot"), (31.1, "extreme_hot"),
    (20, "normal"), (19.9, "cold"), (18, "cold"), (17.9, "extreme_cold"), (None, "normal"),
])
def test_indoor_boundaries(temp, state):
    assert indoor_state(temp) == state


@pytest.mark.parametrize("status, minutes", [
    ("off", 0), (None, 0), ("on(2h)", 120), ("on(90m)", 90), ("on", None), ("on(?)", None),
])
def test_induction_minutes(status, minutes):
    assert induction_on_minutes(status) == minutes


def test_indoor_extreme_alone_is_warning():    # [D4]
    c = care("normal", env={"temp": 32})
    assert evaluate(c, month=8)["risk_level"] == "경고"


def test_indoor_abnormal_alone_is_caution():
    c = care("normal", env={"temp": 29})
    assert evaluate(c, month=8)["risk_level"] == "주의"


# 4. 조치 선택
def test_heat_actions_aircon_cool_to_comfort_top():
    r = evaluate(care("heat"), month=9)
    assert types(r) == ["control_device", "notify_guardian"]
    assert r["actions"][0]["value"] == {"device": "aircon", "mode": "cool", "target": 26}
    assert r["actions"][0]["needs_approval"] is True


def test_cold_actions_aircon_heat_to_comfort_bottom():
    r = evaluate(care("normal", env={"temp": 17}), month=1)
    assert r["actions"][0]["value"] == {"device": "aircon", "mode": "heat", "target": 20}


def test_induction_actions_turn_off():
    r = evaluate(care("induction"), month=8)
    assert types(r) == ["control_device", "notify_guardian"]
    assert r["actions"][0]["value"] == {"device": "induction", "action": "off"}


def test_induction_needs_cctv_to_know_nobody_is_there():
    c = care("induction", cctv=None)
    assert "INDUCTION_UNATTENDED" not in detect_causes(c)


def test_fall_actions_119_and_hospital():
    r = evaluate(care("fall"), month=8)
    assert types(r) == ["call_119", "speaker_check", "hospital_info", "notify_guardian"]


def test_single_vital_danger_gets_hospital_without_119():
    c = care("normal", vitals={"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 90})
    r = evaluate(c, month=8)
    assert r["risk_level"] == "경고"
    assert types(r) == ["hospital_info", "notify_guardian"]


# D2, 정보 누락
def test_fallen_posture_counts_as_fall_even_if_flag_false():   # [D2]
    cctv = {**CCTV_FALL, "fall_suspected": False}
    assert "FALL_DETECTED" in detect_causes(care("normal", cctv=cctv))


def test_lying_alone_does_not_raise():   # [D3]
    assert evaluate(care("normal", cctv=CCTV_LYING), month=8)["risk_level"] == "정상"


def test_cctv_unavailable_judges_by_vitals_only():
    c = care("critical", cctv={"available": False})
    r = evaluate(c, month=8)
    assert r["risk_level"] == "위급"
    assert "CCTV_UNAVAILABLE" in r["reason_codes"]


def test_cached_vitals_marked_stale_without_changing_level():
    c = care("normal", vitals={**SCENARIOS["normal"]["vitals"], "source": "cache"})
    r = evaluate(c, month=8)
    assert r["risk_level"] == "정상"
    assert "VITAL_STALE" in r["reason_codes"]


def test_risk_level_ignores_info_only_causes():
    assert risk_level(["VITAL_STALE", "CCTV_UNAVAILABLE"], "상") == "정상"


def test_reason_text_for_fallback():
    assert evaluate(care("fall"), month=8)["reason"] == "CCTV 쓰러짐 의심 + 심박·혈압 변화 + 산소포화도 변화"


def test_heat_reason_does_not_repeat_indoor():
    r = evaluate(care("heat"), month=8)
    assert r["reason"] == "실내 온도 극한 + 심박·혈압 변화"
    assert "hospital_info" not in types(r)
