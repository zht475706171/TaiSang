from pathlib import Path
from taisang.agent_core.skill_tool import SkillTool
from taisang.agent_core.context import ContextManager
from taisang.skills.types import Skill


def test_skill_not_found():
    tool = SkillTool(skills=[], ctx=None)
    result = tool.run({"skill": "missing"})
    assert result["error"] == "skill not found"


def test_disabled_skill_returns_error():
    s = Skill(name="x", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user", disabled=True)
    tool = SkillTool(skills=[s], ctx=None)
    result = tool.run({"skill": "x"})
    assert result["error"] == "skill disabled"


def test_normal_call_injects_user_message_on_flush():
    """run() 只入队,flush() 才 append_user(延迟注入保证消息序)。"""
    s = Skill(name="commit", description="d", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="调用 git commit", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    result = tool.run({"skill": "commit"})
    assert result["ok"] is True
    assert result["injected"] is True
    # run 后未 flush:ctx 还没有注入
    assert not [m for m in ctx.messages() if m["role"] == "user"]
    tool.flush()
    msgs = ctx.messages()
    assert any("调用 git commit" in m.get("content", "") for m in msgs if m["role"] == "user")


def test_run_without_flush_keeps_pending():
    """ctx 为 None 时 run 正常,pending 滞留不报错,flush 清空。"""
    s = Skill(name="x", description="d", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="body", source="user")
    tool = SkillTool(skills=[s], ctx=None)
    result = tool.run({"skill": "x"})
    assert result["ok"] is True
    assert len(tool.pending) == 1
    tool.flush()  # ctx=None,清空不报错
    assert tool.pending == []


def test_skill_dir_substitution():
    s = Skill(name="r", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("C:/some/dir"), content="读 ${TAISANG_SKILL_DIR}/a.txt", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r"})
    tool.flush()
    msgs = ctx.messages()
    injected = [m["content"] for m in msgs if m["role"] == "user"][-1]
    assert "C:/some/dir/a.txt" in injected
    assert "${TAISANG_SKILL_DIR}" not in injected


def test_allowed_tools_hint():
    s = Skill(name="r", description="d", when_to_use="",
              allowed_tools=["Bash", "Read"], dir_path=Path("."), content="body", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r"})
    tool.flush()
    injected = [m["content"] for m in ctx.messages() if m["role"] == "user"][-1]
    assert "只允许使用以下工具: Bash, Read" in injected


def test_args_passed_through():
    s = Skill(name="r", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r", "args": "fix bug #123"})
    tool.flush()
    injected = [m["content"] for m in ctx.messages() if m["role"] == "user"][-1]
    assert "fix bug #123" in injected


def test_tool_registry_registers_skill_tool():
    from taisang.agent_core.tools import ToolRegistry
    s = Skill(name="x", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user")
    reg = ToolRegistry(cwd=Path("."), skills=[s], ctx=None)
    schemas = reg.schemas()
    names = [sch["name"] for sch in schemas]
    assert "skill" in names


def test_tool_registry_without_skills_no_skill_tool():
    """向后兼容:不传 skills 时 ToolRegistry 不注册 SkillTool。"""
    from taisang.agent_core.tools import ToolRegistry
    reg = ToolRegistry(cwd=Path("."))
    schemas = reg.schemas()
    names = [sch["name"] for sch in schemas]
    assert "skill" not in names