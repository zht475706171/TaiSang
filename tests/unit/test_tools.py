"""测试 Agent 5 工具。"""

from pathlib import Path

from code_reader.agent_core.tools import (
    GlobTool,
    GrepTool,
    LookupMapTool,
    ReadFileTool,
    ToolRegistry,
    TraceCallChainTool,
)
from code_reader.indexer.linker import CallGraphNode
from code_reader.types import FileSummary, GlobalSummary, RepoMap


def test_read_file_tool(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = ReadFileTool(source_root=tmp_path)
    result = tool.run({"path": "a.py"})
    assert "def foo" in result["content"]
    assert result["error"] is None


def test_read_file_tool_missing_file(tmp_path):
    tool = ReadFileTool(source_root=tmp_path)
    result = tool.run({"path": "nope.py"})
    assert result["error"] is not None
    assert "not found" in result["error"].lower()


def test_grep_tool(tmp_path):
    (tmp_path / "a.py").write_text(
        "def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8"
    )
    tool = GrepTool(source_root=tmp_path)
    result = tool.run({"pattern": "def foo", "scope": "a.py"})
    assert len(result["matches"]) == 1
    assert result["matches"][0]["line"] == 1


def test_grep_tool_truncates_large_results(tmp_path):
    (tmp_path / "big.py").write_text("\n".join(f"x = {i}" for i in range(1000)), encoding="utf-8")
    tool = GrepTool(source_root=tmp_path, max_matches=100)
    result = tool.run({"pattern": "x = ", "scope": "big.py"})
    assert len(result["matches"]) == 100
    assert result["truncated"] is True


def test_glob_tool(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    tool = GlobTool(source_root=tmp_path)
    result = tool.run({"pattern": "*.py"})
    assert set(result["matches"]) == {"a.py", "b.py"}


def test_trace_call_chain_tool():
    graph = {
        "a.py::a": CallGraphNode(
            "a.py::a",
            "a",
            "a.py",
            (1, 5),
            resolved_calls=["b.py::b"],
            unresolved_calls=[],
        ),
        "b.py::b": CallGraphNode(
            "b.py::b",
            "b",
            "b.py",
            (1, 5),
            resolved_calls=["c.py::c"],
            unresolved_calls=[],
        ),
        "c.py::c": CallGraphNode(
            "c.py::c",
            "c",
            "c.py",
            (1, 5),
            resolved_calls=[],
            unresolved_calls=[],
        ),
    }
    tool = TraceCallChainTool(call_graph=graph)
    result = tool.run({"symbol_id": "a.py::a", "depth": 2})
    assert result["chain"] == ["a.py::a", "b.py::b", "c.py::c"]


def test_trace_call_chain_unknown_symbol():
    tool = TraceCallChainTool(call_graph={})
    result = tool.run({"symbol_id": "unknown", "depth": 3})
    assert result["chain"] == []
    assert result["error"] is not None


def test_lookup_map_tool_file_layer():
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={
            "a.py": FileSummary(file="a.py", summary="a 文件摘要", symbol_ids=[]),
        },
    )
    tool = LookupMapTool(repo_map=rm)
    result = tool.run({"layer": "file", "query": "a"})
    assert "a.py" in result["text"]


def test_lookup_map_tool_global_layer():
    rm = RepoMap(
        global_summary=GlobalSummary(
            entry_points=["a.py::main"],
            core_modules=[""],
            dependency_summary="全局摘要",
        ),
        module_summaries={},
        file_summaries={},
    )
    tool = LookupMapTool(repo_map=rm)
    result = tool.run({"layer": "global", "query": ""})
    assert "全局摘要" in result["text"]
    assert "main" in result["text"]


def test_tool_registry_lists_schemas():
    reg = ToolRegistry(
        source_root=Path("."),
        call_graph={},
        repo_map=RepoMap(
            global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
            module_summaries={},
            file_summaries={},
        ),
    )
    schemas = reg.schemas()
    names = {s["name"] for s in schemas}
    assert names == {"read_file", "grep", "glob", "trace_call_chain", "lookup_map"}


def test_tool_registry_dispatches():
    reg = ToolRegistry(
        source_root=Path("."),
        call_graph={},
        repo_map=RepoMap(
            global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
            module_summaries={},
            file_summaries={},
        ),
    )
    result = reg.call("glob", {"pattern": "*.nonexistent"})
    assert isinstance(result, dict)
    assert "matches" in result
