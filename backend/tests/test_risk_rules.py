"""위험도 규칙표·취약도 계산 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 테스트를 넣음. 계획서 8.8 테스트 목록 1~4번과 결정 D1·D2.
#   - notes/_지난파일/test_risk_rules.py(폭염·한파)는 쓰지 않고 README 시나리오 기준으로 새로 씀.
#   - 시나리오 값은 README 6장 mock_data.py와 같음. mock 값이 바뀌면 여기도 같이 바꿔야 함.
# 2026-10-08 해든 (4단계): 낙상 축 도입으로 CCTV_FALL → FALL_DETECTED, fall 조치에 speaker_check 추가.
#   낙상 케이스는 tests/test_fall_cases.py에 따로 모음.
# 2026-10-08 해든 (축 정리): 근거 문장이 축별 원인(심박·혈압 / 산소포화도 / 체온)으로 바뀜. 축 테스트는 tests/test_axes.py.
# 2026-10-08 해든 (2단계): heat 근거 문장 테스트 추가. tests/test_llm_contract.py가 SCENARIOS·care()를 가져다 씀.
# 2026-10-08 해든 (워치 버튼): 스피커 확인 이름을 워치 버튼 확인(watch_check, watch_response)으로 바꿈.
# 2026-10-08 해든 (시연 시나리오 확정안): SCENARIOS를 확정안 4장 값으로 바꿈(기기 구조 형식, fall 바이탈은 심박만 위험).
#   경계값을 확정안 2장 위험 범위·실내 30℃/16℃로 바꾸고, 확정안 5장·8장 기대값 테스트(test_demo_*)를 추가.
# 2026-10-08 해든 (main 문서 개정판): docs/scenarios.md 2·5·8장 기준(NEWS2, 실내 28/20·극한 31/18)으로 기대값을 바꿈. critical 119는 해든 결정으로 승인 요청.
# 2026-10-08 해든 (확정안과 다른 부분 정리): 시연 설정에서 워치 확인을 꺼서 fall 조치가 확정안대로 3개(119·응급실·알림).
# 2026-10-12 해든: README대로 critical(VITAL_SEVERE) 119 자동 연결, 에어컨 조치 값에 action 추가에 맞춰 기대값을 바꿈.
# 2026-10-12 해든 (README 9장 최종 맞춤): CCTV 약한 의심 = 경고(CCTV_SUSPECT_IS_CRITICAL False), 119 시간 초과 자동 연결 끔(ENABLE_TIMEOUT_119 False). 예전 동작은 monkeypatch로 확인.

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

# 시연 시나리오 확정안 4장 mock_data.py 값 (두나 님 mock이 바뀌면 여기도 같이 바꿈)
OFF = {"aircon": {"state": "off"}, "induction": {"state": "off", "minutes": 0, "temperature": 0}}
SCENARIOS = {
    "normal": {"vitals": {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98},
               "env": {"temp": 24, "humidity": 50}, "devices": OFF, "cctv": CCTV_NORMAL},
    "heat": {"vitals": {"hr": 105, "sbp": 140, "temp": 37.8, "spo2": 96},
             "env": {"temp": 33, "humidity": 75}, "devices": OFF, "cctv": CCTV_NORMAL},
    "induction": {"vitals": {"hr": 80, "sbp": 130, "temp": 36.6, "spo2": 97},
                  "env": {"temp": 26, "humidity": 55},
                  "devices": {"aircon": {"state": "off"}, "induction": {"state": "on", "minutes": 120, "temperature": 300}},
                  "cctv": CCTV_EMPTY},
    "fall": {"vitals": {"hr": 118, "sbp": 120, "temp": 36.4, "spo2": 96},      # 심박 변화만 (2점) 범위
             "env": {"temp": 25, "humidity": 50}, "devices": OFF, "cctv": CCTV_FALL},
    "critical": {"vitals": {"hr": 140, "sbp": 85, "temp": 36.0, "spo2": 88},
                 "env": {"temp": 25, "humidity": 50}, "devices": OFF, "cctv": CCTV_LYING},
}
# 확정안 3장 테스트 프로필
PROFILES = {
    "profile-01": {"age": 84, "lives_alone": True, "has_condition": True, "mobility_limited": True},     # 상
    "profile-02": {"age": 78, "lives_alone": True, "has_condition": False, "mobility_limited": False},   # 중
    "profile-03": {"age": 70, "lives_alone": True, "has_condition": False, "mobility_limited": False},   # 하
}


def care(name, vulnerability="중", **override):
    return {**SCENARIOS[name], "vulnerability": vulnerability, **override}


def types(result):
    return [a["type"] for a in result["actions"]]


# 0. 시연 시나리오 확정안 5장(시나리오별 기대 결과)·8장(테스트 케이스)
def test_demo_profiles_vulnerability():
    assert [vulnerability(PROFILES[p]) for p in PROFILES] == ["상", "중", "하"]


@pytest.mark.parametrize("name, profile, cctv_ok, level", [
    ("normal", "profile-01", True, "정상"),
    ("heat", "profile-02", True, "경고"),
    ("heat", "profile-01", True, "위급"),        # 경고 → 보정
    ("induction", "profile-03", True, "주의"),
    ("induction", "profile-01", True, "경고"),   # 주의 → 보정
    ("fall", "profile-03", True, "위급"),        # CCTV
    ("fall", "profile-03", False, "주의"),       # CCTV 분석 실패 → 심박 변화만
    ("critical", "profile-01", False, "위급"),   # CCTV 분석 실패 → 바이탈 3개
    ("fall", "profile-01", True, "위급"),
    ("critical", "profile-01", True, "위급"),
])
def test_demo_expected_levels(name, profile, cctv_ok, level):
    c = care(name, vulnerability(PROFILES[profile]))
    if not cctv_ok:
        c["cctv"] = {"available": False}
    assert evaluate(c, month=8)["risk_level"] == level


@pytest.mark.parametrize("name, profile, actions, auto", [
    ("normal", "profile-01", [], None),
    ("heat", "profile-02", ["control_device", "notify_guardian"], None),
    ("induction", "profile-03", ["control_device", "notify_guardian"], None),
    ("fall", "profile-01", ["call_119", "hospital_info", "notify_guardian"], None),
    ("critical", "profile-01", ["call_119", "hospital_info", "notify_guardian"], "VITAL_SEVERE"),   # README: 승인 없이 119
])
def test_demo_expected_actions(name, profile, actions, auto):
    """docs/scenarios.md 5장 조치안. 기기 제어와 fall 119는 승인 필요, critical 119만 자동 연결 (README VITAL_SEVERE)."""
    r = evaluate(care(name, vulnerability(PROFILES[profile])), month=8)
    assert types(r) == actions
    assert r["auto_119"] == auto
    for a in r["actions"]:
        if a["type"] == "control_device" or (a["type"] == "call_119" and not auto):
            assert a["needs_approval"] is True
        if a["type"] == "call_119" and auto:
            assert a["needs_approval"] is False


def test_demo_section8_extra_cases():
    """docs/scenarios.md 8장: 과열만으로 방치, CCTV 실패여도 바이탈로 자동 119, 바이탈 캐시면 자동 연결 안 함."""
    dev = {"aircon": {"state": "off"}, "induction": {"state": "on", "minutes": 30, "temperature": 300}}
    assert evaluate(care("induction", "하", devices=dev), month=8)["risk_level"] == "주의"
    no_cctv = evaluate(care("critical", "상", cctv={"available": False}), month=8)
    assert (no_cctv["risk_level"], no_cctv["auto_119"]) == ("위급", "VITAL_SEVERE")
    cached = evaluate(care("critical", "상", vitals={**SCENARIOS["critical"]["vitals"], "source": "cache"}), month=8)
    assert (cached["risk_level"], cached["auto_119"]) == ("위급", None)


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
    # docs/scenarios.md 2-1장: NEWS2 점수 그대로 (3점 = 위험 범위)
    ("hr", 90, 0), ("hr", 91, 1), ("hr", 110, 1), ("hr", 111, 2), ("hr", 130, 2), ("hr", 131, 3),
    ("hr", 51, 0), ("hr", 50, 1), ("hr", 41, 1), ("hr", 40, 3),
    ("spo2", 96, 0), ("spo2", 95, 1), ("spo2", 94, 1), ("spo2", 93, 2), ("spo2", 92, 2), ("spo2", 91, 3),
    ("sbp", 111, 0), ("sbp", 110, 1), ("sbp", 100, 2), ("sbp", 91, 2), ("sbp", 90, 3), ("sbp", 219, 0), ("sbp", 220, 3),
    ("temp", 38.0, 0), ("temp", 38.1, 1), ("temp", 39.1, 2), ("temp", 40.0, 3),
    ("temp", 36.1, 0), ("temp", 36.0, 1), ("temp", 35.1, 1), ("temp", 35.0, 3),
    ("hr", None, None),
])
def test_vital_score_boundaries(name, value, score):
    assert vital_score(name, value) == score


@pytest.mark.parametrize("temp, state", [
    # docs/scenarios.md 2-2장: 이상 28℃ 초과 / 20℃ 미만, 극한 31℃ 초과 / 18℃ 미만
    (28, "normal"), (28.1, "hot"), (31, "hot"), (31.1, "extreme_hot"),
    (20, "normal"), (19.9, "cold"), (18, "cold"), (17.9, "extreme_cold"), (None, "normal"),
])
def test_indoor_boundaries(temp, state):
    assert indoor_state(temp) == state


@pytest.mark.parametrize("status, minutes", [
    ("off", 0), (None, 0), ("on(2h)", 120), ("on(90m)", 90), ("on", None), ("on(?)", None),
    ({"state": "off", "minutes": 0, "temperature": 0}, 0), ({"state": "on", "minutes": 120, "temperature": 300}, 120),
    ({"state": "on"}, None),
])
def test_induction_minutes(status, minutes):
    assert induction_on_minutes(status) == minutes


def test_indoor_abnormal_alone_is_caution():      # docs/scenarios.md 2-3장 environment 축
    assert evaluate(care("normal", env={"temp": 33}), month=8)["risk_level"] == "경고"   # 극한
    assert evaluate(care("normal", env={"temp": 30}), month=8)["risk_level"] == "주의"
    assert evaluate(care("normal", env={"temp": 28}), month=8)["risk_level"] == "정상"


def test_indoor_with_vital_change_is_warning():   # 확정안 판정 순서 2
    c = care("normal", env={"temp": 30}, vitals={"hr": 95, "sbp": 125, "temp": 36.5, "spo2": 98})
    assert evaluate(c, month=8)["risk_level"] == "경고"


def test_induction_overheat_without_long_time():
    devices = {"aircon": {"state": "off"}, "induction": {"state": "on", "minutes": 10, "temperature": 260}}
    assert "INDUCTION_UNATTENDED" in detect_causes(care("induction", devices=devices))
    devices["induction"]["temperature"] = 200
    assert "INDUCTION_UNATTENDED" not in detect_causes(care("induction", devices=devices))


# 4. 조치 선택
def test_heat_actions_aircon_cool_to_comfort_top():
    r = evaluate(care("heat"), month=9)
    assert types(r) == ["control_device", "notify_guardian"]
    assert r["actions"][0]["value"] == {"device": "aircon", "action": "cool", "mode": "cool", "target": 26}
    assert r["actions"][0]["needs_approval"] is True


def test_cold_actions_aircon_heat_to_comfort_bottom():
    r = evaluate(care("normal", env={"temp": 15}), month=1)
    assert r["actions"][0]["value"] == {"device": "aircon", "action": "heat", "mode": "heat", "target": 20}


def test_induction_actions_turn_off():
    r = evaluate(care("induction"), month=8)
    assert types(r) == ["control_device", "notify_guardian"]
    assert r["actions"][0]["value"] == {"device": "induction", "action": "off"}


def test_induction_needs_cctv_to_know_nobody_is_there():
    c = care("induction", cctv=None)
    assert "INDUCTION_UNATTENDED" not in detect_causes(c)


def test_fall_actions_119_and_hospital():
    r = evaluate(care("fall"), month=8)
    assert types(r) == ["call_119", "hospital_info", "notify_guardian"]


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
    assert evaluate(care("fall"), month=8)["reason"] == "CCTV 쓰러짐 의심 + 심박·혈압 변화"


def test_heat_reason_has_body_temp_and_indoor():
    r = evaluate(care("heat"), month=8)
    assert r["reason"].startswith("실내 온도 극한")       # docs/scenarios.md 5장: 실내 온도 극한 + 심박·혈압 변화
    assert "심박·혈압 변화" in r["reason"]
    assert "hospital_info" not in types(r)  # 위험 범위(3점) 바이탈이 없어 병원 정보 없음


def test_demo_settings_follow_final_plan():
    """README 9장: 워치 확인은 끔, CCTV 약한 의심은 경고, 시간 초과 119 없음. 바이탈 매우 위험이면 119 자동 연결."""
    import src.rules.risk as risk
    assert risk.ENABLE_WATCH_CHECK is False and risk.CCTV_SUSPECT_IS_CRITICAL is False and risk.ENABLE_TIMEOUT_119 is False
    assert risk.ENABLE_AUTO_119 is True and risk.ENABLE_AUTO_119_VITAL is True and risk.VITAL_DANGER_FROM_NEWS2 is True and risk.ENABLE_ENV_EXTREME is True


@pytest.mark.parametrize("cctv", [
    {**CCTV_FALL, "confidence": "low"},                                                     # 흐린 사진
    {"person_visible": True, "posture": "sitting", "fall_suspected": True, "description": "바닥에 앉아 계심"},  # 바닥에 주저앉음
])
def test_cctv_weak_suspicion_is_warning_with_capture(cctv):
    """README 9장 (해든 10/12): 흐린 사진·자세와 플래그 불일치는 낙상 의심(FALL_SUSPECTED) = 경고. 캡처는 그대로 붙임."""
    r = evaluate(care("normal", "하", cctv={**cctv, "image_path": "assets/cctv/x.png"}), month=8)
    assert r["risk_level"] == "경고" and r["fall_state"] == "suspected" and types(r) == ["notify_guardian"]
    assert r["actions"][-1]["value"]["cctv_check"] == "fall" and r["actions"][-1]["value"]["cctv_image"] == "assets/cctv/x.png"


@pytest.mark.parametrize("cctv", [
    {**CCTV_FALL, "confidence": "low"},
    {"person_visible": True, "posture": "sitting", "fall_suspected": True, "description": "바닥에 앉아 계심"},
])
def test_cctv_suspicion_is_critical_when_switched_on(cctv, monkeypatch):
    """예전 확정안 설정(CCTV_SUSPECT_IS_CRITICAL = True)을 켜면 의심도 위급 + 119 승인 요청."""
    import src.rules.risk as risk
    monkeypatch.setattr(risk, "CCTV_SUSPECT_IS_CRITICAL", True)
    r = evaluate(care("normal", "하", cctv={**cctv, "image_path": "assets/cctv/x.png"}), month=8)
    assert r["risk_level"] == "위급" and types(r) == ["call_119", "hospital_info", "notify_guardian"]
    assert r["actions"][0]["needs_approval"] is True
