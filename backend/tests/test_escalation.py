"""승인 알림·119 자동 연결 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 새 파일. rules/risk.py의 119 자동 연결(auto_119_reason)과 시간 초과 처리,
#   fallback.py 알림 문구, Summary auto_119·timeout_119 상황을 확인. 흐름: notes/승인-119-흐름.md
# 2026-10-08 해든 (워치 버튼): 스피커 확인 이름을 워치 버튼 확인(watch_check, watch_response)으로 바꿈.
# 2026-10-08 해든 (시연 시나리오 확정안): 바이탈만으로 바로 연결(VITAL_SEVERE)은 기본 꺼짐 → critical은 119 승인 요청.
#   켰을 때 동작은 monkeypatch로 따로 확인.
# 2026-10-08 해든 (확정안과 다른 부분 정리): 119 바로 연결·워치 확인은 시연에서 꺼 둠. 이 파일은 extended_design으로 켜고 확인.
# 2026-10-08 해든 (main 문서 개정판): docs/scenarios.md 기준(NEWS2, fall SpO2 96)으로 기대값을 바꿈. critical 119는 해든 결정으로 승인 요청 유지.
# 2026-10-12 해든: README대로 critical(VITAL_SEVERE) 119 자동 연결, 에어컨 조치 값에 action 추가에 맞춰 기대값을 바꿈.

import json

import pytest

import src.rules.risk as risk
from src.agents.emergency import run_emergency
from src.agents.summary import run_summary
from src.llm.fallback import emergency_alert_message, pending_guardian_message, reminder_guardian_message
from src.llm.prompts import build_summary_ctx, validate_summary
from src.rules.risk import after_guardian_timeout, evaluate
from tests.test_fall_cases import CRITICAL_VITALS, NORMAL_VITALS, cam, case, extended_design  # noqa: F401 (확장 설계 켜기)
from tests.test_risk_rules import SCENARIOS


def call_119(r):
    return next((a for a in r["actions"] if a["type"] == "call_119"), None)


def notify(r):
    return next(a for a in r["actions"] if a["type"] == "notify_guardian")


def full(name, **extra):
    return {**SCENARIOS[name], "vulnerability": "중", **extra}


# ---------- 언제 119가 바로 가는가 ----------

@pytest.mark.parametrize("desc, care_status, auto", [
    ("쓰러짐 + 무응답", case(cam("fallen", True), {"watch_response": "none"}), "ELDER_NO_RESPONSE"),
    ("누워 있음 + 무응답", case(cam("lying"), {"watch_response": "none"}), "ELDER_NO_RESPONSE"),
    ("critical (바이탈 위험 3개) → 119 자동 연결 (README)", full("critical"), "VITAL_SEVERE"),
    ("쓰러짐만 (응답 모름)", case(cam("fallen", True)), None),
    ("쓰러짐 + 워치 '도와주세요' 버튼", case(cam("fallen", True), {"watch_response": "help"}), None),
    ("README fall (바이탈 1~2점 변화)", full("fall"), None),
])
def test_auto_119_cases(desc, care_status, auto):
    r = evaluate(care_status, month=8)
    assert r["auto_119"] == auto, desc
    a = call_119(r)
    assert a is not None and a["needs_approval"] is (auto is None), desc
    assert notify(r)["value"]["kind"] == ("emergency_alert" if auto else "approval_request")


def test_stale_vitals_do_not_auto_call():
    vitals = {**CRITICAL_VITALS, "source": "cache", "measured_at": "10:30"}
    r = evaluate(case(cam("sitting"), vitals=vitals), month=8)
    assert r["risk_level"] == "위급" and r["auto_119"] is None
    assert call_119(r)["needs_approval"] is True


def test_no_response_but_not_critical_level_does_not_call():
    # 낙상 신호 없이 워치만 무응답 → 낙상 축이 안 올라가 위급이 아님 → 119 없음
    r = evaluate(case(cam("sitting"), {"watch_response": "none"}), month=8)
    assert r["risk_level"] == "정상" and call_119(r) is None


def test_vital_severe_auto_when_switched_on(monkeypatch):
    monkeypatch.setattr(risk, "ENABLE_AUTO_119_VITAL", True)
    r = evaluate(full("critical"), month=8)
    assert r["auto_119"] == "VITAL_SEVERE" and call_119(r)["needs_approval"] is False


def test_auto_119_switch_off(monkeypatch):
    monkeypatch.setattr(risk, "ENABLE_AUTO_119", False)
    r = evaluate(full("critical"), month=8)
    assert r["auto_119"] is None and call_119(r)["needs_approval"] is True


# ---------- 승인 대기 시간 초과 ----------

def test_timeout_executes_119_and_reminds_devices():
    care = case(cam("fallen", True), vitals=NORMAL_VITALS)
    care["env"] = {"temp": 33}
    r = evaluate(care, month=8)
    t = after_guardian_timeout(r["actions"])
    assert [a["type"] for a in t["execute"]] == ["call_119"]
    assert [a["value"]["device"] for a in t["remind"]] == ["aircon"]


def test_device_only_never_auto_executes():
    r = evaluate(full("induction"), month=8)
    assert after_guardian_timeout(r["actions"])["execute"] == []
    assert notify(r)["value"] == {"kind": "approval_request", "remind_after_seconds": risk.GUARDIAN_REMIND_SEC}


def test_info_only_notify_has_no_reminder():
    r = evaluate(case(cam("fallen", True, confidence="low")), month=8)    # 의심(경고): 승인 조치 없음
    assert notify(r)["value"] == {"kind": "info", "remind_after_seconds": None}


# ---------- 알림 문구 ----------

def test_alert_messages():
    r = evaluate(full("fall"), month=8)
    assert "60초 안에 응답이 없으면 119에 자동으로 연락합니다" in pending_guardian_message("위급", r["reason"], r["actions"])
    assert "60초" not in pending_guardian_message("주의", "인덕션", evaluate(full("induction"), month=8)["actions"])
    assert reminder_guardian_message("위급", 30).endswith("30초 뒤 119에 자동으로 연락합니다.")
    msg = emergency_alert_message("심박 위험 범위", "ELDER_NO_RESPONSE", "○○병원 응급실 (1.2km)")
    assert msg.startswith("[긴급] 어르신이 워치 확인에 응답하지 않아 119에 바로 연락했습니다")


# ---------- Summary ----------

EXECUTED_119 = [{"action": "call_119", "result": "success"}, {"action": "notify_guardian", "result": "success"}]


def test_auto_119_summary_template(monkeypatch):
    monkeypatch.setattr(risk, "ENABLE_AUTO_119_VITAL", True)
    em = run_emergency(full("critical"), find_hospital=lambda area: "○○병원 응급실 (1.2km)", month=8)
    assert em["actions"][0]["label"] == "119 바로 연결" and em["actions"][0]["needs_approval"] is False
    sm = run_summary(em, approved=False, executed=EXECUTED_119, decided_by="auto")
    assert sm["guardian_message"].startswith("바이탈 여러 항목이 매우 위험해 119에 바로 연락했습니다")
    assert sm["elder_message"]


def test_timeout_summary_template():
    em = run_emergency(full("fall"), find_hospital=lambda area: "○○병원 응급실 (1.2km)", month=8)
    sm = run_summary(em, approved=False, executed=EXECUTED_119, decided_by="timeout")
    assert sm["guardian_message"].startswith("보호자 응답이 없어 119에 바로 연락했습니다")


def test_timeout_without_119_success_is_device_fail():
    em = run_emergency(full("fall"), month=8)
    ctx = build_summary_ctx(em["context"], False, [{"action": "call_119", "result": "fail"}], "timeout")
    assert ctx["situation"] == "device_fail"


@pytest.mark.parametrize("guardian, word", [
    ("승인하신 대로 119에 연락했습니다.", "승인한 것처럼"),
    ("어르신 응답이 없어 구급 요청을 했습니다.", '"119"와 "연락"'),
])
def test_auto_summary_validation(guardian, word):
    em = run_emergency(full("critical"), month=8)
    ctx = build_summary_ctx(em["context"], False, EXECUTED_119, "auto")
    raw = json.dumps({"guardian_message": guardian, "elder_message": "곧 도움이 도착해요."}, ensure_ascii=False)
    _, errors = validate_summary(raw, ctx)
    assert any(word in e for e in errors), errors


@pytest.mark.parametrize("name, decided_by", [("critical", "auto"), ("fall", "timeout")])
def test_auto_templates_pass_validation(name, decided_by):
    from src.llm.fallback import fallback_summary
    em = run_emergency(full(name), find_hospital=lambda area: "○○병원 응급실 (1.2km)", month=8)
    ctx = build_summary_ctx(em["context"], False, EXECUTED_119, decided_by)
    _, errors = validate_summary(json.dumps(fallback_summary(ctx), ensure_ascii=False), ctx)
    assert errors == []


def test_info_situation_has_no_approval_word():
    em = run_emergency(case(cam("fallen", True, confidence="low")), month=8)     # 의심: 워치 확인·알림만
    ctx = build_summary_ctx(em["context"], True, [{"action": "watch_check", "result": "success"},
                                                  {"action": "notify_guardian", "result": "success"}])
    assert ctx["situation"] == "info"
    sm = run_summary(em, approved=True, executed=[{"action": "notify_guardian", "result": "success"}])
    assert "승인" not in sm["guardian_message"]


def test_cold_label_keeps_heat_mode():
    care = {**SCENARIOS["normal"], "vulnerability": "중", "env": {"temp": 16}}
    em = run_emergency(care, month=1)
    ctx = build_summary_ctx(em["context"], True, [{"action": "control_device", "device": "aircon", "result": "success"}])
    assert ctx["succeeded_labels"] == ["에어컨 난방 20℃로 켜기"]
