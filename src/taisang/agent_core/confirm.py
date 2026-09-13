"""交互式确认入口。agent 改文件前调用,用户 y/n 确认。"""

from __future__ import annotations

from collections.abc import Callable


def default_confirmer(file_path: str, old: str, new: str) -> bool:
    """默认确认器:打印 diff 概要,stdin 读 y/n。"""
    print(f"\n[CONFIRM] agent wants to edit: {file_path}")
    if old:
        print(f"  replace ({len(old)} chars): {old[:80]!r}...")
        print(f"  with    ({len(new)} chars): {new[:80]!r}...")
    else:
        print(f"  write new file ({len(new)} chars)")
    try:
        ans = input("  allow? (y/N): ").strip().lower()
        return ans == "y"
    except (EOFError, KeyboardInterrupt):
        return False


class AutoApproveConfirmer:
    """测试用:无脑同意所有改动。"""

    def __call__(self, file_path: str, old: str, new: str) -> bool:
        return True


class AutoDenyConfirmer:
    """测试用:无脑拒绝所有改动。"""

    def __call__(self, file_path: str, old: str, new: str) -> bool:
        return False


class BypassableConfirmer:
    """包装真实 confirmer,持有 bypass 标志引用。

    bypass_getter 返回 True 时直接放行(免确认模式),不调 inner confirmer。
    bypass_getter 返回 False 时走 inner confirmer 正常问用户。

    bypass_getter 通常是 lambda: permission.bypass_enabled,
    这样 confirmer 和 PermissionManager 共享同一个布尔源,
    Web 设置面板切换时两者自动同步。
    """

    def __init__(self, inner: Callable[[str, str, str], bool], bypass_getter: Callable[[], bool]) -> None:
        self._inner = inner
        self._bypass_getter = bypass_getter

    def __call__(self, file_path: str, old: str, new: str) -> bool:
        if self._bypass_getter():
            return True
        return self._inner(file_path, old, new)
