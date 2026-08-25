"""关键流程候选挖掘:从入口 BFS 找端到端调用链。

策略:对每个入口符号 BFS 找第一条到叶子节点(无 resolved_calls)的路径,
过滤长度 < min_depth 的过短链,过滤长度 > max_depth 的过长链。
"""

from __future__ import annotations

from collections import deque

from ..indexer.linker import build_call_graph, render_chain
from ..types import FlowCandidate, RepoIndex


def find_flow_candidates(
    idx: RepoIndex,
    entry_symbol_ids: list[str],
    max_depth: int = 8,
    min_depth: int = 3,
) -> list[FlowCandidate]:
    """从每个入口 BFS 找第一条端到端路径,过滤太短/太长。

    Args:
        idx: 仓库索引
        entry_symbol_ids: 入口符号 id 列表
        max_depth: 链最大长度(含入口),超过则截断
        min_depth: 链最小长度(含入口),低于则丢弃

    Returns:
        流程候选列表,每条含 chain / rendered / hop_count
    """
    graph = build_call_graph(idx.symbols)
    flows: list[FlowCandidate] = []
    for entry_id in entry_symbol_ids:
        if entry_id not in graph:
            continue
        # BFS 找最深的一条链(简化:找第一条到叶子节点的链)
        chain = _bfs_to_leaf(graph, entry_id, max_depth)
        if len(chain) < min_depth:
            continue
        flows.append(
            FlowCandidate(
                name=graph[entry_id].name,
                entry_symbol_id=entry_id,
                chain=chain,
                hop_count=len(chain),
                rendered=render_chain(graph, chain),
            )
        )
    return flows


def _bfs_to_leaf(graph: dict, start: str, max_depth: int) -> list[str]:
    """BFS 找到第一个叶子节点(无 resolved_calls)的路径。

    Args:
        graph: 调用图
        start: 起点 symbol_id
        max_depth: 路径最大长度(含起点),超过即返回当前路径

    Returns:
        symbol_id 列表,从 start 到第一个找到的叶子
    """
    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    visited: set[str] = {start}
    last_path: list[str] = [start]
    while queue:
        node_id, path = queue.popleft()
        last_path = path
        if len(path) >= max_depth:
            return path
        node = graph.get(node_id)
        if not node or not node.resolved_calls:
            return path  # 叶子
        for callee in node.resolved_calls:
            if callee not in visited:
                visited.add(callee)
                queue.append((callee, path + [callee]))
    return last_path
