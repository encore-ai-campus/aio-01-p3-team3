"""API 계약 테스트 (/health, /health/ready, 이후 /care/run, /care/approve, /cctv/{name}) — 기화·지혜"""

from fastapi.testclient import TestClient

from src import main as backend_app


def test_health():
    response = TestClient(backend_app.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend"}


def test_ready_lists_mcp_tools(monkeypatch):
    async def fake_list_tools():
        return ["get_vitals", "get_indoor_env"]

    monkeypatch.setattr(backend_app.mcp_client, "list_tools", fake_list_tools)
    response = TestClient(backend_app.app).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["tools"] == ["get_vitals", "get_indoor_env"]


def test_ready_returns_503_when_mcp_down(monkeypatch):
    async def fake_list_tools():
        raise backend_app.mcp_client.McpConnectionError("MCP 연결 실패: ConnectError")

    monkeypatch.setattr(backend_app.mcp_client, "list_tools", fake_list_tools)
    response = TestClient(backend_app.app).get("/health/ready")
    assert response.status_code == 503
