"""测试核心数据类型能正确构造和序列化。"""

from code_reader.types import (
    Answer,
    Citation,
    FileSummary,
    GlobalSummary,
    ModuleSummary,
    RepoIndex,
    RepoMap,
    Snippet,
    Symbol,
    SymbolKind,
)


def test_symbol_basic():
    s = Symbol(
        id="fastapi/application.py::FastAPI.run",
        kind=SymbolKind.FUNCTION,
        name="run",
        file="fastapi/application.py",
        line_range=(110, 145),
        calls=["uvicorn.run"],
        imports=["uvicorn"],
    )
    assert s.kind == SymbolKind.FUNCTION
    assert s.line_range == (110, 145)
    assert s.calls == ["uvicorn.run"]
    assert s.imports == ["uvicorn"]


def test_symbol_kind_values():
    assert SymbolKind.FUNCTION != SymbolKind.CLASS
    assert SymbolKind.METHOD.value == "method"


def test_repo_index_holds_symbols():
    sym = Symbol(
        id="app.py::main",
        kind=SymbolKind.FUNCTION,
        name="main",
        file="app.py",
        line_range=(1, 10),
        calls=[],
        imports=[],
    )
    idx = RepoIndex(
        source_root="/tmp/test-repo",
        commit_hash="abc123",
        symbols=[sym],
        files=["app.py"],
    )
    assert len(idx.symbols) == 1
    assert idx.files == ["app.py"]


def test_repo_map_three_layers():
    fmap = {"app.py": FileSummary(file="app.py", summary="应用入口", symbol_ids=["app.py::main"])}
    mmap = {"": ModuleSummary(path="", summary="根模块", file_count=1)}
    gmap = GlobalSummary(
        entry_points=["app.py::main"],
        core_modules=[""],
        dependency_summary="无外部依赖",
    )
    rm = RepoMap(global_summary=gmap, module_summaries=mmap, file_summaries=fmap)
    assert rm.file_summaries["app.py"].summary == "应用入口"


def test_citation_and_answer():
    c = Citation(file="app.py", line_range=(1, 10), symbol_id="app.py::main")
    a = Answer(
        text="main 是应用入口",
        citations=[c],
        complete=True,
    )
    assert a.citations[0].file == "app.py"
    assert a.complete is True


def test_snippet_basic():
    s = Snippet(
        file="app.py",
        line_range=(1, 10),
        text="def main(): pass",
        score=0.85,
        symbol_id="app.py::main",
    )
    assert s.file == "app.py"
    assert s.score == 0.85
    assert s.symbol_id == "app.py::main"


def test_snippet_optional_symbol_id():
    s = Snippet(file="app.py", line_range=(1, 10), text="x", score=0.5)
    assert s.symbol_id is None


def test_symbol_serialization_round_trip():
    """Symbol should survive model_dump + model_validate round-trip."""
    original = Symbol(
        id="fastapi:src/main.py:func_main",
        kind=SymbolKind.FUNCTION,
        name="main",
        file="src/main.py",
        line_range=(1, 10),
        calls=["uvicorn.run"],
        imports=["uvicorn"],
    )
    dumped = original.model_dump()
    restored = Symbol.model_validate(dumped)
    assert restored == original
    assert restored.line_range == (1, 10)
    assert restored.calls == ["uvicorn.run"]
    assert restored.imports == ["uvicorn"]


def test_repo_map_json_round_trip():
    """RepoMap should survive model_dump_json + model_validate_json round-trip."""
    original = RepoMap(
        global_summary=GlobalSummary(
            entry_points=["main"],
            core_modules=["src"],
            dependency_summary="Depends on uvicorn and starlette.",
        ),
        module_summaries={
            "src": ModuleSummary(path="src", summary="Top-level package.", file_count=1)
        },
        file_summaries={
            "src/main.py": FileSummary(
                file="src/main.py",
                summary="Entry point.",
                symbol_ids=["fastapi:src/main.py:func_main"],
            )
        },
    )
    json_str = original.model_dump_json()
    restored = RepoMap.model_validate_json(json_str)
    assert restored == original
    assert restored.file_summaries["src/main.py"].symbol_ids == ["fastapi:src/main.py:func_main"]
    assert restored.global_summary.core_modules == ["src"]


def test_line_range_accepts_tuple():
    """line_range tuple is accepted as given; behavior locked for downstream contract."""
    s = Symbol(
        id="x:f:fn",
        kind=SymbolKind.FUNCTION,
        name="fn",
        file="f.py",
        line_range=(10, 5),
    )
    # Pydantic accepts the tuple as given; we do not enforce start <= end here
    # (indexer guarantees ordering at construction time).
    assert s.line_range == (10, 5)
