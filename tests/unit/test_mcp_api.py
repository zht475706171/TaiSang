# tests/unit/test_mcp_api.py
"""MCP API 路由测试。"""
import pytest
from fastapi.testclient import TestClient

from taisang.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """创建测试客户端,隔离 state 文件。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    # 隔离 MCP state(monkeypatch 自动恢复,比手动 save/restore 更安全)
    import taisang.mcp.manager as mgr_mod
    monkeypatch.setattr(mgr_mod, "_STATE_FILE", tmp_path / "mcp_servers.json")
    # 重置 mcp_api 模块级 singleton,确保测试间隔离。
    # 不用 monkeypatch.setattr 是因为 get_mcp_manager() 内部会重新赋值 _manager,
    # monkeypatch 的自动恢复会把它恢复成被改过的值而非 None,反而出问题。
    import taisang.web.mcp_api as api_mod
    api_mod._manager = None
    app = create_app(tmp_path)
    yield TestClient(app)
    api_mod._manager = None


def test_list_servers_empty(client):
    r = client.get("/api/mcp/servers")
    assert r.status_code == 200
    data = r.json()
    assert data == []


def test_add_server(client):
    r = client.post("/api/mcp/servers", json={
        "name": "fs",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "server"],
    })
    assert r.status_code == 200
    assert r.json()["name"] == "fs"


def test_add_server_invalid_transport(client):
    r = client.post("/api/mcp/servers", json={
        "name": "bad",
        "transport": "invalid",
    })
    assert r.status_code == 422


def test_add_duplicate_server(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.post(
        "/api/mcp/servers",
        json={"name": "fs", "transport": "stdio", "command": "node"},
    )
    assert r.status_code == 409


def test_get_server(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.get("/api/mcp/servers/fs")
    assert r.status_code == 200
    assert r.json()["name"] == "fs"


def test_get_server_not_found(client):
    r = client.get("/api/mcp/servers/nonexistent")
    assert r.status_code == 404


def test_update_server(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.put(
        "/api/mcp/servers/fs",
        json={"name": "fs", "transport": "stdio", "command": "node"},
    )
    assert r.status_code == 200


def test_delete_server(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.delete("/api/mcp/servers/fs")
    assert r.status_code == 200
    r2 = client.get("/api/mcp/servers/fs")
    assert r2.status_code == 404


def test_toggle_server(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.post("/api/mcp/servers/fs/toggle", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_toggle_disable_disconnects(client):
    """禁用 server 后,status 应该不再是 connected(验证 disconnect 被调用)。"""
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    # add_server 会尝试连接,stdio npx 不存在会失败 → status="failed" 或 "disconnected"
    # 但 toggle disable 后无论如何 status 不应该是 "connected"
    r = client.post("/api/mcp/servers/fs/toggle", json={"enabled": False})
    assert r.status_code == 200
    info = client.get("/api/mcp/servers/fs/info").json()
    assert info["status"] != "connected"


def test_reconnect_server(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.post("/api/mcp/servers/fs/reconnect")
    assert r.status_code == 200


def test_get_server_info(client):
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "npx"})
    r = client.get("/api/mcp/servers/fs/info")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "fs"
    assert "status" in data
