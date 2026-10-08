"""CCTV 이미지 비전 모델 호출, 분석 결과 JSON 파싱 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 CCTV 분석 함수를 넣음. 계획서 8.6, README 8장, 해든 낙상 설계(10/8).
#   - analyze_cctv_image(): 이미지 → 비전 LLM 1번 호출 → 검증·보정. 실패하면 예외만 던짐.
#   - analyze_cctv_or_unavailable(): 2회 재시도 뒤 "영상 판단 불가" (README DR-VISION-01). 상옥 님 재시도가 붙기 전 임시.
#   - 보정: posture가 fallen이면 fall_suspected를 true로 [D2], 사람이 안 보이면 posture none.
#   - 위험도는 여기서 정하지 않음. backend rules/risk.py의 낙상 축이 이 결과로 판정함.
#
# [팀 합의] 두나 님: tools/cctv.py의 analyze_cctv(image_path)에서 analyze_cctv_or_unavailable(image_path)를 부르면 됨.
#   mcp_server/requirements/runtime.txt에 openai(또는 google-genai)와 pillow, config/.env.example에 OPENAI_API_KEY 추가가 필요.

import base64
import io
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Callable

from src.vision.prompt import CCTV_SCHEMA, DESCRIPTION_MAX, POSTURES, cctv_prompt

VisionLLM = Callable[[str, str], str]    # (프롬프트, 이미지 data URL) → 응답 문자열

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"    # [팀 합의] 전체: 계획서 D9, 문장 작성과 같은 모델
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
TIMEOUT_SECONDS = 15.0                   # 이미지가 있어 문장 호출(10초)보다 조금 길게
MAX_RETRIES = 0                          # SDK 재시도는 끔 (재시도는 바깥에서 셈)
LONG_SIDE = 1024                         # 긴 변을 이 크기로 줄여 비용·시간을 줄임
RETRIES = 2                              # README: CCTV 분석은 2회 재시도

CONFIRM_WORDS = ["쓰러졌", "사망", "의식 없", "의식이 없", "숨을 쉬지", "골절", "뇌진탕", "출혈이 심"]
UNAVAILABLE_TEXT = "영상 판단 불가"


class CCTVOutputError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("CCTV 분석 결과 검증 실패: " + "; ".join(errors))
        self.errors = errors


# ---------- 이미지 ----------

def encode_image(image_path: str | Path) -> str:
    """이미지 파일 → data URL. Pillow가 있으면 긴 변을 LONG_SIDE로 줄이고 JPEG으로 바꾼다."""
    path = Path(image_path)
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as img:
            img.thumbnail((LONG_SIDE, LONG_SIDE))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            raw, mime = buf.getvalue(), "image/jpeg"
    except ImportError:
        pass        # Pillow가 없으면 원본 그대로 보냄
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


# ---------- 비전 LLM 만들기 ----------

def make_vision_llm(model: str | None = None, client=None, use: str | None = None) -> VisionLLM:
    """키가 있는 쪽을 씀 (OpenAI 우선). client는 테스트용 가짜를 넣을 때만 쓴다."""
    use = (use or os.getenv("LLM_PROVIDER") or
           ("openai" if os.getenv("OPENAI_API_KEY") else "gemini" if os.getenv("GEMINI_API_KEY") else "")).lower()
    if use == "openai":
        return _openai_vision(model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL), client)
    if use == "gemini":
        return _gemini_vision(model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL), client)
    raise RuntimeError("OPENAI_API_KEY 또는 GEMINI_API_KEY를 mcp_server/config/.env에 넣으세요.")


def _openai_vision(model: str, client) -> VisionLLM:
    if client is None:
        from openai import OpenAI
        client = OpenAI(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
    text_format = {"format": {"type": "json_schema", "name": "cctv_output", "strict": True, "schema": CCTV_SCHEMA}}

    def llm(prompt: str, data_url: str) -> str:
        response = client.responses.create(
            model=model, temperature=0.0, text=text_format,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt},
                                                {"type": "input_image", "image_url": data_url}]}],
        )
        return response.output_text or ""

    return llm


def _gemini_vision(model: str, client) -> VisionLLM:
    from google.genai import types
    if client is None:
        from google import genai
        client = genai.Client(http_options={"timeout": int(TIMEOUT_SECONDS * 1000)})

    def llm(prompt: str, data_url: str) -> str:
        header, b64 = data_url.split(",", 1)
        mime = header[5:].split(";")[0]
        image = types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime)
        response = client.models.generate_content(
            model=model, contents=[prompt, image],
            config={"temperature": 0.0, "response_mime_type": "application/json"},
        )
        return response.text or ""

    return llm


# ---------- 검증·보정 ----------

def validate_cctv(raw: str) -> tuple[dict | None, list[str]]:
    """(보정된 결과 또는 None, 오류 목록). 보정: [D2] fallen → fall_suspected true, 사람 없음 → posture none."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, ["JSON 파싱 실패"]
    if not isinstance(data, dict):
        return None, ["JSON 객체가 아님"]

    errors = []
    for key, kind in (("person_visible", bool), ("fall_suspected", bool), ("posture", str), ("description", str)):
        if not isinstance(data.get(key), kind):
            errors.append(f"{key} 누락 또는 자료형 오류({kind.__name__})")
    if errors:
        return None, errors
    if data["posture"] not in POSTURES:
        errors.append(f"posture는 {POSTURES} 중 하나여야 함 (현재 {data['posture']!r})")
    desc = data["description"].strip()
    if not desc or len(desc) > DESCRIPTION_MAX:
        errors.append(f"description은 1~{DESCRIPTION_MAX}자여야 함 (현재 {len(desc)}자)")
    if len(re.findall(r"[.!?](?=\s|$)", desc)) > 1:
        errors.append("description은 한 문장이어야 함")
    found = [w for w in CONFIRM_WORDS if w in desc]
    if found:
        errors.append(f"확정·진단 표현 사용: {found} (\"~로 보입니다\", \"의심됩니다\"로 쓸 것)")
    if errors:
        return None, errors

    out = {
        "person_visible": data["person_visible"],
        "posture": data["posture"],
        "fall_suspected": data["fall_suspected"],
        "confidence": data.get("confidence") if data.get("confidence") in ("high", "low") else "high",
        "description": desc,
    }
    if not out["person_visible"]:            # 사람이 안 보이면 자세도 낙상도 없음
        out["posture"], out["fall_suspected"] = "none", False
    elif out["posture"] == "none":           # 사람이 보인다는데 자세가 none → 모순이라 확신 낮춤
        out["confidence"] = "low"
    if out["posture"] == "fallen":           # [D2] 보수적으로 낙상 의심으로 고침
        out["fall_suspected"] = True
    return out, []


# ---------- 분석 ----------

# [팀 합의] 상옥 님: 재시도를 감쌀 함수. 성공하면 결과 dict, 실패하면 예외(SDK 예외 또는 CCTVOutputError).
def analyze_cctv_image(image_path: str, llm: VisionLLM, errors: list[str] | None = None) -> dict:
    raw = llm(cctv_prompt(errors), encode_image(image_path))
    data, problems = validate_cctv(raw)
    if problems:
        raise CCTVOutputError(problems)
    return {"image_path": str(image_path), "available": True, **data}


def unavailable(image_path: str, reason: str = "") -> dict:
    """README Join Guard: "영상 판단 불가"로 표시하고 바이탈 기준으로만 판정. 캡처 원본은 보호자에게 보여줌."""
    return {"image_path": str(image_path), "available": False, "person_visible": None, "posture": "none",
            "fall_suspected": False, "confidence": "low", "description": UNAVAILABLE_TEXT, "error": reason}


# 임시: 상옥 님 재시도(with_healing)가 붙기 전까지 쓰는 함수.
def analyze_cctv_or_unavailable(image_path: str, llm: VisionLLM | None = None, retries: int = RETRIES) -> dict:
    """첫 호출 + 재시도 retries번. 모두 실패하면 unavailable(). llm이 없으면 키를 찾아 만든다."""
    if not Path(image_path).is_file():
        return unavailable(image_path, "이미지 파일 없음")
    try:
        llm = llm or make_vision_llm()
    except Exception as e:        # 키 없음, 패키지 없음
        return unavailable(image_path, f"{type(e).__name__}: {e}")
    errors, last = None, ""
    for _ in range(retries + 1):
        try:
            return analyze_cctv_image(image_path, llm, errors)
        except CCTVOutputError as e:
            errors, last = e.errors, "; ".join(e.errors)
        except Exception as e:    # 시간 초과, 연결 오류 등
            errors, last = None, f"{type(e).__name__}: {e}"
    return unavailable(image_path, last)
