"""Command 管理 API 路由:list / toggle / reload / import / delete。

对齐 skills_api 的模式。v1 简化:
- 每次 list 都重扫磁盘(loader 纯函数无缓存)
- toggle 持久化到 ~/.taisang/commands_state.json(进程外也可见)
- reload 是 no-op(loader 无缓存)
- import 只支持 .md 单文件(command 是平铺文件,不像 skill 是目录)
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import File, HTTPException, UploadFile

from ..commands.loader import _parse_command_md, load_commands
from ..commands.state import (
    clear_disabled,
    load_disabled_state,
    save_disabled_state,
    set_disabled,
)
from ..commands.types import Command
from ..config import load_skills_config  # command 复用 skills 的目录配置(user_dirs/project_dirs)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _command_dirs(source_root: Path) -> tuple[list[Path], list[Path]]:
    """返回 (user_dirs, project_dirs) for commands。

    复用 skills 配置:user_dirs 同 skills,project_dirs 加 source_root/.taisang/commands。
    """
    cfg = load_skills_config()
    user_dirs = list(cfg.user_dirs)
    # command 用独立的 .taisang/commands 目录(不和 skills 混)
    user_command_dirs = [Path(d).parent / "commands" for d in user_dirs] if user_dirs else [
        Path.home() / ".taisang" / "commands"
    ]
    project_dirs = list(cfg.project_dirs) + [source_root / ".taisang" / "commands"]
    return user_command_dirs, project_dirs


def load_commands_with_state(source_root: Path) -> list[Command]:
    """加载所有 command(user + project + system),应用 disabled 状态。

    session_registry._build_session 和 list/toggle 路由共用,保证 UI 和 agent 同一份。
    """
    user_dirs, project_dirs = _command_dirs(source_root)
    commands = load_commands(user_dirs=user_dirs, project_dirs=project_dirs)
    disabled = load_disabled_state()
    for c in commands:
        c.disabled = disabled.get(c.name, False)
    return commands


def _import_root() -> Path:
    """导入目标目录:user_dirs 第一个(默认 ~/.taisang/commands)。"""
    user_dirs, _ = _command_dirs(Path("/dummy"))
    return user_dirs[0]


def _deletable_roots(source_root: Path) -> set[Path]:
    """允许删除的 command .md 文件的父目录集合(user/project 源)。"""
    user_dirs, project_dirs = _command_dirs(source_root)
    return {r.resolve() for r in user_dirs + project_dirs}


def register_commands_routes(app, source_root: Path) -> None:
    """把 commands 路由挂到 app,闭包绑定 source_root。"""

    @app.get("/api/commands")
    async def list_commands() -> dict:
        """列出所有 command(name/description/argument_hint/source/allowed_tools/disabled)。"""
        commands = load_commands_with_state(source_root)
        return {"commands": [
            {
                "name": c.name,
                "description": c.description,
                "argument_hint": c.argument_hint,
                "source": c.source,
                "allowed_tools": c.allowed_tools,
                "disabled": c.disabled,
            }
            for c in commands
        ]}

    @app.post("/api/commands/reload")
    async def reload_commands() -> dict:
        """no-op:loader 无缓存,下次 list 重读磁盘。"""
        return {"ok": True}

    @app.post("/api/commands/{name}/toggle")
    async def toggle_command(name: str) -> dict:
        """切换 command 的 disabled 状态,持久化。"""
        commands = load_commands_with_state(source_root)
        if not any(c.name == name for c in commands):
            raise HTTPException(404, "command not found")
        state = load_disabled_state()
        new_val = not state.get(name, False)
        set_disabled(name, new_val)
        return {"ok": True, "disabled": new_val}

    @app.post("/api/commands/import")
    async def import_command(file: UploadFile = File(...), overwrite: bool = False) -> dict:
        """导入 command:.md 单文件。

        同名已存在 → 409;前端确认后带 ?overwrite=true 重试覆盖。
        文件名(去扩展)作为 command name,frontmatter name 字段优先。
        """
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(400, "文件超过 10MB 上限")
        filename = file.filename or ""
        if not filename.lower().endswith((".md", ".markdown")):
            raise HTTPException(400, "只支持 .md 文件")
        text = data.decode("utf-8", errors="replace")
        # 先 parse 一遍拿 name(校验格式)
        root = _import_root()
        root.mkdir(parents=True, exist_ok=True)
        # 临时路径用于 parse(需要真实文件路径,但 parse 不读文件,只看内容)
        stem = Path(filename).stem
        tmp_path = root / filename
        cmd = _parse_command_md(tmp_path, source="user")
        # _parse_command_md 不读文件,只 parse 文本——但签名是 path+source
        # 这里直接 parse 文本:
        from ..commands.loader import _FRONTMATTER_RE
        import yaml

        m = _FRONTMATTER_RE.match(text)
        name = stem
        if m:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
                name = str(fm.get("name") or stem)
            except yaml.YAMLError:
                raise HTTPException(400, "frontmatter yaml 损坏")
        if not _NAME_RE.match(name):
            raise HTTPException(400, f"command name 非法: {name}")
        target = root / f"{name}.md"
        if target.exists() and not overwrite:
            raise HTTPException(409, f"command {name} 已存在,确认覆盖请带 ?overwrite=true")
        target.write_text(text, encoding="utf-8")
        return {"ok": True, "name": name}

    @app.delete("/api/commands/{name}")
    async def delete_command(name: str) -> dict:
        """删除 command。内置(system)不可删;连带清掉 disabled 状态记录。"""
        commands = load_commands_with_state(source_root)
        cmd = next((c for c in commands if c.name == name), None)
        if cmd is None:
            raise HTTPException(404, "command not found")
        if cmd.source == "system":
            raise HTTPException(400, "内置 command 不能删除")
        if cmd.file_path.parent.resolve() not in _deletable_roots(source_root):
            raise HTTPException(400, "command 文件不在可管理范围内,拒绝删除")
        try:
            cmd.file_path.unlink()
        except OSError as e:
            raise HTTPException(500, f"删除失败: {e}") from e
        clear_disabled(name)
        return {"ok": True, "deleted": name}