"""核心模块候选挖掘:按目录聚类,统计文件数/符号数/入度。

目录路径取 PurePosixPath.parent,根目录文件用空串 ""。
按 (in_degree, symbol_count) 降序取 top_k。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from ..indexer.linker import build_call_graph
from ..types import ModuleCandidate, RepoIndex


def _dir_of(file: str) -> str:
    """文件路径 → 所属目录。根目录文件返回空串。

    Args:
        file: 文件相对路径(可能含 / 或 \\)

    Returns:
        目录路径字符串;根目录文件返回 ""
    """
    d = str(PurePosixPath(file.replace("\\", "/")).parent)
    if d == ".":
        d = ""
    return d


def find_module_candidates(idx: RepoIndex, top_k: int = 5) -> list[ModuleCandidate]:
    """按目录聚类,统计每个模块的文件数/符号数/入度。

    Args:
        idx: 仓库索引
        top_k: 返回前 top_k 个模块

    Returns:
        按 (in_degree, symbol_count) 降序排列的模块候选列表
    """
    files_by_dir: dict[str, set[str]] = defaultdict(set)
    syms_by_dir: dict[str, int] = defaultdict(int)
    for s in idx.symbols:
        d = _dir_of(s.file)
        files_by_dir[d].add(s.file)
        syms_by_dir[d] += 1
    # 入度:从调用图算(简化:用 in_degree 总和)
    graph = build_call_graph(idx.symbols)
    in_degree: dict[str, int] = defaultdict(int)
    for node in graph.values():
        for callee in node.resolved_calls:
            if callee in graph:
                callee_dir = _dir_of(graph[callee].file)
            else:
                callee_dir = ""
            in_degree[callee_dir] += 1
    cands = [
        ModuleCandidate(
            path=d,
            file_count=len(files),
            symbol_count=syms_by_dir[d],
            in_degree=in_degree[d],
        )
        for d, files in files_by_dir.items()
    ]
    cands.sort(key=lambda m: (m.in_degree, m.symbol_count), reverse=True)
    return cands[:top_k]
