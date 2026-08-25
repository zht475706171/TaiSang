"""outliner mechanism_candidates 单元测试。"""

from code_reader.outliner.mechanism_candidates import find_mechanism_candidates
from code_reader.types import RepoIndex, Symbol, SymbolKind


def test_mechanism_candidates_score_by_in_degree():
    """被引用最多的符号分数最高,跨模块引用计数为不同模块调用者集合大小。"""
    symbols = [
        Symbol(
            id="a.py::hub",
            kind=SymbolKind.FUNCTION,
            name="hub",
            file="a.py",
            line_range=(1, 5),
            calls=[],
            imports=[],
        ),
        Symbol(
            id="b.py::user1",
            kind=SymbolKind.FUNCTION,
            name="user1",
            file="b.py",
            line_range=(1, 3),
            calls=["hub"],
            imports=[],
        ),
        Symbol(
            id="c.py::user2",
            kind=SymbolKind.FUNCTION,
            name="user2",
            file="c.py",
            line_range=(1, 3),
            calls=["hub"],
            imports=[],
        ),
        Symbol(
            id="d.py::user3",
            kind=SymbolKind.FUNCTION,
            name="user3",
            file="d.py",
            line_range=(1, 3),
            calls=["hub"],
            imports=[],
        ),
    ]
    idx = RepoIndex(
        source_root=".",
        commit_hash="x",
        symbols=symbols,
        files=["a.py", "b.py", "c.py", "d.py"],
        index_errors=[],
    )
    cands = find_mechanism_candidates(idx, top_k=10)
    assert cands[0].symbol_id == "a.py::hub"
    assert cands[0].in_degree == 3
    assert cands[0].cross_module_refs == 3  # b/c/d 三个不同模块引用
