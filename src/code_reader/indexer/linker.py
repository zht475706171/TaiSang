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


def _file_module_name(file: str) -> str:
    """a/b/c.py → c(取文件名去 .py)。

    import 通常写 `from c import x` 或 `import c`,所以模块名就是文件名去后缀。
    对 Windows 路径也兼容(同时处理 / 和 \\)。
    """
    last = file.replace("\\", "/").rsplit("/", 1)[-1]
    return last[:-3] if last.endswith(".py") else last


def build_call_graph(symbols: list[Symbol]) -> dict[str, CallGraphNode]:
    """构建全局调用图。

    匹配优先级:
    1. method 内调 self.foo → 同 class 的 method
    2. 同文件唯一匹配
    3. import 解析(caller.imports 含候选所在模块名)且唯一匹配
    4. 全局唯一 name
    5. 否则 unresolved
    """
    by_name: dict[str, list[str]] = {}
    for s in symbols:
        by_name.setdefault(s.name, []).append(s.id)

    # file → 模块名映射(候选 symbol 的 file → 模块名)
    file_to_module: dict[str, str] = {}
    for s in symbols:
        if s.file not in file_to_module:
            file_to_module[s.file] = _file_module_name(s.file)

    graph: dict[str, CallGraphNode] = {}
    for s in symbols:
        node = CallGraphNode(
            symbol_id=s.id,
            name=s.name,
            file=s.file,
            line_range=s.line_range,
        )
        caller_class = _method_class(s.id)
        caller_imports = set(s.imports)
        for call_name in s.calls:
            candidates = by_name.get(call_name, [])
            # 策略 1: method 内调 self.foo → 同 class 的 method
            if caller_class:
                candidate = next(
                    (sid for sid in candidates if _method_class(sid) == caller_class),
                    None,
                )
                if candidate:
                    node.resolved_calls.append(candidate)
                    continue
            # 策略 2: 同文件唯一匹配
            same_file = [sid for sid in candidates if sid.split("::", 1)[0] == s.file]
            if len(same_file) == 1:
                node.resolved_calls.append(same_file[0])
                continue
            # 策略 3: import 解析唯一匹配
            import_matched = [
                sid
                for sid in candidates
                if file_to_module.get(sid.split("::", 1)[0]) in caller_imports
            ]
            if len(import_matched) == 1:
                node.resolved_calls.append(import_matched[0])
                continue
            # 策略 4: 全局唯一 name
            if len(candidates) == 1:
                node.resolved_calls.append(candidates[0])
                continue
            # 策略 5: unresolved
            node.unresolved_calls.append(call_name)
        graph[s.id] = node
    return graph


def render_chain(graph: dict[str, CallGraphNode], chain: list[str]) -> str:
    """把 symbol_id 列表展开成人话叙事:'name (file:start-end) → name2 (file2:...)'。

    缺失的 sid 标为 `[missing: <sid>]`,继续输出其余节点。
    """
    parts: list[str] = []
    for sid in chain:
        node = graph.get(sid)
        if not node:
            parts.append(f"[missing: {sid}]")
            continue
        start, end = node.line_range
        parts.append(f"{node.name} ({node.file}:{start}-{end})")
    return " → ".join(parts)


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
