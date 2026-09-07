# src/taisang/mcp/client.py
"""MCP 客户端:连接管理、能力拉取、工具调用。"""
from __future__ import annotations

import logging
from typing import Any

from mcp import ClientSession

from .types import (
    McpPromptInfo,
    McpResourceInfo,
    McpServerConfig,
    McpToolInfo,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transport wrappers — expose SDK context managers as classes so that
# `patch("taisang.mcp.client.StdioClientTransport")` works in tests.
# ---------------------------------------------------------------------------

try:
    from mcp.client.stdio import stdio_client as _stdio_client  # noqa: F401
except ImportError:  # pragma: no cover
    _stdio_client = None  # type: ignore[assignment]

try:
    from mcp.client.sse import sse_client as _sse_client  # noqa: F401
except ImportError:  # pragma: no cover
    _sse_client = None  # type: ignore[assignment]


class StdioClientTransport:
    """Stdio transport — wraps mcp.client.stdio.stdio_client.

    In production this is instantiated with command/args/env, and used as
    an async context manager to obtain (read, write) streams:

        async with StdioClientTransport(cmd, args, env) as (read, write):
            ...

    In tests this class is mocked, so its internals are never executed.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ):
        self.command = command
        self.args = args or []
        self.env = env or {}

    async def __aenter__(self) -> Any:
        from mcp.client.stdio import stdio_client
        self._ctx = stdio_client(command=self.command, args=self.args, env=self.env)
        return await self._ctx.__aenter__()

    async def __aexit__(self, *exc: Any) -> None:
        await self._ctx.__aexit__(*exc)


class SSEClientTransport:
    """SSE transport — wraps mcp.client.sse.sse_client.

    In production this is instantiated with url/headers, and used as an
    async context manager to obtain (read, write) streams:

        async with SSEClientTransport(url, headers) as (read, write):
            ...

    In tests this class is mocked, so its internals are never executed.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self.url = url
        self.headers = headers or {}

    async def __aenter__(self) -> Any:
        from mcp.client.sse import sse_client
        self._ctx = sse_client(url=self.url, headers=self.headers)
        return await self._ctx.__aenter__()

    async def __aexit__(self, *exc: Any) -> None:
        await self._ctx.__aexit__(*exc)


# ---------------------------------------------------------------------------
# Client — wraps ClientSession to accept a transport object.
#
# Tests mock `taisang.mcp.client.Client` so the wrapper logic below is
# never executed in test runs.  In production the wrapper opens the
# transport, creates a real ClientSession, and delegates all calls.
# ---------------------------------------------------------------------------

class Client:
    """Wraps ClientSession to accept a transport object.

    Usage:
        client = Client(transport)
        await client.connect()        # opens transport + creates session
        await client.initialize()     # MCP handshake
        tools = await client.list_tools()
        await client.close()          # clean up
    """

    def __init__(self, transport: Any) -> None:
        self._transport = transport
        self._session: ClientSession | None = None
        self._transport_ctx: Any = None

    async def connect(self) -> None:
        """Open transport streams and create ClientSession."""
        read, write = await self._transport.__aenter__()
        self._transport_ctx = self._transport
        self._session = ClientSession(read, write)
        await self._session.__aenter__()

    async def initialize(self) -> None:
        """Perform MCP handshake."""
        if self._session is None:
            raise RuntimeError("Not connected")
        await self._session.initialize()

    async def close(self) -> None:
        """Close session and transport."""
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport_ctx = None

    async def list_tools(self) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected")
        return await self._session.list_tools()

    async def list_resources(self) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected")
        return await self._session.list_resources()

    async def list_prompts(self) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected")
        return await self._session.list_prompts()

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected")
        return await self._session.call_tool(name, args)

    async def read_resource(self, uri: str) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected")
        return await self._session.read_resource(uri)

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self._session is None:
            raise RuntimeError("Not connected")
        return await self._session.get_prompt(name, arguments=arguments or {})


# ---------------------------------------------------------------------------
# MCPClient
# ---------------------------------------------------------------------------

class MCPClient:
    """单个 MCP server 的客户端封装。

    用法:
        client = MCPClient(config)
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("tool_name", {"arg": "val"})
        await client.disconnect()
    """

    _SUPPORTED_TRANSPORTS = ("stdio", "sse")

    def __init__(self, config: McpServerConfig) -> None:
        if config.transport not in self._SUPPORTED_TRANSPORTS:
            raise ValueError(f"Unsupported transport: {config.transport}")
        self.config = config
        self._session: Client | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """建立连接,握手协商能力。

        1. 创建 transport 实例(stdio 或 sse)
        2. 用 transport 创建 Client 会话
        3. 调用 connect() 打开 transport 流
        4. 调用 initialize() 完成 MCP 握手
        """
        if self.config.transport == "stdio":
            transport = StdioClientTransport(
                command=self.config.command or "",
                args=self.config.args,
                env=self.config.env,
            )
        elif self.config.transport == "sse":
            transport = SSEClientTransport(
                url=self.config.url or "",
                headers=self.config.headers,
            )
        else:
            # Should not happen — __init__ already validates
            raise ValueError(f"Unsupported transport: {self.config.transport}")

        self._session = Client(transport)
        await self._session.connect()
        await self._session.initialize()
        self._connected = True

    async def disconnect(self) -> None:
        """关闭连接。"""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
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
                    {
                        "name": a.name,
                        "description": a.description or "",
                        "required": a.required or False,
                    }
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
        result = await self._session.get_prompt(name, args)
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
