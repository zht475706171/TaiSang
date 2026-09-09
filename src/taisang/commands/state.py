"""Command disabled 状态持久化:~/.taisang/commands_state.json。

对齐 skills_state.json 的模式:原子写(tmp + os.replace),chmod 0o600 best-effort。
记录被禁用的 command name,进程外(UI 切换)也可见。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_STATE_FILE = Path.home() / ".taisang" / "commands_state.json"


def load_disabled_state() -> dict[str, bool]:
    """读 ~/.taisang/commands_state.json,返回 {name: disabled_bool}。"""
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_disabled_state(state: dict[str, bool]) -> None:
    """原子写 commands_state.json。"""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, _STATE_FILE)


def apply_disabled_state(commands) -> None:
    """把 disabled 状态应用到 command 列表(原地改 disabled 字段)。"""
    disabled = load_disabled_state()
    for c in commands:
        c.disabled = disabled.get(c.name, False)


def set_disabled(name: str, disabled: bool) -> None:
    """切换单个 command 的 disabled 状态并持久化。"""
    state = load_disabled_state()
    if disabled:
        state[name] = True
    else:
        state.pop(name, None)
    save_disabled_state(state)


def clear_disabled(name: str) -> None:
    """删除 command 时清掉它的 disabled 记录(避免孤儿状态)。"""
    state = load_disabled_state()
    if state.pop(name, None) is not None:
        save_disabled_state(state)