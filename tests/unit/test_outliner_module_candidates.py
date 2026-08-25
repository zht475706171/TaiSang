"""outliner module_candidates 单元测试。"""

from code_reader.outliner.module_candidates import find_module_candidates
from code_reader.types import RepoIndex, Symbol, SymbolKind


def test_module_candidates_group_by_dir():
    """按目录聚类,core 目录含 2 文件 2 符号,根目录路径用空串或目录名。"""
    symbols = [
        Symbol(
            id="core/a.py::x",
            kind=SymbolKind.FUNCTION,
            name="x",
            file="core/a.py",
            line_range=(1, 2),
            calls=[],
            imports=[],
        ),
        Symbol(
            id="core/b.py::y",
            kind=SymbolKind.FUNCTION,
            name="y",
            file="core/b.py",
            line_range=(1, 2),
            calls=[],
            imports=[],
        ),
        Symbol(
            id="utils/c.py::z",
            kind=SymbolKind.FUNCTION,
            name="z",
            file="utils/c.py",
            line_range=(1, 2),
            calls=[],
            imports=[],
        ),
    ]
    idx = RepoIndex(
        source_root=".",
        commit_hash="x",
        symbols=symbols,
        files=["core/a.py", "core/b.py", "utils/c.py"],
        index_errors=[],
    )
    mods = find_module_candidates(idx, top_k=5)
    paths = [m.path for m in mods]
    assert "core" in paths
    assert "utils" in paths
    core_mod = next(m for m in mods if m.path == "core")
    assert core_mod.file_count == 2
    assert core_mod.symbol_count == 2
