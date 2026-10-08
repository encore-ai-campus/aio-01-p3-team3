"""LLM API 호출 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 LLM 호출 함수를 넣음.
#   - 출처: notes/openai_llm.py의 make_openai_llm(구조화 출력 strict, 시간 제한 10초, SDK 재시도 끔)을 그대로 쓰고,
#     스키마를 emergency/summary로 바꿈. README .env 표에 따라 키가 GEMINI_API_KEY뿐이면 Gemini를 씀.
#   - generate(): 1번 호출하고 검증. 실패하면 예외만 던짐 (재시도·템플릿 대체는 AutoHealing 몫).
#   - generate_or_template(): 상옥 님 with_healing이 붙기 전까지 쓰는 임시 함수 (재요청 1회 → 템플릿).
#
# 팀원과 겹치는 부분에는 "# [팀 합의] 이름: 설명" 주석을 달았음.

import os
from typing import Callable

from src.llm import fallback, prompts

LLM = Callable[[str], str]   # 프롬프트 문자열 → 응답 문자열

# [팀 합의] 전체: 시연 모델. README .env 예시 기본값(OPENAI_MODEL, GEMINI_MODEL)을 그대로 읽는다.
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
TEMPERATURE = 0.2
# [팀 합의] 상옥 님: 호출당 시간 제한 10초. 시간 초과는 예외로 올라가니 AutoHealing이 실패로 보고 재요청.
TIMEOUT_SECONDS = 10.0
# [팀 합의] 상옥 님: SDK 자체 재시도는 끈다. 재요청은 AutoHealing만 해야 시도 횟수와 로그가 맞는다.
MAX_RETRIES = 0

STEPS = {
    "emergency": (prompts.emergency_prompt, prompts.validate_emergency, prompts.EMERGENCY_SCHEMA, fallback.fallback_emergency),
    "summary": (prompts.summary_prompt, prompts.validate_summary, prompts.SUMMARY_SCHEMA, fallback.fallback_summary),
}


class LLMOutputError(Exception):
    """LLM이 답은 했지만 검증을 통과하지 못함. errors를 다음 프롬프트의 교정 요청에 넣는다."""

    def __init__(self, step: str, errors: list[str]):
        super().__init__(f"{step} 출력 검증 실패: {'; '.join(errors)}")
        self.step = step
        self.errors = errors


# ---------- 호출 함수 만들기 ----------

def provider() -> str | None:
    """LLM_PROVIDER가 있으면 그것, 없으면 키가 있는 쪽 (OpenAI 우선). 키가 하나도 없으면 None."""
    chosen = os.getenv("LLM_PROVIDER")
    if chosen:
        return chosen.lower()
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return None


def make_llm(step: str, model: str | None = None, client=None, use: str | None = None) -> LLM:
    """step: "emergency" 또는 "summary". client는 테스트용 가짜를 넣을 때만 쓴다."""
    if step not in STEPS:
        raise ValueError(f"step은 {list(STEPS)} 중 하나여야 합니다.")
    use = use or provider()
    schema = STEPS[step][2]
    if use == "openai":
        return _openai_llm(step, schema, model, client)
    if use == "gemini":
        return _gemini_llm(schema, model, client)
    raise RuntimeError("OPENAI_API_KEY 또는 GEMINI_API_KEY를 backend/config/.env에 넣으세요.")


def _openai_llm(step: str, schema: dict, model: str | None, client) -> LLM:
    model = model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    if client is None:
        from openai import OpenAI   # 키 없이 테스트할 때는 패키지를 불러오지 않게 여기서 import
        client = OpenAI(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
    text_format = {"format": {"type": "json_schema", "name": f"{step}_output", "strict": True, "schema": schema}}

    def llm(prompt: str) -> str:
        response = client.responses.create(model=model, input=prompt, temperature=TEMPERATURE, text=text_format)
        return response.output_text or ""

    return llm


def _gemini_llm(schema: dict, model: str | None, client) -> LLM:
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    if client is None:
        from google import genai
        client = genai.Client(http_options={"timeout": int(TIMEOUT_SECONDS * 1000)})
    # Gemini는 JSON 응답만 강제하고 키 검사는 validate_*에 맡긴다
    config = {"temperature": TEMPERATURE, "response_mime_type": "application/json"}

    def llm(prompt: str) -> str:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        return response.text or ""

    return llm


# ---------- 호출 + 검증 ----------

# [팀 합의] 상옥 님: AutoHealing이 감쌀 함수. 성공하면 검증된 dict, 실패하면 예외(SDK 예외 또는 LLMOutputError).
#   재요청 때는 직전 LLMOutputError.errors를 errors=로 넘기면 프롬프트에 교정 요청이 붙는다.
#   예: with_healing(None, lambda: generate("emergency", ctx, llm), task_id, "llm", use_cache=False)
def generate(step: str, ctx: dict, llm: LLM, errors: list[str] | None = None) -> dict:
    build, validate, _, _ = STEPS[step]
    raw = llm(build(ctx, errors))
    data, problems = validate(raw, ctx)
    if problems:
        raise LLMOutputError(step, problems)
    return data


def template(step: str, ctx: dict) -> dict:
    """재요청까지 실패했을 때 쓰는 템플릿 (README DR-LLM-01)."""
    return STEPS[step][3](ctx)


# 임시: 상옥 님 healing/retry.py가 준비되면 이 함수 대신 with_healing으로 generate()를 감싼다.
def generate_or_template(step: str, ctx: dict, llm: LLM | None, retries: int = 1) -> tuple[dict, dict]:
    """(결과, 기록). llm이 None이면 바로 템플릿. 기록: attempts, fallback_used, errors."""
    log = {"attempts": 0, "fallback_used": False, "errors": []}
    errors = None
    while llm is not None and log["attempts"] <= retries:
        log["attempts"] += 1
        try:
            return generate(step, ctx, llm, errors), log
        except LLMOutputError as e:
            errors = e.errors
            log["errors"].append("; ".join(e.errors))
        except Exception as e:     # 시간 초과, 연결 오류 등
            errors = None
            log["errors"].append(f"{type(e).__name__}: {e}")
    log["fallback_used"] = True
    return template(step, ctx), log
