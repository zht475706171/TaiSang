"""MCP 快速添加解析层测试。"""
import pytest

from taisang.mcp.importer import (
    McpImportError,
    McpParseError,
    McpValidationError,
    parse_cli,
)


def test_parse_cli_stdio_basic():
    cfg = parse_cli("filesystem npx -y @modelcontextprotocol/server-filesystem /tmp")
    assert cfg.name == "filesystem"
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_parse_cli_stdio_single_arg():
    cfg = parse_cli("echo echo hello")
    assert cfg.name == "echo"
    assert cfg.command == "echo"
    assert cfg.args == ["hello"]


def test_parse_cli_sse():
    cfg = parse_cli("search --transport sse https://example.com/sse")
    assert cfg.name == "search"
    assert cfg.transport == "sse"
    assert cfg.url == "https://example.com/sse"
    assert cfg.command is None
    assert cfg.args == []


def test_parse_cli_sse_explicit_transport():
    """显式 --transport stdio 也认。"""
    cfg = parse_cli("fs --transport stdio npx -y server")
    assert cfg.name == "fs"
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "server"]


def test_parse_cli_empty_line():
    with pytest.raises(McpParseError, match="empty"):
        parse_cli("   ")


def test_parse_cli_missing_name():
    """只有 flag 没有 name。"""
    with pytest.raises(McpParseError, match="name"):
        parse_cli("--transport sse https://example.com/sse")


def test_parse_cli_invalid_transport():
    with pytest.raises(McpParseError, match="transport"):
        parse_cli("foo --transport bar baz")


def test_parse_cli_sse_extra_tokens():
    """sse 后面只能一个 url,多个 token 报错。"""
    with pytest.raises(McpParseError, match="url"):
        parse_cli("search --transport sse https://a.com/sse extra")


def test_parse_cli_sse_missing_url():
    with pytest.raises(McpParseError, match="url"):
        parse_cli("search --transport sse")


def test_parse_cli_stdio_missing_command():
    """stdio 只有 name 没有命令。"""
    with pytest.raises(McpParseError, match="command"):
        parse_cli("fs")


def test_parse_cli_invalid_name_chars():
    """name 含非法字符。"""
    with pytest.raises(McpValidationError, match="name"):
        parse_cli("foo/bar npx")


def test_parse_cli_name_starts_with_dash():
    with pytest.raises(McpValidationError, match="name"):
        parse_cli("-bad npx")


def test_parse_cli_transport_in_middle():
    """--transport 可以出现在任意位置(被识别并移除)。"""
    cfg = parse_cli("fs npx --transport stdio -y server")
    assert cfg.name == "fs"
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "server"]