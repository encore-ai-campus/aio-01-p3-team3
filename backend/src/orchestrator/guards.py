"""Join Guard, Handoff Guard — 기화 (README 5장)

모든 Guard는 LLM이 아닌 코드 규칙이다.
- Join Guard: 결과가 다 모였는가. 바이탈을 끝내 못 얻으면(캐시·mock도 실패) 안전 종료한다.
  나머지(실내·기기·CCTV·프로필)가 빠지면 빠진 채로 진행한다. (판정 규칙이 보수적으로 처리)
- Handoff Guard: Orchestration 2로 넘길 가치가 있는가. 위험도 "정상"이면 "이상 없음"으로 끝낸다.
"""

from src.schemas import CareStatusResult

VITAL_FAILURES = {"vital_unavailable", "vital_db_error"}
SENSOR_CHECK_MESSAGE = "어르신 바이탈 센서에 연결할 수 없습니다. 센서 상태를 직접 확인해 주세요."


def join_guard(care_status: CareStatusResult) -> str | None:
    """안전 종료해야 하면 보호자 안내 문구를, 계속 진행하면 None을 돌려준다."""
    if care_status.vital is None or VITAL_FAILURES & set(care_status.errors):
        return SENSOR_CHECK_MESSAGE
    return None


def handoff_guard(risk_level: str) -> bool:
    """Orchestration 2(승인·조치)로 넘길지. 정상이면 False → no_issue로 종료."""
    return risk_level != "정상"
