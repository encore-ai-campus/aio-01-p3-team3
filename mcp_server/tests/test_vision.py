"""CCTV 분석 결과 JSON 형식 테스트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 테스트를 넣음 (가짜 비전 LLM, 키 없이 돌아감). 계획서 8.8-7과 애매한 장면 보정.

import base64
import json

import pytest

from src.vision.analyzer import (
    UNAVAILABLE_TEXT,
    analyze_cctv_or_unavailable,
    encode_image,
    make_vision_llm,
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
    base = {"person_visible": True, "posture": "sitting", "fall_suspected": False,
            "confidence": "high", "description": "거실 소파에 앉아 있는 것으로 보입니다."}
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
    assert errors == [] and data["posture"] == "sitting"


def test_fallen_forces_fall_suspected():           # [D2]
    data, _ = validate_cctv(raw(posture="fallen", fall_suspected=False, description="바닥에 누워 있는 것으로 보입니다."))
    assert data["fall_suspected"] is True


def test_not_visible_forces_none():
    data, _ = validate_cctv(raw(person_visible=False, posture="lying", fall_suspected=True, description="사람이 보이지 않습니다."))
    assert (data["posture"], data["fall_suspected"]) == ("none", False)


def test_visible_but_none_posture_lowers_confidence():
    data, _ = validate_cctv(raw(posture="none"))
    assert data["confidence"] == "low"


def test_missing_confidence_defaults_high():
    d = json.loads(raw())
    del d["confidence"]
    data, errors = validate_cctv(json.dumps(d, ensure_ascii=False))
    assert errors == [] and data["confidence"] == "high"


def test_code_block_accepted():
    assert validate_cctv("```json\n" + raw() + "\n```")[1] == []


@pytest.mark.parametrize("output, word", [
    ("사진입니다", "JSON 파싱"),
    (raw(posture="crawling"), "posture는"),
    (raw(description="가" * 61), "description은 1~"),
    (raw(description=""), "description은 1~"),
    (raw(description="바닥에 있습니다. 움직이지 않습니다."), "한 문장"),
    (raw(posture="fallen", description="어르신이 쓰러졌습니다."), "확정·진단"),
    (raw(posture="fallen", description="골절이 의심됩니다."), "확정·진단"),
    (json.dumps({"posture": "sitting"}), "person_visible 누락"),
    (raw(fall_suspected="yes"), "fall_suspected 누락"),
])
def test_bad_output_caught(output, word):
    data, errors = validate_cctv(output)
    assert data is None and any(word in e for e in errors), errors


# ---------- 분석 흐름 ----------

def test_analyze_success(image):
    llm = FakeVision(raw(posture="fallen", fall_suspected=True, description="거실 바닥에 누워 있는 것으로 보입니다."))
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
    assert '"confidence"' in p and "바닥인지 침대·소파인지" in p and "골절" in p


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
