"""Skill 管理 API 路由:list / toggle / reload。

v1 简化:
- 每次 list 都重扫磁盘(loader 是纯函数,无缓存)
- toggle 持久化到 ~/.taisang/skills_state.json(进程外也可见)
- reload 是 no-op(loader 无缓存,下次 list 重读);返回 {ok: true}
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from fastapi import File, HTTPException, UploadFile

from ..config import load_skills_config
from ..skills.importer import (
    SkillExistsError,
    SkillImportError,
    import_skill_md,
    import_skill_zip,
)
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


def _import_root() -> Path:
    """导入目标目录:user_dirs 第一个(默认 ~/.taisang/skills)。"""
    cfg = load_skills_config()
    root = cfg.user_dirs[0] if cfg.user_dirs else Path.home() / ".taisang" / "skills"
    return root


def _deletable_roots(source_root: Path) -> set[Path]:
    """允许删除的 skill 目录的父目录集合(user/project 源)。"""
    cfg = load_skills_config()
    roots = list(cfg.user_dirs) + list(cfg.project_dirs) + [source_root / ".taisang" / "skills"]
    return {r.resolve() for r in roots}


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

    @app.post("/api/skills/import")
    async def import_skill(file: UploadFile = File(...), overwrite: bool = False) -> dict:
        """导入 skill:.md 单文件或 zip(目录形式)。

        同名已存在 → 409;前端确认后带 ?overwrite=true 重试覆盖。
        """
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(400, "文件超过 10MB 上限")
        filename = (file.filename or "").lower()
        root = _import_root()
        try:
            if filename.endswith((".md", ".markdown")):
                name, _target = import_skill_md(
                    data.decode("utf-8", errors="replace"), root, overwrite
                )
            elif filename.endswith(".zip"):
                name, _target = import_skill_zip(data, root, overwrite)
            else:
                raise HTTPException(400, "只支持 .md 或 .zip 文件")
        except SkillExistsError as e:
            raise HTTPException(409, str(e)) from e
        except SkillImportError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "name": name}

    @app.delete("/api/skills/{name}")
    async def delete_skill(name: str) -> dict:
        """删除 skill。内置(system)不可删;连带清掉 disabled 状态记录。"""
        skills = load_skills_with_state(source_root)
        skill = next((s for s in skills if s.name == name), None)
        if skill is None:
            raise HTTPException(404, "skill not found")
        if skill.source == "system":
            raise HTTPException(400, "内置 skill 不能删除")
        if skill.dir_path.parent.resolve() not in _deletable_roots(source_root):
            raise HTTPException(400, "skill 目录不在可管理范围内,拒绝删除")
        shutil.rmtree(skill.dir_path)
        state = _load_disabled_state()
        if name in state:
            del state[name]
            _save_disabled_state(state)
        return {"ok": True, "deleted": name}