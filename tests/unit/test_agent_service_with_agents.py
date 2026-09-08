# tests/unit/test_agent_service_with_agents.py
"""AgentService + 多 agent 集成单测。"""
from __future__ import annotations

from pathlib import Path

from taisang.agent_core.service import AgentService
from taisang.llm_client import MockLLM, LLMResponse


def _make_service(tmp_path: Path, agent_id: str = "", is_fork_child: bool = False) -> AgentService:
    llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    return AgentService(
        llm=llm,
        source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
        agent_id=agent_id,
        is_fork_child=is_fork_child,
    )


def test_service_has_agent_id_field(tmp_path: Path) -> None:
    """AgentService 实例带 agent_id 属性。"""
    svc = _make_service(tmp_path, agent_id="child-1")
    assert svc.agent_id == "child-1"


def test_service_has_is_fork_child_field(tmp_path: Path) -> None:
    """AgentService 实例带 is_fork_child 属性。"""
    svc = _make_service(tmp_path, is_fork_child=True)
    assert svc.is_fork_child is True


def test_service_has_pending_async_notifications(tmp_path: Path) -> None:
    """AgentService 实例带 _pending_async_notifications 队列。"""
    svc = _make_service(tmp_path)
    assert svc._pending_async_notifications == []


def test_flush_async_notifications_injects_user_message(tmp_path: Path) -> None:
    """flush_async_notifications 把队列里的通知 append_user 到 ctx。"""
    svc = _make_service(tmp_path)
    svc._pending_async_notifications.append("[子 agent 'explore' 完成]\n找到 3 个文件")
    svc.flush_async_notifications()
    # ctx 末尾应该有一条 user 消息含通知文本
    msgs = svc.ctx.messages()
    # system prompt 占第一条,append_user 后是 user 消息
    assert any(
        m.get("role") == "user" and "子 agent 'explore' 完成" in str(m.get("content", ""))
        for m in msgs
    )
    # 队列清空
    assert svc._pending_async_notifications == []


def test_flush_async_notifications_empty_noop(tmp_path: Path) -> None:
    """空队列 flush 不 append 任何消息。"""
    svc = _make_service(tmp_path)
    before = len(svc.ctx.messages())
    svc.flush_async_notifications()
    assert len(svc.ctx.messages()) == before


def test_main_loop_flushes_async_notifications_after_tool_results(tmp_path: Path) -> None:
    """主循环在本轮 tool_result append 完后自动 flush_async_notifications。

    用脚本化 MockLLM:第 1 步调一个无副作用工具(返回 ok),第 2 步给最终答案。
    在 tool 执行前塞一条 async 通知到队列,验证下轮 LLM 调用时 ctx 含通知 user 消息。
    """
    from taisang.agent_core.events import AgentEvent, TOOL_CALL, FINAL_ANSWER
    llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Glob", "arguments": '{"pattern": "*.py"}'}
        }]),
        LLMResponse(text="done", tool_calls=[]),
    ])
    svc = AgentService(llm=llm, source_root=tmp_path, confirmer=lambda *a, **kw: True)
    # 在 run 之前塞一条 async 通知
    svc._pending_async_notifications.append("[子 agent 'explore' 完成]\n找到 utils.py")
    events: list[AgentEvent] = []
    answer = svc.run("test query", on_event=lambda e: events.append(e))
    # 验证通知被 flush 进 ctx(下轮 LLM 看到了)
    msgs = svc.ctx.messages()
    has_notification = any(
        m.get("role") == "user" and "子 agent 'explore' 完成" in str(m.get("content", ""))
        for m in msgs
    )
    assert has_notification, "async 通知应该被 flush 进 ctx"
    assert answer.text == "done"


def test_main_agent_can_dispatch_subagent_via_agent_tool(tmp_path: Path) -> None:
    """主 agent 调 Agent 工具派 explore 子 agent,子 agent 返回结果作为 tool_result,
    主 agent 收到后给最终答案。"""
    from taisang.agent_core.events import AgentEvent, TOOL_CALL, TOOL_RESULT, FINAL_ANSWER
    from taisang.agents.types import AgentDefinition
    # 子 agent 的 MockLLM:返回"找到 utils.py"
    child_llm = MockLLM([LLMResponse(text="找到 utils.py", tool_calls=[])])
    # 主 agent 的 MockLLM:第 1 步调 Agent 工具,第 2 步给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "找 utils", "prompt": "找 utils 文件", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="根据子 agent 报告,utils.py 找到了", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        explore = AgentDefinition(
            agent_type="explore", when_to_use="搜索",
            disallowed_tools=["Edit", "Write", "Agent"], max_turns=10,
            base_dir=tmp_path, system_prompt="You are a search agent.",
        )
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[explore],
        )
        events: list[AgentEvent] = []
        answer = svc.run("帮我找 utils 文件", on_event=lambda e: events.append(e))
        # 主 agent 给最终答案
        assert "utils.py" in answer.text
        # 事件流含 Agent 工具调用
        tool_calls = [e for e in events if e.type == TOOL_CALL]
        assert any(e.payload.get("name") == "Agent" for e in tool_calls)
    finally:
        import taisang.agent_core.agent_tool as at_mod2
        import taisang.llm_client
        at_mod2._make_child_llm = lambda parent_llm: parent_llm