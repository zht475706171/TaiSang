"""测试跨文件 linker:把多个文件的 Symbol 拼成全局调用图。"""

from code_reader.indexer.linker import build_call_graph, render_chain, resolve_call_chain
from code_reader.types import Symbol, SymbolKind


def _sym(id_, kind, name, file, line, calls=None, imports=None):
    return Symbol(
        id=id_,
        kind=kind,
        name=name,
        file=file,
        line_range=(line, line + 5),
        calls=calls or [],
        imports=imports or [],
    )


def test_build_call_graph_links_cross_file_call():
    """a.py 的 func_a 调 func_b,b.py 定义 func_b。"""
    symbols = [
        _sym("a.py::func_a", SymbolKind.FUNCTION, "func_a", "a.py", 1, calls=["func_b"]),
        _sym("b.py::func_b", SymbolKind.FUNCTION, "func_b", "b.py", 1, calls=[]),
    ]
    graph = build_call_graph(symbols)
    # func_a 的 resolved_calls 应该指向 b.py::func_b
    assert "b.py::func_b" in graph["a.py::func_a"].resolved_calls


def test_build_call_graph_unresolved_call_kept_as_name():
    """调用了不存在于全局表的名字(比如 print),保留原名,不崩。"""
    symbols = [
        _sym("a.py::func_a", SymbolKind.FUNCTION, "func_a", "a.py", 1, calls=["print", "func_b"]),
    ]
    graph = build_call_graph(symbols)
    # func_b 未定义,只保留名字
    assert "print" in graph["a.py::func_a"].unresolved_calls
    assert "func_b" in graph["a.py::func_a"].unresolved_calls


def test_resolve_call_chain_two_hops():
    """a → b → c 的调用链,depth=2 返回 a, b, c。"""
    symbols = [
        _sym("a.py::a", SymbolKind.FUNCTION, "a", "a.py", 1, calls=["b"]),
        _sym("b.py::b", SymbolKind.FUNCTION, "b", "b.py", 1, calls=["c"]),
        _sym("c.py::c", SymbolKind.FUNCTION, "c", "c.py", 1, calls=[]),
    ]
    graph = build_call_graph(symbols)
    chain = resolve_call_chain(graph, "a.py::a", depth=2)
    assert chain == ["a.py::a", "b.py::b", "c.py::c"]


def test_resolve_call_chain_handles_cycle():
    """a → b → a 形成环,depth=3 时不应无限循环。"""
    symbols = [
        _sym("a.py::a", SymbolKind.FUNCTION, "a", "a.py", 1, calls=["b"]),
        _sym("b.py::b", SymbolKind.FUNCTION, "b", "b.py", 1, calls=["a"]),
    ]
    graph = build_call_graph(symbols)
    chain = resolve_call_chain(graph, "a.py::a", depth=3)
    # 环到 a 时停止,不重复
    assert chain == ["a.py::a", "b.py::b"]


def test_resolve_call_chain_unknown_symbol_returns_single():
    """查不存在的 symbol_id,只返回它自己(或空)。"""
    symbols = [_sym("a.py::a", SymbolKind.FUNCTION, "a", "a.py", 1, calls=[])]
    graph = build_call_graph(symbols)
    chain = resolve_call_chain(graph, "unknown::x", depth=3)
    assert chain == []


def test_build_call_graph_method_qualified():
    """Stack.push 调用 self.items.append,push 的 calls 里有 append,append 未定义则 unresolved。"""
    symbols = [
        _sym("stack.py::Stack.push", SymbolKind.METHOD, "push", "stack.py", 5, calls=["append"]),
    ]
    graph = build_call_graph(symbols)
    assert "append" in graph["stack.py::Stack.push"].unresolved_calls


def test_build_call_graph_method_call_to_other_method_in_same_class():
    """Stack.push 调用 self.pop,pop 也在 Stack 里,应解析到 Stack.pop。"""
    symbols = [
        _sym("stack.py::Stack.push", SymbolKind.METHOD, "push", "stack.py", 5, calls=["pop"]),
        _sym("stack.py::Stack.pop", SymbolKind.METHOD, "pop", "stack.py", 8, calls=[]),
    ]
    graph = build_call_graph(symbols)
    # push 调 pop,pop 在同一个 class Stack 里,应解析
    assert "stack.py::Stack.pop" in graph["stack.py::Stack.push"].resolved_calls


def test_linker_resolves_via_import():
    """a.py 的 helper 调用,通过 import 解析到 b.py::helper。"""
    symbols = [
        Symbol(
            id="a.py::main",
            kind=SymbolKind.FUNCTION,
            name="main",
            file="a.py",
            line_range=(1, 3),
            calls=["helper"],
            imports=["b"],
        ),
        Symbol(
            id="b.py::helper",
            kind=SymbolKind.FUNCTION,
            name="helper",
            file="b.py",
            line_range=(1, 2),
            calls=[],
            imports=[],
        ),
    ]
    graph = build_call_graph(symbols)
    assert "b.py::helper" in graph["a.py::main"].resolved_calls


def test_linker_same_module_priority():
    """a.py 调 foo,同模块的 a.py::foo 优先于其他模块的 foo。"""
    symbols = [
        Symbol(
            id="a.py::caller",
            kind=SymbolKind.FUNCTION,
            name="caller",
            file="a.py",
            line_range=(1, 3),
            calls=["foo"],
            imports=[],
        ),
        Symbol(
            id="a.py::foo",
            kind=SymbolKind.FUNCTION,
            name="foo",
            file="a.py",
            line_range=(5, 6),
            calls=[],
            imports=[],
        ),
        Symbol(
            id="b.py::foo",
            kind=SymbolKind.FUNCTION,
            name="foo",
            file="b.py",
            line_range=(1, 2),
            calls=[],
            imports=[],
        ),
    ]
    graph = build_call_graph(symbols)
    assert graph["a.py::caller"].resolved_calls == ["a.py::foo"]


def test_render_chain_renders_human_readable():
    """render_chain 把 [symbol_id, ...] 展开成 'name (file:line) → ...' 格式。"""
    symbols = [
        Symbol(
            id="a.py::main",
            kind=SymbolKind.FUNCTION,
            name="main",
            file="a.py",
            line_range=(10, 20),
            calls=["helper"],
            imports=[],
        ),
        Symbol(
            id="b.py::helper",
            kind=SymbolKind.FUNCTION,
            name="helper",
            file="b.py",
            line_range=(5, 8),
            calls=[],
            imports=[],
        ),
    ]
    graph = build_call_graph(symbols)
    rendered = render_chain(graph, ["a.py::main", "b.py::helper"])
    assert "main (a.py:10-20)" in rendered
    assert "helper (b.py:5-8)" in rendered
    assert "→" in rendered


def test_render_chain_handles_missing_sid():
    """render_chain 对 graph 里没有的 sid 标为 [missing: <sid>],其余节点正常输出。"""
    symbols = [
        Symbol(
            id="a.py::main",
            kind=SymbolKind.FUNCTION,
            name="main",
            file="a.py",
            line_range=(1, 3),
            calls=[],
            imports=[],
        ),
    ]
    graph = build_call_graph(symbols)
    rendered = render_chain(graph, ["a.py::main", "unknown::x"])
    assert "main (a.py:1-3)" in rendered
    assert "[missing: unknown::x]" in rendered
    assert "→" in rendered


def test_render_chain_empty_and_single():
    """render_chain 对空 chain 返回空串,单元素 chain 不含 →。"""
    symbols = [
        Symbol(
            id="a.py::main",
            kind=SymbolKind.FUNCTION,
            name="main",
            file="a.py",
            line_range=(1, 3),
            calls=[],
            imports=[],
        ),
    ]
    graph = build_call_graph(symbols)
    assert render_chain(graph, []) == ""
    single = render_chain(graph, ["a.py::main"])
    assert "main (a.py:1-3)" in single
    assert "→" not in single
