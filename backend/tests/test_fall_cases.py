"""낙상 축 케이스 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 새 파일. 4단계 낙상 축(rules/risk.py detect_fall)의 케이스 표를 그대로 테스트로 옮김.
#   케이스 표 원본: notes/낙상-판정-케이스표.md (번호 F1~F25가 같음).
#   바이탈은 따로 적지 않으면 정상(normal 시나리오 값), 취약도 "중", 8월 기준.
# 2026-10-08 해든 (말투): 스피커 문구는 risk.SPEAKER_MESSAGE와 비교.
# 2026-10-08 해든 (축 정리): 축 이름을 fall / cardio / respiratory / environment로 바꿈.
# 2026-10-08 해든 (워치 버튼): 스피커 확인 이름을 워치 버튼 확인(watch_check, watch_response)으로 바꿈.
# 2026-10-08 해든 (확정안과 다른 부분 정리): 시연 설정에서 꺼 둔 확장 설계를 extended_design으로 켜고 확인.

import pytest

import src.rules.risk as risk
from src.rules.risk import evaluate
from tests.test_risk_rules import SCENARIOS


@pytest.fixture(autouse=True)
def extended_design(monkeypatch):
    """이 파일은 해든 확장 설계(워치 확인, 119 바로 연결, CCTV 확신 낮으면 낙상 의심=경고)를 확인한다.
    시연(확정안)에서는 설정값으로 꺼 두었고, 시연 흐름은 tests/test_risk_rules.py의 test_demo_*가 확인한다."""
    monkeypatch.setattr(risk, "ENABLE_WATCH_CHECK", True)
    monkeypatch.setattr(risk, "ENABLE_AUTO_119", True)
    monkeypatch.setattr(risk, "CCTV_SUSPECT_IS_CRITICAL", False)

NORMAL_VITALS = SCENARIOS["normal"]["vitals"]
CRITICAL_VITALS = SCENARIOS["critical"]["vitals"]
ONE_DANGER_VITALS = {**NORMAL_VITALS, "spo2": 90}


def cam(posture, fall=False, visible=True, confidence="high"):
    return {"person_visible": visible, "posture": posture, "fall_suspected": fall,
            "confidence": confidence, "description": "테스트 장면"}


def case(cctv, event=None, vitals=NORMAL_VITALS, vulnerability="중"):
    c = {"vitals": vitals, "env": {"temp": 24}, "devices": {"aircon": "off", "induction": "off"},
         "cctv": cctv, "vulnerability": vulnerability}
    if event:
        c["fall_event"] = event
    return c


UNAVAILABLE = {"available": False}

# (번호, 설명, care_status, 낙상 상태, 최종 위험도, 119 포함, 워치 확인 포함)
CASES = [
    ("F1", "신호 없음, 앉아 있음", case(cam("sitting")), "none", "정상", False, False),
    ("F2", "CCTV 바닥 쓰러짐 + 바이탈 정상", case(cam("fallen", True)), "confirmed", "위급", True, True),
    ("F3", "쓰러짐 + 워치 무응답", case(cam("fallen", True), {"watch_response": "none"}), "critical", "위급", True, False),
    ("F4", "쓰러짐 + 괜찮다고 답함 (바닥에 그대로)", case(cam("fallen", True), {"watch_response": "ok"}), "confirmed", "위급", True, False),
    ("F5", "쓰러짐 + 워치 '도와주세요' 버튼", case(cam("fallen", True), {"watch_response": "help"}), "confirmed", "위급", True, False),
    ("F6", "바닥 자세지만 사진이 흐림 (확신 낮음)", case(cam("fallen", True, confidence="low")), "suspected", "경고", False, True),
    ("F7", "CCTV는 낙상 의심인데 앉아 있음 (바닥에 앉았을 수 있음)", case(cam("sitting", True)), "suspected", "경고", False, True),
    ("F8", "워치 감지 + CCTV 앉아 있음", case(cam("sitting"), {"watch_fall": True}), "false_alarm", "정상", False, False),
    ("F9", "워치 감지 + 서 있음 + 워치 무응답", case(cam("standing"), {"watch_fall": True, "watch_response": "none"}), "critical", "위급", True, False),
    ("F10", "워치 감지 + 화면에 사람 없음", case(cam("none", visible=False), {"watch_fall": True}), "suspected", "경고", False, True),
    ("F11", "워치 감지 + CCTV 판단 불가", case(UNAVAILABLE, {"watch_fall": True}), "suspected", "경고", False, True),
    ("F12", "워치 감지 + 사람 없음 + 괜찮다고 답함", case(cam("none", visible=False), {"watch_fall": True, "watch_response": "ok"}), "false_alarm", "정상", False, False),
    ("F13", "누워 있음만 (침대·소파) [D3]", case(cam("lying")), "none", "정상", False, False),
    ("F14", "누워 있음 + 워치 무응답", case(cam("lying"), {"watch_response": "none"}), "critical", "위급", True, False),
    ("F15", "누워 있음 + 90초 움직임 없음", case(cam("lying"), {"immobile_seconds": 90}), "confirmed", "위급", True, True),
    ("F16", "누워 있음 + 30초 움직임 없음", case(cam("lying"), {"immobile_seconds": 30}), "none", "정상", False, False),
    ("F17", "워치 감지 + 머리 충격 의심", case(cam("none", visible=False), {"watch_fall": True, "head_impact_suspected": True}), "critical", "위급", True, True),
    ("F18", "쓰러짐 + 바이탈 여러 항목 위험", case(cam("fallen", True), vitals=CRITICAL_VITALS), "critical", "위급", True, True),
    ("F19", "워치 감지(사람 안 보임) + 산소포화도 90%", case(cam("none", visible=False), {"watch_fall": True}, vitals=ONE_DANGER_VITALS), "critical", "위급", True, True),
    ("F20", "흐린 사진 낙상 의심 + 취약도 상", case(cam("fallen", True, confidence="low"), vulnerability="상"), "suspected", "위급", True, True),
    ("F21", "사람 안 보임, 워치 없음", case(cam("none", visible=False)), "none", "정상", False, False),
    ("F22", "CCTV 판단 불가, 워치 없음, 바이탈 정상", case(UNAVAILABLE), "none", "정상", False, False),
    ("F23", "자세 fallen인데 플래그 false [D2]", case(cam("fallen", False)), "confirmed", "위급", True, True),
    ("F24", "워치 오탐 + 취약도 상 [D1]", case(cam("standing"), {"watch_fall": True}, vulnerability="상"), "false_alarm", "정상", False, False),
    ("F25", "쓰러짐 + 오래 누워 있음 + 무응답", case(cam("fallen", True), {"immobile_seconds": 75, "watch_response": "none"}), "critical", "위급", True, False),
]


@pytest.mark.parametrize("no, desc, care_status, state, level, has_119, has_watch", CASES, ids=[c[0] for c in CASES])
def test_fall_case(no, desc, care_status, state, level, has_119, has_watch):
    r = evaluate(care_status, month=8)
    kinds = [a["type"] for a in r["actions"]]
    assert r["fall_state"] == state, (no, desc, r["reason_codes"])
    assert r["risk_level"] == level, (no, desc, r["reason_codes"])
    assert ("call_119" in kinds) == has_119, (no, desc, kinds)
    assert ("watch_check" in kinds) == has_watch, (no, desc, kinds)


def test_normal_vitals_do_not_make_fall_safe():
    """핵심: 바이탈 정상이어도 낙상 축만으로 위급."""
    r = evaluate(case(cam("fallen", True), {"watch_response": "none", "immobile_seconds": 75}), month=8)
    assert r["axes"] == {"fall": "위급", "cardio": "정상", "respiratory": "정상", "environment": "정상"}
    assert r["risk_level"] == "위급"
    assert r["reason"] == "CCTV 쓰러짐 의심 + 워치 확인 무응답 + 오래 움직임 없음"


def test_final_is_highest_axis():
    r = evaluate(case(cam("sitting"), vitals=ONE_DANGER_VITALS), month=8)
    assert r["axes"]["respiratory"] == "경고" and r["axes"]["fall"] == "정상"
    assert r["risk_level"] == "경고"


def test_false_alarm_is_recorded_in_reason():
    r = evaluate(case(cam("sitting"), {"watch_fall": True}), month=8)
    assert r["reason_codes"] == ["FALL_FALSE_ALARM"]
    assert r["actions"] == []


def test_watch_check_action_shape():
    r = evaluate(case(cam("fallen", True, confidence="low")), month=8)
    watch = next(a for a in r["actions"] if a["type"] == "watch_check")
    assert watch["needs_approval"] is False
    assert watch["value"] == {"message": risk.WATCH_MESSAGE, "wait_seconds": 30}


def test_watch_check_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(risk, "ENABLE_WATCH_CHECK", False)
    kinds = [a["type"] for a in evaluate(case(cam("fallen", True)), month=8)["actions"]]
    assert "watch_check" not in kinds


def test_watch_result_second_round():
    """워치 확인 뒤 다시 판정: 무응답이면 위급으로 오르고, 괜찮다고 하면 오탐으로 내려감."""
    first = evaluate(case(cam("fallen", True, confidence="low")), month=8)
    no_answer = evaluate(case(cam("fallen", True, confidence="low"), {"watch_response": "none"}), month=8)
    answered = evaluate(case(cam("sitting", True), {"watch_response": "ok"}), month=8)
    assert (first["risk_level"], no_answer["risk_level"], answered["risk_level"]) == ("경고", "위급", "정상")
