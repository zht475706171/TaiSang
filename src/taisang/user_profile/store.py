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

from .types import DEFAULT_PROFILE_TEMPLATE, UserProfile

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


def _extract_content(raw: dict) -> str:
    """从 user_profile 段提取 content 字段,兼容旧版 5 字段格式。

    旧版:{"tech_stack": "Python", "code_style": "...", ...} → 拼成 ### 标题段
    新版:{"content": "### 技术栈\n..."} → 直接取
    """
    if not isinstance(raw, dict):
        return ""
    # 新版:有 content 字段
    if "content" in raw:
        c = raw.get("content")
        return c if isinstance(c, str) else ""
    # 旧版兼容:5 字段拼成 ### 标题段
    legacy_labels = {
        "tech_stack": "技术栈",
        "code_style": "代码风格",
        "communication": "沟通",
        "environment": "环境",
        "taboos": "禁忌",
    }
    parts = []
    for key, label in legacy_labels.items():
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(f"### {label}\n{val}")
    return "\n\n".join(parts)


def load_profile(settings_path: Path | None = None) -> UserProfile:
    """加载画像。损坏/缺失/类型错 → fallback 空 UserProfile。"""
    sp = settings_path or _DEFAULT_SETTINGS_PATH
    raw = _load_settings_file(sp).get("user_profile")
    content = _extract_content(raw if isinstance(raw, dict) else {})
    try:
        return UserProfile(content=content)
    except ValidationError:
        return UserProfile()


def save_profile_content(
    content: str,
    source: str,
    session_id: str | None,
    settings_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """整篇覆盖画像 content,返回 (old_content, snapshot_before)。

    读-改-写全程持锁,保证原子性。其它段(llm/skills/prompts)原样保留。
    """
    sp = settings_path or _DEFAULT_SETTINGS_PATH
    with _profile_lock:
        cfg = _load_settings_file(sp)
        old_profile = UserProfile(content=_extract_content(cfg.get("user_profile", {})))
        old = old_profile.content
        snapshot_before = old_profile.model_dump()
        new_profile = UserProfile(content=content)
        cfg["user_profile"] = new_profile.model_dump()
        _atomic_write_settings(sp, cfg)
    return old, snapshot_before


def reset_profile_to_default(
    source: str,
    session_id: str | None,
    settings_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """恢复默认模板(5 个空标题骨架)。

    语义等同 save_profile_content(DEFAULT_PROFILE_TEMPLATE, ...)。
    """
    return save_profile_content(
        DEFAULT_PROFILE_TEMPLATE,
        source=source,
        session_id=session_id,
        settings_path=settings_path,
    )


def clear_profile(
    source: str,
    session_id: str | None,
    settings_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """清空画像(整篇置空)。语义等同 save_profile_content("", ...)。"""
    return save_profile_content(
        "",
        source=source,
        session_id=session_id,
        settings_path=settings_path,
    )
