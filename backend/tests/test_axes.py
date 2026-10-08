"""판정 축 4개(낙상·보행 / 심뇌 / 호흡 / 환경) 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 새 파일. 해든 분류(10/8)로 축을 정리한 것 확인.
#   1. 낙상·보행: CCTV/워치 + 무응답      → fall
#   2. 심뇌 위험: 심박·혈압 + 이상 행동    → cardio
#   3. 호흡 위험: SpO2 + 호흡 곤란 정황    → respiratory
#   4. 환경 위험: 실내 고온·저온(+체온·인덕션) + 에어컨/보일러 제어 → environment
# 2026-10-08 해든 (확정안 판정 순서): 위험 범위 안쪽 작은 바이탈 변화만으로는 정상 (VITAL_CHANGE_ALONE_RAISES = False).
# 2026-10-08 해든 (main 문서 개정판): docs/scenarios.md 2-3장대로 변화(1~2점)도 그 축 주의, 위험 범위는 NEWS2 3점.

import pytest

import src.rules.risk as risk
from src.rules.risk import evaluate
from tests.test_risk_rules import SCENARIOS, care

N = SCENARIOS["normal"]["vitals"]


def v(**kw):
    return {**N, **kw}


def run(vitals=None, signs=None, **kw):
    c = care("normal", vitals=vitals or N, **kw)
    if signs:
        c["signs"] = signs
    return evaluate(c, month=8)


@pytest.mark.parametrize("name, axes", [
    ("normal", {"fall": "정상", "cardio": "정상", "respiratory": "정상", "environment": "정상"}),
    ("heat", {"fall": "정상", "cardio": "주의", "respiratory": "정상", "environment": "경고"}),    # 실내 극한 33℃ + 심박 변화
    ("induction", {"fall": "정상", "cardio": "정상", "respiratory": "정상", "environment": "주의"}),
    ("fall", {"fall": "위급", "cardio": "주의", "respiratory": "정상", "environment": "정상"}),    # 심박 118 변화(2점)
    ("critical", {"fall": "정상", "cardio": "경고", "respiratory": "경고", "environment": "주의"}),   # 체온 36.0 변화
])
def test_readme_scenarios_axes(name, axes):
    assert evaluate(care(name), month=8)["axes"] == axes


def test_multi_danger_across_axes_is_critical():
    """심박 위험(심뇌) + SpO2 위험(호흡): 축은 각각 경고지만 합치면 위급 (축을 넘는 규칙)."""
    r = run(v(hr=140, spo2=88))
    assert r["axes"]["cardio"] == "경고" and r["axes"]["respiratory"] == "경고"
    assert r["risk_level"] == "위급"
    assert "call_119" in [a["type"] for a in r["actions"]]


# 심뇌
@pytest.mark.parametrize("vitals, signs, level", [
    (v(hr=95), None, "주의"),                                  # 심박 변화만 → 주의 (docs/scenarios.md 2-3장)
    (None, {"abnormal_behavior": True}, "주의"),               # 이상 행동 정황만
    (v(hr=95), {"abnormal_behavior": True}, "경고"),           # 변화 + 정황
    (v(sbp=230), None, "경고"),                                # 혈압 위험 범위
    (v(sbp=230), {"abnormal_behavior": True}, "위급"),         # 위험 + 정황
])
def test_cardio_axis(vitals, signs, level):
    r = run(vitals, signs)
    assert r["axes"]["cardio"] == level and r["risk_level"] == level


def test_cardio_danger_with_sign_calls_119():
    kinds = [a["type"] for a in run(v(sbp=230), {"abnormal_behavior": True})["actions"]]
    assert kinds == ["call_119", "hospital_info", "notify_guardian"]


# 호흡
@pytest.mark.parametrize("vitals, signs, level", [
    (v(spo2=94), None, "주의"),                                # 변화만 → 주의
    (None, {"breathing_distress": True}, "주의"),
    (v(spo2=95), {"breathing_distress": True}, "경고"),
    (v(spo2=90), None, "경고"),
    (v(spo2=90), {"breathing_distress": True}, "위급"),
])
def test_respiratory_axis(vitals, signs, level):
    r = run(vitals, signs)
    assert r["axes"]["respiratory"] == level and r["risk_level"] == level


# 환경 (체온 포함)
@pytest.mark.parametrize("vitals, env, level", [
    (v(temp=40.2), {"temp": 24}, "경고"),       # 고체온 위험 범위 (실내 정상)
    (v(temp=35.8), {"temp": 24}, "주의"),       # 체온 변화만 → 주의
    (v(temp=34.8), {"temp": 15}, "경고"),       # 저체온 위험 범위 + 실내 저온
    (None, {"temp": 30}, "주의"),               # 실내 이상만 (28℃ 초과)
])
def test_environment_axis(vitals, env, level):
    r = run(vitals, env=env)
    assert r["axes"]["environment"] == level


def test_body_temp_danger_gets_hospital():
    kinds = [a["type"] for a in run(v(temp=40.2))["actions"]]
    assert "hospital_info" in kinds


def test_heating_device_can_be_boiler(monkeypatch):
    monkeypatch.setattr(risk, "HEATING_DEVICE", "boiler")
    r = evaluate(care("normal", env={"temp": 15}), month=1)
    assert r["actions"][0]["value"] == {"device": "boiler", "mode": "heat", "target": 20}
    hot = evaluate(care("normal", env={"temp": 33}), month=8)
    assert hot["actions"][0]["value"]["device"] == "aircon"      # 냉방은 그대로 에어컨


# 낙상·보행
def test_gait_unsteady_alone_is_caution():
    c = care("normal")
    c["fall_event"] = {"gait_unsteady": True}
    r = evaluate(c, month=8)
    assert r["axes"]["fall"] == "주의" and r["reason_codes"] == ["GAIT_UNSTEADY"]


def test_signs_missing_means_numbers_only():
    """정황 입력이 없으면 지금 시연처럼 수치만으로 판정."""
    assert run(v(spo2=90))["risk_level"] == run(v(spo2=90), {})["risk_level"] == "경고"


def test_vital_change_alone_can_be_switched_off(monkeypatch):
    """예전 확정안(작은 변화만으로는 정상)은 설정값으로 되돌릴 수 있음."""
    monkeypatch.setattr(risk, "VITAL_CHANGE_ALONE_RAISES", False)
    assert run(v(hr=95))["risk_level"] == "정상"

