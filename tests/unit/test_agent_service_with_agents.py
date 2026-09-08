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