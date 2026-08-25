"""测试分层摘要:用 MockLLM 避免真调 API。"""

from code_reader.llm_client import LLMResponse, MockLLM
from code_reader.summarizer.prompts import build_file_summary_prompt
from code_reader.summarizer.service import SummarizerService
from code_reader.types import RepoIndex, Symbol, SymbolKind


def _idx(symbols, files=None) -> RepoIndex:
    return RepoIndex(
        source_root="https://github.com/test/repo",
        commit_hash="abc",
        symbols=symbols,
        files=files or [s.file for s in symbols],
    )


def _sym(id_, name, file, line=1, calls=None, imports=None):
    return Symbol(
        id=id_,
        kind=SymbolKind.FUNCTION,
        name=name,
        file=file,
        line_range=(line, line + 5),
        calls=calls or [],
        imports=imports or [],
    )


def test_build_file_summary_prompt_contains_source_and_symbols():
    prompt = build_file_summary_prompt(
        rel_path="a.py",
        source="def foo():\n    return 1\n",
        symbols=[_sym("a.py::foo", "foo", "a.py")],
    )
    assert "def foo" in prompt
    assert "foo" in prompt
    assert "a.py" in prompt


def test_summarize_file_uses_llm_response(tmp_path):
    mock = MockLLM([LLMResponse(text="这是 a.py 的摘要:定义 foo 函数返回 1", tool_calls=[])])
    service = SummarizerService(llm=mock)
    idx = _idx([_sym("a.py::foo", "foo", "a.py")])
    # 需要源码,用一个临时文件
    src_file = tmp_path / "a.py"
    src_file.write_text("def foo():\n    return 1\n", encoding="utf-8")
    repo_map = service.summarize(idx, source_root=tmp_path)
    assert "a.py" in repo_map.file_summaries
    assert "foo" in repo_map.file_summaries["a.py"].summary


def test_summarize_file_failure_skips_and_records(tmp_path):
    """LLM 调用失败应跳过文件,不崩。"""

    class FailingLLM:
        def chat(self, messages, tools):
            raise RuntimeError("API down")

    service = SummarizerService(llm=FailingLLM())
    idx = _idx([_sym("a.py::foo", "foo", "a.py")])
    src_file = tmp_path / "a.py"
    src_file.write_text("def foo():\n    return 1\n", encoding="utf-8")
    # 不应抛异常
    repo_map = service.summarize(idx, source_root=tmp_path)
    # 该文件没有摘要
    assert "a.py" not in repo_map.file_summaries
    # 失败被记录
    assert any(e["file"] == "a.py" for e in service.errors)


def test_summarize_module_level_aggregates_files(tmp_path):
    """同目录的文件摘要聚合到模块级。"""
    mock = MockLLM(
        [
            LLMResponse(text="a.py 摘要", tool_calls=[]),
            LLMResponse(text="b.py 摘要", tool_calls=[]),
            LLMResponse(text="根模块聚合:含 a 和 b 两个文件", tool_calls=[]),
        ]
    )
    service = SummarizerService(llm=mock)
    idx = _idx(
        [
            _sym("a.py::foo", "foo", "a.py"),
            _sym("b.py::bar", "bar", "b.py"),
        ],
        files=["a.py", "b.py"],
    )
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    repo_map = service.summarize(idx, source_root=tmp_path)
    # 根模块 "" 应有摘要
    assert "" in repo_map.module_summaries
    assert repo_map.module_summaries[""].file_count == 2


def test_summarize_global_level(tmp_path):
    """全局级摘要应包含入口点。"""
    mock = MockLLM(
        [
            LLMResponse(text="a.py 摘要,定义 main", tool_calls=[]),
            LLMResponse(text="根模块", tool_calls=[]),
            LLMResponse(text="全局:入口是 main,依赖无", tool_calls=[]),
        ]
    )
    service = SummarizerService(llm=mock)
    idx = _idx([_sym("a.py::main", "main", "a.py")], files=["a.py"])
    (tmp_path / "a.py").write_text("def main():\n    pass\n", encoding="utf-8")
    repo_map = service.summarize(idx, source_root=tmp_path)
    assert "main" in repo_map.global_summary.entry_points


def test_file_summary_not_truncated_to_200(tmp_path):
    """LLM 返回 600 字摘要,终值不应被切到 200 字。"""
    from code_reader.llm_client import LLMResponse, MockLLM
    from code_reader.summarizer.service import SummarizerService
    from code_reader.types import RepoIndex, Symbol

    long_summary = "x" * 600  # 600 字
    mock = MockLLM([LLMResponse(text=long_summary, tool_calls=[])])
    service = SummarizerService(llm=mock)
    src = tmp_path / "a.py"
    src.write_text("def f():\n    pass\n", encoding="utf-8")
    idx = RepoIndex(
        source_root=str(tmp_path),
        commit_hash="x",
        symbols=[
            Symbol(
                id="a.py::f",
                kind="function",
                name="f",
                file="a.py",
                line_range=(1, 2),
                calls=[],
                imports=[],
            )
        ],
        files=["a.py"],
        index_errors=[],
    )
    repo_map = service.summarize(idx, source_root=tmp_path)
    assert len(repo_map.file_summaries["a.py"].summary) == 600
