"""测试 Agent 工具。"""

from pathlib import Path

from taisang.agent_core.permission import AutoApprovePermissionManager
from taisang.agent_core.tools import (
    GlobTool,
    GrepTool,
    ReadFileTool,
    ToolRegistry,
)


def _perm(tmp_path):
    """构造 AutoApprove 权限器(tmp_path 已批准)。测试不问用户。"""
    return AutoApprovePermissionManager(initial_dirs=[tmp_path])


def test_read_file_tool(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = ReadFileTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"path": "a.py"})
    assert "def foo" in result["content"]
    assert result["error"] is None


def test_read_file_tool_missing_file(tmp_path):
    tool = ReadFileTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"path": "nope.py"})
    assert result["error"] is not None
    assert "not found" in result["error"].lower()


def test_grep_tool(tmp_path):
    (tmp_path / "a.py").write_text(
        "def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8"
    )
    tool = GrepTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"pattern": "def foo", "scope": "a.py"})
    assert len(result["matches"]) == 1
    assert result["matches"][0]["line"] == 1


def test_grep_tool_truncates_large_results(tmp_path):
    (tmp_path / "big.py").write_text("\n".join(f"x = {i}" for i in range(1000)), encoding="utf-8")
    tool = GrepTool(cwd=tmp_path, permission=_perm(tmp_path), max_matches=100)
    result = tool.run({"pattern": "x = ", "scope": "big.py"})
    assert len(result["matches"]) == 100
    assert result["truncated"] is True


def test_glob_tool(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    tool = GlobTool(cwd=tmp_path, permission=_perm(tmp_path))
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
        shell=shell,
    )
    result = reg.call("glob", {"pattern": "*.nonexistent"})
    assert isinstance(result, dict)
    assert "matches" in result
    shell.close()


def test_read_file_tool_rejects_path_traversal(tmp_path):
    """read_file 路径含 ../../ 应被权限器拒,返回 permission denied。
    AutoDeny 模拟:tmp_path 外的目录不批准 → check 返回 False。
    """
    from taisang.agent_core.permission import AutoDenyPermissionManager

    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    # AutoDeny 只对已批准目录放行;tmp_path 在 initial_dirs 里所以放行,
    # 但 ../../etc/passwd 解析到 tmp_path 外,project root 不在已批准 → 拒。
    # 不过 AutoDeny._ask 无脑拒,所以 tmp_path 外的路径必拒。
    tool = ReadFileTool(cwd=tmp_path, permission=AutoDenyPermissionManager(initial_dirs=[tmp_path]))
    result = tool.run({"path": "../../etc/passwd"})
    assert result["content"] == ""
    assert result["error"] is not None
    assert "permission denied" in result["error"]


def test_grep_tool_rejects_path_traversal_scope(tmp_path):
    """grep 的 scope 含 ../../ 应被权限器拒,glob + fallback 都不应越界访问。"""
    from taisang.agent_core.permission import AutoDenyPermissionManager

    tool = GrepTool(cwd=tmp_path, permission=AutoDenyPermissionManager(initial_dirs=[tmp_path]))
    # scope 作为 glob 模式,../../etc/* 不应在 tmp_path 内命中任何文件
    result = tool.run({"pattern": "anything", "scope": "../../etc/*"})
    # 关键:不崩,matches 为空(traversal 被拒或不命中)
    assert result["matches"] == []
    # glob 模式的 parent 目录不被批准 → 返回 error
    assert result["error"] is not None
    assert "permission denied" in result["error"]


def test_grep_tool_bad_regex_returns_error(tmp_path):
    """grep 的 pattern 是非法正则,应返回 bad regex 错误而非崩溃。"""
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    tool = GrepTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"pattern": "(a+", "scope": "a.py"})
    assert result["matches"] == []
    assert result["error"] is not None
    assert "bad regex" in result["error"]


def test_glob_truncates_at_100(tmp_path):
    """Glob 匹配 >100 文件应硬切到 100,truncated=True,note 含提示。"""
    for i in range(150):
        (tmp_path / f"f{i:03d}.py").write_text("x", encoding="utf-8")
    tool = GlobTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"pattern": "*.py"})
    assert len(result["matches"]) == 100
    assert result["truncated"] is True
    assert "truncated" in result["note"].lower()


def test_glob_not_truncated_under_limit(tmp_path):
    """Glob 匹配 <=100 文件应 truncated=False,无 note 键。"""
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
    tool = GlobTool(cwd=tmp_path, permission=_perm(tmp_path))
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
    tool = ReadFileTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"path": "big.py", "limit": 5})
    assert result["error"] is None
    assert result["truncated"] is False  # 走 limit 分支,不走字节闸门
    assert result["total_lines"] == 400
    assert result["limit"] == 5  # 要 5 行拿到 5 行
    assert result["content"].count("\n") == 4  # 5 行拼回有 4 个换行


def test_read_with_offset(tmp_path):
    """offset=3 limit=2 应返回第 3-4 行。"""
    (tmp_path / "a.py").write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    tool = ReadFileTool(cwd=tmp_path, permission=_perm(tmp_path))
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
    tool = GrepTool(cwd=tmp_path, permission=_perm(tmp_path))
    result = tool.run({"pattern": "a+", "scope": "min.py"})
    assert result["matches"] == []
    assert result["error"] is None


# --- ToolRegistry cancel_event 中断检查 ---

def test_tool_registry_call_raises_interrupted_when_cancel_set(tmp_path):
    """cancel_event set 时,ToolRegistry.call 抛 InterruptedError。"""
    import threading
    import pytest

    from taisang.agent_core.tools import ToolRegistry

    cancel = threading.Event()
    cancel.set()
    registry = ToolRegistry(cwd=tmp_path, cancel_event=cancel)
    with pytest.raises(InterruptedError, match="cancelled"):
        registry.call("read_file", {"path": "x.py"})


def test_tool_registry_call_normal_when_cancel_not_set(tmp_path):
    """cancel_event 未 set 时,ToolRegistry.call 正常执行(不抛 InterruptedError)。"""
    import threading

    from taisang.agent_core.tools import ToolRegistry

    cancel = threading.Event()
    registry = ToolRegistry(cwd=tmp_path, cancel_event=cancel)
    result = registry.call("read_file", {"path": "nonexistent.py"})
    assert "error" in result


def test_tool_registry_cancel_event_default_none(tmp_path):
    """cancel_event 默认 None(向后兼容)。"""
    from taisang.agent_core.tools import ToolRegistry

    registry = ToolRegistry(cwd=tmp_path)
    assert registry._cancel_event is None
    result = registry.call("read_file", {"path": "nonexistent.py"})
    assert "error" in result


def test_tool_registry_call_passes_cancel_event_to_bash(tmp_path):
    """ToolRegistry.call 把 cancel_event 透传给 BashTool.run,执行中 set 能中断。

    对标 Claude Code:cancel 信号贯穿全链路,工具执行中也能被 kill。
    """
    import threading
    import time
    import pytest
    from taisang.agent_core.tools import ToolRegistry
    from taisang.agent_core.shell import PipeShell
    from taisang.storage.paths import PathManager

    shell = PipeShell(cwd=tmp_path)
    try:
        cancel = threading.Event()
        registry = ToolRegistry(
            cwd=tmp_path,
            shell=shell,
            cancel_event=cancel,
            bash_timeout=30,
            observations_dir=PathManager.observations_dir(tmp_path),
        )
        result_holder = {}
        def _run():
            try:
                result_holder["result"] = registry.call(
                    "Bash",
                    {"command": 'python -c "import time; time.sleep(20)"'},
                )
            except Exception as e:
                result_holder["error"] = e
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.5)
        cancel.set()
        t.join(timeout=5)
        assert not t.is_alive(), "Bash should be interrupted"
        # InterruptedError 被 ToolRegistry.call 透传
        assert isinstance(result_holder.get("error"), InterruptedError)
    finally:
        shell.close()


def test_tool_registry_call_non_bash_tools_dont_get_cancel_event(tmp_path):
    """非 Bash 工具(无 cancel_event 参数)正常调用,不因 inspect 检查报错。"""
    import threading
    from taisang.agent_core.tools import ToolRegistry

    cancel = threading.Event()
    registry = ToolRegistry(cwd=tmp_path, cancel_event=cancel)
    # read_file 无 cancel_event 参数,应正常执行不报错
    result = registry.call("read_file", {"path": "nonexistent.py"})
    assert "error" in result
    assert "InterruptedError" not in str(result)


def test_todo_write_tool_basic(tmp_path):
    """TodoWriteTool 基本行为:schema 校验 + 覆盖式更新 service.todos + emit 事件 + return observation。"""
    from taisang.agent_core.tools import TodoWriteTool, ToolRegistry
    from taisang.agent_core.events import TODO_UPDATE

    # 用一个最小 fake service 模拟 AgentService 的 todos + _emit_todo_update
    class FakeService:
        def __init__(self):
            self.todos = []
            self.emitted = []
        def _emit_todo_update(self, todos, agent_id=""):
            self.emitted.append((todos, agent_id))

    service = FakeService()
    tool = TodoWriteTool(service=service)

    # schema 结构校验
    schema = tool.schema()
    assert schema["name"] == "TodoWrite"
    assert schema["parameters"]["properties"]["todos"]["type"] == "array"
    status_enum = schema["parameters"]["properties"]["todos"]["items"]["properties"]["status"]["enum"]
    assert set(status_enum) == {"pending", "in_progress", "completed"}

    # 正常调用:覆盖式更新 + emit + return
    result = tool.run({"todos": [
        {"content": "读文件", "status": "in_progress", "activeForm": "正在读文件"},
        {"content": "总结", "status": "pending"},
    ]})
    assert result["ok"] is True
    assert result["count"] == 2
    assert len(service.todos) == 2
    assert service.todos[0]["content"] == "读文件"
    assert service.todos[0]["status"] == "in_progress"
    assert service.todos[0]["activeForm"] == "正在读文件"
    assert service.todos[1]["activeForm"] == ""  # 缺省 activeForm 为空串
    assert len(service.emitted) == 1
    assert service.emitted[0][0] == service.todos  # emit 全量快照
    assert service.emitted[0][1] == ""  # 主 agent_id 为空

    # 覆盖式:第二次调用替换整个列表
    result2 = tool.run({"todos": [{"content": "新任务", "status": "pending"}]})
    assert result2["count"] == 1
    assert len(service.todos) == 1
    assert service.todos[0]["content"] == "新任务"
    assert len(service.emitted) == 2

    # schema 校验:status 非法
    bad = tool.run({"todos": [{"content": "x", "status": "invalid"}]})
    assert "error" in bad
    # 非法不更新 todos
    assert len(service.todos) == 1
    assert len(service.emitted) == 2

    # schema 校验:缺 content
    bad2 = tool.run({"todos": [{"status": "pending"}]})
    assert "error" in bad2

    # schema 校验:todos 非数组
    bad3 = tool.run({"todos": "not array"})
    assert "error" in bad3


def test_tool_registry_registers_todo_write_tool(tmp_path):
    """ToolRegistry 传 service 时注册 TodoWriteTool,call 能正常调度。"""
    from taisang.agent_core.tools import ToolRegistry
    from taisang.agent_core.events import TODO_UPDATE

    class FakeService:
        def __init__(self):
            self.todos = []
            self.emitted = []
        def _emit_todo_update(self, todos, agent_id=""):
            self.emitted.append((todos, agent_id))

    service = FakeService()
    registry = ToolRegistry(cwd=tmp_path, service=service)
    assert "TodoWrite" in registry._tools  # noqa: SLF001

    # schema 包含 TodoWrite
    schemas = registry.schemas()
    names = [s["name"] for s in schemas]
    assert "TodoWrite" in names

    # call 调度
    result = registry.call("TodoWrite", {"todos": [{"content": "test", "status": "in_progress"}]})
    assert result["ok"] is True
    assert len(service.todos) == 1
    assert len(service.emitted) == 1


def test_tool_registry_without_service_does_not_register_todo_write(tmp_path):
    """ToolRegistry 不传 service 时不注册 TodoWrite(向后兼容)。"""
    from taisang.agent_core.tools import ToolRegistry

    registry = ToolRegistry(cwd=tmp_path)
    assert "TodoWrite" not in registry._tools  # noqa: SLF001


def test_base_tool_default_max_result_size_chars():
    """_BaseTool 子类默认 max_result_size_chars=100_000,可被覆写。"""
    from taisang.agent_core.tools import _BaseTool
    class _DummyTool(_BaseTool):
        name = "dummy"
    t = _DummyTool()
    assert t.max_result_size_chars == 100_000
