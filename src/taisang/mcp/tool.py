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

    def __init__(self, server_name: str, tool_info: McpToolInfo, manager: MCPManager) -> None:
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

    def __init__(self, manager: MCPManager) -> None:
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

    def __init__(self, manager: MCPManager) -> None:
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
