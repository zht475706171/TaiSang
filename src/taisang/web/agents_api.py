# src/taisang/web/agents_api.py
"""Agent 管理 API 路由:list / toggle / reload。

跟 skills_api 对称:v1 不做 import / delete,只读 + 开关 + 重载。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from ..agents.loader import _load_disabled_state, _save_disabled_state, load_agents_with_state


def register_agents_routes(app, source_root: Path) -> None:
    """把 agents 路由挂到 app,闭包绑定 source_root。"""

    @app.get("/api/agents")
    async def list_agents() -> dict:
        """列出所有 agent(agent_type/when_to_use/source/tools/disabled/background)。"""
        agents = load_agents_with_state(source_root)
        return {"agents": [
            {
                "agent_type": a.agent_type,
                "when_to_use": a.when_to_use,
                "source": a.source,
                "tools": a.tools,
                "disallowed_tools": a.disallowed_tools,
                "disabled": a.disabled,
                "background": a.background,
                "max_turns": a.max_turns,
            }
            for a in agents
        ]}

    @app.post("/api/agents/reload")
    async def reload_agents() -> dict:
        """no-op:loader 无缓存,下次 list 重读磁盘。"""
        return {"ok": True}

    @app.post("/api/agents/{name}/toggle")
    async def toggle_agent(name: str) -> dict:
        """切换 agent 的 disabled 状态,持久化到 agents_state.json。"""
        agents = load_agents_with_state(source_root)
        if not any(a.agent_type == name for a in agents):
            raise HTTPException(404, "agent not found")
        state = _load_disabled_state()
        state[name] = not state.get(name, False)
        _save_disabled_state(state)
        return {"ok": True, "disabled": state[name]}