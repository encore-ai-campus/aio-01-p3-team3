"""Summary Agent: 보호자용 결과 보고, 어르신용 짧은 안내(LLM) — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 run_summary()를 넣음.
#   승인/거절과 실행 결과(executed)로 상황(done / device_fail / rejected)을 정하고 안내문을 만든다.
#   거절이면 어르신용은 빈 문자열 (README 5장 "거절 → 보호자용 기록만"). 어르신 안내는 승인·실행 뒤에만 [D7].
# 2026-10-08 해든 (승인·119 흐름): decided_by 추가. auto(119 바로 연결) / timeout(보호자 무응답으로 자동 연결)이면
#   "보호자 승인" 없이 연락한 이유를 쓰는 상황(auto_119 / timeout_119)으로 안내문을 만든다.
# 2026-10-12 해든 (주석 정리): 60초 무응답 자동 연결은 최종 결정(기화, #27)으로 쓰지 않음. timeout은 설정을 켤 때만 생긴다고 적음.

from src.llm.client import LLM, generate_or_template
from src.llm.prompts import build_summary_ctx


# [팀 합의] 지혜 님: emergency_result는 run_emergency() 결과(승인 대기 때 저장한 것), executed는 README 응답 2 형식.
#   기기 제어 결과에는 {"action": "control_device", "device": "aircon", "result": "fail"}처럼 device를 넣어 주세요.
#   decided_by: 보호자가 누르면 "guardian", 119를 승인 없이 바로 연결했으면 "auto", 60초 무응답으로 연결했으면 "timeout"
#   ("timeout"은 ENABLE_TIMEOUT_119가 True일 때만 생김. 최종 결정(기화 10/12)으로 꺼져 있어 시연에서는 나오지 않음).
def run_summary(emergency_result: dict, approved: bool, executed: list[dict] | None = None,
                llm: LLM | None = None, decided_by: str = "guardian") -> dict:
    """→ {"guardian_message", "elder_message", "fallback_used", "llm_log"}
    decided_by: guardian(보호자 승인·거절) / auto(119 바로 연결) / timeout(보호자 무응답으로 119 자동 연결)."""
    ctx = build_summary_ctx(emergency_result["context"], approved, executed, decided_by)
    out, log = generate_or_template("summary", ctx, llm)
    return {
        "guardian_message": out["guardian_message"],
        "elder_message": out["elder_message"],
        "fallback_used": log["fallback_used"],
        "llm_log": log,
    }
