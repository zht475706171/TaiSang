"""outliner flow_candidates 单元测试。"""

from code_reader.outliner.flow_candidates import find_flow_candidates
from code_reader.types import RepoIndex, Symbol, SymbolKind


def test_flow_candidates_from_entry():
    """从入口 main BFS 找到 main → handle → process 的端到端链。"""
    symbols = [
        Symbol(
            id="main.py::main",
            kind=SymbolKind.FUNCTION,
            name="main",
            file="main.py",
            line_range=(1, 3),
            calls=["handle"],
            imports=["svc"],
        ),
        Symbol(
            id="svc.py::handle",
            kind=SymbolKind.FUNCTION,
            name="handle",
            file="svc.py",
            line_range=(1, 3),
            calls=["process"],
            imports=[],
        ),
        Symbol(
            id="svc.py::process",
            kind=SymbolKind.FUNCTION,
            name="process",
            file="svc.py",
            line_range=(5, 7),
            calls=[],
            imports=[],
        ),
    ]
    idx = RepoIndex(
        source_root=".",
        commit_hash="x",
        symbols=symbols,
        files=["main.py", "svc.py"],
        index_errors=[],
    )
    flows = find_flow_candidates(idx, entry_symbol_ids=["main.py::main"], max_depth=8)
    assert len(flows) == 1
    assert flows[0].chain == ["main.py::main", "svc.py::handle", "svc.py::process"]
    assert "main (main.py:1-3)" in flows[0].rendered
    assert "→" in flows[0].rendered
