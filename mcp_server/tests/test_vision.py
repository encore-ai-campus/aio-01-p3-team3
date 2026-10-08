"""CCTV 분석 결과 JSON 형식 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 테스트를 넣음 (가짜 비전 LLM, 키 없이 돌아감). 계획서 8.8-7과 애매한 장면 보정.
# 2026-10-08 해든 (CCTV 판단 방식 변경): LLM 답이 "보이는 사실 4개"로 바뀌어 raw()와 보정 테스트를 다시 씀.
#   사실 → 자세·낙상 의심 표(FACT_RULES)는 test_fact_rules에서 확정안 이미지 4장 장면으로 확인.

import base64
import json

import pytest

from src.vision.analyzer import (
    UNAVAILABLE_TEXT,
    analyze_cctv_or_unavailable,
    encode_image,
    make_vision_llm,
    facts_to_result,
    validate_cctv,
)
from src.vision.prompt import cctv_prompt

# 1x1 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def image(tmp_path):
    p = tmp_path / "fall.png"
    p.write_bytes(PNG)
    return str(p)


def raw(**kw):
    base = {"person_visible": True, "body_support": "furniture", "body_shape": "seated",
            "image_clear": True, "description": "거실 소파에 앉아 있는 것으로 보입니다."}
    return json.dumps({**base, **kw}, ensure_ascii=False)


class FakeVision:
    def __init__(self, *answers):
        self.answers, self.prompts, self.images = list(answers), [], []

    def __call__(self, prompt, data_url):
        self.prompts.append(prompt)
        self.images.append(data_url)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


# ---------- 검증·보정 ----------

def test_good_output_passes():
    data, errors = validate_cctv(raw())
    assert errors == [] and data["posture"] == "sitting" and data["fall_suspected"] is False
    assert data["facts"]["body_support"] == "furniture"


@pytest.mark.parametrize("shape, support, clear, posture, fall, confidence", [
    ("horizontal", "floor", True, "fallen", True, "high"),        # fall.jpg: 거실 바닥에 쓰러짐
    ("horizontal", "furniture", True, "lying", False, "high"),    # lying.jpg: 소파에 누움
    ("seated", "furniture", True, "sitting", False, "high"),      # normal.jpg: 소파에 앉음
    ("seated", "floor", True, "sitting", True, "high"),           # 바닥에 주저앉음
    ("upright", "floor", True, "standing", False, "high"),
    ("horizontal", "unclear", False, "fallen", True, "low"),      # 어두운 화장실 앞
    ("unclear", "unclear", False, "fallen", True, "low"),
    ("unclear", "furniture", True, "sitting", False, "low"),
])
def test_fact_rules(shape, support, clear, posture, fall, confidence):
    out = facts_to_result({"person_visible": True, "body_support": support, "body_shape": shape, "image_clear": clear})
    assert (out["posture"], out["fall_suspected"], out["confidence"]) == (posture, fall, confidence)


def test_not_visible_is_none():       # kitchen_empty.jpg
    data, _ = validate_cctv(raw(person_visible=False, body_support="none", body_shape="none", description="주방에 사람이 보이지 않습니다."))
    assert (data["person_visible"], data["posture"], data["fall_suspected"]) == (False, "none", False)


def test_not_visible_wins_over_other_facts():
    data, _ = validate_cctv(raw(person_visible=False, body_shape="horizontal", body_support="floor", description="사람이 보이지 않습니다."))
    assert (data["posture"], data["fall_suspected"]) == ("none", False)


def test_code_block_accepted():
    assert validate_cctv("```json\n" + raw() + "\n```")[1] == []


@pytest.mark.parametrize("output, word", [
    ("사진입니다", "JSON 파싱"),
    (raw(body_shape="crawling"), "body_shape는"),
    (raw(body_support="table"), "body_support는"),
    (raw(description="가" * 61), "description은 1~"),
    (raw(description=""), "description은 1~"),
    (raw(description="바닥에 있습니다. 움직이지 않습니다."), "한 문장"),
    (raw(body_shape="horizontal", description="어르신이 쓰러졌습니다."), "확정·진단"),
    (raw(body_shape="horizontal", description="골절이 의심됩니다."), "확정·진단"),
    (json.dumps({"body_shape": "seated"}), "person_visible 누락"),
    (raw(image_clear="yes"), "image_clear 누락"),
])
def test_bad_output_caught(output, word):
    data, errors = validate_cctv(output)
    assert data is None and any(word in e for e in errors), errors


# ---------- 분석 흐름 ----------

def test_analyze_success(image):
    llm = FakeVision(raw(body_shape="horizontal", body_support="floor", description="거실 바닥에 누워 있는 것으로 보입니다."))
    out = analyze_cctv_or_unavailable(image, llm)
    assert out["available"] is True and out["posture"] == "fallen" and out["image_path"] == image
    assert llm.images[0].startswith("data:image/")


def test_retry_with_fix_request_then_success(image):
    llm = FakeVision("엉뚱한 답", raw())
    out = analyze_cctv_or_unavailable(image, llm)
    assert out["available"] is True
    assert "[교정 요청]" in llm.prompts[1]


def test_three_failures_become_unavailable(image):     # 첫 호출 + 2회 재시도
    llm = FakeVision("x", TimeoutError("15s"), "y")
    out = analyze_cctv_or_unavailable(image, llm)
    assert out["available"] is False and out["description"] == UNAVAILABLE_TEXT
    assert len(llm.prompts) == 3


def test_missing_image_is_unavailable(tmp_path):
    out = analyze_cctv_or_unavailable(str(tmp_path / "none.jpg"), FakeVision())
    assert out["available"] is False and "이미지 파일 없음" in out["error"]


def test_no_key_is_unavailable(image, monkeypatch):
    for k in ("LLM_PROVIDER", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert analyze_cctv_or_unavailable(image)["available"] is False


def test_prompt_has_ambiguous_rules():
    p = cctv_prompt()
    assert '"body_support"' in p and "unclear" in p and "골절" in p
    assert "낙상인지, 위험한지는 판단하지 않는다" in p


def test_encode_image(image):
    assert encode_image(image).startswith("data:image/")


class FakeOpenAI:
    def __init__(self):
        self.kwargs = None
        self.responses = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("R", (), {"output_text": raw()})()


def test_openai_vision_sends_image_and_strict_schema(image):
    client = FakeOpenAI()
    out = analyze_cctv_or_unavailable(image, make_vision_llm(model="m", client=client, use="openai"))
    assert out["available"] is True
    content = client.kwargs["input"][0]["content"]
    assert content[1]["type"] == "input_image" and content[1]["image_url"].startswith("data:image/")
    assert client.kwargs["text"]["format"]["strict"] is True
