"""노인 실시간 케어용 FastMCP 서버."""

import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.responses import FileResponse, JSONResponse

from .mock_data import SCENARIOS
from .tools.cctv import analyze_cctv, capture_cctv
from .tools.home import control_device, get_device_status, get_indoor_env
from .tools.hospital import find_hospital
from .tools.notify import call_119, notify_guardian
from .tools.vitals import get_vitals


PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / "config" / ".env")

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8010"))
CCTV_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "cctv"
CCTV_IMAGE_NAMES = {
    Path(str(data["cctv_image_path"])).name
    for data in SCENARIOS.values()
}
CCTV_VIDEO_DIR = Path(__file__).resolve().parent.parent / "assets" / "video"
# 영상 이름은 CCTV 이미지 이름에서 확장자만 .mp4로 바꾼 것 (normal.png → normal.mp4)
CCTV_VIDEO_NAMES = {Path(name).with_suffix(".mp4").name for name in CCTV_IMAGE_NAMES}

mcp = FastMCP(
    "elder-care-tools",
    host=MCP_HOST,
    port=MCP_PORT,
    stateless_http=True,
    json_response=True,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
VISION_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
MOCK_ACTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

# 조회형 도구
mcp.tool(annotations=READ_ONLY)(get_vitals)
mcp.tool(annotations=READ_ONLY)(get_indoor_env)
mcp.tool(annotations=READ_ONLY)(get_device_status)
mcp.tool(annotations=READ_ONLY)(capture_cctv)
mcp.tool(annotations=VISION_READ_ONLY)(analyze_cctv)
mcp.tool(annotations=READ_ONLY)(find_hospital)

# 실제 외부 동작을 수행하지 않는 실행형 Mock 도구
mcp.tool(annotations=MOCK_ACTION)(control_device)
mcp.tool(annotations=MOCK_ACTION)(notify_guardian)
mcp.tool(annotations=MOCK_ACTION)(call_119)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request) -> JSONResponse:
    """MCP 프로세스와 등록 도구 수를 확인한다."""

    return JSONResponse(
        {
            "status": "ok",
            "service": "elder-care-mcp",
            "tool_count": 9,
        }
    )


@mcp.custom_route("/cctv/{name}", methods=["GET"])
async def get_cctv_image(request):
    """허용된 시나리오의 CCTV Mock 이미지만 반환한다."""

    name = request.path_params["name"]
    if name not in CCTV_IMAGE_NAMES:
        return JSONResponse(
            {"error": "CCTV_IMAGE_NOT_FOUND", "name": name},
            status_code=404,
        )

    image_path = CCTV_ASSET_DIR / name
    if not image_path.is_file():
        return JSONResponse(
            {"error": "CCTV_IMAGE_NOT_READY", "name": name},
            status_code=404,
        )

    return FileResponse(image_path)


@mcp.custom_route("/video/{name}", methods=["GET"])
async def get_cctv_video(request):
    """허용된 CCTV 영상(이미지와 같은 이름의 .mp4)만 반환한다."""

    name = request.path_params["name"]
    if name not in CCTV_VIDEO_NAMES:
        return JSONResponse(
            {"error": "CCTV_VIDEO_NOT_FOUND", "name": name},
            status_code=404,
        )

    video_path = CCTV_VIDEO_DIR / name
    if not video_path.is_file():
        return JSONResponse(
            {"error": "CCTV_VIDEO_NOT_READY", "name": name},
            status_code=404,
        )

    return FileResponse(video_path, media_type="video/mp4")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
