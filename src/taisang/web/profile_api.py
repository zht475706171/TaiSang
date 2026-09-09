"""用户画像管理 API:GET / PUT / RESET / ROLLBACK / HISTORY。

画像正文存 settings.json user_profile 段(经 store.py),
变更历史存 profile_history.jsonl(经 history.py)。
不广播到活跃 session(画像不即时生效,等各自下次 autocompact 或新会话)。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..user_profile.history import append_profile_change, read_profile_history, rollback_profile
from ..user_profile.store import (
    _atomic_write_settings,
    _load_settings_file,
    load_profile,
    reset_profile_field,
    save_profile_field,
)
from ..user_profile.types import ProfileFieldKey, UserProfile


class ProfileFieldUpdate(BaseModel):
    """PUT /api/profile 请求体:单栏更新。"""

    field: ProfileFieldKey
    content: str


class ProfileFieldReset(BaseModel):
    """POST /api/profile/reset 请求体:单栏清空。"""

    field: ProfileFieldKey


def _profile_to_dict(p: UserProfile) -> dict:
    """画像 → 响应 dict(含 total_chars)。"""
    d = p.model_dump()
    # total_chars:5 栏总和(format_profile_section 截断前)
    d["total_chars"] = sum(len(v) for v in d.values() if isinstance(v, str))
    return d


def register_profile_routes(
    app: FastAPI,
    settings_path: Path | None = None,
    history_path: Path | None = None,
) -> None:
    """注册 /api/profile 路由。settings_path/history_path 测试用注入,生产用默认。"""

    @app.get("/api/profile")
    async def get_profile() -> dict:
        p = load_profile(settings_path=settings_path)
        return _profile_to_dict(p)

    @app.put("/api/profile")
    async def update_profile(req: ProfileFieldUpdate) -> dict:
        # field 枚举由 pydantic 校验(非法 → 422)
        old, snapshot_before = save_profile_field(
            field=req.field,
            content=req.content,
            source="user",
            session_id=None,
            settings_path=settings_path,
        )
        append_profile_change(
            field=req.field,
            old=old,
            new=req.content,
            source="user",
            session_id=None,
            snapshot_before=snapshot_before,
            history_path=history_path,
        )
        p = load_profile(settings_path=settings_path)
        return _profile_to_dict(p)

    @app.post("/api/profile/reset")
    async def reset_profile(req: ProfileFieldReset) -> dict:
        old, snapshot_before = reset_profile_field(
            field=req.field,
            source="user",
            session_id=None,
            settings_path=settings_path,
        )
        append_profile_change(
            field=req.field,
            old=old,
            new="",
            source="user",
            session_id=None,
            snapshot_before=snapshot_before,
            history_path=history_path,
        )
        p = load_profile(settings_path=settings_path)
        return _profile_to_dict(p)

    @app.post("/api/profile/rollback")
    async def rollback() -> dict:
        try:
            rolled_back = rollback_profile(history_path=history_path)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

        # 写回 settings.json(整体覆盖)
        sp = settings_path or (Path.home() / ".taisang" / "settings.json")
        cfg = _load_settings_file(sp)
        # 回滚前的 snapshot(供 history 记录)
        before = UserProfile(**cfg.get("user_profile", {}))
        snapshot_before_rollback = before.model_dump()
        cfg["user_profile"] = rolled_back.model_dump()
        _atomic_write_settings(sp, cfg)

        # 追加 rollback history
        append_profile_change(
            field="*",
            old="",
            new="(rollback)",
            source="rollback",
            session_id=None,
            snapshot_before=snapshot_before_rollback,
            history_path=history_path,
        )

        return _profile_to_dict(rolled_back)

    @app.get("/api/profile/history")
    async def get_history() -> list[dict]:
        return read_profile_history(history_path=history_path)
