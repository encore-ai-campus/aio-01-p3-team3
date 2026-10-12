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


def install_cctv(monkeypatch, behavior):
    requested = []

    async def fake_fetch(name):
        requested.append(name)
        return behavior(name)

    monkeypatch.setattr(backend_app.mcp_client, "fetch_cctv_image", fake_fetch)
    return requested


def test_cctv_image_is_relayed_from_mcp(monkeypatch):
    requested = install_cctv(monkeypatch, lambda name: (b"\x89PNG-fake", "image/png"))
    response = TestClient(backend_app.app).get("/cctv/fall.png")
    assert response.status_code == 200
    assert response.content == b"\x89PNG-fake"
    assert response.headers["content-type"] == "image/png"
    assert requested == ["fall.png"]


def test_cctv_image_not_found(monkeypatch):
    def missing(name):
        raise backend_app.mcp_client.CctvImageNotFound(name)
    install_cctv(monkeypatch, missing)
    assert TestClient(backend_app.app).get("/cctv/none.png").status_code == 404


def test_cctv_image_returns_503_when_mcp_down(monkeypatch):
    def down(name):
        raise backend_app.mcp_client.McpConnectionError("MCP 연결 실패")
    install_cctv(monkeypatch, down)
    assert TestClient(backend_app.app).get("/cctv/fall.png").status_code == 503


def test_cctv_rejects_non_image_or_path_names(monkeypatch):
    requested = install_cctv(monkeypatch, lambda name: (b"x", "image/png"))
    client = TestClient(backend_app.app)
    for name in ["server.py", "..png", "%2e%2e%2fsecret.png"]:
        assert client.get(f"/cctv/{name}").status_code == 404, name
    assert requested == []           # MCP 서버까지 가지 않음


def install_video(monkeypatch, behavior):
    requested = []

    async def fake_fetch(name):
        requested.append(name)
        return behavior(name)

    monkeypatch.setattr(backend_app.mcp_client, "fetch_cctv_video", fake_fetch)
    return requested


def test_cctv_video_is_relayed_from_mcp(monkeypatch):
    requested = install_video(monkeypatch, lambda name: (b"\x00\x00ftypmp42", "video/mp4"))
    response = TestClient(backend_app.app).get("/video/lying.mp4")
    assert response.status_code == 200
    assert response.content == b"\x00\x00ftypmp42"
    assert response.headers["content-type"] == "video/mp4"
    assert requested == ["lying.mp4"]


def test_cctv_video_not_found_and_mcp_down(monkeypatch):
    def missing(name):
        raise backend_app.mcp_client.CctvVideoNotFound(name)
    install_video(monkeypatch, missing)
    assert TestClient(backend_app.app).get("/video/fall.mp4").status_code == 404

    def down(name):
        raise backend_app.mcp_client.McpConnectionError("MCP 연결 실패")
    install_video(monkeypatch, down)
    assert TestClient(backend_app.app).get("/video/fall.mp4").status_code == 503


def test_cctv_video_rejects_non_mp4_or_path_names(monkeypatch):
    requested = install_video(monkeypatch, lambda name: (b"x", "video/mp4"))
    client = TestClient(backend_app.app)
    for name in ["server.py", "fall.png", "..mp4", "%2e%2e%2fsecret.mp4", "a%20b.mp4"]:
        assert client.get(f"/video/{name}").status_code == 404, name
    assert requested == []

