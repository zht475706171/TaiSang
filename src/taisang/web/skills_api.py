"""Skill 管理 API 路由:list / toggle / reload。

v1 简化:
- 每次 list 都重扫磁盘(loader 是纯函数,无缓存)
- toggle 持久化到 ~/.taisang/skills_state.json(进程外也可见)
- reload 是 no-op(loader 无缓存,下次 list 重读);返回 {ok: true}
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import HTTPException

from ..config import load_skills_config
from ..skills.loader import load_skills
from ..skills.types import Skill

_STATE_FILE = Path.home() / ".taisang" / "skills_state.json"


def _load_disabled_state() -> dict[str, bool]:
    """读 ~/.taisang/skills_state.json,记录被禁用的 skill name。"""
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_disabled_state(state: dict[str, bool]) -> None:
    """原子写 skills_state.json。"""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, _STATE_FILE)


def load_skills_with_state(source_root: Path) -> list[Skill]:
    """加载所有 skill(user + project),应用 skills_state.json 的 disabled 状态。

    本模块的 list/toggle 路由和 session_registry._build_session 共用,
    保证 UI 上的开关和新会话里的 agent 看到同一份状态。
    """
    cfg = load_skills_config()
    project_dirs = list(cfg.project_dirs) + [source_root / ".taisang" / "skills"]
    skills = load_skills(user_dirs=cfg.user_dirs, project_dirs=project_dirs)
    disabled = _load_disabled_state()
    for s in skills:
        s.disabled = disabled.get(s.name, False)
    return skills


def register_skills_routes(app, source_root: Path) -> None:
    """把 skills 路由挂到 app,闭包绑定 source_root。"""

    @app.get("/api/skills")
    async def list_skills() -> dict:
        """列出所有 skill(name/description/when_to_use/source/allowed_tools/disabled)。"""
        skills = load_skills_with_state(source_root)
        return {"skills": [
            {
                "name": s.name,
                "description": s.description,
                "when_to_use": s.when_to_use,
                "source": s.source,
                "allowed_tools": s.allowed_tools,
                "disabled": s.disabled,
            }
            for s in skills
        ]}

    @app.post("/api/skills/reload")
    async def reload_skills() -> dict:
        """no-op:loader 无缓存,下次 list 重读磁盘。"""
        return {"ok": True}

    @app.post("/api/skills/{name}/toggle")
    async def toggle_skill(name: str) -> dict:
        """切换 skill 的 disabled 状态,持久化到 skills_state.json。"""
        skills = load_skills_with_state(source_root)
        if not any(s.name == name for s in skills):
            raise HTTPException(404, "skill not found")
        state = _load_disabled_state()
        state[name] = not state.get(name, False)
        _save_disabled_state(state)
        return {"ok": True, "disabled": state[name]}