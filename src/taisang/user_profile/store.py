"""用户画像存储:加载/保存到 ~/.taisang/settings.json 的 user_profile 段。

原子写(tmp + os.replace + chmod 0o600 best-effort),保留其它段(llm/skills/prompts)。
threading.Lock 串行化读-改-写,消除 web 线程 + agent 线程并发竞态。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .types import ProfileFieldKey, UserProfile

_DEFAULT_SETTINGS_PATH = Path.home() / ".taisang" / "settings.json"

# 进程级锁:串行化所有画像写,消除读-改-写竞态。
# web 线程(PUT /api/profile)和 agent 线程(update_profile 工具)争同一把锁。
_profile_lock = threading.Lock()


def _load_settings_file(settings_path: Path) -> dict:
    """加载 settings.json,损坏/不存在返回 {}。"""
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _atomic_write_settings(settings_path: Path, data: dict) -> None:
    """原子写 settings.json,保留权限 0o600(best-effort,Windows 跳过)。"""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, settings_path)


def load_profile(settings_path: Path | None = None) -> UserProfile:
    """加载画像。损坏/缺失/类型错 → fallback 空 UserProfile。"""
    sp = settings_path or _DEFAULT_SETTINGS_PATH
    raw = _load_settings_file(sp).get("user_profile")
    if not isinstance(raw, dict):
        return UserProfile()
    try:
        return UserProfile(**raw)
    except ValidationError:
        return UserProfile()


def save_profile_field(
    field: ProfileFieldKey,
    content: str,
    source: str,
    session_id: str | None,
    settings_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """更新单栏,返回 (old_value, snapshot_before)。

    读-改-写全程持锁,保证原子性。其它段(llm/skills/prompts)原样保留。
    """
    sp = settings_path or _DEFAULT_SETTINGS_PATH
    with _profile_lock:
        cfg = _load_settings_file(sp)
        profile = UserProfile(**cfg.get("user_profile", {}))
        old = getattr(profile, field)
        snapshot_before = profile.model_dump()
        setattr(profile, field, content)
        cfg["user_profile"] = profile.model_dump()
        _atomic_write_settings(sp, cfg)
    return old, snapshot_before


def reset_profile_field(
    field: ProfileFieldKey,
    source: str,
    session_id: str | None,
    settings_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """清空单栏,语义等同 save_profile_field(field, "", ...)。"""
    return save_profile_field(
        field, "", source=source, session_id=session_id, settings_path=settings_path
    )
