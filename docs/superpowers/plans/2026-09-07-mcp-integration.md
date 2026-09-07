# TaiSang MCP 接入实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 TaiSang agent 加上 MCP 客户端能力：通过 UI 配置任意 MCP server（stdio/SSE），连接后自动拉取 Tools/Resources/Prompts，动态注入 agent 工具列表。

**Architecture:** MCPManager 管理配置和连接生命周期，MCPClient 封装单个 server 的连接/能力拉取/工具调用。MCPTool 注册到 ToolRegistry，名称 `mcp__<server>__<tool>`。Resources/Prompts 通过伪工具 `mcp_resource` / `mcp_prompt` 暴露。前端 McpManage 页做完整 CRUD + 状态管理。

**Tech Stack:** Python 3.12 + FastAPI + `mcp` SDK / Vue 3.5 + Vite + TDesign / pytest (TDD)

---

## 范围

### v1 包含
- 传输: stdio + SSE
- 能力: Tools + Resources + Prompts 全支持
- ToolRegistry 动态注册 MCP 工具
- Resources/Prompts 通过伪工具暴露
- Web UI: McpManage 页（增删查改 + 启用/禁用 + 重连 + 状态显示）
- 配置持久化: `~/.taisang/mcp_servers.json`

### v1 不做
- OAuth 认证
- WebSocket / HTTP Streamable 传输
- MCP server 发现/市场

---

## 文件结构

### 新建
- `src/taisang/mcp/__init__.py` — 包导出
- `src/taisang/mcp/types.py` — 数据模型
- `src/taisang/mcp/client.py` — MCPClient 连接/能力拉取/工具调用
- `src/taisang/mcp/tool.py` — MCPTool + McpResourceTool + McpPromptTool
- `src/taisang/mcp/manager.py` — MCPManager 配置 CRUD + 连接生命周期
- `src/taisang/web/mcp_api.py` — FastAPI 路由
- `frontend/src/views/McpManage.vue` — 管理页
- `frontend/src/stores/mcp.ts` — MCP store
- `frontend/src/api/mcp.ts` — MCP API 请求
- `tests/unit/test_mcp_types.py`
- `tests/unit/test_mcp_client.py`
- `tests/unit/test_mcp_manager.py`
- `tests/unit/test_mcp_tool.py`
- `tests/unit/test_mcp_api.py`

### 修改
- `src/taisang/agent_core/tools.py` — ToolRegistry 接受 mcp_manager
- `src/taisang/agent_core/service.py` — AgentService 传 mcp_manager
- `src/taisang/agent_core/prompts.py` — SYSTEM_PROMPT 追加 MCP 能力段
- `src/taisang/web/app.py` — 挂载 mcp_api router
- `src/taisang/web/session_registry.py` — _build_session 传 mcp_manager
- `frontend/src/router/index.ts` — 加 `/mcp` 路由
- `frontend/src/components/Sidebar.vue` — MCP 管理点击跳 `/mcp`
- `pyproject.toml` — 加 `mcp` 依赖

---

## 依赖安装

```bash
pip install "mcp[cli]"
```

`mcp` SDK 提供:
- `mcp.client.stdio.StdioClientTransport`
- `mcp.client.sse.SSEClientTransport`
- `mcp.Client` (MCP 协议客户端)
- `mcp.types.Tool`, `mcp.types.Resource`, `mcp.types.Prompt` (类型定义)
- `mcp.server.Server` (测试用 mock server)

---

## Task 1: MCP 数据模型

**Files:**
- Create: `src/taisang/mcp/__init__.py`
- Create: `src/taisang/mcp/types.py`
- Test: `tests/unit/test_mcp_types.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mcp_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'taisang.mcp'`

- [ ] **Step 3: Write implementation**

```python
# src/taisang/mcp/__init__.py
"""MCP (Model Context Protocol) 客户端模块。"""

# src/taisang/mcp/types.py
"""MCP 数据模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class McpServerConfig(BaseModel):
    """单个 MCP server 配置。"""

    name: str
    transport: Literal["stdio", "sse"]
    enabled: bool = True
    # stdio
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    # sse
    url: str | None = None
    headers: dict[str, str] = {}


class McpToolInfo(BaseModel):
    """MCP server 暴露的工具信息。"""

    name: str
    description: str
    input_schema: dict = {}


class McpResourceInfo(BaseModel):
    """MCP server 暴露的资源信息。"""

    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None


class McpPromptInfo(BaseModel):
    """MCP server 暴露的 prompt 信息。"""

    name: str
    description: str = ""
    arguments: list[dict] = []


class McpServerInfo(BaseModel):
    """MCP server 运行时状态。"""

    name: str
    status: Literal["connected", "disconnected", "failed", "disabled"]
    error: str | None = None
    tools: list[McpToolInfo] = []
    resources: list[McpResourceInfo] = []
    prompts: list[McpPromptInfo] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mcp_types.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/__init__.py src/taisang/mcp/types.py tests/unit/test_mcp_types.py
git commit -m "feat(mcp): add MCP data models (McpServerConfig, McpToolInfo, McpResourceInfo, McpPromptInfo, McpServerInfo)"
```

---

## Task 2: MCPClient — 连接与能力拉取

**Files:**
- Create: `src/taisang/mcp/client.py`
- Test: `tests/unit/test_mcp_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_client.py
"""MCPClient 测试 — 用 mock 验证连接/能力拉取/工具调用逻辑。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taisang.mcp.client import MCPClient
from taisang.mcp.types import McpServerConfig, McpToolInfo


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
    mock_sdk_client.list_tools = AsyncMock(return_value=MagicMock(tools=[
        MagicMock(name="read_file", description="Read a file", inputSchema={"type": "object"}),
        MagicMock(name="write_file", description="Write a file", inputSchema={"type": "object"}),
    ]))

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
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(resources={})))
    mock_sdk_client.list_resources = AsyncMock(return_value=MagicMock(resources=[
        MagicMock(uri="file:///README.md", name="readme", description="README", mimeType="text/markdown"),
    ]))

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
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(prompts={})))
    mock_sdk_client.list_prompts = AsyncMock(return_value=MagicMock(prompts=[
        MagicMock(name="review", description="Code review", arguments=[]),
    ]))

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
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(resources={})))
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
    mock_sdk_client.initialize = AsyncMock(return_value=MagicMock(capabilities=MagicMock(prompts={})))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mcp_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'taisang.mcp.client'`

- [ ] **Step 3: Write implementation**

```python
# src/taisang/mcp/client.py
"""MCP 客户端:连接管理、能力拉取、工具调用。"""
from __future__ import annotations

import logging
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from .types import (
    McpPromptInfo,
    McpResourceInfo,
    McpServerConfig,
    McpToolInfo,
)

log = logging.getLogger(__name__)


class MCPClient:
    """单个 MCP server 的客户端封装。

    用法:
        client = MCPClient(config)
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("tool_name", {"arg": "val"})
        await client.disconnect()
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """建立连接,握手协商能力。"""
        from mcp.client.sse import sse_client

        if self.config.transport == "stdio":
            # stdio: 子进程通信
            # mcp SDK 的 stdio_client 是 context manager,需要配合 ClientSession
            # 这里用底层方式:创建 transport + session
            from mcp.client.stdio import stdio_client as stdio_transport_ctx

            self._transport_ctx = stdio_transport_ctx(
                command=self.config.command or "",
                args=self.config.args,
                env=self.config.env,
            )
            read, write = await self._transport_ctx.__aenter__()
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            self._connected = True
        elif self.config.transport == "sse":
            # SSE: HTTP 连接
            self._transport_ctx = sse_client(
                url=self.config.url or "",
                headers=self.config.headers,
            )
            read, write = await self._transport_ctx.__aenter__()
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            self._connected = True
        else:
            raise ValueError(f"Unsupported transport: {self.config.transport}")

    async def disconnect(self) -> None:
        """关闭连接。"""
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if hasattr(self, "_transport_ctx"):
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            del self._transport_ctx
        self._connected = False

    async def list_tools(self) -> list[McpToolInfo]:
        """拉取工具列表。"""
        if not self._session:
            return []
        result = await self._session.list_tools()
        return [
            McpToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {},
            )
            for t in result.tools
        ]

    async def list_resources(self) -> list[McpResourceInfo]:
        """拉取资源列表。"""
        if not self._session:
            return []
        result = await self._session.list_resources()
        return [
            McpResourceInfo(
                uri=r.uri,
                name=r.name,
                description=r.description or "",
                mime_type=r.mimeType,
            )
            for r in result.resources
        ]

    async def list_prompts(self) -> list[McpPromptInfo]:
        """拉取 prompt 列表。"""
        if not self._session:
            return []
        result = await self._session.list_prompts()
        return [
            McpPromptInfo(
                name=p.name,
                description=p.description or "",
                arguments=[
                    {"name": a.name, "description": a.description or "", "required": a.required or False}
                    for a in (p.arguments or [])
                ],
            )
            for p in result.prompts
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """调用工具,返回结果文本。"""
        if not self._session:
            raise RuntimeError("Not connected")
        result = await self._session.call_tool(name, args)
        if result.isError:
            # 提取错误文本
            error_text = self._extract_text(result.content)
            raise RuntimeError(f"MCP tool error: {error_text}")
        return self._extract_text(result.content)

    async def read_resource(self, uri: str) -> str:
        """读取资源内容。"""
        if not self._session:
            raise RuntimeError("Not connected")
        result = await self._session.read_resource(uri)
        parts: list[str] = []
        for c in result.contents:
            if hasattr(c, "text"):
                parts.append(c.text)
            elif hasattr(c, "blob"):
                parts.append(f"(binary: {len(c.blob)} bytes)")
        return "\n".join(parts)

    async def get_prompt(self, name: str, args: dict[str, Any] | None = None) -> str:
        """获取 prompt 模板内容。"""
        if not self._session:
            raise RuntimeError("Not connected")
        result = await self._session.get_prompt(name, arguments=args or {})
        parts: list[str] = []
        for msg in result.messages:
            content = msg.content
            if hasattr(content, "text"):
                parts.append(content.text)
        return "\n".join(parts)

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        """从 MCP content blocks 提取文本。"""
        parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif hasattr(block, "data"):
                parts.append(f"(binary: {len(block.data)} bytes)")
        return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mcp_client.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/client.py tests/unit/test_mcp_client.py
git commit -m "feat(mcp): add MCPClient with connect/list_tools/list_resources/list_prompts/call_tool/read_resource/get_prompt"
```

---

## Task 3: MCPTool — 动态工具注册

**Files:**
- Create: `src/taisang/mcp/tool.py`
- Test: `tests/unit/test_mcp_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_tool.py
"""MCPTool / McpResourceTool / McpPromptTool 测试。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taisang.mcp.tool import MCPTool, McpPromptTool, McpResourceTool
from taisang.mcp.types import McpPromptInfo, McpResourceInfo, McpToolInfo


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
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mcp_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'taisang.mcp.tool'`

- [ ] **Step 3: Write implementation**

```python
# src/taisang/mcp/tool.py
"""MCP 工具:注册到 ToolRegistry 的动态工具。"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..agent_core.tools import _BaseTool
from .types import McpToolInfo

if TYPE_CHECKING:
    from .manager import MCPManager


class MCPTool(_BaseTool):
    """单个 MCP 工具的封装。

    注册到 ToolRegistry,名称 mcp__<server>__<tool>。
    run() 调用 MCPManager.call_tool() 执行。
    """

    def __init__(self, server_name: str, tool_info: McpToolInfo, manager: "MCPManager") -> None:
        self._server_name = server_name
        self._tool_info = tool_info
        self._manager = manager

    @property
    def name(self) -> str:
        return f"mcp__{self._server_name}__{self._tool_info.name}"

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self._tool_info.description,
            "parameters": self._tool_info.input_schema,
        }

    def run(self, args: dict[str, Any]) -> dict:
        try:
            result = asyncio.run(
                self._manager.call_tool(self._server_name, self._tool_info.name, args)
            )
            return {"content": result, "error": None}
        except Exception as e:
            return {"content": "", "error": str(e)}


class McpResourceTool(_BaseTool):
    """读取 MCP 资源。LLM 调 mcp_resource(server, uri) 读取。"""

    name = "mcp_resource"

    def __init__(self, manager: "MCPManager") -> None:
        self._manager = manager

    def schema(self) -> dict:
        return {
            "name": "mcp_resource",
            "description": "读取 MCP server 暴露的资源。参数: server(服务器名), uri(资源URI)",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务器名"},
                    "uri": {"type": "string", "description": "资源 URI"},
                },
                "required": ["server", "uri"],
            },
        }

    def run(self, args: dict[str, Any]) -> dict:
        server = args.get("server", "")
        uri = args.get("uri", "")
        try:
            result = asyncio.run(self._manager.read_resource(server, uri))
            return {"content": result, "error": None}
        except Exception as e:
            return {"content": "", "error": str(e)}


class McpPromptTool(_BaseTool):
    """获取 MCP prompt 模板。LLM 调 mcp_prompt(server, name) 获取。"""

    name = "mcp_prompt"

    def __init__(self, manager: "MCPManager") -> None:
        self._manager = manager

    def schema(self) -> dict:
        return {
            "name": "mcp_prompt",
            "description": (
                "获取 MCP server 的 prompt 模板,内容作为 user 消息注入对话。"
                "参数: server(服务器名), name(prompt名), args(可选参数)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务器名"},
                    "name": {"type": "string", "description": "prompt 名称"},
                    "args": {"type": "object", "description": "prompt 参数(可选)"},
                },
                "required": ["server", "name"],
            },
        }

    def run(self, args: dict[str, Any]) -> dict:
        server = args.get("server", "")
        name = args.get("name", "")
        prompt_args = args.get("args")
        try:
            result = asyncio.run(self._manager.get_prompt(server, name, prompt_args))
            return {"content": result, "error": None}
        except Exception as e:
            return {"content": "", "error": str(e)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mcp_tool.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/tool.py tests/unit/test_mcp_tool.py
git commit -m "feat(mcp): add MCPTool/McpResourceTool/McpPromptTool for ToolRegistry integration"
```

---

## Task 4: MCPManager — 配置 CRUD + 连接生命周期

**Files:**
- Create: `src/taisang/mcp/manager.py`
- Test: `tests/unit/test_mcp_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_manager.py
"""MCPManager 测试。"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taisang.mcp.manager import MCPManager
from taisang.mcp.types import McpServerConfig, McpServerInfo


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mcp_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'taisang.mcp.manager'`

- [ ] **Step 3: Write implementation**

```python
# src/taisang/mcp/manager.py
"""MCP 管理器:配置 CRUD + 连接生命周期 + 能力汇总。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .client import MCPClient
from .types import (
    McpPromptInfo,
    McpResourceInfo,
    McpServerConfig,
    McpServerInfo,
    McpToolInfo,
)

log = logging.getLogger(__name__)

_STATE_FILE = Path.home() / ".taisang" / "mcp_servers.json"


class MCPManager:
    """MCP 服务器管理器。

    - 管理 server 配置(内存 + 持久化到 ~/.taisang/mcp_servers.json)
    - 维护 server 连接(dict[str, MCPClient])
    - 提供 call_tool / read_resource / get_prompt 统一接口
    - 汇总所有 server 的 tools/resources/prompts
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self._state_path = state_path or _STATE_FILE
        self._configs: dict[str, McpServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._server_info: dict[str, McpServerInfo] = {}
        self._load_state()

    def _load_state(self) -> None:
        """从磁盘加载配置。"""
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            for name, cfg in data.get("servers", {}).items():
                self._configs[name] = McpServerConfig(**cfg)
        except (json.JSONDecodeError, OSError, Exception) as e:
            log.warning("Failed to load MCP state: %s", e)

    def _save_state(self) -> None:
        """原子写配置到磁盘。"""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "servers": {name: cfg.model_dump() for name, cfg in self._configs.items()}
        }
        tmp = self._state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self._state_path)

    # ── 配置 CRUD ──────────────────────────────────────────

    def add_server(self, config: McpServerConfig) -> None:
        if config.name in self._configs:
            raise ValueError(f"MCP server '{config.name}' already exists")
        self._configs[config.name] = config
        self._save_state()

    def remove_server(self, name: str) -> None:
        if name not in self._configs:
            raise ValueError(f"MCP server '{name}' not found")
        # 断开连接
        if name in self._clients:
            client = self._clients.pop(name)
            try:
                import asyncio
                asyncio.run(client.disconnect())
            except Exception:
                pass
        del self._configs[name]
        self._server_info.pop(name, None)
        self._save_state()

    def update_server(self, name: str, config: McpServerConfig) -> None:
        if name not in self._configs:
            raise ValueError(f"MCP server '{name}' not found")
        # 断开旧连接
        if name in self._clients:
            client = self._clients.pop(name)
            try:
                import asyncio
                asyncio.run(client.disconnect())
            except Exception:
                pass
        self._configs[name] = config
        self._server_info.pop(name, None)
        self._save_state()

    def get_server(self, name: str) -> McpServerConfig | None:
        return self._configs.get(name)

    def list_servers(self) -> list[McpServerConfig]:
        return list(self._configs.values())

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self._configs:
            raise ValueError(f"MCP server '{name}' not found")
        self._configs[name].enabled = enabled
        self._save_state()
        # 禁用时断开连接
        if not enabled and name in self._clients:
            client = self._clients.pop(name)
            try:
                import asyncio
                asyncio.run(client.disconnect())
            except Exception:
                pass
            self._server_info.pop(name, None)

    # ── 连接管理 ──────────────────────────────────────────

    async def connect_server(self, name: str) -> None:
        """连接单个 server,拉取能力。"""
        cfg = self._configs.get(name)
        if not cfg:
            raise ValueError(f"MCP server '{name}' not found")
        if not cfg.enabled:
            self._server_info[name] = McpServerInfo(name=name, status="disabled")
            return

        client = MCPClient(cfg)
        try:
            await client.connect()
            self._clients[name] = client
            # 拉取能力
            tools = await client.list_tools()
            resources = await client.list_resources()
            prompts = await client.list_prompts()
            self._server_info[name] = McpServerInfo(
                name=name,
                status="connected",
                tools=tools,
                resources=resources,
                prompts=prompts,
            )
        except Exception as e:
            log.error("Failed to connect MCP server '%s': %s", name, e)
            self._server_info[name] = McpServerInfo(
                name=name,
                status="failed",
                error=str(e),
            )

    async def disconnect_server(self, name: str) -> None:
        """断开单个 server。"""
        if name in self._clients:
            client = self._clients.pop(name)
            await client.disconnect()
        self._server_info.pop(name, None)

    async def reconnect_server(self, name: str) -> None:
        """重连单个 server。"""
        await self.disconnect_server(name)
        await self.connect_server(name)

    async def connect_all(self) -> None:
        """连接所有 enabled 的 server。"""
        for name, cfg in self._configs.items():
            if cfg.enabled:
                await self.connect_server(name)

    # ── 状态查询 ──────────────────────────────────────────

    def get_server_info(self, name: str) -> McpServerInfo:
        if name in self._server_info:
            return self._server_info[name]
        if name in self._configs and not self._configs[name].enabled:
            return McpServerInfo(name=name, status="disabled")
        if name in self._configs:
            return McpServerInfo(name=name, status="disconnected")
        raise ValueError(f"MCP server '{name}' not found")

    def list_server_info(self) -> list[McpServerInfo]:
        result = []
        for name in self._configs:
            result.append(self.get_server_info(name))
        return result

    # ── 工具/资源/ prompt 操作 ─────────────────────────────

    async def call_tool(self, server_name: str, tool_name: str, args: dict[str, Any]) -> str:
        """调用 MCP 工具。"""
        if server_name not in self._clients:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return await self._clients[server_name].call_tool(tool_name, args)

    async def read_resource(self, server_name: str, uri: str) -> str:
        """读取 MCP 资源。"""
        if server_name not in self._clients:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return await self._clients[server_name].read_resource(uri)

    async def get_prompt(self, server_name: str, prompt_name: str, args: dict[str, Any] | None = None) -> str:
        """获取 MCP prompt。"""
        if server_name not in self._clients:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return await self._clients[server_name].get_prompt(prompt_name, args)

    # ── 汇总(ToolRegistry 用) ──────────────────────────────

    def get_all_mcp_tools(self) -> list[dict]:
        """返回所有 MCP 工具,格式 [{name, server, tool_info}, ...]。"""
        result = []
        for name, info in self._server_info.items():
            if info.status != "connected":
                continue
            for tool in info.tools:
                result.append({
                    "name": f"mcp__{name}__{tool.name}",
                    "server": name,
                    "tool_info": tool,
                })
        return result

    def get_all_mcp_resources(self) -> list[dict]:
        """返回所有 MCP 资源,格式 [{server, resource_info}, ...]。"""
        result = []
        for name, info in self._server_info.items():
            if info.status != "connected":
                continue
            for res in info.resources:
                result.append({"server": name, "resource": res})
        return result

    def get_all_mcp_prompts(self) -> list[dict]:
        """返回所有 MCP prompts,格式 [{server, prompt_info}, ...]。"""
        result = []
        for name, info in self._server_info.items():
            if info.status != "connected":
                continue
            for prompt in info.prompts:
                result.append({"server": name, "prompt": prompt})
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_mcp_manager.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/mcp/manager.py tests/unit/test_mcp_manager.py
git commit -m "feat(mcp): add MCPManager with config CRUD, connection lifecycle, and capability aggregation"
```

---

## Task 5: ToolRegistry 集成

**Files:**
- Modify: `src/taisang/agent_core/tools.py`
- Modify: `src/taisang/agent_core/service.py`

- [ ] **Step 1: 修改 ToolRegistry 接受 mcp_manager**

在 `ToolRegistry.__init__` 中新增 `mcp_manager` 参数:

```python
# src/taisang/agent_core/tools.py
def __init__(
    self,
    cwd: Path,
    shell=None,
    confirmer=None,
    permission: PermissionManager | None = None,
    bash_timeout: int = 30,
    observations_dir: Path | None = None,
    skills: list | None = None,
    ctx=None,
    mcp_manager=None,  # 新增
) -> None:
    # ... 原有代码不变 ...

    # MCP 工具:动态注册
    if mcp_manager:
        from .mcp_tool import MCPTool, McpResourceTool, McpPromptTool
        for mcp_tool in mcp_manager.get_all_mcp_tools():
            self._tools[mcp_tool["name"]] = MCPTool(
                server_name=mcp_tool["server"],
                tool_info=mcp_tool["tool_info"],
                manager=mcp_manager,
            )
        # 伪工具(仅当有 MCP server 时)
        self._tools["mcp_resource"] = McpResourceTool(mcp_manager)
        self._tools["mcp_prompt"] = McpPromptTool(mcp_manager)
```

- [ ] **Step 2: 修改 AgentService 传 mcp_manager**

```python
# src/taisang/agent_core/service.py
def __init__(
    self,
    llm: LLMClient | MockLLM,
    source_root: Path,
    confirmer,
    session_memory=None,
    compaction_state: ContentReplacementState | None = None,
    max_steps: int = 50,
    token_budget: int = 32_000,
    debug: bool = False,
    permission: PermissionManager | None = None,
    allow_dirs: list[Path] | None = None,
    on_append: "Callable[[dict], None] | None" = None,
    skills: list[Skill] | None = None,
    mcp_manager=None,  # 新增
) -> None:
    # ... 原有代码 ...
    # ToolRegistry 创建时传 mcp_manager
    self._registry = ToolRegistry(
        cwd=source_root,
        shell=self.shell,
        confirmer=confirmer,
        permission=self.permission,
        skills=skills,
        ctx=self.ctx,
        mcp_manager=mcp_manager,  # 新增
    )
```

注意:AgentService 需要在 `__init__` 里创建 ToolRegistry,而不是依赖外部传入。查看现有代码确认 ToolRegistry 的创建位置,在相应位置加上 `mcp_manager` 参数。

- [ ] **Step 3: 运行现有测试确保不破坏**

Run: `pytest tests/ -q`
Expected: 251 passed (原有测试不受影响)

- [ ] **Step 4: Commit**

```bash
git add src/taisang/agent_core/tools.py src/taisang/agent_core/service.py
git commit -m "feat(mcp): integrate MCP tools into ToolRegistry and AgentService"
```

---

## Task 6: SYSTEM_PROMPT 注入 MCP 能力段

**Files:**
- Modify: `src/taisang/agent_core/prompts.py`

- [ ] **Step 1: 修改 build_system_prompt 支持 MCP 段**

```python
# src/taisang/agent_core/prompts.py
MCP_SECTION_HEADER = """

## MCP 服务器
"""


def build_system_prompt(skills_section: str = "", mcp_section: str = "") -> str:
    """组装完整 system prompt:基础 + skills 段 + MCP 段。"""
    prompt = SYSTEM_PROMPT
    if skills_section:
        prompt += SKILLS_SECTION_HEADER + "\n" + skills_section + "\n"
    if mcp_section:
        prompt += MCP_SECTION_HEADER + "\n" + mcp_section + "\n"
    return prompt


def format_mcp_section(manager) -> str:
    """格式化 MCP 能力段,注入 system prompt。"""
    if not manager:
        return ""
    infos = manager.list_server_info()
    connected = [i for i in infos if i.status == "connected"]
    if not connected:
        return ""

    lines: list[str] = []
    all_tools = manager.get_all_mcp_tools()
    if all_tools:
        lines.append("### 可用 MCP 工具")
        for t in all_tools:
            tool = t["tool_info"]
            lines.append(f"- {t['name']}: {tool.description}")
        lines.append("")

    all_resources = manager.get_all_mcp_resources()
    if all_resources:
        lines.append("### 可用 MCP 资源")
        for r in all_resources:
            res = r["resource"]
            lines.append(f"- {r['server']}: {res.uri} - {res.name}")
        lines.append("")

    all_prompts = manager.get_all_mcp_prompts()
    if all_prompts:
        lines.append("### 可用 MCP 提示")
        for p in all_prompts:
            prompt = p["prompt"]
            lines.append(f"- {p['server']}: {prompt.name} - {prompt.description}")
        lines.append("")

    lines.append("调 MCP 工具: 直接用 mcp__<server>__<tool> 工具名")
    lines.append("读 MCP 资源: 调 mcp_resource(server, uri)")
    lines.append("用 MCP 提示: 调 mcp_prompt(server, name)")
    return "\n".join(lines)
```

- [ ] **Step 2: 修改 AgentService 调用**

在 `AgentService.__init__` 中:

```python
from ..mcp.manager import MCPManager
from .prompts import format_mcp_section

# 在 system prompt 组装处:
skills_section = format_skill_listing(self.skills)
mcp_section = format_mcp_section(mcp_manager) if mcp_manager else ""
self.ctx.append_system(build_system_prompt(skills_section, mcp_section))
```

同样修改 `AgentService.reset()` 中的 system prompt 重建。

- [ ] **Step 3: 运行测试**

Run: `pytest tests/ -q`
Expected: 251 passed

- [ ] **Step 4: Commit**

```bash
git add src/taisang/agent_core/prompts.py src/taisang/agent_core/service.py
git commit -m "feat(mcp): inject MCP capabilities into system prompt"
```

---

## Task 7: SessionRegistry 集成

**Files:**
- Modify: `src/taisang/web/session_registry.py`

- [ ] **Step 1: 修改 _build_session 传 mcp_manager**

```python
# src/taisang/web/session_registry.py
class SessionRegistry:
    def __init__(self, source_root: Path, allow_dirs: list[Path] | None = None) -> None:
        # ... 原有代码 ...
        # MCPManager:进程级单例,启动时连接所有 enabled server
        self._mcp_manager = MCPManager()
        import asyncio
        asyncio.run(self._mcp_manager.connect_all())

    def _build_session(self, session_id: str) -> _Session:
        # ... 原有代码 ...
        agent = AgentService(
            llm=llm,
            source_root=self.source_root,
            confirmer=confirmer,
            session_memory=session_mem,
            permission=permission,
            allow_dirs=[self.source_root] + self.allow_dirs,
            on_append=store.append,
            skills=skills,
            mcp_manager=self._mcp_manager,  # 新增
        )
        # ... 原有代码 ...
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/ -q`
Expected: 251 passed

- [ ] **Step 3: Commit**

```bash
git add src/taisang/web/session_registry.py
git commit -m "feat(mcp): integrate MCPManager into SessionRegistry"
```

---

## Task 8: MCP API 路由

**Files:**
- Create: `src/taisang/web/mcp_api.py`
- Test: `tests/unit/test_mcp_api.py`
- Modify: `src/taisang/web/app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_api.py
"""MCP API 路由测试。"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from taisang.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """创建测试客户端,隔离 state 文件。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    # 隔离 MCP state
    import taisang.mcp.manager as mgr_mod
    orig_state = mgr_mod._STATE_FILE
    mgr_mod._STATE_FILE = tmp_path / "mcp_servers.json"
    app = create_app(tmp_path)
    yield TestClient(app)
    mgr_mod._STATE_FILE = orig_state


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
    r = client.post("/api/mcp/servers", json={"name": "fs", "transport": "stdio", "command": "node"})
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
    r = client.put("/api/mcp/servers/fs", json={"name": "fs", "transport": "stdio", "command": "node"})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_mcp_api.py -v`
Expected: FAIL — `404` (路由不存在)

- [ ] **Step 3: Write implementation**

```python
# src/taisang/web/mcp_api.py
"""MCP 管理 API 路由。"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..mcp.manager import MCPManager
from ..mcp.types import McpServerConfig

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class ServerIn(BaseModel):
    name: str
    transport: str  # "stdio" | "sse"
    enabled: bool = True
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}


class ToggleIn(BaseModel):
    enabled: bool


# 模块级 MCPManager 实例(进程单例)
_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


@router.get("/servers")
async def list_servers() -> list[dict]:
    mgr = get_mcp_manager()
    return [s.model_dump() for s in mgr.list_servers()]


@router.get("/servers/{name}")
async def get_server(name: str) -> dict:
    mgr = get_mcp_manager()
    cfg = mgr.get_server(name)
    if not cfg:
        raise HTTPException(404, f"Server '{name}' not found")
    return cfg.model_dump()


@router.post("/servers")
async def add_server(req: ServerIn) -> dict:
    mgr = get_mcp_manager()
    try:
        config = McpServerConfig(**req.model_dump())
        mgr.add_server(config)
    except ValueError as e:
        raise HTTPException(409, str(e))
    # 自动连接
    await mgr.connect_server(config.name)
    return mgr.get_server(config.name).model_dump()


@router.put("/servers/{name}")
async def update_server(name: str, req: ServerIn) -> dict:
    mgr = get_mcp_manager()
    try:
        config = McpServerConfig(**req.model_dump())
        mgr.update_server(name, config)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # 自动重连
    await mgr.connect_server(name)
    return mgr.get_server(name).model_dump()


@router.delete("/servers/{name}")
async def delete_server(name: str) -> dict:
    mgr = get_mcp_manager()
    try:
        mgr.remove_server(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"deleted": True}


@router.post("/servers/{name}/toggle")
async def toggle_server(name: str, req: ToggleIn) -> dict:
    mgr = get_mcp_manager()
    try:
        mgr.set_enabled(name, req.enabled)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if req.enabled:
        await mgr.connect_server(name)
    return mgr.get_server(name).model_dump()


@router.post("/servers/{name}/reconnect")
async def reconnect_server(name: str) -> dict:
    mgr = get_mcp_manager()
    if not mgr.get_server(name):
        raise HTTPException(404, f"Server '{name}' not found")
    await mgr.reconnect_server(name)
    return mgr.get_server_info(name).model_dump()


@router.get("/servers/{name}/info")
async def get_server_info(name: str) -> dict:
    mgr = get_mcp_manager()
    try:
        info = mgr.get_server_info(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return info.model_dump()
```

- [ ] **Step 4: 挂载路由**

```python
# src/taisang/web/app.py
from .mcp_api import get_mcp_manager, router as mcp_router

# 在 create_app 里:
mcp_mgr = get_mcp_manager()
# 启动时连接所有 enabled server
import asyncio
asyncio.run(mcp_mgr.connect_all())
app.include_router(mcp_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_mcp_api.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add src/taisang/web/mcp_api.py src/taisang/web/app.py tests/unit/test_mcp_api.py
git commit -m "feat(mcp): add MCP management API routes (CRUD + toggle + reconnect)"
```

---

## Task 9: 前端 MCP Store + API

**Files:**
- Create: `frontend/src/api/mcp.ts`
- Create: `frontend/src/stores/mcp.ts`

- [ ] **Step 1: 创建 API 请求层**

```typescript
// frontend/src/api/mcp.ts
import { apiGet, apiPost, apiPut, apiDelete } from './request'

export interface McpServer {
  name: string
  transport: 'stdio' | 'sse'
  enabled: boolean
  command: string | null
  args: string[]
  env: Record<string, string>
  url: string | null
  headers: Record<string, string>
}

export interface McpToolInfo {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface McpResourceInfo {
  uri: string
  name: string
  description: string
  mime_type: string | null
}

export interface McpPromptInfo {
  name: string
  description: string
  arguments: Record<string, unknown>[]
}

export interface McpServerInfo {
  name: string
  status: 'connected' | 'disconnected' | 'failed' | 'disabled'
  error: string | null
  tools: McpToolInfo[]
  resources: McpResourceInfo[]
  prompts: McpPromptInfo[]
}

export function listMcpServers(): Promise<McpServer[]> {
  return apiGet<McpServer[]>('/api/mcp/servers')
}

export function addMcpServer(cfg: Partial<McpServer>): Promise<McpServer> {
  return apiPost<McpServer>('/api/mcp/servers', cfg)
}

export function updateMcpServer(name: string, cfg: Partial<McpServer>): Promise<McpServer> {
  return apiPut<McpServer>(`/api/mcp/servers/${name}`, cfg)
}

export function deleteMcpServer(name: string): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`/api/mcp/servers/${name}`)
}

export function toggleMcpServer(name: string, enabled: boolean): Promise<McpServer> {
  return apiPost<McpServer>(`/api/mcp/servers/${name}/toggle`, { enabled })
}

export function reconnectMcpServer(name: string): Promise<McpServerInfo> {
  return apiPost<McpServerInfo>(`/api/mcp/servers/${name}/reconnect`, {})
}

export function getMcpServerInfo(name: string): Promise<McpServerInfo> {
  return apiGet<McpServerInfo>(`/api/mcp/servers/${name}/info`)
}
```

- [ ] **Step 2: 创建 Pinia Store**

```typescript
// frontend/src/stores/mcp.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { McpServer, McpServerInfo } from '@/api/mcp'
import {
  listMcpServers,
  addMcpServer,
  updateMcpServer,
  deleteMcpServer,
  toggleMcpServer,
  reconnectMcpServer,
  getMcpServerInfo,
} from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServer[]>([])
  const serverInfos = ref<Record<string, McpServerInfo>>({})
  const loading = ref(false)

  async function fetchServers() {
    loading.value = true
    try {
      servers.value = await listMcpServers()
      // 拉取每个 server 的详细信息
      for (const s of servers.value) {
        try {
          serverInfos.value[s.name] = await getMcpServerInfo(s.name)
        } catch {
          // 忽略单个 server 的错误
        }
      }
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
  }
})
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/mcp.ts frontend/src/stores/mcp.ts
git commit -m "feat(mcp): add frontend MCP API layer and Pinia store"
```

---

## Task 10: 前端 McpManage 页面

**Files:**
- Create: `frontend/src/views/McpManage.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/Sidebar.vue`

- [ ] **Step 1: 创建 McpManage.vue**

参考 `SkillManage.vue` 的布局风格,创建 MCP 管理页。核心结构:

```vue
<template>
  <div class="mcp-manage">
    <div class="page-header">
      <h2 class="page-title">MCP 管理</h2>
      <t-button theme="primary" @click="showAddDialog = true">
        <template #icon><t-icon name="add" /></template>
        添加服务器
      </t-button>
    </div>

    <!-- 服务器卡片列表 -->
    <div class="server-cards">
      <t-card v-for="server in mcpStore.servers" :key="server.name" class="server-card">
        <template #title>
          <div class="card-header">
            <span class="server-name">{{ server.name }}</span>
            <t-tag :theme="statusTheme(server.name)" size="small">
              {{ statusLabel(server.name) }}
            </t-tag>
            <t-tag theme="default" size="small">
              {{ server.transport === 'stdio' ? 'stdio' : 'SSE' }}
            </t-tag>
          </div>
        </template>

        <!-- 配置摘要 -->
        <div class="config-summary">
          <template v-if="server.transport === 'stdio'">
            <code>{{ server.command }} {{ server.args.join(' ') }}</code>
          </template>
          <template v-else>
            <code>{{ server.url }}</code>
          </template>
        </div>

        <!-- 能力列表 -->
        <div class="capabilities" v-if="getInfo(server.name)">
          <t-collapse>
            <t-collapse-panel header="工具" v-if="getInfo(server.name)?.tools?.length">
              <ul>
                <li v-for="t in getInfo(server.name)?.tools" :key="t.name">
                  <code>mcp__{{ server.name }}__{{ t.name }}</code> — {{ t.description }}
                </li>
              </ul>
            </t-collapse-panel>
            <t-collapse-panel header="资源" v-if="getInfo(server.name)?.resources?.length">
              <ul>
                <li v-for="r in getInfo(server.name)?.resources" :key="r.uri">
                  <code>{{ r.uri }}</code> — {{ r.name }}
                </li>
              </ul>
            </t-collapse-panel>
            <t-collapse-panel header="提示" v-if="getInfo(server.name)?.prompts?.length">
              <ul>
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

        <!-- 操作按钮 -->
        <template #footer>
          <t-switch :value="server.enabled" @change="(v: boolean) => mcpStore.toggleServer(server.name, v)" />
          <t-button variant="text" size="small" @click="mcpStore.reconnectServer(server.name)">重连</t-button>
          <t-button variant="text" size="small" @click="startEdit(server)">编辑</t-button>
          <t-button variant="text" theme="danger" size="small" @click="confirmDelete(server.name)">删除</t-button>
        </template>
      </t-card>
    </div>

    <!-- 空状态 -->
    <div v-if="!mcpStore.servers.length" class="empty-tip">
      暂无 MCP 服务器。点右上角"添加服务器"配置。
    </div>

    <!-- 添加/编辑对话框 -->
    <t-dialog v-model:visible="showAddDialog" :header="editing ? '编辑服务器' : '添加服务器'" @confirm="onSubmit">
      <t-form ref="formRef" :data="formData" :rules="formRules">
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
          <t-form-item label="参数" name="args">
            <t-textarea v-model="formData.argsText" placeholder="每行一个参数" />
          </t-form-item>
        </template>
        <template v-else>
          <t-form-item label="URL" name="url">
            <t-input v-model="formData.url" placeholder="https://example.com/sse" />
          </t-form-item>
        </template>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
import { useMcpStore } from '@/stores/mcp'
import type { McpServer, McpServerInfo } from '@/api/mcp'

const mcpStore = useMcpStore()
const showAddDialog = ref(false)
const editing = ref(false)
const formRef = ref()

const formData = reactive({
  name: '',
  transport: 'stdio' as 'stdio' | 'sse',
  command: '',
  argsText: '',
  url: '',
})

const formRules = {
  name: [{ required: true, message: '请输入名称' }],
  command: [{ required: true, message: '请输入命令', validator: () => formData.transport !== 'stdio' || !!formData.command }],
  url: [{ required: true, message: '请输入 URL', validator: () => formData.transport !== 'sse' || !!formData.url }],
}

function getInfo(name: string): McpServerInfo | undefined {
  return mcpStore.serverInfos[name]
}

function statusTheme(name: string): string {
  const info = getInfo(name)
  if (!info) return 'default'
  const map: Record<string, string> = { connected: 'success', failed: 'danger', disabled: 'warning', disconnected: 'default' }
  return map[info.status] || 'default'
}

function statusLabel(name: string): string {
  const info = getInfo(name)
  if (!info) return '未知'
  const map: Record<string, string> = { connected: '已连接', failed: '失败', disabled: '已禁用', disconnected: '未连接' }
  return map[info.status] || info.status
}

function startEdit(server: McpServer) {
  editing.value = true
  Object.assign(formData, {
    name: server.name,
    transport: server.transport,
    command: server.command || '',
    argsText: server.args.join('\n'),
    url: server.url || '',
  })
  showAddDialog.value = true
}

function confirmDelete(name: string) {
  // 用 TDesign 的 DialogPlugin 确认
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定删除 MCP 服务器 "${name}" 吗？`,
    onConfirm: async () => {
      await mcpStore.removeServer(name)
      confirmDialog.hide()
    },
    onCancel: () => confirmDialog.hide(),
  })
}

async function onSubmit() {
  const valid = await formRef.value.validate()
  if (!valid) return

  const cfg: Partial<McpServer> = {
    name: formData.name,
    transport: formData.transport,
    command: formData.command || null,
    args: formData.argsText.split('\n').filter(Boolean),
    url: formData.url || null,
  }

  if (editing.value) {
    await mcpStore.updateServer(formData.name, cfg)
  } else {
    await mcpStore.addServer(cfg)
  }
  showAddDialog.value = false
  editing.value = false
  // 重置表单
  Object.assign(formData, { name: '', transport: 'stdio', command: '', argsText: '', url: '' })
}

onMounted(() => mcpStore.fetchServers())
</script>

<style scoped>
.mcp-manage { max-width: 900px; margin: 0 auto; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { margin: 0; }
.server-cards { display: flex; flex-direction: column; gap: 16px; }
.server-card { width: 100%; }
.card-header { display: flex; align-items: center; gap: 8px; }
.server-name { font-weight: 600; }
.config-summary { margin: 8 0; padding: 8px; background: var(--td-bg-color-secondarypage); border-radius: 4px; }
.config-summary code { font-size: 12px; word-break: break-all; }
.capabilities { margin-top: 12px; }
.error-text { color: var(--td-error-color); font-size: 12px; margin-top: 8px; }
.empty-tip { text-align: center; padding: 48px; color: var(--td-text-color-placeholder); }
</style>
```

- [ ] **Step 2: 添加路由**

```typescript
// frontend/src/router/index.ts
const McpManage = () => import('@/views/McpManage.vue')

// 在 routes 里加:
{ path: '/mcp', name: 'mcp', component: McpManage },
```

- [ ] **Step 3: 修改 Sidebar MCP 入口**

```vue
<!-- frontend/src/components/Sidebar.vue -->
<!-- 把 MCP 管理入口从无效点击改成跳转 -->
<div class="menu-item" @click="router.push('/mcp')">
  <t-icon name="server" class="menu-icon" />
  <span class="menu-title">MCP 管理</span>
</div>
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/McpManage.vue frontend/src/router/index.ts frontend/src/components/Sidebar.vue
git commit -m "feat(mcp): add McpManage page with CRUD, toggle, reconnect, and status display"
```

---

## Task 11: 依赖 + 集成测试

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 mcp 依赖**

```toml
# pyproject.toml
[project.optional-dependencies]
web = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "mcp[cli]>=1.0",  # 新增
]
```

- [ ] **Step 2: 安装依赖**

Run: `pip install "mcp[cli]"`
Expected: 安装成功

- [ ] **Step 3: 运行全量测试**

Run: `pytest tests/ -q`
Expected: 251 + 9 + 13 + 11 + 17 + 11 = 311 passed

- [ ] **Step 4: 运行 lint**

Run: `ruff check src/ tests/`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: add mcp SDK dependency"
```

---

## 实施顺序建议

Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

Task 1-4 是纯后端基础,可以连续做。Task 5-7 是集成层,依赖前 4 个 task 的产出。Task 8 是 API 路由,依赖 Task 4 的 MCPManager。Task 9-10 是前端,依赖 Task 8 的 API。Task 11 收尾。

**并行机会**:Task 9-10(前端)可以在 Task 8 完成后立即开始,不必等 Task 5-7 全做完。

**预计产出**:约 60 个新测试,覆盖数据模型、客户端、工具封装、管理器、API 路由全链路。