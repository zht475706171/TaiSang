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


def test_import_cli_stdio(client):
    r = client.post("/api/mcp/servers/import-cli", json={
        "line": "filesystem npx -y @modelcontextprotocol/server-filesystem /tmp",
    })
    assert r.status_code == 200
    info = r.json()
    assert info["name"] == "filesystem"
    assert "status" in info


def test_import_cli_sse(client):
    r = client.post("/api/mcp/servers/import-cli", json={
        "line": "search --transport sse https://example.com/sse",
    })
    assert r.status_code == 200
    info = r.json()
    assert info["name"] == "search"
    assert "status" in info


def test_import_cli_overwrites_existing(client):
    """同名覆盖:已有 fs,新配置覆盖,状态仍可见。"""
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "old"})
    r = client.post("/api/mcp/servers/import-cli", json={
        "line": "fs npx -y new-server",
    })
    assert r.status_code == 200
    # 配置被覆盖
    cfg = client.get("/api/mcp/servers/fs").json()
    assert cfg["command"] == "npx"
    assert cfg["args"] == ["-y", "new-server"]


def test_import_cli_parse_error(client):
    """CLI 语法错 → 422。"""
    r = client.post("/api/mcp/servers/import-cli", json={
        "line": "--transport bad https://example.com/sse",
    })
    assert r.status_code == 422


def test_import_cli_empty_line(client):
    r = client.post("/api/mcp/servers/import-cli", json={"line": "   "})
    assert r.status_code == 422


def test_import_cli_missing_line_field(client):
    """body 没有 line 字段 → 422(pydantic 校验)。"""
    r = client.post("/api/mcp/servers/import-cli", json={})
    assert r.status_code == 422


def test_import_batch_all_new(client):
    """批量新增,全部新。"""
    text = """
    {
      "mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "srv1"]},
        "fs2": {"command": "npx", "args": ["-y", "srv2"]}
      }
    }
    """
    r = client.post("/api/mcp/servers/import", json={"text": text})
    assert r.status_code == 200
    data = r.json()
    assert set(data["added"]) == {"fs", "fs2"}
    assert data["updated"] == []
    assert data["failed"] == []


def test_import_batch_overwrites_existing(client):
    """部分已存在 → update。"""
    client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "old"})
    text = """
    {
      "mcpServers": {
        "fs": {"command": "npx", "args": ["new"]},
        "fs2": {"command": "npx", "args": ["new2"]}
      }
    }
    """
    r = client.post("/api/mcp/servers/import", json={"text": text})
    assert r.status_code == 200
    data = r.json()
    assert set(data["added"]) == {"fs2"}
    assert set(data["updated"]) == {"fs"}
    assert data["failed"] == []
    # 验证 fs 被覆盖
    cfg = client.get("/api/mcp/servers/fs").json()
    assert cfg["command"] == "npx"
    assert cfg["args"] == ["new"]


def test_import_batch_partial_failure(client):
    """部分 add_server 失败不影响其他(解析阶段失败整体 422,运行阶段失败进 failed)。"""
    text = """
    {
      "servers": [
        {"name": "ok", "transport": "stdio", "command": "npx"},
        {"name": "bad", "transport": "sse"}
      ]
    }
    """
    r = client.post("/api/mcp/servers/import", json={"text": text})
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data["added"]
    assert "bad" in [f["name"] for f in data["failed"]]


def test_import_batch_parse_error(client):
    """JSON 语法错整体 → 422。"""
    r = client.post("/api/mcp/servers/import", json={"text": "not json"})
    assert r.status_code == 422


def test_import_batch_unknown_format(client):
    r = client.post("/api/mcp/servers/import", json={"text": '{"foo": "bar"}'})
    assert r.status_code == 422


def test_import_batch_empty_text(client):
    r = client.post("/api/mcp/servers/import", json={"text": ""})
    assert r.status_code == 422
