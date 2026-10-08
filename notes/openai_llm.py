"""
OpenAI 호출 함수 (LLM 파트, 초안) - 시연 모델: OpenAI (해든 선택 10/7, [팀 합의] 팀 전체 합의 전)

llm_contract.py의 call_writer / call_summary에 넘기는 llm(prompt) -> str 함수를 만듭니다.
구조화 출력(JSON 스키마, strict)으로 키 이름과 자료형을 고정합니다.
개수·글자 수·의료 표현·지어낸 수치는 여전히 llm_contract의 validate_*가 검사합니다.

사용 예:
    writer_llm = make_openai_llm("writer")
    raw = call_writer(ctx, writer_llm)
    data, errors = validate_writer(raw, ctx)

팀원과 겹치는 부분에는 "# [팀 합의] 이름: 설명" 주석을 달았습니다.
"""

import os
from typing import Callable

DEFAULT_MODEL = "gpt-4.1-mini"  # backend/src/main.py의 OPENAI_MODEL 기본값과 같음
TEMPERATURE = 0.2               # 계획서: 0.0~0.3
# [팀 합의] 상옥 님: 호출당 시간 제한 10초(해든 결정). 시간 초과는 예외로 올라가니 AutoHealing.llm()이 실패로 보고 재요청.
TIMEOUT_SECONDS = 10.0
# [팀 합의] 상옥 님: SDK 자체 재시도는 끈다(max_retries=0). 재요청 1회는 AutoHealing.llm()만 담당해야
#   재시도 횟수와 로그(run_logs)가 맞는다. 켜 두면 SDK가 몰래 2번 더 호출한다.
MAX_RETRIES = 0

# strict 모드는 모든 키를 required에 넣고 additionalProperties를 false로 둬야 한다.
SCHEMAS = {
    "writer": {
        "type": "object",
        "properties": {
            "actions": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["actions", "reason"],
        "additionalProperties": False,
    },
    "summary": {
        "type": "object",
        "properties": {
            "elder_message": {"type": "string"},
            "guardian_message": {"type": "string"},
        },
        "required": ["elder_message", "guardian_message"],
        "additionalProperties": False,
    },
}


def make_openai_llm(step: str, model: str | None = None, client=None) -> Callable[[str], str]:
    """step: "writer" 또는 "summary". client는 테스트용 가짜를 넣을 때만 쓴다."""
    if step not in SCHEMAS:
        raise ValueError("step은 writer 또는 summary여야 합니다.")
    model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY를 설정하세요.")
        from openai import OpenAI  # 키 없이 테스트할 때는 openai 패키지가 없어도 되게 여기서 불러온다
        client = OpenAI(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)

    text_format = {"format": {"type": "json_schema", "name": f"{step}_output", "strict": True, "schema": SCHEMAS[step]}}

    def llm(prompt: str) -> str:
        response = client.responses.create(model=model, input=prompt, temperature=TEMPERATURE, text=text_format)
        return response.output_text or ""

    return llm
