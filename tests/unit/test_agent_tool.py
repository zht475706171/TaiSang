# tests/unit/test_agent_tool.py
"""AgentTool 单测。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from taisang.agent_core.agent_tool import AgentTool
from taisang.agent_core.context import ContextManager
from taisang.agent_core.service import AgentService
from taisang.agents.types import AgentDefinition
from taisang.llm_client import MockLLM, LLMResponse


def _make_parent_service(tmp_path: Path, agents: list[AgentDefinition]) -> AgentService:
    """建主 AgentService,带 agents 列表(供 AgentTool 用)。"""
    llm = MockLLM([LLMResponse(text="parent final", tool_calls=[])])
    return AgentService(
        llm=llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
        agents=agents,
    )


def _make_explore_agent() -> AgentDefinition:
    """建一个测试用 explore agent 定义。"""
    return AgentDefinition(
        agent_type="explore",
        when_to_use="搜索",
        tools=None,
        disallowed_tools=["Edit", "Write", "Agent"],
        max_turns=20,
        base_dir=Path("/tmp"),
        system_prompt="You are a search agent.",
    )


def test_agent_tool_a_mode_sync_returns_child_answer(tmp_path: Path) -> None:
    """A 模式 sync:子 agent 跑完返回 Answer.text 作为 tool_result。"""
    agents = [_make_explore_agent()]
    parent = _make_parent_service(tmp_path, agents)
    child_llm = MockLLM([LLMResponse(text="找到 3 个文件", tool_calls=[])])
    import taisang.agent_core.agent_tool as at_mod
    original_make = at_mod._make_child_llm
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=agents,
            parent_service=parent,
            source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({
            "description": "找 utils",
            "prompt": "找项目里的 utils 文件",
            "subagent_type": "explore",
        })
    finally:
        at_mod._make_child_llm = original_make
    assert result["text"] == "找到 3 个文件"
    assert result["agent_type"] == "explore"


def test_agent_tool_a_mode_agent_not_found(tmp_path: Path) -> None:
    """A 模式:agent_type 找不到 → tool_result error。"""
    agents = [_make_explore_agent()]
    parent = _make_parent_service(tmp_path, agents)
    tool = AgentTool(
        agents=agents, parent_service=parent, source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
    )
    result = tool.run({
        "description": "bad", "prompt": "x", "subagent_type": "nonexistent",
    })
    assert "error" in result
    assert "nonexistent" in result["error"]


def test_agent_tool_a_mode_disabled_agent(tmp_path: Path) -> None:
    """A 模式:disabled agent → tool_result error。"""
    a = _make_explore_agent()
    a.disabled = True
    parent = _make_parent_service(tmp_path, [a])
    tool = AgentTool(
        agents=[a], parent_service=parent, source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
    )
    result = tool.run({
        "description": "x", "prompt": "y", "subagent_type": "explore",
    })
    assert "error" in result
    assert "disabled" in result["error"]


def test_agent_tool_b_mode_fork_inherits_parent_messages(tmp_path: Path) -> None:
    """B 模式 fork:子 agent 深拷贝父 messages,看得到父对话历史。"""
    parent = _make_parent_service(tmp_path, [])
    parent.ctx.append_user("用户原始问题")
    parent.ctx.append_assistant(text="我正在处理", tool_calls=None)
    seen_messages: list = []
    def fake_chat(messages, tools):
        seen_messages.extend(messages)
        return LLMResponse(text="fork 结果", tool_calls=[])
    def fake_chat_stream(messages, tools):
        seen_messages.extend(messages)
        from taisang.llm_stream import StreamChunk
        yield StreamChunk(text_delta="fork 结果")
        yield StreamChunk(tool_calls=[], usage=None, is_final=True)
    child_llm = MockLLM([])
    child_llm.chat = fake_chat
    child_llm.chat_stream = fake_chat_stream
    import taisang.agent_core.agent_tool as at_mod
    original_make = at_mod._make_child_llm
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({"description": "继续", "prompt": "接着做 Task 3"})
    finally:
        at_mod._make_child_llm = original_make
    assert result["text"] == "fork 结果"
    all_text = str(seen_messages)
    assert "用户原始问题" in all_text


def test_agent_tool_b_mode_fork_in_fork_rejected(tmp_path: Path) -> None:
    """B 模式:fork 子 agent 内再 fork → 拒绝(fork 递归防护)。"""
    parent = _make_parent_service(tmp_path, [])
    parent.is_fork_child = True
    tool = AgentTool(
        agents=[], parent_service=parent, source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
    )
    result = tool.run({"description": "继续", "prompt": "再 fork 一次"})
    assert "error" in result
    assert "fork" in result["error"].lower()


def test_agent_tool_a_mode_child_tools_exclude_agent(tmp_path: Path) -> None:
    """A 模式:子 agent 工具集不含 AgentTool(防递归)。"""
    a = _make_explore_agent()
    parent = _make_parent_service(tmp_path, [a])
    captured_tools: list = []
    child_llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    def fake_chat(messages, tools):
        captured_tools.extend(tools)
        return LLMResponse(text="ok", tool_calls=[])
    child_llm.chat = fake_chat
    import taisang.agent_core.agent_tool as at_mod
    original_make = at_mod._make_child_llm
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[a], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        tool.run({"description": "x", "prompt": "y", "subagent_type": "explore"})
    finally:
        at_mod._make_child_llm = original_make
    tool_names = {t["name"] for t in captured_tools}
    assert "Agent" not in tool_names


def test_agent_tool_a_mode_max_turns_override(tmp_path: Path) -> None:
    """A 模式:子 agent max_steps 用 agent.max_turns(20),不是默认 50。"""
    a = _make_explore_agent()
    assert a.max_turns == 20
    parent = _make_parent_service(tmp_path, [a])
    child_llm = MockLLM([LLMResponse(text="", tool_calls=[{
        "id": "tc", "type": "function",
        "function": {"name": "glob", "arguments": '{"pattern": "*"}'}
    }])] * 100)
    import taisang.agent_core.agent_tool as at_mod
    original_make = at_mod._make_child_llm
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[a], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({"description": "x", "prompt": "y", "subagent_type": "explore"})
    finally:
        at_mod._make_child_llm = original_make
    # 子 agent 到 max_turns=20 返回 "(达到最大步数 ...)" 或类似
    # Answer.complete=False when max_steps hit
    assert "达到最大步数" in result["text"] or "max" in result["text"].lower() or result.get("complete") is False


def test_agent_tool_a_mode_async_returns_launched(tmp_path: Path) -> None:
    """A 模式 async:立即返回 async_launched,后台跑完通知入队。"""
    a = _make_explore_agent()
    parent = _make_parent_service(tmp_path, [a])
    child_llm = MockLLM([LLMResponse(text="async 结果", tool_calls=[])])
    import taisang.agent_core.agent_tool as at_mod
    original_make = at_mod._make_child_llm
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[a], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({
            "description": "异步搜索", "prompt": "找文件",
            "subagent_type": "explore", "run_in_background": True,
        })
        assert result["status"] == "async_launched"
        assert "agent_id" in result
        time.sleep(0.5)
        assert len(parent._pending_async_notifications) > 0
        assert "async 结果" in parent._pending_async_notifications[0]
    finally:
        at_mod._make_child_llm = original_make


def test_make_child_llm_uses_subagent_when_enabled(tmp_path, monkeypatch):
    """enabled=true + model/base_url 填 → 返回独立 LLMClient,与 parent_llm 不同实例。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    # 写子配置到 settings.json
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(
        enabled=True, base_url="https://sub.api", api_key="sk-sub", model="glm-4.5",
    ))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is not parent_llm
    # LLMClient 实例(不是 MockLLM)
    from taisang.llm_client import LLMClient
    assert isinstance(child, LLMClient)
    assert child.model == "glm-4.5"
    assert child.cfg.base_url == "https://sub.api"
    assert child.cfg.api_key == "sk-sub"


def test_make_child_llm_fallback_parent_when_disabled(tmp_path, monkeypatch):
    """enabled=false → fallback parent_llm。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=False, base_url="https://sub", api_key="k", model="m"))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is parent_llm


def test_make_child_llm_fallback_parent_when_model_empty(tmp_path, monkeypatch):
    """enabled=true 但 model 空 → fallback parent_llm。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="k", model=""))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is parent_llm


def test_make_child_llm_fallback_parent_when_base_url_empty(tmp_path, monkeypatch):
    """enabled=true 但 base_url 空 → fallback parent_llm。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="", api_key="k", model="m"))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is parent_llm


def test_make_child_llm_allows_empty_api_key(tmp_path, monkeypatch):
    """enabled=true + model/base_url 填 + api_key 空 → 返回独立 LLMClient,api_key 为空字符串。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="", model="m"))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    from taisang.llm_client import LLMClient
    assert isinstance(child, LLMClient)
    assert child.cfg.api_key == ""  # 允许空
    assert child.cfg.model == "m"