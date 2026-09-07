"""MCP 快速添加解析层。

纯函数,无副作用:把 CLI 一行 / JSON 文本 / 上传文件 解析成 McpServerConfig 列表。
"""
from __future__ import annotations

import re

from pydantic import ValidationError

from .types import McpServerConfig

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_URL_RE = re.compile(r"^https?://")


class McpImportError(Exception):
    """导入解析基类。"""


class McpParseError(McpImportError):
    """语法层错误(name 缺失、transport 非法、token 数不对)。"""


class McpValidationError(McpImportError):
    """字段层错误(name 字符集、URL 形态、pydantic 校验失败)。"""


def parse_cli(line: str) -> McpServerConfig:
    """解析单行 CLI 语法 → 一个 McpServerConfig。

    语法:
        stdio:  `<name> <command> [args...]`
        sse:    `<name> --transport sse <url>`
        也可显式 `--transport stdio`。

    规则:
        - 首个非 flag token = name
        - `--transport <value>` 只接受 stdio/sse
        - 未指定 transport 默认 stdio
        - stdio: 剩余 token 第一个是 command,其余是 args
        - sse: 剩余 token 恰好一个是 url
    """
    tokens = line.split()
    if not tokens:
        raise McpParseError("empty CLI line")

    # 提取 --transport flag
    transport = "stdio"  # 默认
    rest: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--transport":
            if i + 1 >= len(tokens):
                raise McpParseError("--transport requires a value (stdio or sse)")
            transport = tokens[i + 1]
            if transport not in ("stdio", "sse"):
                raise McpParseError(f"invalid transport: {transport}")
            i += 2
            continue
        rest.append(tok)
        i += 1

    if not rest:
        raise McpParseError("missing name")

    if transport == "sse":
        # sse 语法: <name> --transport sse <url>。
        # 只剩 1 个 token 时无法区分 name/url,按 token 形态判:
        #   - 像 url(http(s)://) → 用户漏了 name
        #   - 否则 → 用户漏了 url(name 已给)
        if len(rest) == 1 and _looks_like_url(rest[0]):
            raise McpParseError("missing name")
        name = rest[0]
        if not _NAME_RE.match(name):
            raise McpValidationError(f"invalid name: {name!r}")
        tail = rest[1:]
        if len(tail) != 1:
            raise McpParseError(f"sse transport requires exactly one url, got {len(tail)}")
        url = tail[0]
        try:
            return McpServerConfig(name=name, transport="sse", url=url)
        except ValidationError as e:
            raise McpValidationError(str(e)) from e

    # stdio
    name = rest[0]
    if not _NAME_RE.match(name):
        raise McpValidationError(f"invalid name: {name!r}")
    tail = rest[1:]
    if not tail:
        raise McpParseError("stdio transport requires a command")
    command = tail[0]
    args = tail[1:]
    try:
        return McpServerConfig(name=name, transport="stdio", command=command, args=args)
    except ValidationError as e:
        raise McpValidationError(str(e)) from e


def _looks_like_url(token: str) -> bool:
    """粗判 token 是否为 url(用于 sse 模式下区分 name 缺失 vs url 缺失)。"""
    return bool(_URL_RE.match(token))


import json
from typing import Any


def parse_json(text: str) -> list[McpServerConfig]:
    """解析 JSON 文本 → McpServerConfig 列表。

    支持四种顶层格式:
        1. claude-code 格式:  {"mcpServers": {name: {command, args, env}}}
           (没 transport,有 url 自动判 sse,否则 stdio)
        2. TaiSang 单对象:    {"name": "...", "transport": "...", ...}
        3. TaiSang 数组:      {"servers": [McpServerConfig, ...]}
        4. TaiSang 裸数组:    [McpServerConfig, ...]
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise McpParseError(f"invalid JSON: {e}") from e

    return _parse_json_data(data)


def _parse_json_data(data: Any) -> list[McpServerConfig]:
    # 1. claude-code 格式
    if isinstance(data, dict) and "mcpServers" in data:
        servers = data["mcpServers"]
        if not isinstance(servers, dict):
            raise McpParseError(f"mcpServers must be an object, got {type(servers).__name__}")
        return [_claude_code_entry_to_config(name, val) for name, val in servers.items()]

    # 2. TaiSang 单对象
    if isinstance(data, dict) and "name" in data:
        return [_taisang_entry_to_config(data)]

    # 3. TaiSang {servers: [...]}
    if isinstance(data, dict) and "servers" in data:
        servers = data["servers"]
        if not isinstance(servers, list):
            raise McpParseError(f"servers must be an array, got {type(servers).__name__}")
        return [_taisang_entry_to_config(e) for e in servers]

    # 4. 裸数组
    if isinstance(data, list):
        return [_taisang_entry_to_config(e) for e in data]

    # 其他
    raise McpParseError("unknown JSON format: expected mcpServers/servers/name/array")


def _claude_code_entry_to_config(name: str, entry: Any) -> McpServerConfig:
    """claude-code 格式单个 entry → McpServerConfig。

    entry 里没 transport,靠 url 字段推断。其余字段透传。
    """
    if not isinstance(entry, dict):
        raise McpParseError(f"mcpServers.{name} must be an object, got {type(entry).__name__}")
    if not _NAME_RE.match(name):
        raise McpValidationError(f"invalid name: {name!r}")

    data = dict(entry)
    data["name"] = name
    if "transport" not in data:
        data["transport"] = "sse" if "url" in data else "stdio"

    if data["transport"] == "stdio" and not data.get("command"):
        raise McpValidationError("stdio transport requires a command")

    try:
        return McpServerConfig(**data)
    except ValidationError as e:
        raise McpValidationError(str(e)) from e


def _taisang_entry_to_config(entry: Any) -> McpServerConfig:
    """TaiSang 扩展格式单 entry → McpServerConfig。"""
    if not isinstance(entry, dict):
        raise McpParseError(f"server entry must be an object, got {type(entry).__name__}")
    try:
        return McpServerConfig(**entry)
    except ValidationError as e:
        raise McpValidationError(str(e)) from e