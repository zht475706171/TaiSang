# MCP 三种快速添加方式 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 MCP 管理页加三种快速添加 MCP server 的方式(CLI 一行式 / 粘贴 JSON / 上传 `.mcp.json` 文件),与现有表单并列,在 Dialog 内用 Tab 切换,每种快路顶部展示使用示例。

**Architecture:** 后端新增 `mcp/importer.py` 纯解析层(纯函数,无副作用),`mcp_api.py` 加两个路由 `import-cli`(单条)和 `import`(批量),同名覆盖语义(add 或 update + connect)。前端 McpManage 添加对话框改成 4 Tab(手动填写 + CLI + 粘贴 JSON + 上传文件),每个快路 Tab 顶部只读展示示例。

**Tech Stack:** Python 3.12 + FastAPI + pydantic + pytest(TDD)/ Vue 3.5 + TDesign + Vite + vue-tsc

---

## 文件结构

### 新建
- `src/taisang/mcp/importer.py` — CLI/JSON 解析(纯函数,无副作用)
- `tests/unit/test_mcp_importer.py` — 解析层测试

### 修改
- `src/taisang/web/mcp_api.py` — 加 `import-cli` + `import` 两个路由
- `tests/unit/test_mcp_api.py` — 加两个路由的测试
- `src/taisang/web/frontend/src/api/mcp.ts` — 加 `importCliMcp` / `importBatchMcp`
- `src/taisang/web/frontend/src/stores/mcp.ts` — 加 `importCli` / `importBatch` action
- `src/taisang/web/frontend/src/views/McpManage.vue` — Dialog 改 4 Tab + 示例展示

---

## Task 1: `mcp/importer.py` — CLI 解析

**Files:**
- Create: `src/taisang/mcp/importer.py`
- Test: `tests/unit/test_mcp_importer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_importer.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_importer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'taisang.mcp.importer'`

- [ ] **Step 3: Write implementation**

```python
# src/taisang/mcp/importer.py
"""MCP 快速添加解析层。

纯函数,无副作用:把 CLI 一行 / JSON 文本 / 上传文件 解析成 McpServerConfig 列表。
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from .types import McpServerConfig

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


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

    name = rest[0]
    if not _NAME_RE.match(name):
        raise McpValidationError(f"invalid name: {name!r}")

    tail = rest[1:]

    if transport == "sse":
        if len(tail) != 1:
            raise McpParseError(f"sse transport requires exactly one url, got {len(tail)}")
        url = tail[0]
        try:
            return McpServerConfig(name=name, transport="sse", url=url)
        except ValidationError as e:
            raise McpValidationError(str(e)) from e

    # stdio
    if not tail:
        raise McpParseError("stdio transport requires a command")
    command = tail[0]
    args = tail[1:]
    try:
        return McpServerConfig(name=name, transport="stdio", command=command, args=args)
    except ValidationError as e:
        raise McpValidationError(str(e)) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_importer.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/importer.py tests/unit/test_mcp_importer.py
git commit -m "feat(mcp): add parse_cli for one-line CLI syntax"
```

---

## Task 2: `mcp/importer.py` — JSON 解析(四种格式)

**Files:**
- Modify: `src/taisang/mcp/importer.py`
- Modify: `tests/unit/test_mcp_importer.py`

- [ ] **Step 1: Append failing tests**

```python
# 追加到 tests/unit/test_mcp_importer.py 末尾

from taisang.mcp.importer import parse_json


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_importer.py -v -k "parse_json"`
Expected: FAIL — `ImportError: cannot import name 'parse_json'`

- [ ] **Step 3: Append implementation**

```python
# 追加到 src/taisang/mcp/importer.py 末尾

import json


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_importer.py -v`
Expected: 13 (CLI) + 13 (JSON) = 26 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/importer.py tests/unit/test_mcp_importer.py
git commit -m "feat(mcp): add parse_json supporting claude-code and TaiSang formats"
```

---

## Task 3: `mcp/importer.py` — 文件解析(超限保护)

**Files:**
- Modify: `src/taisang/mcp/importer.py`
- Modify: `tests/unit/test_mcp_importer.py`

- [ ] **Step 1: Append failing tests**

```python
# 追加到 tests/unit/test_mcp_importer.py 末尾

from taisang.mcp.importer import parse_mcp_json_file


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_importer.py -v -k "parse_file"`
Expected: FAIL — `ImportError: cannot import name 'parse_mcp_json_file'`

- [ ] **Step 3: Append implementation**

```python
# 追加到 src/taisang/mcp/importer.py 末尾


def parse_mcp_json_file(content: bytes, max_size: int = 1_000_000) -> list[McpServerConfig]:
    """解析上传文件 bytes → McpServerConfig 列表。

    - 超限 → McpImportError
    - 非 UTF-8 → McpParseError
    - 解析复用 parse_json
    """
    if len(content) > max_size:
        raise McpImportError(f"file too large: {len(content)} bytes (max {max_size})")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise McpParseError(f"file is not UTF-8: {e}") from e
    return parse_json(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_importer.py -v`
Expected: 26 + 6 = 32 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/importer.py tests/unit/test_mcp_importer.py
git commit -m "feat(mcp): add parse_mcp_json_file with size limit and UTF-8 validation"
```

---

## Task 4: `mcp_api.py` — `import-cli` 路由(单条,同名覆盖)

**Files:**
- Modify: `src/taisang/web/mcp_api.py`
- Modify: `tests/unit/test_mcp_api.py`

- [ ] **Step 1: Append failing tests**

```python
# 追加到 tests/unit/test_mcp_api.py 末尾


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_api.py -v -k "import_cli"`
Expected: FAIL — 404(路由不存在)

- [ ] **Step 3: Append implementation**

```python
# 追加到 src/taisang/web/mcp_api.py(在现有路由之后)

from ..mcp.importer import McpImportError, McpParseError, McpValidationError, parse_cli


class ImportCliIn(BaseModel):
    line: str


@router.post("/servers/import-cli")
async def import_cli(req: ImportCliIn) -> dict:
    """CLI 一行式导入(单条,同名覆盖)。"""
    mgr = get_mcp_manager()
    try:
        config = parse_cli(req.line)
    except (McpParseError, McpValidationError) as e:
        raise HTTPException(422, str(e)) from e

    # 同名覆盖
    if mgr.get_server(config.name) is not None:
        mgr.update_server(config.name, config)
        await mgr.reconnect_server(config.name)
    else:
        mgr.add_server(config)
        await mgr.connect_server(config.name)

    return mgr.get_server_info(config.name).model_dump()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_api.py -v -k "import_cli"`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/mcp_api.py tests/unit/test_mcp_api.py
git commit -m "feat(mcp): add POST /api/mcp/servers/import-cli route"
```

---

## Task 5: `mcp_api.py` — `import` 批量路由(JSON / 文件上传共用)

**Files:**
- Modify: `src/taisang/web/mcp_api.py`
- Modify: `tests/unit/test_mcp_api.py`

- [ ] **Step 1: Append failing tests**

```python
# 追加到 tests/unit/test_mcp_api.py 末尾


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
    """部分失败不影响其他。"""
    text = """
    {
      "servers": [
        {"name": "ok", "transport": "stdio", "command": "npx"},
        {"name": "bad", "transport": "invalid"}
      ]
    }
    """
    r = client.post("/api/mcp/servers/import", json={"text": text})
    assert r.status_code == 200
    data = r.json()
    assert set(data["added"]) == {"ok"}
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_api.py -v -k "import_batch"`
Expected: FAIL — 404(路由不存在)

- [ ] **Step 3: Append implementation**

```python
# 追加到 src/taisang/web/mcp_api.py(在 import-cli 之后)

from ..mcp.importer import parse_json


class ImportBatchIn(BaseModel):
    text: str


@router.post("/servers/import")
async def import_batch(req: ImportBatchIn) -> dict:
    """批量导入 JSON 配置(同名覆盖,部分失败不影响其他)。

    返回 {added: [...], updated: [...], failed: [{name, error}]}。
    """
    mgr = get_mcp_manager()
    try:
        configs = parse_json(req.text)
    except (McpParseError, McpValidationError) as e:
        raise HTTPException(422, str(e)) from e

    if not configs:
        raise HTTPException(422, "no server configurations found in input")

    existing = {s.name for s in mgr.list_servers()}
    added: list[str] = []
    updated: list[str] = []
    failed: list[dict] = []

    for cfg in configs:
        try:
            if mgr.get_server(cfg.name) is not None:
                mgr.update_server(cfg.name, cfg)
                await mgr.reconnect_server(cfg.name)
                updated.append(cfg.name)
            else:
                mgr.add_server(cfg)
                await mgr.connect_server(cfg.name)
                added.append(cfg.name)
        except (McpImportError, ValueError, Exception) as e:
            failed.append({"name": cfg.name, "error": str(e)})
        except (McpImportError, ValueError, Exception) as e:
            failed.append({"name": cfg.name, "error": str(e)})

    return {"added": added, "updated": updated, "failed": failed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_api.py -v -k "import_batch"`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/mcp_api.py tests/unit/test_mcp_api.py
git commit -m "feat(mcp): add POST /api/mcp/servers/import batch route"
```

---

## Task 6: 前端 API 层 — `importCliMcp` / `importBatchMcp`

**Files:**
- Modify: `src/taisang/web/frontend/src/api/mcp.ts`

- [ ] **Step 1: Append API 函数**

```typescript
// 追加到 src/taisang/web/frontend/src/api/mcp.ts 末尾

export interface ImportBatchResult {
  added: string[]
  updated: string[]
  failed: { name: string; error: string }[]
}

export function importCliMcp(line: string): Promise<McpServerInfo> {
  return apiPost<McpServerInfo>('/api/mcp/servers/import-cli', { line })
}

export function importBatchMcp(text: string): Promise<ImportBatchResult> {
  return apiPost<ImportBatchResult>('/api/mcp/servers/import', { text })
}
```

- [ ] **Step 2: type-check**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | tail -10`
Expected: 无新增错误(只看是否有我们引入的错误)

- [ ] **Step 3: Commit**

```bash
git add src/taisang/web/frontend/src/api/mcp.ts
git commit -m "feat(mcp): add importCliMcp and importBatchMcp API functions"
```

---

## Task 7: 前端 Store — `importCli` / `importBatch` action

**Files:**
- Modify: `src/taisang/web/frontend/src/stores/mcp.ts`

- [ ] **Step 1: 修改 store**

```typescript
# src/taisang/web/frontend/src/stores/mcp.ts 完整替换内容
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { McpServer, McpServerInfo, ImportBatchResult } from '@/api/mcp'
import {
  listMcpServers,
  addMcpServer,
  updateMcpServer,
  deleteMcpServer,
  toggleMcpServer,
  reconnectMcpServer,
  getMcpServerInfo,
  importCliMcp,
  importBatchMcp,
} from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServer[]>([])
  const serverInfos = ref<Record<string, McpServerInfo>>({})
  const loading = ref(false)

  async function fetchServers() {
    loading.value = true
    try {
      servers.value = await listMcpServers()
      await Promise.all(
        servers.value.map(async (s) => {
          try {
            serverInfos.value[s.name] = await getMcpServerInfo(s.name)
          } catch {
            // 忽略单个 server 的错误
          }
        }),
      )
    } finally {
      loading.value = false
    }
  }

  async function addServer(cfg: Partial<McpServer>) {
    const res = await addMcpServer(cfg)
    await fetchServers()
    return res
  }

  async function updateServer(name: string, cfg: Partial<McpServer>) {
    const res = await updateMcpServer(name, cfg)
    await fetchServers()
    return res
  }

  async function removeServer(name: string) {
    await deleteMcpServer(name)
    await fetchServers()
  }

  async function toggleServer(name: string, enabled: boolean) {
    const res = await toggleMcpServer(name, enabled)
    await fetchServers()
    return res
  }

  async function reconnectServer(name: string) {
    const res = await reconnectMcpServer(name)
    serverInfos.value[name] = res
    return res
  }

  async function importCli(line: string) {
    const res = await importCliMcp(line)
    await fetchServers()
    return res
  }

  async function importBatch(text: string): Promise<ImportBatchResult> {
    const res = await importBatchMcp(text)
    await fetchServers()
    return res
  }

  return {
    servers,
    serverInfos,
    loading,
    fetchServers,
    addServer,
    updateServer,
    removeServer,
    toggleServer,
    reconnectServer,
    importCli,
    importBatch,
  }
})
```

- [ ] **Step 2: type-check**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | tail -10`
Expected: 无新增错误

- [ ] **Step 3: Commit**

```bash
git add src/taisang/web/frontend/src/stores/mcp.ts
git commit -m "feat(mcp): add importCli and importBatch store actions"
```

---

## Task 8: `McpManage.vue` — Dialog 改 4 Tab + 示例展示

**Files:**
- Modify: `src/taisang/web/frontend/src/views/McpManage.vue`

- [ ] **Step 1: 整体替换 McpManage.vue**

```vue
<template>
  <div class="mcp-manage">
    <div class="page-header">
      <h2 class="page-title">MCP 管理</h2>
      <t-button theme="primary" aria-label="添加 MCP 服务器" @click="openAdd">
        <template #icon>
          <t-icon name="add" />
        </template>
        添加服务器
      </t-button>
    </div>

    <div v-if="mcpStore.loading" class="loading-tip">加载中…</div>

    <div v-else-if="mcpStore.servers.length === 0" class="empty-tip">
      暂无 MCP 服务器。点右上角"添加服务器"配置。
    </div>

    <div v-else class="server-cards">
      <t-card v-for="server in mcpStore.servers" :key="server.name" class="server-card">
        <template #title>
          <div class="card-header">
            <span class="server-name">{{ server.name }}</span>
            <t-tag :theme="statusTheme(server.name)" size="small">{{ statusLabel(server.name) }}</t-tag>
            <t-tag theme="default" size="small">{{ server.transport === 'stdio' ? 'stdio' : 'SSE' }}</t-tag>
            <t-tag v-if="!server.enabled" theme="warning" size="small">已禁用</t-tag>
          </div>
        </template>

        <div class="config-summary">
          <template v-if="server.transport === 'stdio'">
            <code>{{ server.command }} {{ server.args.join(' ') }}</code>
          </template>
          <template v-else>
            <code>{{ server.url }}</code>
          </template>
        </div>

        <div class="capabilities" v-if="getInfo(server.name)">
          <t-collapse>
            <t-collapse-panel
              v-if="getInfo(server.name)?.tools?.length"
              :header="`工具 (${getInfo(server.name)?.tools?.length ?? 0})`"
            >
              <ul class="cap-list">
                <li v-for="t in getInfo(server.name)?.tools" :key="t.name">
                  <code>mcp__{{ server.name }}__{{ t.name }}</code> — {{ t.description }}
                </li>
              </ul>
            </t-collapse-panel>
            <t-collapse-panel
              v-if="getInfo(server.name)?.resources?.length"
              :header="`资源 (${getInfo(server.name)?.resources?.length ?? 0})`"
            >
              <ul class="cap-list">
                <li v-for="r in getInfo(server.name)?.resources" :key="r.uri">
                  <code>{{ r.uri }}</code> — {{ r.name }}
                </li>
              </ul>
            </t-collapse-panel>
            <t-collapse-panel
              v-if="getInfo(server.name)?.prompts?.length"
              :header="`提示 (${getInfo(server.name)?.prompts?.length ?? 0})`"
            >
              <ul class="cap-list">
                <li v-for="p in getInfo(server.name)?.prompts" :key="p.name">
                  <code>{{ p.name }}</code> — {{ p.description }}
                </li>
              </ul>
            </t-collapse-panel>
          </t-collapse>
          <div v-if="getInfo(server.name)?.error" class="error-text">
            {{ getInfo(server.name)?.error }}
          </div>
        </div>

        <template #footer>
          <div class="card-footer">
            <t-switch :value="server.enabled" @change="(v: boolean) => onToggle(server.name, v)" />
            <t-button variant="text" size="small" :aria-label="`重连 ${server.name}`" @click="onReconnect(server.name)">重连</t-button>
            <t-button variant="text" size="small" :aria-label="`编辑 ${server.name}`" @click="openEdit(server)">编辑</t-button>
            <t-button variant="text" theme="danger" size="small" :aria-label="`删除 ${server.name}`" @click="confirmDelete(server.name)">
              删除
            </t-button>
          </div>
        </template>
      </t-card>
    </div>

    <t-dialog v-model:visible="showDialog" :header="editing ? '编辑服务器' : '添加服务器'" @confirm="onSubmit">
      <!-- 编辑模式:只显示手动填写 Tab -->
      <div v-if="editing" class="form-section">
        <t-form ref="formRef" :data="formData" :rules="formRules" label-width="80px">
          <t-form-item label="名称" name="name">
            <t-input v-model="formData.name" placeholder="如 filesystem" disabled />
          </t-form-item>
          <t-form-item label="传输方式" name="transport">
            <t-select v-model="formData.transport">
              <t-option value="stdio" label="stdio (本地子进程)" />
              <t-option value="sse" label="SSE (远程 HTTP)" />
            </t-select>
          </t-form-item>
          <template v-if="formData.transport === 'stdio'">
            <t-form-item label="命令" name="command">
              <t-input v-model="formData.command" placeholder="如 npx" />
            </t-form-item>
            <t-form-item label="参数" name="argsText">
              <t-textarea v-model="formData.argsText" placeholder="每行一个参数" :autosize="{ minRows: 2 }" />
            </t-form-item>
          </template>
          <template v-else>
            <t-form-item label="URL" name="url">
              <t-input v-model="formData.url" placeholder="https://example.com/sse" />
            </t-form-item>
          </template>
        </t-form>
      </div>

      <!-- 添加模式:4 Tab -->
      <div v-else>
        <t-tabs v-model="activeTab">
          <t-tab-panel value="manual" label="手动填写">
            <t-form ref="formRef" :data="formData" :rules="formRules" label-width="80px">
              <t-form-item label="名称" name="name">
                <t-input v-model="formData.name" placeholder="如 filesystem" />
              </t-form-item>
              <t-form-item label="传输方式" name="transport">
                <t-select v-model="formData.transport">
                  <t-option value="stdio" label="stdio (本地子进程)" />
                  <t-option value="sse" label="SSE (远程 HTTP)" />
                </t-select>
              </t-form-item>
              <template v-if="formData.transport === 'stdio'">
                <t-form-item label="命令" name="command">
                  <t-input v-model="formData.command" placeholder="如 npx" />
                </t-form-item>
                <t-form-item label="参数" name="argsText">
                  <t-textarea v-model="formData.argsText" placeholder="每行一个参数" :autosize="{ minRows: 2 }" />
                </t-form-item>
              </template>
              <template v-else>
                <t-form-item label="URL" name="url">
                  <t-input v-model="formData.url" placeholder="https://example.com/sse" />
                </t-form-item>
              </template>
            </t-form>
          </t-tab-panel>

          <t-tab-panel value="cli" label="CLI 一行">
            <div class="example-block">
              <div class="example-title">示例</div>
              <pre class="example-code"><code># stdio(本地子进程)
filesystem npx -y @modelcontextprotocol/server-filesystem /tmp

# sse(远程 HTTP)
search --transport sse https://example.com/sse</code></pre>
            </div>
            <t-textarea
              v-model="cliInput"
              placeholder="filesystem npx -y @modelcontextprotocol/server-filesystem /tmp"
              :autosize="{ minRows: 2 }"
            />
          </t-tab-panel>

          <t-tab-panel value="json" label="粘贴 JSON">
            <div class="example-block">
              <div class="example-title">示例</div>
              <pre class="example-code"><code>// claude-code 格式
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}

// TaiSang 扩展(可含 SSE)
{
  "servers": [
    {"name": "search", "transport": "sse", "url": "https://example.com/sse"}
  ]
}</code></pre>
            </div>
            <t-textarea
              v-model="jsonInput"
              placeholder='{"mcpServers": {...}}'
              :autosize="{ minRows: 6 }"
            />
          </t-tab-panel>

          <t-tab-panel value="file" label="上传文件">
            <div class="example-block">
              <div class="example-title">示例 .mcp.json</div>
              <pre class="example-code"><code>{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}</code></pre>
            </div>
            <input
              ref="fileInputRef"
              type="file"
              accept=".json,.mcp.json"
              class="file-input"
              @change="onFileSelect"
            />
            <div v-if="fileName" class="file-name">已选:{{ fileName }}</div>
          </t-tab-panel>
        </t-tabs>
      </div>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive, computed } from 'vue'
import { MessagePlugin, DialogPlugin, type FormInstanceFunctions } from 'tdesign-vue-next'
import { useMcpStore } from '@/stores/mcp'
import type { McpServer, McpServerInfo } from '@/api/mcp'

type TagTheme = 'default' | 'success' | 'danger' | 'warning'

const mcpStore = useMcpStore()
const showDialog = ref(false)
const editing = ref(false)
const formRef = ref<FormInstanceFunctions>()
const activeTab = ref<'manual' | 'cli' | 'json' | 'file'>('manual')
const cliInput = ref('')
const jsonInput = ref('')
const fileContent = ref('')
const fileName = ref('')
const fileInputRef = ref<HTMLInputElement>()

const formData = reactive({
  name: '',
  transport: 'stdio' as 'stdio' | 'sse',
  command: '',
  argsText: '',
  url: '',
})

const formRules = computed(() => ({
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  command: formData.transport === 'stdio'
    ? [{ required: true, message: '请输入命令', trigger: 'blur' }]
    : [],
  url: formData.transport === 'sse'
    ? [{ required: true, message: '请输入 URL', trigger: 'blur' }]
    : [],
}))

function getInfo(name: string): McpServerInfo | undefined {
  return mcpStore.serverInfos[name]
}

function statusTheme(name: string): TagTheme {
  const info = getInfo(name)
  if (!info) return 'default'
  const map: Record<string, TagTheme> = {
    connected: 'success',
    failed: 'danger',
    disabled: 'warning',
    disconnected: 'default',
  }
  return map[info.status] ?? 'default'
}

function statusLabel(name: string): string {
  const info = getInfo(name)
  if (!info) return '未知'
  const map: Record<string, string> = {
    connected: '已连接',
    failed: '失败',
    disabled: '已禁用',
    disconnected: '未连接',
  }
  return map[info.status] || info.status
}

function openAdd() {
  editing.value = false
  activeTab.value = 'manual'
  Object.assign(formData, { name: '', transport: 'stdio', command: '', argsText: '', url: '' })
  cliInput.value = ''
  jsonInput.value = ''
  fileContent.value = ''
  fileName.value = ''
  showDialog.value = true
}

function openEdit(server: McpServer) {
  editing.value = true
  Object.assign(formData, {
    name: server.name,
    transport: server.transport,
    command: server.command || '',
    argsText: server.args.join('\n'),
    url: server.url || '',
  })
  showDialog.value = true
}

async function onSubmit() {
  if (editing.value) {
    await submitManual()
    return
  }

  // 添加模式:根据 activeTab 分发
  if (activeTab.value === 'manual') {
    await submitManual()
  } else if (activeTab.value === 'cli') {
    await submitCli()
  } else if (activeTab.value === 'json') {
    await submitJson(jsonInput.value)
  } else if (activeTab.value === 'file') {
    await submitJson(fileContent.value)
  }
}

async function submitManual() {
  const valid = await formRef.value?.validate?.()
  if (valid !== true) return

  const cfg: Partial<McpServer> = {
    name: formData.name,
    transport: formData.transport,
    command: formData.transport === 'stdio' ? formData.command : null,
    args:
      formData.transport === 'stdio'
        ? formData.argsText.split('\n').map((s) => s.trim()).filter(Boolean)
        : [],
    url: formData.transport === 'sse' ? formData.url : null,
  }

  try {
    if (editing.value) {
      await mcpStore.updateServer(formData.name, cfg)
      MessagePlugin.success('已更新')
    } else {
      await mcpStore.addServer(cfg)
      MessagePlugin.success('已添加')
    }
    showDialog.value = false
  } catch (e) {
    MessagePlugin.error(`保存失败: ${e}`)
  }
}

async function submitCli() {
  if (!cliInput.value.trim()) {
    MessagePlugin.warning('请输入 CLI 命令')
    return
  }
  try {
    await mcpStore.importCli(cliInput.value.trim())
    MessagePlugin.success('已添加')
    showDialog.value = false
  } catch (e) {
    MessagePlugin.error(`添加失败: ${e}`)
  }
}

async function submitJson(text: string) {
  if (!text.trim()) {
    MessagePlugin.warning('请提供 JSON 配置')
    return
  }
  try {
    const result = await mcpStore.importBatch(text)
    const parts: string[] = []
    if (result.added.length) parts.push(`新增 ${result.added.length}`)
    if (result.updated.length) parts.push(`更新 ${result.updated.length}`)
    if (result.failed.length) parts.push(`失败 ${result.failed.length}`)
    MessagePlugin.success(`导入完成:${parts.join('、')}`)
    if (result.failed.length) {
      console.warn('Import failures:', result.failed)
    }
    showDialog.value = false
  } catch (e) {
    MessagePlugin.error(`导入失败: ${e}`)
  }
}

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > 1_000_000) {
    MessagePlugin.error('文件超过 1MB 上限')
    input.value = ''
    return
  }
  fileName.value = file.name
  const reader = new FileReader()
  reader.onload = () => {
    fileContent.value = String(reader.result || '')
  }
  reader.onerror = () => {
    MessagePlugin.error('读取文件失败')
  }
  reader.readAsText(file)
}

async function onToggle(name: string, enabled: boolean) {
  try {
    await mcpStore.toggleServer(name, enabled)
  } catch (e) {
    MessagePlugin.error(`切换失败: ${e}`)
  }
}

async function onReconnect(name: string) {
  try {
    await mcpStore.reconnectServer(name)
    MessagePlugin.success(`已重连 ${name}`)
  } catch (e) {
    MessagePlugin.error(`重连失败: ${e}`)
  }
}

function confirmDelete(name: string) {
  const dialog = DialogPlugin.confirm({
    header: '删除 MCP 服务器',
    body: `确定删除 "${name}"?该操作不可恢复。`,
    confirmBtn: '删除',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      try {
        await mcpStore.removeServer(name)
        MessagePlugin.success('已删除')
      } catch (e) {
        MessagePlugin.error(`删除失败: ${e}`)
      }
    },
  })
}

onMounted(() => mcpStore.fetchServers())
</script>

<style scoped>
.mcp-manage {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 960px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.loading-tip,
.empty-tip {
  padding: 32px 16px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
  text-align: center;
}
.server-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.server-card {
  width: 100%;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.server-name {
  font-weight: 600;
}
.config-summary {
  margin: 8px 0;
  padding: 8px 12px;
  background: var(--td-bg-color-component);
  border-radius: 4px;
}
.config-summary code {
  font-size: 12px;
  word-break: break-all;
}
.capabilities {
  margin-top: 12px;
}
.cap-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
}
.cap-list code {
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
.error-text {
  color: var(--td-error-color);
  font-size: 12px;
  margin-top: 8px;
}
.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
.example-block {
  margin-bottom: 12px;
}
.example-title {
  font-size: 12px;
  color: var(--td-text-color-secondary);
  margin-bottom: 4px;
}
.example-code {
  margin: 0;
  padding: 10px 12px;
  background: var(--td-bg-color-component);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--td-text-color-primary);
  font-family: 'SFMono-Regular', Consolas, monospace;
  white-space: pre;
  overflow-x: auto;
  max-height: 200px;
}
.file-input {
  font-size: 13px;
}
.file-name {
  margin-top: 8px;
  font-size: 12px;
  color: var(--td-text-color-secondary);
}
</style>
```

- [ ] **Step 2: type-check**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: 无新增错误

- [ ] **Step 3: 前端构建**

Run: `cd src/taisang/web/frontend && npm run build 2>&1 | tail -20`
Expected: 构建成功

- [ ] **Step 4: 复制构建产物到 static**

Run: `cp -r src/taisang/web/frontend/dist/* src/taisang/web/static/ 2>&1`
Expected: 复制成功(检查 `src/taisang/web/static/assets/` 有新 `McpManage-*.js`)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/frontend/src/views/McpManage.vue src/taisang/web/static/
git commit -m "feat(mcp): 4-tab add dialog with CLI/JSON/file quick-add + examples"
```

---

## Task 9: 全量回归 + 收尾

**Files:** 无(纯验证)

- [ ] **Step 1: 全量 pytest**

Run: `python -m pytest tests/ -q 2>&1 | tail -10`
Expected: 全绿(基线 324 + 新增约 25 = ~349 passed)

- [ ] **Step 2: ruff lint(看新增代码是否有 lint 问题)**

Run: `python -m ruff check src/taisang/mcp/importer.py src/taisang/web/mcp_api.py tests/unit/test_mcp_importer.py tests/unit/test_mcp_api.py 2>&1`
Expected: 无新增错误(基线错误不管)

- [ ] **Step 3: black 格式检查**

Run: `python -m black --check src/taisang/mcp/importer.py src/taisang/web/mcp_api.py tests/unit/test_mcp_importer.py tests/unit/test_mcp_api.py 2>&1`
Expected: 无需修改

- [ ] **Step 4: push**

Run: `git push 2>&1`
Expected: 推送成功

- [ ] **Step 5: 更新 memory 日志**

追加到 `memory/2026-09-04.md` 末尾一段"第十二轮:MCP 三种快速添加方式",记录:
- 决策:CLI 单条 / JSON 批量 / 上传文件 / 同名覆盖
- 实现:importer.py 三函数(parse_cli/parse_json/parse_mcp_json_file)+ 两个 API 路由 + 前端 4 Tab Dialog + 示例展示
- 测试数 + commit 列表
- 踩坑(如果有)

```bash
git add memory/2026-09-04.md
git commit -m "docs(memory): 补记第十二轮 MCP 快速添加方式"
git push
```

---

## 实施顺序

Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

- Task 1-3:纯后端解析层,TDD,可连续做
- Task 4-5:API 路由,依赖 Task 1-3 的解析层
- Task 6-7:前端 API + store,依赖 Task 4-5 的路由
- Task 8:前端 UI,依赖 Task 6-7
- Task 9:回归 + 收尾

每个 Task 独立 commit,可单独 review。

## 预计产出

- `mcp/importer.py` ~120 行(纯函数)
- `mcp_api.py` 增量 ~40 行(两个路由 + 两 BaseModel)
- 前端 `api/mcp.ts` 增量 ~15 行
- 前端 `stores/mcp.ts` 增量 ~20 行
- 前端 `McpManage.vue` 重写(从单表单变 4 Tab)
- 测试:CLI 13 + JSON 13 + 文件 6 + API 12 = ~44 个新测试