from pathlib import Path
from taisang.skills.listing import format_skill_listing
from taisang.skills.types import Skill


def test_listing_format():
    skills = [
        Skill(name="commit", description="生成 commit", when_to_use="用户说提交时",
              allowed_tools=None, dir_path=Path("."), content="", source="user"),
        Skill(name="review", description="代码审查", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="project"),
    ]
    listing = format_skill_listing(skills, char_budget=2000)
    assert "- commit: 生成 commit - 用户说提交时" in listing
    assert "- review: 代码审查" in listing


def test_listing_truncates_long_description():
    long_desc = "x" * 300
    skills = [
        Skill(name="r", description=long_desc, when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="user")
    ]
    listing = format_skill_listing(skills, char_budget=2000)
    assert "…" in listing
    assert len(long_desc) > 250  # 确认原始就长


def test_listing_over_budget_falls_back_to_names_only():
    # 造大量 skill 触发降级
    skills = [
        Skill(name=f"s{i}", description="d" * 200, when_to_use="w" * 200,
              allowed_tools=None, dir_path=Path("."), content="", source="user")
        for i in range(100)
    ]
    listing = format_skill_listing(skills, char_budget=500)
    assert "- s0" in listing  # 至少有名字
    # 不应含完整 description
    assert "d" * 200 not in listing


def test_listing_empty_skills():
    assert format_skill_listing([], char_budget=2000) == ""


def test_listing_disabled_skills_excluded():
    skills = [
        Skill(name="a", description="da", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="user",
              disabled=False),
        Skill(name="b", description="db", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="user",
              disabled=True),
    ]
    listing = format_skill_listing(skills, char_budget=2000)
    assert "- a: da" in listing
    assert "- b:" not in listing
    assert "db" not in listing


def test_service_system_prompt_contains_skills():
    from unittest.mock import MagicMock
    from taisang.agent_core.service import AgentService

    skills = [
        Skill(name="commit", description="生成 commit", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="user")
    ]
    llm = MagicMock()
    llm.chat.return_value = MagicMock(tool_calls=None, text="done", usage=None)
    svc = AgentService(llm=llm, source_root=Path("."), confirmer=lambda *a: True,
                       skills=skills)
    sys_msgs = [m for m in svc.ctx.messages() if m["role"] == "system"]
    assert any("commit" in m["content"] for m in sys_msgs)