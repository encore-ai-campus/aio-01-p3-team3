"""IoT Agent: 실내 온습도·기기 상태·CCTV 조회와 분석 — 기화
(승인 후 control_device 실행은 ⑤ Action 단계에서 추가)

- 실내 온습도·기기 상태: MCP 조회 + 상옥 님 with_healing 재시도 (3회). 실패하면 None → "확인 불가"로 진행
- CCTV: capture_cctv로 이미지 경로를 받고 analyze_cctv(해든 님 비전 분석)로 판단 (2회).
  실패하면 status "failed" → 바이탈 기준으로만 판정 (README DR-VISION-01)
"""

import asyncio
import math

from src import mcp_client
from src.healing.retry import RecoveryError, RetryPolicy, with_healing
from src.orchestrator.validation import validate_cctv_candidate
from src.schemas import CctvAnalysis, DeviceStatus, IndoorEnvironment

READ_POLICY = RetryPolicy(max_attempts=3)
VISION_POLICY = RetryPolicy(max_attempts=2, timeout_s=60)   # 비전 LLM 호출이라 시간 여유를 둠

# 해든 님 분석기는 confidence를 "high"/"low"로, 스키마는 0~1 숫자로 받는다.
# 해든 님 normalize_care_status()는 0.6 이상을 "high"로 다시 읽는다.
CONFIDENCE = {"high": 0.9, "low": 0.3}


def _tool_args(profile_id: str, scenario: str) -> dict:
    return {"profile_id": profile_id, "scenario": scenario}


async def _read(db, run_id: str, step: str, tool: str, args: dict, model):
    """MCP 조회 + 재시도. 끝내 실패하면 None (예외를 던지지 않음)."""
    async def fetch():
        try:
            return await mcp_client.call_tool(tool, args)
        except mcp_client.McpToolError as error:
            raise ValueError(str(error)) from error   # 잘못된 입력은 재시도해도 같으므로 실패로 기록

    try:
        result = await with_healing(db=db, run_id=run_id, step=step, fetch=fetch,
                                    validate=model.model_validate, policy=READ_POLICY)
    except (RecoveryError, ValueError):
        return None
    return model.model_validate(result["data"]).model_dump()


def _humidity_is_valid(value) -> bool:
    """습도는 위험 판정에 쓰지 않으므로 유효한 숫자 범위만 확인한다."""
    return (type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= 100)


async def _read_environment(db, run_id: str, profile_id: str, scenario: str):
    """온도는 AutoHealing 검증·재시도, 습도 오류는 해당 필드만 비운다.

    fetch 단계에서 습도만 None으로 정리하면 캐시에도 정리된 형태가 저장됩니다.
    기존 캐시에 잘못된 습도가 있더라도 온도까지 버리지 않도록 반환 후에도
    같은 정리를 한 번 더 합니다.
    """
    humidity_was_invalid = False

    async def fetch():
        nonlocal humidity_was_invalid
        # 재시도가 다음 정상 응답을 받으면 직전 응답의 습도 오류 표시는 지운다.
        humidity_was_invalid = False
        try:
            raw = await mcp_client.call_tool(
                "get_indoor_env", _tool_args(profile_id, scenario)
            )
        except mcp_client.McpToolError as error:
            raise ValueError(str(error)) from error
        if not isinstance(raw, dict):
            return raw
        normalized = dict(raw)
        humidity = normalized.get("humidity_percent")
        if humidity is not None and not _humidity_is_valid(humidity):
            normalized["humidity_percent"] = None
            humidity_was_invalid = True
        return normalized

    try:
        result = await with_healing(
            db=db, run_id=run_id, step="iot_env", fetch=fetch,
            validate=IndoorEnvironment.model_validate, policy=READ_POLICY,
        )
    except (RecoveryError, ValueError):
        return None, humidity_was_invalid

    data = dict(result["data"])
    humidity = data.get("humidity_percent")
    if humidity is not None and not _humidity_is_valid(humidity):
        # 낡은 캐시 등 이미 저장된 입력도 온도와 분리해 처리한다.
        data["humidity_percent"] = None
        humidity_was_invalid = True
    return IndoorEnvironment.model_validate(data).model_dump(), humidity_was_invalid


def _to_cctv(image_path: str, raw: dict) -> dict:
    """해든 님 분석 결과 → 스키마 CctvAnalysis."""
    available = raw.get("available", True)
    return CctvAnalysis(
        image_path=raw.get("image_path", image_path),
        person_visible=raw.get("person_visible"),
        posture=raw.get("posture"),
        fall_suspected=raw.get("fall_suspected"),
        confidence=CONFIDENCE.get(raw.get("confidence")),
        description=raw.get("description"),
        status="analyzed" if available else "unavailable",
    ).model_dump()


async def _cctv(db, run_id: str, profile_id: str, scenario: str, fault) -> dict:
    try:
        capture = await mcp_client.call_tool("capture_cctv", _tool_args(profile_id, scenario))
    except (mcp_client.McpConnectionError, mcp_client.McpToolError):
        return CctvAnalysis(status="failed", description="영상 판단 불가").model_dump()
    image_path = capture["image_path"]

    async def analyze():
        try:
            return await mcp_client.call_tool("analyze_cctv", {"image_path": image_path})
        except mcp_client.McpToolError as error:
            raise ValueError(str(error)) from error

    try:
        result = await with_healing(db=db, run_id=run_id, step="vision", fetch=analyze,
                                    # CCTV 출력 계약 위반은 기존 AutoHealing이 재시도한다.
                                    validate=validate_cctv_candidate, policy=VISION_POLICY,
                                    fault=fault)
    except (RecoveryError, ValueError):
        # 캡처 경로는 남겨서 보호자가 원본을 직접 확인할 수 있게 한다
        return CctvAnalysis(image_path=image_path, status="failed", description="영상 판단 불가").model_dump()
    return _to_cctv(image_path, result["data"])


async def run_iot(*, db, run_id: str, profile_id: str, scenario: str, fault=()) -> dict:
    """→ {"indoor_environment", "devices", "cctv", "errors"}. 셋을 동시에 조회한다."""
    args = _tool_args(profile_id, scenario)
    (env, humidity_invalid), devices, cctv = await asyncio.gather(
        _read_environment(db, run_id, profile_id, scenario),
        _read(db, run_id, "iot_devices", "get_device_status", args, DeviceStatus),
        _cctv(db, run_id, profile_id, scenario, fault),
    )
    errors = []
    if env is None:
        errors.append("indoor_environment_unavailable")
    if humidity_invalid:
        # 습도만 제외했음을 로그·최종 결과에서 알 수 있게 보존한다.
        errors.append("indoor_humidity_invalid")
    if devices is None:
        errors.append("devices_unavailable")
    if cctv["status"] == "failed":
        errors.append("cctv_failed")
    return {"indoor_environment": env, "devices": devices, "cctv": cctv, "errors": errors}
