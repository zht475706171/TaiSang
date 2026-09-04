"""Skill 端到端集成测试:AgentService 主循环 + SkillTool + system prompt 清单。

不走 HTTP,直接构造 AgentService:MockLLM 脚本化先调 skill 工具再给最终答案,
验证:system prompt 含 skill 清单 → LLM 调 skill → SKILL.md 注入 ctx 为 user
消息 → 主循环继续 → 最终答案。
"""

from pathlib import Path

from taisang.agent_core.service import AgentService
from taisang.llm_client import LLMResponse, MockLLM
from taisang.skills.types import Skill

_SKILL = Skill(
    name="commit",
    description="生成 commit message 并提交",
    when_to_use="用户说提交时",
    allowed_tools=["Bash", "Read"],
    dir_path=Path("C:/fake/skills/commit"),
    content="执行 git commit,模板见 ${TAISANG_SKILL_DIR}/template.txt",
    source="user",
)

_SKILL_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "skill", "arguments": '{"skill": "commit"}'},
}


def _tool_call_response() -> LLMResponse:
    return LLMResponse(text="", tool_calls=[_SKILL_CALL])


def test_agent_loop_invokes_skill_and_injects(tmp_path):
    """LLM 调 skill 工具 → SKILL.md 正文作为 user 消息注入 ctx → 主循环继续。"""
    mock = MockLLM([_tool_call_response(), LLMResponse(text="已提交", tool_calls=[])])
    svc = AgentService(
        llm=mock,
        source_root=tmp_path,
        confirmer=lambda *a: True,
        skills=[_SKILL],
    )

    # 1) system prompt 含 skill 清单
    sys_msgs = [m for m in svc.ctx.messages() if m["role"] == "system"]
    assert any("- commit: 生成 commit message 并提交 - 用户说提交时" in m["content"] for m in sys_msgs)

    answer = svc.run("帮我提交")

    # 2) 第一次 LLM 调用的 tools 里含 skill 工具
    first_call_tools = [t["name"] for t in mock.calls[0]["tools"]]
    assert "skill" in first_call_tools

    # 3) SKILL.md 正文作为 user 消息注入(allowed_tools 提示段 + 标题 + ${TAISANG_SKILL_DIR} 替换)
    user_msgs = [m["content"] for m in svc.ctx.messages() if m["role"] == "user"]
    injected = [c for c in user_msgs if "# Skill: commit" in c]
    assert len(injected) == 1
    assert "只允许使用以下工具: Bash, Read" in injected[0]
    assert "C:/fake/skills/commit/template.txt" in injected[0]
    assert "${TAISANG_SKILL_DIR}" not in injected[0]

    # 4) 主循环继续:第二次 LLM 调用能看到注入的消息,最终答案返回
    second_call_user_msgs = [
        m["content"] for m in mock.calls[1]["messages"]
        if m["role"] == "user" and "# Skill: commit" in m.get("content", "")
    ]
    assert len(second_call_user_msgs) == 1
    assert answer.complete is True
    assert answer.text == "已提交"


def test_agent_loop_disabled_skill_returns_error_observation(tmp_path):
    """disabled skill:SkillTool 返回 error observation,LLM 拿到错误继续。"""
    disabled = Skill(
        name="commit",
        description="d",
        when_to_use="",
        allowed_tools=None,
        dir_path=Path("."),
        content="body",
        source="user",
        disabled=True,
    )
    mock = MockLLM([_tool_call_response(), LLMResponse(text="skill 不可用", tool_calls=[])])
    svc = AgentService(
        llm=mock,
        source_root=tmp_path,
        confirmer=lambda *a: True,
        skills=[disabled],
    )

    answer = svc.run("帮我提交")

    # disabled skill 不进 system prompt 清单
    sys_msgs = [m for m in svc.ctx.messages() if m["role"] == "system"]
    assert all("commit" not in m["content"] for m in sys_msgs if "可用 Skills" in m["content"])

    # 但 skill 工具仍注册(LLM 可能仍尝试调),返回 error observation
    tool_msgs = [m for m in svc.ctx.messages() if m["role"] == "tool"]
    assert any("skill disabled" in m["content"] for m in tool_msgs)
    assert answer.complete is True
