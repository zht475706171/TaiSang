# tests/unit/test_mcp_tool.py
"""MCPTool / McpResourceTool / McpPromptTool 测试。"""
from unittest.mock import AsyncMock, MagicMock

from taisang.mcp.tool import McpPromptTool, McpResourceTool, MCPTool
from taisang.mcp.types import McpToolInfo


def _make_manager():
    """Mock MCPManager。"""
    mgr = MagicMock()
    mgr.call_tool = AsyncMock(return_value="tool result")
    mgr.read_resource = AsyncMock(return_value="resource content")
    mgr.get_prompt = AsyncMock(return_value="prompt text")
    return mgr


def test_mcp_tool_name():
    info = McpToolInfo(name="read_file", description="Read file", input_schema={"type": "object"})
    tool = MCPTool(server_name="fs", tool_info=info, manager=_make_manager())
    assert tool.name == "mcp__fs__read_file"


def test_mcp_tool_schema():
    info = McpToolInfo(
        name="read_file",
        description="Read a file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    tool = MCPTool(server_name="fs", tool_info=info, manager=_make_manager())
    schema = tool.schema()
    assert schema["name"] == "mcp__fs__read_file"
    assert schema["description"] == "Read a file"
    assert schema["parameters"]["properties"]["path"]["type"] == "string"


def test_mcp_tool_run():
    info = McpToolInfo(name="read_file", description="Read file", input_schema={})
    mgr = _make_manager()
    tool = MCPTool(server_name="fs", tool_info=info, manager=mgr)
    result = tool.run({"path": "/test.txt"})
    assert result["content"] == "tool result"
    assert result["error"] is None
    mgr.call_tool.assert_awaited_once_with("fs", "read_file", {"path": "/test.txt"})


def test_mcp_tool_run_error():
    info = McpToolInfo(name="bad_tool", description="Bad", input_schema={})
    mgr = MagicMock()
    mgr.call_tool = AsyncMock(side_effect=RuntimeError("tool failed"))
    tool = MCPTool(server_name="srv", tool_info=info, manager=mgr)
    result = tool.run({})
    assert result["error"] is not None
    assert "tool failed" in result["error"]


def test_mcp_resource_tool_name():
    tool = McpResourceTool(_make_manager())
    assert tool.name == "mcp_resource"


def test_mcp_resource_tool_schema():
    tool = McpResourceTool(_make_manager())
    schema = tool.schema()
    assert schema["name"] == "mcp_resource"
    assert "server" in schema["parameters"]["properties"]
    assert "uri" in schema["parameters"]["properties"]


def test_mcp_resource_tool_run():
    mgr = _make_manager()
    tool = McpResourceTool(mgr)
    result = tool.run({"server": "fs", "uri": "file:///test.txt"})
    assert result["content"] == "resource content"
    mgr.read_resource.assert_awaited_once_with("fs", "file:///test.txt")


def test_mcp_prompt_tool_name():
    tool = McpPromptTool(_make_manager())
    assert tool.name == "mcp_prompt"


def test_mcp_prompt_tool_schema():
    tool = McpPromptTool(_make_manager())
    schema = tool.schema()
    assert schema["name"] == "mcp_prompt"
    assert "server" in schema["parameters"]["properties"]
    assert "name" in schema["parameters"]["properties"]


def test_mcp_prompt_tool_run():
    mgr = _make_manager()
    tool = McpPromptTool(mgr)
    result = tool.run({"server": "fs", "name": "review", "args": {"code": "def foo(): pass"}})
    assert result["content"] == "prompt text"
    mgr.get_prompt.assert_awaited_once_with("fs", "review", {"code": "def foo(): pass"})


def test_mcp_resource_tool_run_error():
    mgr = MagicMock()
    mgr.read_resource = AsyncMock(side_effect=RuntimeError("resource not found"))
    tool = McpResourceTool(mgr)
    result = tool.run({"server": "fs", "uri": "file:///nonexistent.txt"})
    assert result["error"] is not None
    assert "resource not found" in result["error"]


def test_mcp_prompt_tool_run_error():
    mgr = MagicMock()
    mgr.get_prompt = AsyncMock(side_effect=RuntimeError("prompt not found"))
    tool = McpPromptTool(mgr)
    result = tool.run({"server": "fs", "name": "nonexistent"})
    assert result["error"] is not None
    assert "prompt not found" in result["error"]
