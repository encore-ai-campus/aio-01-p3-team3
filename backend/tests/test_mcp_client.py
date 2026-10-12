"""MCP 호출 래퍼 테스트. 실제 MCP 서버 없이 가짜 세션으로 확인한다. — 기화"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from src import mcp_client


def text(value: str):
    return SimpleNamespace(text=value)


def fake_result(*, structured=None, texts=(), is_error=False):
    return SimpleNamespace(structuredContent=structured, content=[text(t) for t in texts], isError=is_error)


def install_session(monkeypatch, result):
    calls = []

    class FakeSession:
        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return result

    @asynccontextmanager
    async def fake_mcp_session(url=None):
        yield FakeSession()

    monkeypatch.setattr(mcp_client, "mcp_session", fake_mcp_session)
    return calls


def test_structured_result_is_returned(monkeypatch):
    vital = {"heart_rate": 72, "systolic_bp": 125, "temperature_c": 36.5, "spo2": 98}
    calls = install_session(monkeypatch, fake_result(structured=vital))
    result = asyncio.run(mcp_client.call_tool("get_vitals", {"profile_id": "profile-01", "scenario": "normal"}))
    assert result == vital
    assert calls == [("get_vitals", {"profile_id": "profile-01", "scenario": "normal"})]


def test_text_json_result_is_parsed(monkeypatch):
    install_session(monkeypatch, fake_result(texts=['{"image_path": "assets/cctv/fall.jpg"}']))
    assert asyncio.run(mcp_client.call_tool("capture_cctv")) == {"image_path": "assets/cctv/fall.jpg"}


def test_tool_error_raises_tool_error(monkeypatch):
    install_session(monkeypatch, fake_result(texts=["지원하지 않는 profile_id입니다: x"], is_error=True))
    with pytest.raises(mcp_client.McpToolError, match="get_vitals"):
        asyncio.run(mcp_client.call_tool("get_vitals", {"profile_id": "x", "scenario": "normal"}))


def install_http(monkeypatch, status_code, content=b"", content_type="image/png"):
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(status_code, content=content, headers={"content-type": content_type})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(mcp_client.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    return requested


def test_cctv_image_comes_from_server_root_not_mcp_path(monkeypatch):
    requested = install_http(monkeypatch, 200, b"\x89PNG-fake")
    content, media_type = asyncio.run(mcp_client.fetch_cctv_image("fall.png", base_url="http://mcp:8010"))
    assert content == b"\x89PNG-fake" and media_type == "image/png"
    assert requested == ["http://mcp:8010/cctv/fall.png"]


def test_cctv_base_url_drops_mcp_suffix():
    assert mcp_client.MCP_URL.endswith("/mcp")
    assert mcp_client.MCP_BASE_URL == mcp_client.MCP_URL[: -len("/mcp")]


def test_cctv_image_404_raises_not_found(monkeypatch):
    install_http(monkeypatch, 404, b'{"error": "CCTV_IMAGE_NOT_FOUND"}', "application/json")
    with pytest.raises(mcp_client.CctvImageNotFound):
        asyncio.run(mcp_client.fetch_cctv_image("none.png"))


def test_cctv_image_server_error_is_connection_error(monkeypatch):
    install_http(monkeypatch, 500)
    with pytest.raises(ConnectionError):
        asyncio.run(mcp_client.fetch_cctv_image("fall.png"))


def test_unreachable_server_raises_connection_error():
    # 9번 포트는 아무것도 듣지 않으므로 바로 연결 실패. AutoHealing이 재시도할 수 있게 ConnectionError 계열이어야 함
    with pytest.raises(ConnectionError):
        asyncio.run(mcp_client.call_tool("get_vitals", url="http://127.0.0.1:9/mcp"))
