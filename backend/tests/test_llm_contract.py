"""LLM 프롬프트·검증·템플릿 테스트 (키 없이 돌아감) — 해든"""

# [변경 기록]
# 2026-10-08 해든: 새 파일. 계획서 8.8 테스트 목록 5·6번.
#   - 검증 함수가 지어낸 수치·확진 표현·개수 불일치를 걸러내는지
#   - 템플릿이 모든 시나리오·상황에서 검증을 통과하는지
#   - 2026-10-08 해든 (현실 상황 점검): 거절이어도 어르신 안내, 보호자 문장 끝 next_step, 새 금지 표현 테스트(test_realistic_*).
#   - 2026-10-08 해든 (말투): 어르신 60자, 다정한 말투·위급 단호 규칙 테스트(test_tone_rules), 템플릿 문구 바뀜.
#   - 2026-10-08 해든 (승인·119 흐름): 119 조치 표시가 "[승인 필요, 60초 응답 없으면 자동 연결]"로 바뀜.
# 2026-10-08 해든 (4단계): fall 조치가 4개(스피커 확인 추가)로 바뀐 것을 반영.
# 2026-10-08 해든 (실제 호출 점검): 실제 gpt-4.1-mini 답에서 나온 문구 3종을 그대로 넣어 걸러지는지 확인.
# 2026-10-08 해든 (워치 버튼·2차 점검): 이름을 워치로 바꾸고, S19 열 안내(ELDER_CARE_TIP)·S15 글자 수 안내·거절 템플릿 판정 근거 테스트 추가.
# 2026-10-08 해든 (확정안과 다른 부분 정리): 시연 설정에서 워치 확인을 꺼서 fall 조치가 확정안대로 3개(119·응급실·알림).
# 2026-10-08 해든 (main 문서 개정판): docs/scenarios.md 기준(NEWS2, fall SpO2 96)으로 기대값을 바꿈.
# 2026-10-12 해든 (README 9장 최종 맞춤): CCTV 약한 의심 = 경고(CCTV_SUSPECT_IS_CRITICAL False), 119 60초 무응답 자동 연결은 팀 의견으로 유지(ENABLE_TIMEOUT_119 True). 반대 설정은 monkeypatch로 확인.

import json

import pytest

from src.llm.fallback import action_label, fallback_emergency, fallback_summary, pending_guardian_message
from src.llm.prompts import (
    build_emergency_ctx,
    build_summary_ctx,
    emergency_prompt,
    summary_prompt,
    validate_emergency,
    validate_summary,
)
from src.rules.risk import evaluate
from tests.test_risk_rules import SCENARIOS, care

HOSPITAL = "○○병원 응급실 (1.2km)"


def emergency_ctx(name, vulnerability="중", **override):
    c = care(name, vulnerability, **override)
    return build_emergency_ctx(c, evaluate(c, month=8), HOSPITAL)


def as_raw(d):
    return json.dumps(d, ensure_ascii=False)


ALERT_SCENARIOS = ["heat", "induction", "fall", "critical"]


# ---------- 조치 이름 ----------

@pytest.mark.parametrize("action, label", [
    ({"type": "call_119"}, "119 호출"),
    ({"type": "control_device", "value": {"device": "aircon", "mode": "cool", "target": 26}}, "에어컨 냉방 26℃로 켜기"),
    ({"type": "control_device", "value": {"device": "induction", "action": "off"}}, "인덕션 끄기"),
    ({"type": "control_device", "value": {"device": "aircon"}}, "에어컨 켜기"),
    ({"type": "notify_guardian"}, "보호자에게 상황 알림"),
])
def test_action_label(action, label):
    assert action_label(action) == label


# ---------- 프롬프트 ----------

def test_emergency_prompt_has_inputs_and_count():
    p = emergency_prompt(emergency_ctx("fall"))
    assert "위급" in p and "심박 118회/분" in p and "119 호출" in p and HOSPITAL in p
    assert "같은 개수(3개)" in p
    assert "[교정 요청]" not in p


def test_prompt_adds_fix_request_on_retry():
    p = emergency_prompt(emergency_ctx("fall"), errors=["JSON 파싱 실패"])
    assert "[교정 요청]" in p and "JSON 파싱 실패" in p


def test_stale_vitals_shown_in_prompt():
    vitals = {**SCENARIOS["fall"]["vitals"], "source": "cache", "measured_at": "10:42"}
    assert "10:42 측정, 이전 측정값" in emergency_prompt(emergency_ctx("fall", vitals=vitals))


def test_cctv_unavailable_shown_in_prompt():
    assert "CCTV: 영상 판단 불가" in emergency_prompt(emergency_ctx("critical", cctv={"available": False}))


def test_rejected_summary_prompt_asks_short_elder_message():
    s = build_summary_ctx(emergency_ctx("fall"), approved=False, executed=[])
    assert "곧 연락드릴 거라고 안심시킨다" in summary_prompt(s)


# ---------- Emergency 검증 ----------

def test_good_emergency_output_passes():
    ctx = emergency_ctx("fall")
    raw = as_raw({"reason": "쓰러짐이 의심되고 심박 118회/분입니다.",
                  "action_texts": ["119에 연락해 구조 요청", "○○병원 응급실 1.2km 안내", "보호자께 상황 알림"]})
    data, errors = validate_emergency(raw, ctx)
    assert errors == [] and data is not None


def test_emergency_code_block_is_accepted():
    ctx = emergency_ctx("induction")
    raw = "```json\n" + as_raw({"reason": "사람이 없는 주방에서 인덕션이 켜져 있습니다.",
                                "action_texts": ["인덕션 끄기", "보호자께 알림"]}) + "\n```"
    assert validate_emergency(raw, ctx)[1] == []


@pytest.mark.parametrize("output, error_word", [
    ({"reason": "심박 150회/분으로 매우 높습니다.", "action_texts": ["119", "병원", "알림"]}, "입력에 없는 수치"),
    ({"reason": "어르신이 쓰러졌습니다.", "action_texts": ["119", "병원", "알림"]}, "확진 표현"),
    ({"reason": "뇌졸중이 의심됩니다.", "action_texts": ["119", "병원", "알림"]}, "진단·약"),
    ({"reason": "쓰러짐 의심입니다.", "action_texts": ["119", "알림"]}, "조치 개수"),
    ({"reason": "쓰러짐 의심입니다.", "action_texts": ["119", "워치", "병원", "알림", "에어컨 켜기"]}, "조치 개수"),
    ({"reason": "가" * 61, "action_texts": ["119", "병원", "알림"]}, "reason은"),
    ({"reason": "쓰러짐 의심", "action_texts": ["119", "가" * 31, "알림"]}, "조치 설명"),
    ({"reason": "쓰러짐 의심"}, "action_texts 누락"),
])
def test_bad_emergency_output_caught(output, error_word):
    data, errors = validate_emergency(as_raw(output), emergency_ctx("fall"))
    assert data is None
    assert any(error_word in e for e in errors), errors


def test_not_json_caught():
    assert validate_emergency("위급 상황입니다", emergency_ctx("fall")) == (None, ["JSON 파싱 실패"])


def test_rounded_number_is_allowed():
    ctx = emergency_ctx("heat")   # 실내 33℃, 심박 105
    raw = as_raw({"reason": "실내 33도 고온에 심박 105회입니다.", "action_texts": ["에어컨 냉방 26도", "보호자께 알림"]})
    assert validate_emergency(raw, ctx)[1] == []


# ---------- Summary 검증 ----------

DONE_119 = [{"action": "call_119", "result": "success"}, {"action": "notify_guardian", "result": "success"}]
DEVICE_FAIL = [{"action": "control_device", "device": "aircon", "result": "fail"},
               {"action": "notify_guardian", "result": "success"}]


def test_summary_situation():
    e = emergency_ctx("heat")
    assert build_summary_ctx(e, True, DONE_119)["situation"] == "done"
    assert build_summary_ctx(e, True, DEVICE_FAIL)["situation"] == "device_fail"
    assert build_summary_ctx(e, False, [])["situation"] == "rejected"


@pytest.mark.parametrize("approved, executed, output, error_word", [
    (True, DONE_119, {"guardian_message": "119에 연락했습니다.", "elder_message": "CCTV로 확인했어요."}, "CCTV"),
    (True, DONE_119, {"guardian_message": "119에 연락했습니다.", "elder_message": "체온이 36.3도예요."}, "수치"),
    (True, DONE_119, {"guardian_message": "119에 연락했습니다.", "elder_message": "가" * 61}, "elder_message는 1~"),
    (True, DONE_119, {"guardian_message": "가" * 121, "elder_message": "기다려 주세요."}, "guardian_message는 1~"),
    (True, DEVICE_FAIL, {"guardian_message": "에어컨을 켰습니다.", "elder_message": "편하게 계세요."}, "실패"),
    (False, [], {"guardian_message": "거절로 기록했습니다.", "elder_message": "편하게 계세요."}, "어르신"),
    (True, DONE_119, {"guardian_message": "약을 드시게 해 주세요.", "elder_message": "편하게 계세요."}, "진단·약"),
])
def test_bad_summary_output_caught(approved, executed, output, error_word):
    s = build_summary_ctx(emergency_ctx("fall"), approved, executed)
    data, errors = validate_summary(as_raw(output), s)
    assert data is None
    assert any(error_word in e for e in errors), errors


def test_elder_may_mention_119():
    s = build_summary_ctx(emergency_ctx("fall"), True, DONE_119)
    raw = as_raw({"guardian_message": "승인하신 대로 119에 연락했습니다. 지금 바로 어르신께 전화해 상태를 확인하세요.",
                  "elder_message": "어르신, 119가 곧 와요. 그대로 기다려 주세요."})
    assert validate_summary(raw, s)[1] == []


@pytest.mark.parametrize("output, word", [
    ({"guardian_message": "119에 연락했습니다. 지금 바로 전화하세요.", "elder_message": "곧 도움이 와요. 그대로 계세요."}, "어르신"),
    ({"guardian_message": "119에 연락했습니다. 지금 바로 전화하세요.", "elder_message": "어르신, 위급해서 119를 불렀어요. 그대로 계세요."}, "겁주는 말"),
    ({"guardian_message": "119에 연락했습니다. 지금 바로 전화하세요.", "elder_message": "어르신, 곧 도움이 와요."}, "지시"),
    ({"guardian_message": "119에 연락했습니다. 혹시 시간 되시면 전화해 주시면 좋겠습니다.",
      "elder_message": "어르신, 곧 도움이 와요. 그대로 계세요."}, "흐린 말"),
    ({"guardian_message": "119에 연락했습니다. 어르신께 전화해 주세요.",
      "elder_message": "어르신, 곧 도움이 와요. 그대로 계세요."}, "지금 바로"),
])
def test_tone_rules(output, word):
    """말투 규칙 (10/8): 어르신은 다정하게 부르고 겁주지 않기, 119면 지시, 위급 보호자 문장은 단호하게."""
    s = build_summary_ctx(emergency_ctx("fall"), True, DONE_119)
    _, errors = validate_summary(as_raw(output), s)
    assert any(word in e for e in errors), errors


# ---------- 템플릿은 모두 검증 통과 (계획서 8.8-6) ----------

@pytest.mark.parametrize("name", ALERT_SCENARIOS)
@pytest.mark.parametrize("vulnerability", ["하", "중", "상"])
def test_emergency_fallback_passes(name, vulnerability):
    ctx = emergency_ctx(name, vulnerability)
    data, errors = validate_emergency(as_raw(fallback_emergency(ctx)), ctx)
    assert errors == []


def test_emergency_fallback_with_missing_info_passes():
    vitals = {**SCENARIOS["critical"]["vitals"], "source": "cache"}
    ctx = emergency_ctx("critical", vitals=vitals, cctv={"available": False})
    assert validate_emergency(as_raw(fallback_emergency(ctx)), ctx)[1] == []


@pytest.mark.parametrize("name", ALERT_SCENARIOS)
@pytest.mark.parametrize("approved, executed", [
    (True, DONE_119),
    (True, DEVICE_FAIL),
    (True, [{"action": "control_device", "device": "induction", "result": "success"},
            {"action": "notify_guardian", "result": "success"}]),
    (True, [{"action": "notify_guardian", "result": "success"}]),
    (False, []),
])
def test_summary_fallback_passes(name, approved, executed):
    s = build_summary_ctx(emergency_ctx(name), approved, executed)
    out = fallback_summary(s)
    assert validate_summary(as_raw(out), s)[1] == [], out


def test_summary_fallback_texts():
    e = emergency_ctx("fall")
    out = fallback_summary(build_summary_ctx(e, True, DONE_119))
    assert out["guardian_message"] == f"승인하신 대로 119에 연락했습니다. 가까운 응급실: {HOSPITAL}. 지금 바로 어르신께 전화해 상태를 확인하세요."
    out = fallback_summary(build_summary_ctx(e, True, DEVICE_FAIL))
    assert out["guardian_message"].startswith("에어컨 켜기에 실패했습니다. 직접 조치가 필요합니다.")
    out = fallback_summary(build_summary_ctx(e, False, []))
    assert out == {"guardian_message": "CCTV 쓰러짐 의심 + 심박·혈압 변화. 보호자 거절로 조치 없이 기록했습니다. "
                                       "위험도 위급. 지금 바로 어르신께 직접 연락해 상태를 확인하세요.",
                   "elder_message": "어르신, 보호자분께 상황을 알려 드렸어요. 곧 연락드릴 거예요."}


def test_pending_message():
    msg = pending_guardian_message("위급", "CCTV 쓰러짐 의심")
    assert msg == "[긴급] 어르신이 위급합니다. 판정 근거: CCTV 쓰러짐 의심. 지금 바로 화면에서 조치를 승인하세요."
    assert pending_guardian_message("주의", "인덕션 켜짐").startswith("[확인 요청] 어르신 상태를 살펴봐 주세요.")


# ---------- 실제 호출에서 나온 문구 (10/8 notes/llm_live_check_result.md) ----------

def test_no_approval_action_cannot_say_approve():
    ctx = emergency_ctx("fall")
    raw = as_raw({"reason": "쓰러짐이 의심됩니다.",
                  "action_texts": ["119 호출 승인", "응급실 정보 안내 승인", "보호자에게 즉시 상황 알림 동의"]})
    data, errors = validate_emergency(raw, ctx)
    assert data is None
    assert sum("승인·동의" in e for e in errors) == 2     # 119는 승인 필요라 괜찮음


def test_prompt_marks_approval_per_action():
    p = emergency_prompt(emergency_ctx("fall"))
    assert "1. 119 호출 [승인 필요, 60초 응답 없으면 자동 연결]" in p and "2. 가까운 병원 정보 안내 [승인 없음, 바로 실행]" in p


@pytest.mark.parametrize("guardian, elder", [
    ("보호자 승인하에 119 호출을 완료했습니다. 환자분은 ○○병원 응급실로 이송 중입니다.", "지금 병원으로 안전하게 이동 중입니다."),
    ("119 호출과 워치 확인을 마쳤습니다. 응급실로 이송 준비를 계속 진행하겠습니다.", "괜찮으신지 계속 확인할게요."),
])
def test_summary_cannot_claim_undone_things(guardian, elder):
    s = build_summary_ctx(emergency_ctx("critical"), True, DONE_119)
    data, errors = validate_summary(as_raw({"guardian_message": guardian, "elder_message": elder}), s)
    assert data is None and any("실행 결과에 없는 일" in e for e in errors), errors


@pytest.mark.parametrize("guardian", [
    "조치를 시도했으나 보호자 거절로 실패했습니다. 직접 조치가 필요합니다.",
    "조치를 시도했으나 실패했습니다. 직접 조치가 필요합니다.",
])
def test_rejection_is_not_failure(guardian):
    s = build_summary_ctx(emergency_ctx("induction"), False, [])
    data, errors = validate_summary(as_raw({"guardian_message": guardian, "elder_message": ""}), s)
    assert data is None and any("거절" in e for e in errors), errors


def test_good_rejection_passes():
    s = build_summary_ctx(emergency_ctx("induction"), False, [])
    raw = as_raw({"guardian_message": "보호자 거절로 인덕션을 끄지 않았습니다. 어르신께 직접 연락해 상태를 확인해 주세요.",
                  "elder_message": "어르신, 보호자분께 상황을 알려 드렸어요. 곧 연락드릴 거예요."})
    assert validate_summary(raw, s)[1] == []


def test_summary_prompt_forbids_undone_and_rejection_wording():
    p = summary_prompt(build_summary_ctx(emergency_ctx("fall"), False, []))
    assert "이송" in p and '"시도", "실패"' in p


# ---------- 현실 상황 20개 실제 호출에서 나온 문구 (10/8 notes/llm_realistic_check_result.md) ----------

def _summary_errors(name, approved, executed, guardian, elder, **ctx_kw):
    s = build_summary_ctx(emergency_ctx(name, **ctx_kw), approved, executed)
    return s, validate_summary(as_raw({"guardian_message": guardian, "elder_message": elder}), s)[1]


NEXT_119 = "지금 바로 어르신께 전화해 상태를 확인하세요."
ELDER_OK_119 = "어르신, 구급대가 오고 있어요. 움직이지 말고 그대로 계세요."


@pytest.mark.parametrize("guardian, word", [
    (f"승인하신 대로 119에 연락했습니다. 지금 바로 병원으로 이동 준비하세요.", "그대로 넣어야"),                # S01
    (f"119에 연락했습니다. 병원으로 이동 준비하세요. {NEXT_119}", "추측"),
    (f"119에 연락했고 보호자님께 상황을 알렸습니다. {NEXT_119}", "보호자 자신"),                            # S01
    (f"낙상 의심과 무응답으로 119에 연락했습니다. {NEXT_119}", "무응답"),                                    # S17 (워치 응답 없음)
])
def test_realistic_guardian_problems_caught(guardian, word):
    _, errors = _summary_errors("fall", True, DONE_119, guardian, ELDER_OK_119)
    assert any(word in e for e in errors), errors


def test_realistic_good_119_passes():
    _, errors = _summary_errors("fall", True, DONE_119, f"CCTV 낙상 의심으로 승인하신 대로 119에 연락했습니다. {NEXT_119}", ELDER_OK_119)
    assert errors == []


def test_notify_guardian_is_not_in_executed():
    s = build_summary_ctx(emergency_ctx("fall"), True, DONE_119)
    assert not any("보호자" in x for x in s["executed"])


def test_watch_executed_text_is_not_success_of_elder():
    s = build_summary_ctx(emergency_ctx("fall"), True, [{"action": "watch_check", "result": "success"}])
    assert s["executed"] == ["워치로 괜찮은지 묻기: 했음 (어르신 응답은 아직 모름)"]


@pytest.mark.parametrize("elder, word", [
    ("어르신, 에어컨을 켜 보았으나 잘 되지 않았어요. 조금만 더 시원하게 해 드릴게요.", "약속"),    # S20
    ("어르신, 보호자께 상황을 알렸어요. 편히 계세요.", "하실 일"),                              # S11
])
def test_realistic_device_fail_elder_caught(elder, word):
    guardian = "에어컨 냉방 26℃로 켜기에 실패했습니다. 직접 조치가 필요합니다. 지금 바로 어르신께 연락하세요."
    s, errors = _summary_errors("heat", True, DEVICE_FAIL, guardian, elder)
    assert s["elder_tip"][0].startswith("에어컨이 켜지지 않았어요")
    assert any(word in e for e in errors), errors


def test_device_fail_elder_with_tip_passes():
    guardian = "에어컨 냉방 26℃로 켜기에 실패했습니다. 직접 조치가 필요합니다. 지금 바로 어르신께 연락하세요."
    _, errors = _summary_errors("heat", True, DEVICE_FAIL, guardian, "어르신, 에어컨이 켜지지 않았어요. 창문을 열고 물을 자주 드세요.")
    assert errors == []


def test_next_step_by_situation():
    from src.llm.prompts import next_step
    assert next_step("done", "경고", False) == "잠시 뒤 어르신 상태를 한 번 더 확인해 주세요."
    assert next_step("info", "경고", False).startswith("지금 바로")
    assert next_step("info", "주의", False) == "어르신께 안부 전화로 상태를 확인해 주세요."
    assert next_step("rejected", "위급", False).startswith("지금 바로")


def test_fever_elder_care_tip():
    """S19: 체온 39.3℃로 알림만 갔을 때 어르신께 열 이야기와 하실 일이 들어감 (LLM·템플릿 둘 다)."""
    from src.llm.prompts import ELDER_CARE_TIP
    ctx = {"risk_level": "주의", "reason_codes": ["BODY_TEMP_CHANGE"], "reason": "체온 39.3℃",
           "vitals": {"hr": 100, "sbp": 125, "temp": 39.3, "spo2": 97}, "env_temp": 24,
           "actions": [{"type": "notify_guardian", "needs_approval": False}], "hospital": None}
    s = build_summary_ctx(ctx, True, [{"action": "notify_guardian", "result": "success"}])
    assert s["situation"] == "info" and s["elder_care"] == ELDER_CARE_TIP["fever"]
    out = fallback_summary(s)
    assert validate_summary(json.dumps(out, ensure_ascii=False), s)[1] == []
    assert "물" in out["elder_message"]
    bad = dict(out, elder_message="어르신, 보호자분께 알려 드렸어요. 편히 계세요.")
    assert any("체온" in e for e in validate_summary(json.dumps(bad, ensure_ascii=False), s)[1])
    cold = build_summary_ctx(dict(ctx, vitals=dict(ctx["vitals"], temp=35.2)), True, [])
    assert cold["elder_care"] == ELDER_CARE_TIP["cold_body"]


def test_summary_prompt_gives_length_budget():
    """S15: 조치가 많은 위급 거절에서 120자를 넘지 않게 앞부분 글자 수를 알려 줌."""
    from src.llm.prompts import GUARDIAN_MAX, summary_prompt
    ctx = {"risk_level": "위급", "reason_codes": ["FALL_DETECTED"], "reason": "CCTV에 누운 모습",
           "vitals": {"hr": 112, "sbp": 120, "temp": 38.2, "spo2": 96}, "env_temp": 33,
           "actions": [{"type": "call_119", "needs_approval": True}], "hospital": None}
    s = build_summary_ctx(ctx, False, [])
    assert f"{GUARDIAN_MAX - len(s['next_step']) - 1}자 이내" in summary_prompt(s)


def test_structured_device_status_in_prompt_and_numbers():
    """확정안 기기 형식 {"state", "minutes", "temperature"}: 프롬프트에 "켜짐 120분 300℃", 300℃는 허용 수치."""
    from tests.test_risk_rules import care
    from src.agents.emergency import run_emergency
    em = run_emergency(care("induction", "하"), month=8)
    assert "인덕션 켜짐 120분 300℃" in emergency_prompt(em["context"])
    raw = as_raw({"reason": "주방에 사람이 없고 인덕션이 300℃로 켜져 있습니다.", "action_texts": ["인덕션 끄기", "보호자께 알림"]})
    assert validate_emergency(raw, em["context"])[1] == []
