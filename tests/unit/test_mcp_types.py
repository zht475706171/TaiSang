# tests/unit/test_mcp_types.py
"""MCP 数据模型测试。"""
from pathlib import Path
from taisang.mcp.types import (
    McpServerConfig,
    McpToolInfo,
    McpResourceInfo,
    McpPromptInfo,
    McpServerInfo,
)


def test_mcp_server_config_stdio():
    cfg = McpServerConfig(
        name="filesystem",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    )
    assert cfg.name == "filesystem"
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.url is None
    assert cfg.enabled is True


def test_mcp_server_config_sse():
    cfg = McpServerConfig(
        name="search",
        transport="sse",
        url="https://api.example.com/sse",
    )
    assert cfg.transport == "sse"
    assert cfg.url == "https://api.example.com/sse"
    assert cfg.command is None


def test_mcp_server_config_default_enabled():
    cfg = McpServerConfig(name="test", transport="stdio", command="echo")
    assert cfg.enabled is True


def test_mcp_tool_info():
    info = McpToolInfo(name="read_file", description="Read a file", input_schema={"type": "object"})
    assert info.name == "read_file"
    assert info.description == "Read a file"
    assert info.input_schema["type"] == "object"


def test_mcp_resource_info():
    info = McpResourceInfo(uri="file:///README.md", name="readme", description="README", mime_type="text/markdown")
    assert info.uri == "file:///README.md"
    assert info.mime_type == "text/markdown"


def test_mcp_prompt_info():
    info = McpPromptInfo(name="review", description="Code review", arguments=[])
    assert info.name == "review"
    assert info.arguments == []


def test_mcp_server_info_connected():
    info = McpServerInfo(
        name="test",
        status="connected",
        tools=[McpToolInfo(name="t1", description="d1", input_schema={})],
        resources=[McpResourceInfo(uri="u1", name="r1", description="d1", mime_type=None)],
        prompts=[McpPromptInfo(name="p1", description="d1", arguments=[])],
    )
    assert info.status == "connected"
    assert len(info.tools) == 1
    assert len(info.resources) == 1
    assert len(info.prompts) == 1


def test_mcp_server_info_failed():
    info = McpServerInfo(name="bad", status="failed", error="connection refused")
    assert info.status == "failed"
    assert info.error == "connection refused"


def test_mcp_server_config_serialization():
    cfg = McpServerConfig(
        name="fs",
        transport="stdio",
        command="npx",
        args=["-y", "server"],
    )
    data = cfg.model_dump()
    assert data["name"] == "fs"
    assert data["command"] == "npx"
    assert data["args"] == ["-y", "server"]

    # round-trip
    cfg2 = McpServerConfig(**data)
    assert cfg2.name == cfg.name
    assert cfg2.command == cfg.command
