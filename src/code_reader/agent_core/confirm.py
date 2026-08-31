"""交互式确认入口。agent 改文件前调用,用户 y/n 确认。"""

from __future__ import annotations


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
