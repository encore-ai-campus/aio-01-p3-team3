"""
FastAPI 앱 — 기화(④), 두나(⑤)
보호자가 어르신과 시나리오를 고르면 /care/run이 모니터링과 위험 판정을 실행하고,
조치가 필요하면 pending_approval을 반환하고 /care/approve가 Action과 Summary를 실행한다.
"""

import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "config" / ".env")

# .env를 먼저 읽어야 MCP_URL·LLM 키가 반영되므로 import를 아래에 둔다
from fastapi import Depends, FastAPI, HTTPException, Query, Response  # noqa: E402

from src import mcp_client  # noqa: E402
from src.db.database import Database  # noqa: E402
from src.db.device_states import DeviceStates  # noqa: E402
from src.db.seed import seed_profiles  # noqa: E402
from src.db.vital_service import VitalService  # noqa: E402
from src.orchestrator.approval_flow import (  # noqa: E402
    PendingApprovalNotFound,
    process_care_approval,
)
from src.orchestrator.care import run_care  # noqa: E402
from src.schemas import (  # noqa: E402
    CareApprovalRequest,
    CareApprovalResponse,
    CareRunRequest,
    CareRunResponse,
    DeviceControlRequest,
    DeviceControlResponse,
    DeviceStatesResponse,
    RunLogsResponse,
    Scenario,
    VitalLatestResponse,
    VitalPoint,
    VitalReadingCreate,
    VitalReadingResponse,
)


@lru_cache
def get_db() -> Database:
    """DB_PATH(compose: /app/data/app.db, 볼륨)의 SQLite. 처음 열 때 시연용 가상 프로필 3명을 넣는다."""
    db = Database()
    seed_profiles(db)
    return db


@asynccontextmanager
async def lifespan(_app):
    get_db()   # 서버가 뜰 때 DB 파일·테이블·프로필을 미리 준비
    yield


app = FastAPI(title="Elder Care Multi-Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    """backend 프로세스가 살아 있는지 확인한다."""
    return {"status": "ok", "service": "backend"}


@app.get("/health/ready")
async def ready() -> dict:
    """MCP 서버까지 연결되는지 확인한다."""
    try:
        tools = await mcp_client.list_tools()
    except mcp_client.McpConnectionError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"status": "ok", "mcp": mcp_client.MCP_URL, "tools": tools}


@app.get("/logs", response_model=RunLogsResponse)
def get_logs(
    run_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Database = Depends(get_db),
) -> RunLogsResponse:
    """최근 AutoHealing 로그를 반환하고, run_id가 있으면 해당 실행만 조회한다."""
    # 로그에는 오류 원문 대신 기존 DB가 저장하는 안전한 코드/예외 종류만 담긴다.
    logs = db.recent_logs(run_id=run_id, limit=limit)
    return RunLogsResponse(logs=logs, count=len(logs))


CCTV_SUFFIXES = (".png", ".jpg", ".jpeg")


@app.get("/cctv/{name}")
async def cctv_image(name: str) -> Response:
    """CCTV 캡처 이미지를 MCP 서버에서 받아 전달한다 (README 2장: 이미지는 경로만 넘기고 화면은 URL로 받음).
    name은 CareStatusResult.cctv.image_path의 파일 이름만 (예: fall.png)."""
    if "/" in name or "\\" in name or ".." in name or not name.lower().endswith(CCTV_SUFFIXES):
        raise HTTPException(status_code=404, detail="CCTV 이미지를 찾을 수 없습니다.")
    try:
        content, media_type = await mcp_client.fetch_cctv_image(name)
    except mcp_client.CctvImageNotFound as error:
        raise HTTPException(status_code=404, detail="CCTV 이미지를 찾을 수 없습니다.") from error
    except mcp_client.McpConnectionError as error:
        raise HTTPException(status_code=503, detail="CCTV 이미지를 가져올 수 없습니다 (MCP 연결 실패).") from error
    return Response(content=content, media_type=media_type)


VIDEO_NAME = re.compile(r"[A-Za-z0-9_-]+\.mp4")


@app.get("/video/{name}")
async def cctv_video(name: str) -> Response:
    """CCTV 영상을 MCP 서버에서 받아 전달한다. name은 CCTV 이미지 이름에서 확장자만 .mp4로 바꾼 것 (예: fall.mp4)."""
    if not VIDEO_NAME.fullmatch(name):
        raise HTTPException(status_code=404, detail="CCTV 영상을 찾을 수 없습니다.")
    try:
        content, media_type = await mcp_client.fetch_cctv_video(name)
    except mcp_client.CctvVideoNotFound as error:
        raise HTTPException(status_code=404, detail="CCTV 영상을 찾을 수 없습니다.") from error
    except mcp_client.McpConnectionError as error:
        raise HTTPException(status_code=503, detail="CCTV 영상을 가져올 수 없습니다 (MCP 연결 실패).") from error
    return Response(content=content, media_type=media_type)


@app.post("/vitals/readings", response_model=VitalReadingResponse)
def create_vital_reading(
    request: VitalReadingCreate,
    db: Database = Depends(get_db),
) -> VitalReadingResponse:
    """바이탈 측정 요청을 검증하고 저장 서비스에 전달한다."""
    # reading_id는 외부 요청에 노출하지 않는 DB 내부 식별자다.
    reading_id = str(uuid4())

    # DB 서비스는 측정 시각을 ISO 문자열로 받으므로 JSON 모드로 변환한다.
    reading = request.model_dump(mode="json")
    reading["reading_id"] = reading_id

    # SQLite 저장 함수는 동기 함수이며, FastAPI의 동기 경로에서 실행한다.
    VitalService(db).save_vital_reading(reading)

    # 응답은 합의된 계약대로 저장 상태와 대상 프로필·측정 시각만 반환한다.
    return VitalReadingResponse(
        profile_id=request.profile_id,
        measured_at=request.measured_at,
    )


@app.get("/vitals/latest", response_model=VitalLatestResponse)
def latest_vital(
    profile_id: str = Query(min_length=1),
    scenario: Scenario | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    max_age_seconds: float = Query(default=120, gt=0, le=3600),
    db: Database = Depends(get_db),
) -> VitalLatestResponse:
    """화면의 실시간 심박수용: 가장 최근 측정값과 최근 이력. 값이 없으면 no_data (오류 아님)."""
    readings = VitalService(db).get_recent_vital_readings(
        profile_id, scenario=scenario, limit=limit, max_age_seconds=max_age_seconds
    )
    if not readings:
        return VitalLatestResponse(status="no_data", profile_id=profile_id, scenario=scenario)
    newest = readings[-1]
    data = newest["data"]
    return VitalLatestResponse(
        status="ok",
        profile_id=profile_id,
        scenario=scenario,
        heart_rate=data["heart_rate"],
        systolic_bp=data.get("systolic_bp"),
        temperature_c=data.get("temperature_c"),
        spo2=data.get("spo2"),
        measured_at=data["measured_at"],
        age_seconds=round(newest["measured_age_s"], 1),
        history=[VitalPoint(measured_at=r["data"]["measured_at"], heart_rate=r["data"]["heart_rate"]) for r in readings],
    )


@app.post("/care/run", response_model=CareRunResponse)
async def care_run(request: CareRunRequest, db: Database = Depends(get_db)) -> CareRunResponse:
    """모니터링 → 위험 판정 → 조치안 생성. 조치가 필요하면 pending_approval (README 6장 응답 1)."""
    DeviceStates(db).clear(request.profile_id)   # 새로 확인하면 토글로 바꾼 기기 상태는 시나리오 기본값으로 돌아간다
    return await run_care(request, db=db)


# 화면 토글(켜짐/꺼짐) → MCP control_device(device, action). 에어컨 켜기는 냉방으로 보낸다.
DEVICE_ACTIONS = {
    ("aircon", "on"): "cool",
    ("aircon", "off"): "off",
    ("induction", "on"): "on",
    ("induction", "off"): "off",
}


@app.get("/devices/{profile_id}", response_model=DeviceStatesResponse)
def get_device_states(profile_id: str, db: Database = Depends(get_db)) -> DeviceStatesResponse:
    """토글로 바꾼 기기 상태 (바꾼 적 없는 기기는 없다)."""
    if db.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="어르신 프로필을 찾을 수 없습니다.")
    return DeviceStatesResponse(profile_id=profile_id, devices=DeviceStates(db).all(profile_id))


@app.post("/devices/control", response_model=DeviceControlResponse)
async def control_device_state(request: DeviceControlRequest, db: Database = Depends(get_db)) -> DeviceControlResponse:
    """에어컨·인덕션을 켜거나 끈다. MCP Mock 제어가 성공하면 그 상태를 저장한다."""
    if db.get_profile(request.profile_id) is None:
        raise HTTPException(status_code=404, detail="어르신 프로필을 찾을 수 없습니다.")
    action = DEVICE_ACTIONS[(request.device, request.state)]
    try:
        result = await mcp_client.call_tool("control_device", {"device": request.device, "action": action})
    except mcp_client.McpConnectionError as error:
        raise HTTPException(status_code=503, detail="기기를 제어할 수 없습니다 (MCP 연결 실패).") from error
    except mcp_client.McpToolError as error:
        raise HTTPException(status_code=502, detail="기기 제어에 실패했습니다.") from error
    DeviceStates(db).set(request.profile_id, request.device, request.state)
    return DeviceControlResponse(
        profile_id=request.profile_id,
        device=request.device,
        state=request.state,
        message=str(result.get("message") or ""),
    )


@app.post("/care/approve", response_model=CareApprovalResponse)
async def care_approve(
    request: CareApprovalRequest,
    db: Database = Depends(get_db),
) -> CareApprovalResponse:
    """보호자 결정에 따라 Action을 실행하고 Summary 결과를 반환한다."""

    try:
        return await process_care_approval(request, db=db)
    except PendingApprovalNotFound as error:
        raise HTTPException(
            status_code=404,
            detail="승인 대기 중인 run_id가 없거나 이미 처리되었습니다.",
        ) from error
