"""Vital Agent: 바이탈 조회 (시뮬레이터 최신값 → 재시도 → 캐시 → MCP mock) — 기화

복구 로직은 상옥 님 healing/vital.py의 get_vitals_with_healing()을 그대로 쓰고,
이 파일은 "어디서 값을 가져올지"만 정한다.
- 1순위: 시뮬레이터가 15초마다 보낸 vital_readings 최신값 (FRESHNESS_SECONDS 안의 값만)
- 실패하면 재시도 → 캐시(이전 측정값) → MCP get_vitals(mock)
"""

from src import mcp_client
from src.db.vital_service import VitalService
from src.healing.vital import VitalDatabaseError, VitalUnavailable, get_vitals_with_healing
from src.schemas import VitalData

# 시뮬레이터 전송 주기 15초 × 3회. 이보다 오래된 값은 "최근 값 없음"으로 본다.
FRESHNESS_SECONDS = 45


def _source(result: dict) -> str:
    """get_vitals_with_healing은 실시간 성공도 source "mock"으로 돌려준다 (상옥 님 코드, live 추가 전 작성).
    recovery로 구분해 실시간 값은 "live"로 바꾼다. TODO(상옥): healing/vital.py에서 직접 "live"를 주면 이 함수 삭제."""
    if result["source"] == "mock" and result["recovery"] in (None, "retry"):
        return "live"
    return result["source"]


async def run_vital(*, db, run_id: str, profile_id: str, scenario: str, fault=()) -> dict:
    """→ {"vital": VitalData 형식 dict | None, "source": live/cache/mock | None, "error": 오류 코드 | None}
    실패해도 예외를 던지지 않는다. 바이탈 없이 진행할지는 Join Guard가 정한다."""
    service = VitalService(db)

    def fetch_latest():
        return service.get_latest_vital_reading(profile_id, max_age_seconds=FRESHNESS_SECONDS, scenario=scenario)

    async def fetch_mock():
        try:
            return await mcp_client.call_tool("get_vitals", {"profile_id": profile_id, "scenario": scenario})
        except mcp_client.McpToolError as error:
            # healing/vital.py는 mock 실패를 ValueError·TimeoutError·ConnectionError로만 받아 로그에 남긴다
            raise ValueError(str(error)) from error

    try:
        result = await get_vitals_with_healing(
            db=db, run_id=run_id, profile_id=profile_id, scenario=scenario,
            fetch_latest=fetch_latest, validate=VitalData.model_validate,
            freshness_seconds=FRESHNESS_SECONDS, fault=fault, mock_fetch=fetch_mock,
        )
    except VitalUnavailable:
        return {"vital": None, "source": None, "error": "vital_unavailable"}
    except VitalDatabaseError:
        return {"vital": None, "source": None, "error": "vital_db_error"}

    vital = VitalData.model_validate(result["data"]).model_dump()
    return {"vital": vital, "source": _source(result), "error": None}
