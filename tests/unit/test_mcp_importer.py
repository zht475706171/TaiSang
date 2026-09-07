"""MCP 快速添加解析层测试。"""

import pytest

from taisang.mcp.importer import (
    McpImportError,
    McpParseError,
    McpValidationError,
    parse_cli,
    parse_json,
    parse_mcp_json_file,
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


def test_parse_cli_transport_no_value():
    """--transport flag 缺值 → McpParseError。"""
    with pytest.raises(McpParseError, match="requires a value"):
        parse_cli("foo --transport")


# ── JSON 四种格式 ──────────────────────────────────────


def test_parse_json_claude_code_format_stdio():
    text = """
    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
      }
    }
    """
    configs = parse_json(text)
    assert len(configs) == 1
    assert configs[0].name == "filesystem"
    assert configs[0].transport == "stdio"
    assert configs[0].command == "npx"
    assert configs[0].args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_parse_json_claude_code_format_auto_sse():
    """claude-code 格式里没有 transport,有 url 自动判 sse。"""
    text = """
    {
      "mcpServers": {
        "search": {
          "url": "https://example.com/sse"
        }
      }
    }
    """
    configs = parse_json(text)
    assert len(configs) == 1
    assert configs[0].name == "search"
    assert configs[0].transport == "sse"
    assert configs[0].url == "https://example.com/sse"


def test_parse_json_claude_code_format_multiple():
    text = """
    {
      "mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "srv"]},
        "search": {"url": "https://example.com/sse"}
      }
    }
    """
    configs = parse_json(text)
    assert len(configs) == 2
    names = {c.name for c in configs}
    assert names == {"fs", "search"}


def test_parse_json_claude_code_format_with_env():
    text = """
    {
      "mcpServers": {
        "fs": {"command": "npx", "args": ["srv"], "env": {"NODE_ENV": "production"}}
      }
    }
    """
    configs = parse_json(text)
    assert configs[0].env == {"NODE_ENV": "production"}


def test_parse_json_taisang_single_object():
    text = """
    {
      "name": "search",
      "transport": "sse",
      "url": "https://example.com/sse"
    }
    """
    configs = parse_json(text)
    assert len(configs) == 1
    assert configs[0].name == "search"
    assert configs[0].transport == "sse"


def test_parse_json_taisang_servers_key():
    text = """
    {
      "servers": [
        {"name": "fs", "transport": "stdio", "command": "npx"},
        {"name": "search", "transport": "sse", "url": "https://example.com/sse"}
      ]
    }
    """
    configs = parse_json(text)
    assert len(configs) == 2
    assert configs[0].name == "fs"
    assert configs[1].name == "search"


def test_parse_json_taisang_bare_array():
    text = """
    [
      {"name": "fs", "transport": "stdio", "command": "npx"}
    ]
    """
    configs = parse_json(text)
    assert len(configs) == 1
    assert configs[0].name == "fs"


def test_parse_json_invalid_json():
    with pytest.raises(McpParseError, match="invalid JSON"):
        parse_json("not json at all")


def test_parse_json_unknown_format():
    """顶层 dict 但没 mcpServers/servers/name。"""
    with pytest.raises(McpParseError, match="unknown JSON format"):
        parse_json('{"foo": "bar"}')


def test_parse_json_empty_mcp_servers():
    text = '{"mcpServers": {}}'
    configs = parse_json(text)
    assert configs == []


def test_parse_json_mcp_servers_value_not_object():
    with pytest.raises(McpParseError, match="mcpServers"):
        parse_json('{"mcpServers": []}')


def test_parse_json_claude_code_entry_missing_command():
    """claude-code 格式里 stdio 但没 command → McpValidationError。"""
    text = '{"mcpServers": {"fs": {"args": ["foo"]}}}'
    with pytest.raises(McpValidationError, match="command"):
        parse_json(text)


def test_parse_json_taisang_entry_missing_name():
    text = '{"servers": [{"transport": "stdio", "command": "npx"}]}'
    with pytest.raises(McpValidationError, match="name"):
        parse_json(text)


def test_parse_json_name_wins_over_servers():
    """顶层同时有 name 和 servers,优先按单对象解析(name 分支先于 servers 分支)。"""
    text = '{"name": "single", "transport": "stdio", "command": "npx", "servers": []}'
    configs = parse_json(text)
    assert len(configs) == 1
    assert configs[0].name == "single"


def test_parse_json_claude_code_entry_not_object():
    """mcpServers.<name> 值不是 object → McpParseError。"""
    text = '{"mcpServers": {"fs": "not an object"}}'
    with pytest.raises(McpParseError, match="mcpServers.fs"):
        parse_json(text)


def test_parse_json_taisang_entry_missing_command():
    """TaiSang 格式 stdio 但缺 command → McpValidationError(parse-time)。"""
    text = '{"servers": [{"name": "fs", "transport": "stdio"}]}'
    with pytest.raises(McpValidationError, match="command"):
        parse_json(text)


# ── 文件解析(超限保护) ──────────────────────────────────


def test_parse_file_basic():
    content = b'{"mcpServers": {"fs": {"command": "npx", "args": ["srv"]}}}'
    configs = parse_mcp_json_file(content)
    assert len(configs) == 1
    assert configs[0].name == "fs"


def test_parse_file_taisang_format():
    content = b'{"servers": [{"name": "fs", "transport": "stdio", "command": "npx"}]}'
    configs = parse_mcp_json_file(content)
    assert len(configs) == 1
    assert configs[0].name == "fs"


def test_parse_file_too_large():
    """超限报 McpImportError。"""
    big = b"x" * (1_000_000 + 1)
    with pytest.raises(McpImportError, match="too large"):
        parse_mcp_json_file(big)


def test_parse_file_non_utf8():
    """非 UTF-8 报 McpParseError。"""
    with pytest.raises(McpParseError):
        parse_mcp_json_file(b"\xff\xfe not utf8")


def test_parse_file_invalid_json():
    with pytest.raises(McpParseError, match="invalid JSON"):
        parse_mcp_json_file(b"not json")


def test_parse_file_custom_max_size():
    """可自定义上限。"""
    content = b'{"mcpServers": {"fs": {"command": "npx"}}}'
    # 默认上限通过
    parse_mcp_json_file(content)
    # 设个极小上限触发拒绝
    with pytest.raises(McpImportError, match="too large"):
        parse_mcp_json_file(content, max_size=10)
