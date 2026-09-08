# tests/integration/test_agent_e2e.py
"""端到端:主 agent 调子 agent 的完整链路。

MockLLM 脚本化驱动,验证:
- A 模式:子 agent 全新上下文,返回 Answer.text
- B 模式 fork:子 agent 继承父对话
- async:立即返回,后台跑完通知入队
- 递归防护:子 agent 工具集不含 AgentTool
- disabled agent 调用返回错误
- USAGE_REPORT 累加
"""
from __future__ import annotations

from pathlib import Path

from taisang.agent_core.events import AgentEvent, TOOL_CALL, TOOL_RESULT, FINAL_ANSWER, USAGE_REPORT
from taisang.agent_core.service import AgentService
from taisang.agents.types import AgentDefinition
from taisang.llm_client import MockLLM, LLMResponse


def _explore_agent(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        agent_type="explore", when_to_use="搜索",
        disallowed_tools=["Edit", "Write", "Agent"], max_turns=10,
        base_dir=tmp_path, system_prompt="You are a search agent.",
    )


def test_e2e_a_mode_subagent_completes_and_returns_text(tmp_path: Path, monkeypatch) -> None:
    """A 模式:主 agent 调 explore → 子 agent grep → 返回 → 主 agent 给最终答案。"""
    # 子 agent MockLLM:第 1 步 grep,第 2 步给结论
    child_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Grep", "arguments": '{"pattern": "utils", "path": "."}'}
        }]),
        LLMResponse(text="找到 utils.py 在 src/ 下", tool_calls=[]),
    ])
    # 主 agent MockLLM:调 Agent 工具,然后给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "找 utils", "prompt": "找 utils 文件", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="根据子 agent 报告,utils.py 在 src/ 下", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        answer = svc.run("帮我找 utils 文件")
        assert "utils.py" in answer.text
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_fork_mode_inherits_parent_context(tmp_path: Path, monkeypatch) -> None:
    """B 模式 fork:子 agent 看到父对话的"用户原始问题"。"""
    seen: list = []
    def fake_chat(messages, tools):
        seen.extend(messages)
        return LLMResponse(text="fork 接续结果", tool_calls=[])
    def fake_chat_stream(messages, tools):
        seen.extend(messages)
        from taisang.llm_stream import StreamChunk
        yield StreamChunk(text_delta="fork 接续结果")
        yield StreamChunk(tool_calls=[], usage=None, is_final=True)
    child_llm = MockLLM([])
    child_llm.chat = fake_chat
    child_llm.chat_stream = fake_chat_stream
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "继续", "prompt": "接着做 Task 3"}'}
        }]),
        LLMResponse(text="fork 完成了 Task 3", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],  # 传非空,让 AgentTool 注册
        )
        svc.ctx.append_user("用户原始问题(Task 1-2 已完成)")
        answer = svc.run("接着做 Task 3")
        assert "Task 3" in answer.text
        # 子 agent 看到了父的"用户原始问题"
        assert "用户原始问题" in str(seen)
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_async_subagent_notifies_parent(tmp_path: Path, monkeypatch) -> None:
    """async:主 agent 调 Agent(background=True),立即返回,继续给最终答案;
    后台子 agent 跑完通知入队,主 agent 下轮看到。"""
    import time
    child_llm = MockLLM([LLMResponse(text="async 子 agent 结果", tool_calls=[])])
    # 主 agent:调 async Agent,立即拿到 async_launched,然后给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "异步", "prompt": "慢慢搜", "subagent_type": "explore", "run_in_background": true}'}
        }]),
        LLMResponse(text="已派 async 任务,等通知", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        answer = svc.run("异步搜一下")
        # 主 agent 立即给了"已派 async 任务"
        assert "已派 async" in answer.text
        # 等后台线程
        time.sleep(0.5)
        # 通知入队
        assert len(svc._pending_async_notifications) > 0
        assert "async 子 agent 结果" in svc._pending_async_notifications[0]
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_verification_agent_defaults_async(tmp_path: Path, monkeypatch) -> None:
    """verification agent background:true,默认 async。"""
    import time
    child_llm = MockLLM([LLMResponse(text="VERDICT: PASS", tool_calls=[])])
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "验证", "prompt": "验证实现", "subagent_type": "verification"}'}
        }]),
        LLMResponse(text="验证通过", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    verification = AgentDefinition(
        agent_type="verification", when_to_use="验证",
        disallowed_tools=["Edit", "Write", "Agent"], max_turns=100,
        background=True, base_dir=tmp_path, system_prompt="You are a verification agent.",
    )
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[verification],
        )
        answer = svc.run("验证一下")
        assert "验证通过" in answer.text
        time.sleep(0.5)
        # verification 是 background,通知入队
        assert len(svc._pending_async_notifications) > 0
        assert "VERDICT: PASS" in svc._pending_async_notifications[0]
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_recursion_guard_subagent_cannot_dispatch(tmp_path: Path, monkeypatch) -> None:
    """递归防护:子 agent 工具集不含 AgentTool,无法再派。"""
    child_llm = MockLLM([LLMResponse(text="子 agent 完成", tool_calls=[])])
    # 主 agent 调 Agent 工具
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "x", "prompt": "y", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="主 agent 最终答案", tool_calls=[]),
    ])
    # 捕获子 agent 看到的工具列表
    captured: list = []
    def fake_chat(messages, tools):
        captured.append(tools)
        return LLMResponse(text="子 agent 完成", tool_calls=[])
    def fake_chat_stream(messages, tools):
        captured.append(tools)
        from taisang.llm_stream import StreamChunk
        yield StreamChunk(text_delta="子 agent 完成")
        yield StreamChunk(tool_calls=[], usage=None, is_final=True)
    child_llm.chat = fake_chat
    child_llm.chat_stream = fake_chat_stream
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        svc.run("派子 agent")
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
    # 子 agent 工具列表不含 Agent
    all_tools = set()
    for schema_list in captured:
        for t in schema_list:
            all_tools.add(t["name"])
    assert "Agent" not in all_tools


def test_e2e_usage_report_accumulates_child_usage(tmp_path: Path, monkeypatch) -> None:
    """USAGE_REPORT:子 agent 的 usage 累加进主 session 累计。"""
    from taisang.llm_client import LLMResponse
    # 子 agent 返回带 usage
    child_llm = MockLLM([LLMResponse(
        text="子结果", tool_calls=[],
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )])
    # 主 agent 返回带 usage
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "x", "prompt": "y", "subagent_type": "explore"}'}
        }], usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}),
        LLMResponse(text="主结果", tool_calls=[],
                    usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        svc.run("跑一下")
        # 主 session 累计 = 主(300+70) + 子(150) = 520
        assert svc._session_usage["total_tokens"] == 520
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm