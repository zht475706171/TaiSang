"""核心机制候选挖掘:调用图指标打分。

打分公式: score = cross_module_refs * 3 + in_degree * 2 + out_degree * 1
- cross_module_refs: 跨模块引用数(不同模块的调用者集合大小)
- in_degree: 被多少符号调用
- out_degree: 它调用多少符号

模块定义:取文件路径顶层目录。根目录文件 → 文件名本身。
"""

from __future__ import annotations

from ..indexer.linker import build_call_graph
from ..types import MechanismCandidate, RepoIndex


def _module_of(file: str) -> str:
    """a/b/c.py → a(取顶层目录,作为模块)。根目录文件 → 文件名。"""
    parts = file.replace("\\", "/").split("/")
    if len(parts) == 1:
        return parts[0]
    return parts[0]


def find_mechanism_candidates(idx: RepoIndex, top_k: int = 20) -> list[MechanismCandidate]:
    """调用图指标打分,top_k 返回。

    Args:
        idx: 仓库索引
        top_k: 返回前 top_k 个候选

    Returns:
        按分数降序排列的机制候选列表(最多 top_k 个)
    """
    graph = build_call_graph(idx.symbols)
    # 算每个 symbol 的入度(被谁调用)+ 跨模块引用 + 出度
    in_degree: dict[str, int] = {sid: 0 for sid in graph}
    cross_module: dict[str, set[str]] = {sid: set() for sid in graph}
    for _sid, node in graph.items():
        caller_module = _module_of(node.file)
        for callee in node.resolved_calls:
            in_degree[callee] = in_degree.get(callee, 0) + 1
            callee_module = _module_of(graph[callee].file) if callee in graph else caller_module
            if callee_module != caller_module:
                cross_module[callee].add(caller_module)
    cands: list[MechanismCandidate] = []
    for sid, node in graph.items():
        out_degree = len(node.resolved_calls)
        # 加权打分:跨模块引用 × 3 + 入度 × 2 + 出度 × 1
        score = len(cross_module[sid]) * 3 + in_degree[sid] * 2 + out_degree * 1
        cands.append(
            MechanismCandidate(
                symbol_id=sid,
                name=node.name,
                file=node.file,
                in_degree=in_degree[sid],
                cross_module_refs=len(cross_module[sid]),
                out_degree=out_degree,
                score=score,
            )
        )
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands[:top_k]
