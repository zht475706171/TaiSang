"""测试 Agent 工具。"""

from pathlib import Path

from code_reader.agent_core.tools import (
    GlobTool,
    GrepTool,
    ReadFileTool,
    ToolRegistry,
)


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


def test_tool_registry_lists_schemas():
    """ToolRegistry 注册 6 个工具:
    read_file / grep / glob / Edit / Write / Bash。
    """
    reg = ToolRegistry(
        source_root=Path("."),
    )
    schemas = reg.schemas()
    names = {s["name"] for s in schemas}
    assert names == {
        "read_file",
        "grep",
        "glob",
        "Edit",
        "Write",
        "Bash",
    }


def test_tool_registry_dispatches():
    reg = ToolRegistry(
        source_root=Path("."),
    )
    result = reg.call("glob", {"pattern": "*.nonexistent"})
    assert isinstance(result, dict)
    assert "matches" in result


def test_read_file_tool_rejects_path_traversal(tmp_path):
    """read_file 路径含 ../../ 应被拒,返回 outside repo root 错误。"""
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    tool = ReadFileTool(source_root=tmp_path)
    result = tool.run({"path": "../../etc/passwd"})
    assert result["content"] == ""
    assert result["error"] is not None
    assert "outside repo root" in result["error"]


def test_grep_tool_rejects_path_traversal_scope(tmp_path):
    """grep 的 scope 含 ../../ 应被拒,glob + fallback 都不应越界访问。"""
    tool = GrepTool(source_root=tmp_path)
    # scope 作为 glob 模式,../../etc/* 不应在 tmp_path 内命中任何文件
    result = tool.run({"pattern": "anything", "scope": "../../etc/*"})
    # 关键:不崩,matches 为空(traversal 被拒或不命中)
    assert result["matches"] == []
    assert result["error"] is None


def test_grep_tool_bad_regex_returns_error(tmp_path):
    """grep 的 pattern 是非法正则,应返回 bad regex 错误而非崩溃。"""
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    tool = GrepTool(source_root=tmp_path)
    result = tool.run({"pattern": "(a+", "scope": "a.py"})
    assert result["matches"] == []
    assert result["error"] is not None
    assert "bad regex" in result["error"]
