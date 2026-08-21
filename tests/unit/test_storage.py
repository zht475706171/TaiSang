"""测试索引 SQLite 持久化。"""

from code_reader.indexer.storage import IndexStorage
from code_reader.types import Symbol, SymbolKind


def _sym(id_, name, file="a.py", line=1):
    return Symbol(
        id=id_,
        kind=SymbolKind.FUNCTION,
        name=name,
        file=file,
        line_range=(line, line + 5),
        calls=[],
        imports=[],
    )


def test_save_and_load_symbols(tmp_path):
    db = tmp_path / "ast.db"
    storage = IndexStorage(db)
    storage.save_symbols(
        "hash1",
        [
            _sym("a.py::foo", "foo"),
            _sym("b.py::bar", "bar", "b.py", 10),
        ],
        commit_hash="abc123",
    )
    loaded = storage.load_symbols("hash1")
    assert len(loaded) == 2
    assert {s.name for s in loaded} == {"foo", "bar"}


def test_load_symbols_returns_empty_for_unknown(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    assert storage.load_symbols("nonexistent") == []


def test_save_and_load_fingerprints(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    storage.save_fingerprints("hash1", {"a.py": "h-a", "b.py": "h-b"})
    fps = storage.load_fingerprints("hash1")
    assert fps == {"a.py": "h-a", "b.py": "h-b"}


def test_load_fingerprints_unknown_returns_empty(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    assert storage.load_fingerprints("nonexistent") == {}


def test_save_symbols_overwrites_old(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    storage.save_symbols("h", [_sym("a.py::foo", "foo")], commit_hash="v1")
    storage.save_symbols("h", [_sym("a.py::bar", "bar")], commit_hash="v2")
    loaded = storage.load_symbols("h")
    assert {s.name for s in loaded} == {"bar"}


def test_save_and_load_index_errors(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    errors = [{"file": "bad.py", "stage": "parse", "error": "syntax error"}]
    storage.save_index_errors("h", errors)
    loaded = storage.load_index_errors("h")
    assert loaded == errors
