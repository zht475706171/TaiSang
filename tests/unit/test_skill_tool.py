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


def test_normal_call_injects_user_message():
    s = Skill(name="commit", description="d", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="调用 git commit", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    result = tool.run({"skill": "commit"})
    assert result["ok"] is True
    assert result["injected"] is True
    msgs = ctx.messages()
    assert any("调用 git commit" in m.get("content", "") for m in msgs if m["role"] == "user")


def test_skill_dir_substitution():
    s = Skill(name="r", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("C:/some/dir"), content="读 ${TAISANG_SKILL_DIR}/a.txt", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r"})
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
    injected = [m["content"] for m in ctx.messages() if m["role"] == "user"][-1]
    assert "只允许使用以下工具: Bash, Read" in injected


def test_args_passed_through():
    s = Skill(name="r", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r", "args": "fix bug #123"})
    injected = [m["content"] for m in ctx.messages() if m["role"] == "user"][-1]
    assert "fix bug #123" in injected