# tests/unit/test_mcp_manager.py
"""MCPManager 测试。"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from taisang.mcp.manager import MCPManager
from taisang.mcp.types import McpServerConfig, McpToolInfo


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """隔离 state 文件到 tmp_path。"""
    state_file = tmp_path / "mcp_servers.json"
    monkeypatch.setattr("taisang.mcp.manager._STATE_FILE", state_file)
    return state_file


def test_init_creates_empty_state(tmp_state):
    mgr = MCPManager()
    assert mgr.list_servers() == []


def test_add_server(tmp_state):
    mgr = MCPManager()
    cfg = McpServerConfig(name="fs", transport="stdio", command="npx", args=["-y", "server"])
    mgr.add_server(cfg)
    servers = mgr.list_servers()
    assert len(servers) == 1
    assert servers[0].name == "fs"


def test_add_server_persists(tmp_state):
    mgr = MCPManager()
    cfg = McpServerConfig(name="fs", transport="stdio", command="npx")
    mgr.add_server(cfg)
    # 重新加载
    mgr2 = MCPManager()
    servers = mgr2.list_servers()
    assert len(servers) == 1
    assert servers[0].name == "fs"


def test_add_duplicate_server_raises(tmp_state):
    mgr = MCPManager()
    cfg = McpServerConfig(name="fs", transport="stdio", command="npx")
    mgr.add_server(cfg)
    with pytest.raises(ValueError, match="already exists"):
        mgr.add_server(cfg)


def test_remove_server(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    mgr.remove_server("fs")
    assert mgr.list_servers() == []


def test_remove_nonexistent_server_raises(tmp_state):
    mgr = MCPManager()
    with pytest.raises(ValueError, match="not found"):
        mgr.remove_server("nonexistent")


def test_update_server(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    updated = McpServerConfig(name="fs", transport="stdio", command="node", args=["server.js"])
    mgr.update_server("fs", updated)
    servers = mgr.list_servers()
    assert servers[0].command == "node"
    assert servers[0].args == ["server.js"]


def test_get_server(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    cfg = mgr.get_server("fs")
    assert cfg is not None
    assert cfg.command == "npx"


def test_get_server_nonexistent(tmp_state):
    mgr = MCPManager()
    assert mgr.get_server("nonexistent") is None


def test_set_enabled(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    mgr.set_enabled("fs", False)
    assert mgr.get_server("fs").enabled is False
    mgr.set_enabled("fs", True)
    assert mgr.get_server("fs").enabled is True


def test_list_server_info_empty(tmp_state):
    mgr = MCPManager()
    assert mgr.list_server_info() == []


def test_list_server_info_with_servers(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    infos = mgr.list_server_info()
    assert len(infos) == 1
    assert infos[0].name == "fs"
    # 未连接时状态为 disconnected
    assert infos[0].status in ("disconnected", "disabled")


def test_get_server_info(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    info = mgr.get_server_info("fs")
    assert info.name == "fs"


def test_get_all_mcp_tools_empty(tmp_state):
    mgr = MCPManager()
    assert mgr.get_all_mcp_tools() == []


def test_get_all_mcp_resources_empty(tmp_state):
    mgr = MCPManager()
    assert mgr.get_all_mcp_resources() == []


def test_get_all_mcp_prompts_empty(tmp_state):
    mgr = MCPManager()
    assert mgr.get_all_mcp_prompts() == []


def test_state_file_format(tmp_state):
    """验证持久化文件格式正确。"""
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx", args=["-y", "srv"]))
    data = json.loads(tmp_state.read_text(encoding="utf-8"))
    assert "servers" in data
    assert "fs" in data["servers"]
    assert data["servers"]["fs"]["command"] == "npx"
    assert data["servers"]["fs"]["args"] == ["-y", "srv"]


@pytest.mark.asyncio
async def test_connect_server_success(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    # Mock MCPClient to avoid real subprocess
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.list_tools = AsyncMock(
        return_value=[McpToolInfo(name="t1", description="d1", input_schema={})],
    )
    mock_client.list_resources = AsyncMock(return_value=[])
    mock_client.list_prompts = AsyncMock(return_value=[])
    with patch("taisang.mcp.manager.MCPClient", return_value=mock_client):
        await mgr.connect_server("fs")
    info = mgr.get_server_info("fs")
    assert info.status == "connected"
    assert len(info.tools) == 1


@pytest.mark.asyncio
async def test_connect_server_failure(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(side_effect=Exception("connection refused"))
    with patch("taisang.mcp.manager.MCPClient", return_value=mock_client):
        await mgr.connect_server("fs")
    info = mgr.get_server_info("fs")
    assert info.status == "failed"
    assert "connection refused" in (info.error or "")


@pytest.mark.asyncio
async def test_connect_server_disabled(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx", enabled=False))
    await mgr.connect_server("fs")
    info = mgr.get_server_info("fs")
    assert info.status == "disabled"


@pytest.mark.asyncio
async def test_disconnect_server(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.list_tools = AsyncMock(return_value=[])
    mock_client.list_resources = AsyncMock(return_value=[])
    mock_client.list_prompts = AsyncMock(return_value=[])
    mock_client.disconnect = AsyncMock()
    with patch("taisang.mcp.manager.MCPClient", return_value=mock_client):
        await mgr.connect_server("fs")
        await mgr.disconnect_server("fs")
    info = mgr.get_server_info("fs")
    assert info.status == "disconnected"
    mock_client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_tool_not_connected_raises(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    with pytest.raises(RuntimeError, match="not connected"):
        await mgr.call_tool("fs", "read_file", {})


@pytest.mark.asyncio
async def test_get_all_mcp_tools_filters_non_connected(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    mgr.add_server(McpServerConfig(name="bad", transport="stdio", command="nonexistent-cmd"))
    # fs connected with 1 tool, bad failed
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.list_tools = AsyncMock(
        return_value=[McpToolInfo(name="t1", description="d1", input_schema={})],
    )
    mock_client.list_resources = AsyncMock(return_value=[])
    mock_client.list_prompts = AsyncMock(return_value=[])
    mock_bad_client = AsyncMock()
    mock_bad_client.connect = AsyncMock(side_effect=Exception("fail"))
    with patch("taisang.mcp.manager.MCPClient", side_effect=[mock_client, mock_bad_client]):
        await mgr.connect_server("fs")
        await mgr.connect_server("bad")
    tools = mgr.get_all_mcp_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "mcp__fs__t1"


def test_update_server_name_mismatch_raises(tmp_state):
    mgr = MCPManager()
    mgr.add_server(McpServerConfig(name="fs", transport="stdio", command="npx"))
    with pytest.raises(ValueError, match="must match"):
        mgr.update_server("fs", McpServerConfig(name="other", transport="stdio", command="node"))


def test_add_server_stdio_requires_command(tmp_state):
    mgr = MCPManager()
    with pytest.raises(ValueError, match="requires 'command'"):
        mgr.add_server(McpServerConfig(name="fs", transport="stdio"))


def test_add_server_sse_requires_url(tmp_state):
    mgr = MCPManager()
    with pytest.raises(ValueError, match="requires 'url'"):
        mgr.add_server(McpServerConfig(name="srv", transport="sse"))
