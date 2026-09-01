"""测试 Agent 工具。"""

from pathlib import Path

from taisang.agent_core.tools import (
    GlobTool,
    GrepTool,
    ReadFileTool,
    ToolRegistry,
)


def test_read_file_tool(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = ReadFileTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"path": "a.py"})
    assert "def foo" in result["content"]
    assert result["error"] is None


def test_read_file_tool_missing_file(tmp_path):
    tool = ReadFileTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"path": "nope.py"})
    assert result["error"] is not None
    assert "not found" in result["error"].lower()


def test_grep_tool(tmp_path):
    (tmp_path / "a.py").write_text(
        "def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8"
    )
    tool = GrepTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"pattern": "def foo", "scope": "a.py"})
    assert len(result["matches"]) == 1
    assert result["matches"][0]["line"] == 1


def test_grep_tool_truncates_large_results(tmp_path):
    (tmp_path / "big.py").write_text("\n".join(f"x = {i}" for i in range(1000)), encoding="utf-8")
    tool = GrepTool(cwd=tmp_path, allow_dirs=[tmp_path], max_matches=100)
    result = tool.run({"pattern": "x = ", "scope": "big.py"})
    assert len(result["matches"]) == 100
    assert result["truncated"] is True


def test_glob_tool(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    tool = GlobTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"pattern": "*.py"})
    assert set(result["matches"]) == {"a.py", "b.py"}


def test_tool_registry_lists_schemas():
    """ToolRegistry 注册 6 个工具:
    read_file / grep / glob / Edit / Write / Bash。
    """
    from taisang.agent_core.shell import PipeShell

    shell = PipeShell(cwd=Path("."))
    reg = ToolRegistry(
        cwd=Path("."),
        allow_dirs=[Path(".")],
        shell=shell,
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
    shell.close()


def test_tool_registry_dispatches():
    from taisang.agent_core.shell import PipeShell

    shell = PipeShell(cwd=Path("."))
    reg = ToolRegistry(
        cwd=Path("."),
        allow_dirs=[Path(".")],
        shell=shell,
    )
    result = reg.call("glob", {"pattern": "*.nonexistent"})
    assert isinstance(result, dict)
    assert "matches" in result
    shell.close()


def test_read_file_tool_rejects_path_traversal(tmp_path):
    """read_file 路径含 ../../ 应被拒,返回 outside allowed dirs 错误。"""
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    tool = ReadFileTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"path": "../../etc/passwd"})
    assert result["content"] == ""
    assert result["error"] is not None
    assert "outside allowed dirs" in result["error"]


def test_grep_tool_rejects_path_traversal_scope(tmp_path):
    """grep 的 scope 含 ../../ 应被拒,glob + fallback 都不应越界访问。"""
    tool = GrepTool(cwd=tmp_path, allow_dirs=[tmp_path])
    # scope 作为 glob 模式,../../etc/* 不应在 tmp_path 内命中任何文件
    result = tool.run({"pattern": "anything", "scope": "../../etc/*"})
    # 关键:不崩,matches 为空(traversal 被拒或不命中)
    assert result["matches"] == []
    assert result["error"] is None


def test_grep_tool_bad_regex_returns_error(tmp_path):
    """grep 的 pattern 是非法正则,应返回 bad regex 错误而非崩溃。"""
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    tool = GrepTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"pattern": "(a+", "scope": "a.py"})
    assert result["matches"] == []
    assert result["error"] is not None
    assert "bad regex" in result["error"]


def test_glob_truncates_at_100(tmp_path):
    """Glob 匹配 >100 文件应硬切到 100,truncated=True,note 含提示。"""
    for i in range(150):
        (tmp_path / f"f{i:03d}.py").write_text("x", encoding="utf-8")
    tool = GlobTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"pattern": "*.py"})
    assert len(result["matches"]) == 100
    assert result["truncated"] is True
    assert "truncated" in result["note"].lower()


def test_glob_not_truncated_under_limit(tmp_path):
    """Glob 匹配 <=100 文件应 truncated=False,无 note 键。"""
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
    tool = GlobTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"pattern": "*.py"})
    assert len(result["matches"]) == 10
    assert result["truncated"] is False
    assert "note" not in result


def test_read_with_limit_bypasses_byte_gate(tmp_path):
    """传 limit 时按行读,不走 32KB 字节闸门,返回 truncated=False。"""
    # 构造 >32KB 的文件(多行,确保 total_lines 足够;总字节数 >32KB)
    (tmp_path / "big.py").write_text(
        "\n".join("y" * 100 for _ in range(400)) + "\n", encoding="utf-8"
    )
    tool = ReadFileTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"path": "big.py", "limit": 5})
    assert result["error"] is None
    assert result["truncated"] is False  # 走 limit 分支,不走字节闸门
    assert result["total_lines"] == 400
    assert result["limit"] == 5  # 要 5 行拿到 5 行
    assert result["content"].count("\n") == 4  # 5 行拼回有 4 个换行


def test_read_with_offset(tmp_path):
    """offset=3 limit=2 应返回第 3-4 行。"""
    (tmp_path / "a.py").write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    tool = ReadFileTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"path": "a.py", "offset": 3, "limit": 2})
    assert result["error"] is None
    assert result["content"] == "line3\nline4"
    assert result["offset"] == 3
    assert result["limit"] == 2
    assert result["total_lines"] == 5  # splitlines 不含末尾空行 -> 5 行


def test_grep_skips_long_lines(tmp_path):
    """grep 应跳过 >500 字符的超长行(minified/base64),不匹配。"""
    long_line = "a" * 600  # 超 MAX_LINE_LENGTH=500
    (tmp_path / "min.py").write_text(long_line + "\n", encoding="utf-8")
    tool = GrepTool(cwd=tmp_path, allow_dirs=[tmp_path])
    result = tool.run({"pattern": "a+", "scope": "min.py"})
    assert result["matches"] == []
    assert result["error"] is None
