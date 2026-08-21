"""跨文件 linker:把多文件 Symbol 拼成全局调用图。

设计:
- build_call_graph 建 symbol_id → CallGraphNode 的图
- resolve_call_chain 从某 symbol 出发 BFS,返回 N 跳调用链
- 弱类型语言(如 Python)调用追踪靠"同名符号"匹配,best-effort
- method 内调 self.xxx 优先解析到同 class 的 method
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..types import Symbol


@dataclass
class CallGraphNode:
    """调用图节点。"""

    symbol_id: str
    name: str
    file: str
    line_range: tuple[int, int]
    resolved_calls: list[str] = field(default_factory=list)  # 解析到的 symbol_id
    unresolved_calls: list[str] = field(default_factory=list)  # 未解析的裸名


def _method_class(symbol_id: str) -> str | None:
    """从 symbol_id 抽 class 名(如果有)。id 格式: file::Class.method 或 file::func。"""
    qual = symbol_id.split("::", 1)[1] if "::" in symbol_id else symbol_id
    if "." in qual:
        return qual.split(".", 1)[0]
    return None


def build_call_graph(symbols: list[Symbol]) -> dict[str, CallGraphNode]:
    """构建全局调用图。

    匹配策略:
    1. caller 是 method 且 call name 跟同 class 内某 method 同名 → 解析到那个 method
    2. 否则在全局按 name 找唯一匹配的 symbol → 解析
    3. 多个同名或无匹配 → 加入 unresolved_calls
    """
    # name → list[symbol_id]
    by_name: dict[str, list[str]] = {}
    for s in symbols:
        by_name.setdefault(s.name, []).append(s.id)

    graph: dict[str, CallGraphNode] = {}
    for s in symbols:
        node = CallGraphNode(
            symbol_id=s.id,
            name=s.name,
            file=s.file,
            line_range=s.line_range,
        )
        caller_class = _method_class(s.id)
        for call_name in s.calls:
            # 策略 1: method 内调 self.xxx → 同 class 的 method
            if caller_class:
                candidate = next(
                    (
                        sid
                        for sid in by_name.get(call_name, [])
                        if _method_class(sid) == caller_class
                    ),
                    None,
                )
                if candidate:
                    node.resolved_calls.append(candidate)
                    continue
            # 策略 2: 全局唯一 name
            candidates = by_name.get(call_name, [])
            if len(candidates) == 1:
                node.resolved_calls.append(candidates[0])
            else:
                node.unresolved_calls.append(call_name)
        graph[s.id] = node
    return graph


def resolve_call_chain(graph: dict[str, CallGraphNode], start: str, depth: int) -> list[str]:
    """BFS 返回从 start 出发的 N 跳调用链(含 start)。

    环检测:遇到已访问节点停止该分支。
    start 不在图中返回 []。
    """
    if start not in graph:
        return []
    visited: set[str] = {start}
    chain: list[str] = [start]
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        node_id, d = queue.popleft()
        if d >= depth:
            continue
        node = graph.get(node_id)
        if not node:
            continue
        for callee in node.resolved_calls:
            if callee in visited:
                continue
            visited.add(callee)
            chain.append(callee)
            queue.append((callee, d + 1))
    return chain
