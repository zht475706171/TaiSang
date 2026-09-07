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
