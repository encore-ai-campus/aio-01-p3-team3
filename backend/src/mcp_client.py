"""MCP 서버 연결 세션, 도구 호출 래퍼 — 기화

에이전트는 call_tool()만 부르면 된다. 실패는 숨기지 않고 예외로 던져서
AutoHealing(healing/)이 재시도·캐시·mock 대체를 판단하게 한다.
- McpConnectionError(ConnectionError): 서버에 닿지 못함 → 재시도 대상
- McpToolError(RuntimeError): 서버는 응답했지만 도구가 실패함 (잘못된 입력 등) → 재시도해도 같은 결과
"""

import json
import os
from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8010/mcp")
# CCTV 이미지는 MCP 도구가 아니라 MCP 서버의 일반 HTTP 경로(/cctv/{name})로 받는다
MCP_BASE_URL = MCP_URL.rstrip("/").removesuffix("/mcp")
CCTV_TIMEOUT_SECONDS = 10.0


class McpConnectionError(ConnectionError):
    """MCP 서버 연결 실패."""


class McpToolError(RuntimeError):
    """MCP 도구가 오류를 돌려줌."""

    def __init__(self, tool: str, message: str):
        super().__init__(f"{tool}: {message}")
        self.tool = tool


class CctvImageNotFound(LookupError):
    """MCP 서버에 해당 CCTV 이미지가 없음 (허용 목록에 없거나 파일이 없음)."""


@asynccontextmanager
async def mcp_session(url: str | None = None):
    async with streamable_http_client(url or MCP_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def _text(result) -> str:
    return "\n".join(item.text for item in result.content if hasattr(item, "text"))


def _payload(result) -> dict:
    """도구 반환값(dict)을 꺼낸다. 구조화 결과가 있으면 그것을, 없으면 텍스트 JSON을 읽는다."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    return json.loads(_text(result))


async def call_tool(name: str, arguments: dict | None = None, *, url: str | None = None) -> dict:
    """MCP 도구 하나를 호출하고 반환값(dict)을 돌려준다."""
    try:
        async with mcp_session(url) as session:
            result = await session.call_tool(name, arguments or {})
    except Exception as error:
        raise McpConnectionError(f"MCP 연결 실패 ({name}): {type(error).__name__}") from error
    if result.isError:
        raise McpToolError(name, _text(result) or "도구 호출 실패")
    return _payload(result)


async def fetch_cctv_image(name: str, *, base_url: str | None = None) -> tuple[bytes, str]:
    """MCP 서버의 CCTV 캡처 이미지를 받는다. → (이미지 바이트, content-type)"""
    url = f"{(base_url or MCP_BASE_URL).rstrip('/')}/cctv/{name}"
    try:
        async with httpx.AsyncClient(timeout=CCTV_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
    except httpx.HTTPError as error:
        raise McpConnectionError(f"MCP 연결 실패 (cctv): {type(error).__name__}") from error
    if response.status_code == 404:
        raise CctvImageNotFound(name)
    if response.status_code != 200:
        raise McpConnectionError(f"MCP CCTV 응답 오류: HTTP {response.status_code}")
    return response.content, response.headers.get("content-type", "application/octet-stream")


async def list_tools(*, url: str | None = None) -> list[str]:
    """등록된 도구 이름 목록. /health/ready에서 MCP 연결 확인용."""
    try:
        async with mcp_session(url) as session:
            tools = (await session.list_tools()).tools
    except Exception as error:
        raise McpConnectionError(f"MCP 연결 실패: {type(error).__name__}") from error
    return [tool.name for tool in tools]
