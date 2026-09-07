# src/taisang/web/mcp_api.py
"""MCP 管理 API 路由。"""
from __future__ import annotations

import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from ..mcp.importer import McpImportError, McpParseError, McpValidationError, parse_cli, parse_json
from ..mcp.manager import MCPManager
from ..mcp.types import McpServerConfig

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class ServerIn(BaseModel):
    name: str
    transport: Literal["stdio", "sse"]  # API 层就拒非法 transport → 422
    enabled: bool = True
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}


class ToggleIn(BaseModel):
    enabled: bool


# 模块级 MCPManager 实例(进程单例)。
# SessionRegistry 也通过 get_mcp_manager() 拿这个实例,
# 保证 API 改的 manager 跟 agent 用的 manager 是同一个。
_manager: MCPManager | None = None
_manager_lock = threading.Lock()


def get_mcp_manager() -> MCPManager:
    """返回进程级 MCPManager 单例(双重检查锁,线程安全)。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:  # double-check
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
    except ValidationError as e:
        # McpServerConfig 自身校验失败(理论上 ServerIn 已挡一层,这里兜底)
        raise HTTPException(422, str(e)) from e
    except ValueError as e:
        # 重复名 / 缺 command / 缺 url
        raise HTTPException(409, str(e)) from e
    # 自动连接(忽略失败 — connect_server 内部已记 failed 状态)
    await mgr.connect_server(config.name)
    # 返回 server info(含 status)而非纯配置,这样 UI 能看到连接是否成功。
    return mgr.get_server_info(config.name).model_dump()


@router.put("/servers/{name}")
async def update_server(name: str, req: ServerIn) -> dict:
    mgr = get_mcp_manager()
    try:
        config = McpServerConfig(**req.model_dump())
        mgr.update_server(name, config)
    except ValidationError as e:
        raise HTTPException(422, str(e)) from e
    except ValueError as e:
        # not found / name 不匹配
        raise HTTPException(404, str(e)) from e
    # 自动重连
    await mgr.reconnect_server(name)
    # 返回 server info(含 status)而非纯配置,这样 UI 能看到连接是否成功。
    return mgr.get_server_info(name).model_dump()


@router.delete("/servers/{name}")
async def delete_server(name: str) -> dict:
    mgr = get_mcp_manager()
    cfg = mgr.get_server(name)
    if not cfg:
        raise HTTPException(404, f"Server '{name}' not found")
    # 先断开(异步),再删配置
    await mgr.disconnect_server(name)
    mgr.remove_server(name)
    return {"deleted": True}


@router.post("/servers/{name}/toggle")
async def toggle_server(name: str, req: ToggleIn) -> dict:
    mgr = get_mcp_manager()
    cfg = mgr.get_server(name)
    if not cfg:
        raise HTTPException(404, f"Server '{name}' not found")
    mgr.set_enabled(name, req.enabled)
    if req.enabled:
        await mgr.connect_server(name)
    else:
        # 关键:禁用时必须真正断开,否则 _server_info 仍是 connected,
        # get_all_mcp_tools 还会向 agent 暴露该 server 的工具(禁用沦为表象)。
        await mgr.disconnect_server(name)
    # McpServerInfo 没有 enabled 字段,而 test_toggle_server 断言响应里有 enabled。
    # 因此合并:config 提供 enabled(以及完整配置),info 覆盖 status/error/能力。
    # info 优先级高,这样 UI 既能看到 enabled 又能看到连接状态。
    return {**mgr.get_server(name).model_dump(), **mgr.get_server_info(name).model_dump()}


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
        raise HTTPException(404, str(e)) from e
    return info.model_dump()


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

    return {"added": added, "updated": updated, "failed": failed}
