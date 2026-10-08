"""Emergency·Summary Agent와 LLM 호출 함수 테스트 (가짜 LLM, 키 없이 돌아감) — 해든"""

# [변경 기록]
# 2026-10-08 해든: 새 파일. 3단계 확인용.
# 2026-10-08 해든 (현실 상황 점검): 거절이면 어르신께 ELDER_REJECTED, 보호자 문장은 next_step으로 끝남.
# 2026-10-08 해든 (말투): Summary 가짜 답을 새 말투 규칙(어르신 호칭, 119 지시, 위급 단호)에 맞게 바꿈.
#   - README 시나리오 5개가 키 없이(템플릿) 승인 대기 → 승인 → 안내문까지 끝까지 도는지
#   - LLM이 형식을 틀리면 교정 요청으로 1번 다시 부르고, 또 틀리면 템플릿으로 바꾸는지
#   - 시간 초과 같은 예외도 템플릿으로 끝나는지 (README DR-LLM-01)
# 2026-10-08 해든 (4단계): fall 조치에 speaker_check가 들어가 조치 4개로 바뀜.
# 2026-10-08 해든 (축 정리): fall 근거 문장이 축별 원인으로 바뀜.
# 2026-10-08 해든 (워치 버튼): 스피커 확인 이름을 워치 버튼 확인(watch_check, watch_response)으로 바꿈.
# 2026-10-08 해든 (확정안과 다른 부분 정리): 시연 설정에서 워치 확인을 꺼서 fall 조치가 확정안대로 3개(119·응급실·알림).
# 2026-10-08 해든 (main 문서 개정판): docs/scenarios.md 기준(NEWS2, fall SpO2 96)으로 기대값을 바꿈.

import json

import pytest

from src.llm.fallback import ELDER_REJECTED
from src.agents.emergency import run_emergency
from src.agents.summary import run_summary
from src.llm.client import LLMOutputError, generate, make_llm
from src.llm.prompts import build_emergency_ctx
from src.rules.risk import evaluate
from tests.test_risk_rules import care

HOSPITAL = "○○병원 응급실 (1.2km)"


def find_hospital(area):
    return HOSPITAL


class FakeLLM:
    """정해 둔 답을 차례로 돌려주고, 받은 프롬프트를 기록한다. 답이 Exception이면 던진다."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)


GOOD_FALL = {"reason": "쓰러짐이 의심되고 심박 118회/분입니다.",
             "action_texts": ["119에 구조 요청", "가까운 응급실 안내", "보호자께 상황 알림"]}
BAD_COUNT = {"reason": "쓰러짐 의심", "action_texts": ["119"]}


# ---------- 키 없이 끝까지 ----------

@pytest.mark.parametrize("name, level", [
    ("heat", "경고"), ("induction", "주의"), ("fall", "위급"), ("critical", "위급"),
])
def test_scenario_runs_end_to_end_without_key(name, level):
    em = run_emergency(care(name), llm=None, find_hospital=find_hospital, month=8)
    assert em["risk_level"] == level
    assert em["fallback_used"] is True
    assert all(a["text"] for a in em["actions"])
    executed = [{"action": a["type"], "device": (a.get("value") or {}).get("device"), "result": "success"}
                for a in em["actions"] if a["type"] != "hospital_info"]
    done = run_summary(em, approved=True, executed=executed)
    assert done["guardian_message"] and done["elder_message"]
    rejected = run_summary(em, approved=False, executed=[])
    assert rejected["elder_message"] == ELDER_REJECTED     # 거절이어도 어르신께 짧게 안내 (ELDER_MESSAGE_ON_REJECT)


def test_normal_stops_without_llm_call():
    llm = FakeLLM()
    em = run_emergency(care("normal"), llm=llm, month=8)
    assert em["risk_level"] == "정상" and em["actions"] == []
    assert llm.prompts == []


def test_fall_result_shape():
    em = run_emergency(care("fall"), llm=None, find_hospital=find_hospital, month=8)
    assert [a["type"] for a in em["actions"]] == ["call_119", "hospital_info", "notify_guardian"]
    assert em["actions"][1]["value"] == HOSPITAL
    assert em["actions"][0]["needs_approval"] is True
    assert em["reason"] == "CCTV 쓰러짐 의심 + 심박·혈압 변화"


def test_hospital_failure_drops_hospital_action():
    def broken(area):
        raise TimeoutError("hospital")
    em = run_emergency(care("fall"), llm=None, find_hospital=broken, month=8)
    assert [a["type"] for a in em["actions"]] == ["call_119", "notify_guardian"]
    assert em["hospital"] is None


def test_hospital_dict_format():
    em = run_emergency(care("fall"), find_hospital=lambda a: [{"name": "△△병원", "distance_km": 0.8}], month=8)
    assert em["hospital"] == "△△병원 (0.8km)"


# ---------- LLM 재요청과 템플릿 대체 ----------

def test_good_llm_answer_used():
    llm = FakeLLM(GOOD_FALL)
    em = run_emergency(care("fall"), llm=llm, find_hospital=find_hospital, month=8)
    assert em["fallback_used"] is False
    assert em["reason"] == GOOD_FALL["reason"]
    assert [a["text"] for a in em["actions"]] == GOOD_FALL["action_texts"]
    assert len(llm.prompts) == 1


def test_bad_then_good_retries_with_fix_request():
    llm = FakeLLM(BAD_COUNT, GOOD_FALL)
    em = run_emergency(care("fall"), llm=llm, find_hospital=find_hospital, month=8)
    assert em["fallback_used"] is False and em["llm_log"]["attempts"] == 2
    assert "[교정 요청]" in llm.prompts[1] and "3개여야 함" in llm.prompts[1]


def test_bad_twice_falls_back_to_template():
    llm = FakeLLM(BAD_COUNT, "JSON 아님")
    em = run_emergency(care("fall"), llm=llm, find_hospital=find_hospital, month=8)
    assert em["fallback_used"] is True and em["llm_log"]["attempts"] == 2
    assert [a["text"] for a in em["actions"]] == ["119 호출", "가까운 병원 정보 안내", "보호자에게 상황 알림"]


def test_timeout_falls_back_to_template():
    llm = FakeLLM(TimeoutError("10s"), TimeoutError("10s"))
    em = run_emergency(care("fall"), llm=llm, find_hospital=find_hospital, month=8)
    assert em["fallback_used"] is True
    assert "TimeoutError" in em["llm_log"]["errors"][0]


def test_llm_cannot_change_level_or_actions():
    llm = FakeLLM({"reason": "괜찮아 보입니다.", "action_texts": ["필요 없음"] * 4})
    em = run_emergency(care("fall"), llm=llm, find_hospital=find_hospital, month=8)
    assert em["risk_level"] == "위급"
    assert [a["type"] for a in em["actions"]] == ["call_119", "hospital_info", "notify_guardian"]


def test_summary_device_fail_template_says_direct_action():
    em = run_emergency(care("heat"), month=8)
    out = run_summary(em, True, [{"action": "control_device", "device": "aircon", "result": "fail"},
                                 {"action": "notify_guardian", "result": "success"}])
    assert "직접 조치가 필요합니다" in out["guardian_message"]


def test_summary_uses_llm_answer():
    em = run_emergency(care("fall"), find_hospital=find_hospital, month=8)
    elder = "어르신, 곧 도움이 와요. 움직이지 말고 그대로 계세요."
    llm = FakeLLM({"guardian_message": "승인하신 대로 119에 연락했습니다. 지금 바로 어르신께 전화해 상태를 확인하세요.", "elder_message": elder})
    out = run_summary(em, True, [{"action": "call_119", "result": "success"}], llm=llm)
    assert out["fallback_used"] is False and out["elder_message"] == elder


# ---------- generate()는 예외만 던짐 (AutoHealing이 감쌀 함수) ----------

def test_generate_raises_with_errors():
    c = care("fall")
    ctx = build_emergency_ctx(c, evaluate(c, 8), HOSPITAL)
    with pytest.raises(LLMOutputError) as e:
        generate("emergency", ctx, FakeLLM(BAD_COUNT))
    assert any("3개여야 함" in x for x in e.value.errors)


# ---------- make_llm (가짜 SDK 클라이언트) ----------

class FakeOpenAI:
    def __init__(self):
        self.kwargs = None
        self.responses = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("R", (), {"output_text": '{"ok": true}'})()


def test_make_openai_llm_uses_strict_schema():
    client = FakeOpenAI()
    llm = make_llm("emergency", model="test-model", client=client, use="openai")
    assert llm("hi") == '{"ok": true}'
    assert client.kwargs["model"] == "test-model"
    assert client.kwargs["text"]["format"]["strict"] is True
    assert client.kwargs["text"]["format"]["schema"]["required"] == ["reason", "action_texts"]


def test_make_llm_without_key_raises(monkeypatch):
    for k in ("LLM_PROVIDER", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError):
        make_llm("summary")
