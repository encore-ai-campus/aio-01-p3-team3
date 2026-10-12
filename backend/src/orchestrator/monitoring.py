"""Orchestration 1: Vital·IoT·Profile 병렬 실행 → CareStatusResult 조립 — 기화

에이전트는 실패해도 예외를 던지지 않고 빈 값과 오류 코드를 돌려준다.
빠진 정보로 계속 갈지(Join Guard), 정상이라 끝낼지(Handoff Guard)는 guards.py가 정한다.
"""

import asyncio

from src.agents.iot import run_iot
from src.agents.profile import run_profile
from src.agents.vital import run_vital
from src.orchestrator.validation import ValidationStatus, validate_care_status
from src.schemas import CareStatusResult


async def _profile(db, profile_id: str) -> dict:
    """DB 프로필 → 취약도. 프로필이 없거나 DB를 못 읽으면 run_profile(None) = "상" (README Join Guard)."""
    try:
        profile = await asyncio.to_thread(db.get_profile, profile_id)
    except Exception:
        return {"vulnerability": run_profile(None)["vulnerability"], "error": "profile_unavailable"}
    error = None if profile else "profile_missing"
    return {**run_profile(profile), "error": error}


async def run_monitoring(*, db, run_id: str, profile_id: str, scenario: str, fault=()) -> CareStatusResult:
    vital, iot, profile = await asyncio.gather(
        run_vital(db=db, run_id=run_id, profile_id=profile_id, scenario=scenario, fault=fault),
        run_iot(db=db, run_id=run_id, profile_id=profile_id, scenario=scenario, fault=fault),
        _profile(db, profile_id),
    )
    errors = [e for e in (vital["error"], profile["error"]) if e] + iot["errors"]
    care_status = CareStatusResult(
        run_id=run_id,
        profile_id=profile_id,
        scenario=scenario,
        vital=vital["vital"],
        indoor_environment=iot["indoor_environment"],
        devices=iot["devices"],
        cctv=iot["cctv"],
        vulnerability=profile["vulnerability"],
        # TODO: 병원 검색 지역. DB 프로필에 area가 없고 두나 님 MCP mock_data에만 있음 → 어디서 가져올지 합의 필요
        area=None,
        source=vital["source"] or "mock",
        errors=errors,
    )

    # 각 Agent의 복구가 끝난 뒤 실행하는 최종 계약 검사다.
    # 여기서 Agent를 다시 호출하지 않고, 오류를 보존해 Join Guard에 넘긴다.
    validation = validate_care_status(care_status)
    if validation.status is ValidationStatus.INVALID:
        care_status.errors.extend(validation.errors)
    return care_status
