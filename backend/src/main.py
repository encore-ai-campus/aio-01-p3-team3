"""
FastAPI 앱 — 기화(④), 두나(⑤)
보호자가 어르신과 시나리오를 고르면 /care/run이 모니터링과 위험 판정을 실행하고,
조치가 필요하면 pending_approval을 반환하고 /care/approve가 Action과 Summary를 실행한다.
"""

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "config" / ".env")

# .env를 먼저 읽어야 MCP_URL·LLM 키가 반영되므로 import를 아래에 둔다
from fastapi import Depends, FastAPI, HTTPException  # noqa: E402

from src import mcp_client  # noqa: E402
from src.db.database import Database  # noqa: E402
from src.db.seed import seed_profiles  # noqa: E402
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


@app.post("/care/run", response_model=CareRunResponse)
async def care_run(request: CareRunRequest, db: Database = Depends(get_db)) -> CareRunResponse:
    """모니터링 → 위험 판정 → 조치안 생성. 조치가 필요하면 pending_approval (README 6장 응답 1)."""
    return await run_care(request, db=db)


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
