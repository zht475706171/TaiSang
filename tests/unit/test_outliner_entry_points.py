"""outliner entry_points 单元测试。"""

from code_reader.outliner.entry_points import find_entry_points
from code_reader.types import RepoIndex, Symbol, SymbolKind


def test_find_entry_points_finds_main():
    """main.py::main 应被识别为入口,kind=main。"""
    symbols = [
        Symbol(
            id="main.py::main",
            kind=SymbolKind.FUNCTION,
            name="main",
            file="main.py",
            line_range=(1, 3),
            calls=[],
            imports=[],
        ),
        Symbol(
            id="utils.py::helper",
            kind=SymbolKind.FUNCTION,
            name="helper",
            file="utils.py",
            line_range=(1, 2),
            calls=[],
            imports=[],
        ),
    ]
    idx = RepoIndex(
        source_root=".",
        commit_hash="x",
        symbols=symbols,
        files=["main.py", "utils.py"],
        index_errors=[],
    )
    entries = find_entry_points(idx)
    assert len(entries) == 1
    assert entries[0].symbol_id == "main.py::main"
    assert entries[0].kind == "main"
