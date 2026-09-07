# tests/unit/test_mcp_client.py
"""MCPClient 测试 — 用 mock 验证连接/能力拉取/工具调用逻辑。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taisang.mcp.client import MCPClient
from taisang.mcp.types import McpServerConfig


def _make_stdio_config(name="test"):
    return McpServerConfig(
        name=name,
        transport="stdio",
        command="echo",
        args=[],
    )


def _make_sse_config(name="test"):
    return McpServerConfig(
        name=name,
        transport="sse",
        url="https://example.com/sse",
    )


def test_client_init_stdio():
    cfg = _make_stdio_config("fs")
    client = MCPClient(cfg)
    assert client.config == cfg
    assert client.is_connected is False


def test_client_init_sse():
    cfg = _make_sse_config("search")
    client = MCPClient(cfg)
    assert client.config.transport == "sse"
    assert client.is_connected is False


def test_client_init_invalid_transport():
    cfg = McpServerConfig(name="bad", transport="stdio", command="echo")
    # 手动改 transport 为非法值
    cfg.transport = "invalid"  # type: ignore
    with pytest.raises(ValueError, match="Unsupported transport"):
        MCPClient(cfg)


@pytest.mark.asyncio
async def test_connect_stdio_success():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock()))

    with patch("taisang.mcp.client.Client", return_value=mock_client), \
         patch("taisang.mcp.client.StdioClientTransport") as mock_transport_cls:
        mock_transport = MagicMock()
        mock_transport_cls.return_value = mock_transport
        await client.connect()

    assert client.is_connected is True
    mock_client.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_sse_success():
    cfg = _make_sse_config()
    client = MCPClient(cfg)

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock()))

    with patch("taisang.mcp.client.Client", return_value=mock_client), \
         patch("taisang.mcp.client.SSEClientTransport") as mock_transport_cls:
        mock_transport = MagicMock()
        mock_transport_cls.return_value = mock_transport
        await client.connect()

    assert client.is_connected is True


@pytest.mark.asyncio
async def test_connect_failure():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(side_effect=Exception("connection refused"))

    with patch("taisang.mcp.client.Client", return_value=mock_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        with pytest.raises(Exception, match="connection refused"):
            await client.connect()

    assert client.is_connected is False


@pytest.mark.asyncio
async def test_list_tools():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(tools={})))
    tool1 = MagicMock()
    tool1.name = "read_file"
    tool1.description = "Read a file"
    tool1.inputSchema = {"type": "object"}
    tool2 = MagicMock()
    tool2.name = "write_file"
    tool2.description = "Write a file"
    tool2.inputSchema = {"type": "object"}
    mock_sdk_client.list_tools = AsyncMock(return_value=MagicMock(tools=[tool1, tool2]))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        tools = await client.list_tools()

    assert len(tools) == 2
    assert tools[0].name == "read_file"
    assert tools[1].name == "write_file"


@pytest.mark.asyncio
async def test_list_resources():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(
        return_value=MagicMock(capabilities=MagicMock(resources={})),
    )
    res1 = MagicMock()
    res1.uri = "file:///README.md"
    res1.name = "readme"
    res1.description = "README"
    res1.mimeType = "text/markdown"
    mock_sdk_client.list_resources = AsyncMock(return_value=MagicMock(resources=[res1]))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        resources = await client.list_resources()

    assert len(resources) == 1
    assert resources[0].uri == "file:///README.md"
    assert resources[0].mime_type == "text/markdown"


@pytest.mark.asyncio
async def test_list_prompts():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(
        return_value=MagicMock(capabilities=MagicMock(prompts={})),
    )
    prompt1 = MagicMock()
    prompt1.name = "review"
    prompt1.description = "Code review"
    prompt1.arguments = []
    mock_sdk_client.list_prompts = AsyncMock(return_value=MagicMock(prompts=[prompt1]))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        prompts = await client.list_prompts()

    assert len(prompts) == 1
    assert prompts[0].name == "review"


@pytest.mark.asyncio
async def test_call_tool():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(tools={})))
    mock_sdk_client.call_tool = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="text", text="file content")],
        isError=False,
    ))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        result = await client.call_tool("read_file", {"path": "/test.txt"})

    assert result == "file content"


@pytest.mark.asyncio
async def test_call_tool_error():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(tools={})))
    mock_sdk_client.call_tool = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="text", text="file not found")],
        isError=True,
    ))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        with pytest.raises(RuntimeError, match="MCP tool error"):
            await client.call_tool("read_file", {"path": "/nonexistent.txt"})


@pytest.mark.asyncio
async def test_read_resource():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(
        return_value=MagicMock(capabilities=MagicMock(resources={})),
    )
    mock_sdk_client.read_resource = AsyncMock(return_value=MagicMock(contents=[
        MagicMock(text="resource content"),
    ]))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        result = await client.read_resource("file:///test.txt")

    assert result == "resource content"


@pytest.mark.asyncio
async def test_get_prompt():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(
        return_value=MagicMock(capabilities=MagicMock(prompts={})),
    )
    mock_sdk_client.get_prompt = AsyncMock(return_value=MagicMock(
        messages=[MagicMock(content=MagicMock(text="Review this code: {code}"))],
    ))

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        result = await client.get_prompt("review", {"code": "def foo(): pass"})

    assert "Review this code" in result


@pytest.mark.asyncio
async def test_disconnect():
    cfg = _make_stdio_config()
    client = MCPClient(cfg)

    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock()))
    mock_sdk_client.close = AsyncMock()

    with patch("taisang.mcp.client.Client", return_value=mock_sdk_client), \
         patch("taisang.mcp.client.StdioClientTransport"):
        await client.connect()
        assert client.is_connected is True
        await client.disconnect()

    assert client.is_connected is False
    mock_sdk_client.close.assert_awaited_once()
