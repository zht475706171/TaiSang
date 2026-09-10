# src/taisang/mcp/manager.py
"""MCP 管理器:配置 CRUD + 连接生命周期 + 能力汇总。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .client import MCPClient
from .types import (
    McpServerConfig,
    McpServerInfo,
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
        except (json.JSONDecodeError, OSError, ValidationError) as e:
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
        if config.transport == "stdio" and not config.command:
            raise ValueError("stdio transport requires 'command'")
        if config.transport == "sse" and not config.url:
            raise ValueError("sse transport requires 'url'")
        self._configs[config.name] = config
        self._save_state()

    def remove_server(self, name: str) -> None:
        """从配置中移除 server。

        注意:此方法仅修改配置并持久化,不会断开已有连接。
        如需断开连接,请先调用 async `disconnect_server(name)`。
        """
        if name not in self._configs:
            raise ValueError(f"MCP server '{name}' not found")
        del self._configs[name]
        self._server_info.pop(name, None)
        self._save_state()

    def update_server(self, name: str, config: McpServerConfig) -> None:
        """更新 server 配置。

        注意:此方法仅修改配置并持久化,不会断开已有连接。
        如需断开连接,请先调用 async `disconnect_server(name)`。
        """
        if name not in self._configs:
            raise ValueError(f"MCP server '{name}' not found")
        if config.name != name:
            raise ValueError(f"Config name '{config.name}' must match key '{name}'")
        self._configs[name] = config
        self._server_info.pop(name, None)
        self._save_state()

    def get_server(self, name: str) -> McpServerConfig | None:
        return self._configs.get(name)

    def list_servers(self) -> list[McpServerConfig]:
        return list(self._configs.values())

    def set_enabled(self, name: str, enabled: bool) -> None:
        """启用/禁用 server。

        注意:此方法仅修改配置并持久化,不会断开已有连接。
        如需断开连接,请先调用 async `disconnect_server(name)`。
        """
        if name not in self._configs:
            raise ValueError(f"MCP server '{name}' not found")
        self._configs[name].enabled = enabled
        self._save_state()

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
        except BaseExceptionGroup as eg:
            # mcp SDK 1.x + anyio:stdio 子进程启动失败/连接异常时抛 BaseExceptionGroup
            # (包 RuntimeError/GeneratorExit/CancelledError 等),`except Exception` 抓不到。
            # 拆出第一层真实错误信息记 failed 状态,不往上抛(保持 add_server 路由 200 行为)。
            msg = "; ".join(str(e) for e in eg.exceptions) or str(eg)
            log.error("Failed to connect MCP server '%s': %s", name, msg)
            self._server_info[name] = McpServerInfo(
                name=name,
                status="failed",
                error=msg,
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

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        args: dict[str, Any] | None = None,
    ) -> str:
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
