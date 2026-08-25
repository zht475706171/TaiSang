"""挖掘入口符号(main / cli / app 等命名约定匹配)。

入口识别策略(命中即标记 kind=main):
1. 入口文件名 + 入口函数名同时命中 → 高置信度入口
2. 普通文件里函数名是 main 且为 .py 文件 → 次级入口

去重:同 symbol_id 只保留第一个。
"""

from __future__ import annotations

from ..types import EntryPoint, RepoIndex

# 入口文件名匹配
_ENTRY_FILES = {"main.py", "cli.py", "app.py", "__main__.py", "run.py", "start.py"}
# 入口函数名匹配
_ENTRY_NAMES = {"main", "__main__", "run", "app", "create_app", "start", "cli"}


def find_entry_points(idx: RepoIndex) -> list[EntryPoint]:
    """从索引里挖掘入口符号。

    Args:
        idx: 仓库索引

    Returns:
        去重后的入口列表(同 symbol_id 只保留一个)
    """
    entries: list[EntryPoint] = []
    for s in idx.symbols:
        # 入口文件 + 入口函数名
        if s.file in _ENTRY_FILES and s.name in _ENTRY_NAMES:
            entries.append(
                EntryPoint(
                    symbol_id=s.id,
                    kind="main",
                    description=f"入口文件 {s.file} 的 {s.name}",
                )
            )
        # 普通文件但函数名是入口
        elif s.name == "main" and s.file.endswith(".py"):
            entries.append(
                EntryPoint(
                    symbol_id=s.id,
                    kind="main",
                    description=f"{s.file} 的 main 函数",
                )
            )
    # 去重(同 symbol_id 只保留一个)
    seen: set[str] = set()
    unique: list[EntryPoint] = []
    for e in entries:
        if e.symbol_id not in seen:
            seen.add(e.symbol_id)
            unique.append(e)
    return unique
