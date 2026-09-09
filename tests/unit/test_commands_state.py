"""测试 commands state:disabled 持久化 + apply + clear。"""

from pathlib import Path
from unittest.mock import patch

from taisang.commands import state as state_mod
from taisang.commands.types import Command


def _make_cmd(name: str, disabled: bool = False) -> Command:
    return Command(
        name=name,
        description="",
        argument_hint="",
        allowed_tools=None,
        content="body",
        file_path=Path("/tmp/x.md"),
        source="user",
        disabled=disabled,
    )


def test_load_disabled_state_missing_file_returns_empty(tmp_path: Path) -> None:
    """state 文件不存在 → 空 dict。"""
    with patch.object(state_mod, "_STATE_FILE", tmp_path / "noexist.json"):
        assert state_mod.load_disabled_state() == {}


def test_save_and_load_disabled_state_roundtrip(tmp_path: Path) -> None:
    """写 → 读 roundtrip。"""
    state_file = tmp_path / "commands_state.json"
    with patch.object(state_mod, "_STATE_FILE", state_file):
        state_mod.save_disabled_state({"commit": True, "review": True})
        loaded = state_mod.load_disabled_state()
        assert loaded == {"commit": True, "review": True}


def test_set_disabled_persists(tmp_path: Path) -> None:
    """set_disabled 写盘。"""
    state_file = tmp_path / "commands_state.json"
    with patch.object(state_mod, "_STATE_FILE", state_file):
        state_mod.set_disabled("commit", True)
        assert state_mod.load_disabled_state() == {"commit": True}
        # 切回 enabled → 移除记录
        state_mod.set_disabled("commit", False)
        assert state_mod.load_disabled_state() == {}


def test_apply_disabled_state_to_commands(tmp_path: Path) -> None:
    """apply_disabled_state 把状态应用到 command 列表。"""
    state_file = tmp_path / "commands_state.json"
    state_file.write_text('{"commit": true}', encoding="utf-8")
    with patch.object(state_mod, "_STATE_FILE", state_file):
        cmds = [_make_cmd("commit"), _make_cmd("review")]
        state_mod.apply_disabled_state(cmds)
        assert cmds[0].disabled is True
        assert cmds[1].disabled is False


def test_clear_disabled_removes_orphan(tmp_path: Path) -> None:
    """clear_disabled 删 command 时清掉孤儿记录。"""
    state_file = tmp_path / "commands_state.json"
    state_file.write_text('{"commit": true, "review": true}', encoding="utf-8")
    with patch.object(state_mod, "_STATE_FILE", state_file):
        state_mod.clear_disabled("commit")
        state = state_mod.load_disabled_state()
        assert "commit" not in state
        assert "review" in state  # 其他保留


def test_clear_disabled_noop_when_not_present(tmp_path: Path) -> None:
    """clear_disabled 对不在记录里的 name 是 no-op(不报错)。"""
    state_file = tmp_path / "commands_state.json"
    state_file.write_text('{"review": true}', encoding="utf-8")
    with patch.object(state_mod, "_STATE_FILE", state_file):
        state_mod.clear_disabled("nonexistent")
        assert state_mod.load_disabled_state() == {"review": True}