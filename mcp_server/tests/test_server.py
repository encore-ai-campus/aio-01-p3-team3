"""FastMCP 도구 등록과 사용자 정의 HTTP 라우트 테스트."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.responses import FileResponse

from src import server


EXPECTED_TOOLS = {
    "get_vitals",
    "get_indoor_env",
    "get_device_status",
    "capture_cctv",
    "analyze_cctv",
    "control_device",
    "find_hospital",
    "notify_guardian",
    "call_119",
}


def test_registers_nine_care_tools() -> None:
    registered = {tool.name for tool in server.mcp._tool_manager.list_tools()}

    assert registered == EXPECTED_TOOLS


def test_health_route() -> None:
    response = asyncio.run(server.health(None))

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status": "ok",
        "service": "elder-care-mcp",
        "tool_count": 9,
    }


def test_cctv_route_rejects_unknown_name() -> None:
    request = SimpleNamespace(path_params={"name": "unknown.png"})
    response = asyncio.run(server.get_cctv_image(request))

    assert response.status_code == 404
    assert json.loads(response.body)["error"] == "CCTV_IMAGE_NOT_FOUND"


def test_cctv_asset_dir_points_to_real_images() -> None:
    expected = Path(__file__).resolve().parents[1] / "assets" / "cctv"

    assert server.CCTV_ASSET_DIR == expected
    for name in server.CCTV_IMAGE_NAMES:
        assert (expected / name).is_file(), name


def test_cctv_route_serves_every_scenario_image() -> None:
    for name in server.CCTV_IMAGE_NAMES:
        request = SimpleNamespace(path_params={"name": name})
        response = asyncio.run(server.get_cctv_image(request))

        assert isinstance(response, FileResponse), name
        assert Path(response.path) == server.CCTV_ASSET_DIR / name


def test_cctv_route_reports_missing_allowed_image(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server, "CCTV_ASSET_DIR", tmp_path)
    request = SimpleNamespace(path_params={"name": "fall.png"})
    response = asyncio.run(server.get_cctv_image(request))

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "error": "CCTV_IMAGE_NOT_READY",
        "name": "fall.png",
    }


def test_dockerfile_copies_cctv_assets() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "deploy" / "Dockerfile"

    assert "COPY assets/ ./assets/" in dockerfile.read_text(encoding="utf-8")


def test_cctv_route_serves_allowed_file(monkeypatch) -> None:
    asset_dir = Path(__file__).resolve().parent
    monkeypatch.setattr(server, "CCTV_ASSET_DIR", asset_dir)
    monkeypatch.setattr(server, "CCTV_IMAGE_NAMES", {"test_placeholder.py"})
    request = SimpleNamespace(path_params={"name": "test_placeholder.py"})

    response = asyncio.run(server.get_cctv_image(request))

    assert isinstance(response, FileResponse)
    assert Path(response.path) == asset_dir / "test_placeholder.py"
