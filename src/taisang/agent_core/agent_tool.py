# src/taisang/agent_core/agent_tool.py
"""AgentTool:主 agent 通过本工具派子 agent。

两种模式:
- A 模式(传 subagent_type):子 agent 全新上下文,用 agent 定义里的 system_prompt,
  工具集按 frontmatter 过滤(白名单 ∩ 父工具 - 黑名单 - AgentTool 自己)。
- B 模式(省略 subagent_type,fork):子 agent 深拷贝父 messages + 复用父 system_prompt,
  工具集 = 父工具集 - AgentTool 自己。fork 递归防护:parent_service.is_fork_child
  为 True 时拒绝。

两种执行模式:
- sync(默认):阻塞等子 agent.run() 返回 Answer.text,作为 tool_result。
- async(run_in_background=True):立即返回 async_launched,后台线程跑完把结果
  注入 parent_service._pending_async_notifications,主循环下轮 flush 注入 user 消息。

权限:子 agent 共用父 PermissionManager / confirmer / shell。
递归防护:子 agent 工具集永远禁 AgentTool(A/B 模式都禁,靠 ToolRegistry 构造时不传 agents)。
"""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from ..agent_core.context import ContextManager
from ..agent_core.events import AgentEvent, FINAL_ANSWER, LLM_THINKING, TOOL_CALL, TOOL_RESULT, USAGE_REPORT
from ..agent_core.service import AgentService
from ..agents.types import AgentDefinition
from .tools import _BaseTool

log = logging.getLogger(__name__)

# 合成 fork agent 定义(system_prompt 留空,实际用父的)
_FORK_AGENT = AgentDefinition(
    agent_type="fork",
    when_to_use="(implicit fork)",
    tools=None,
    disallowed_tools=[],
    base_dir=Path("."),
    system_prompt="",
)


def _make_child_llm(parent_llm):
    """默认子 agent 用父 LLM(同 client)。测试用 monkeypatch 替换。"""
    return parent_llm


class AgentTool(_BaseTool):
    """派子 agent 工具。主 agent 通过 task({...}) 调用。"""

    name = "Agent"

    def __init__(
        self,
        agents: list[AgentDefinition],
        parent_service: AgentService,
        source_root: Path,
        confirmer,
        session_memory=None,
        mcp_manager=None,
    ) -> None:
        """
        agents:可用 agent 列表(已过滤 disabled,loader 产出)。
        parent_service:主 AgentService 实例(用于 fork 深拷贝 messages + 接收 async 通知)。
        source_root / confirmer / session_memory / mcp_manager:子 agent 透传共用。
        """
        self.agents = {a.agent_type: a for a in agents}
        self.parent_service = parent_service
        self.source_root = source_root
        self.confirmer = confirmer
        self.session_memory = session_memory
        self.mcp_manager = mcp_manager

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "Launch a subagent to handle a complex task. Pass subagent_type to use "
                "a specialized agent (starts fresh, no parent context). Omit subagent_type "
                "to fork yourself — the fork inherits the full conversation context. "
                "Available agent types are listed in the system prompt. "
                "Set run_in_background=true to run async; you'll be notified on completion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "3-5 word summary of the task"},
                    "prompt": {"type": "string", "description": "The task for the subagent"},
                    "subagent_type": {
                        "type": "string",
                        "description": "Agent type; omit to fork (inherit parent context)",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "Run async; you'll be notified on completion",
                    },
                },
                "required": ["description", "prompt"],
            },
        }

    def run(self, args: dict) -> dict:
        """执行子 agent 派遣。"""
        description = args.get("description", "")
        prompt = args.get("prompt", "")
        subagent_type = args.get("subagent_type")
        run_in_background = bool(args.get("run_in_background", False))

        if subagent_type:
            agent = self.agents.get(subagent_type)
            if agent is None:
                available = ", ".join(sorted(self.agents.keys())) or "(none)"
                return {"error": f"agent type '{subagent_type}' not found, available: {available}"}
            if agent.disabled:
                return {"error": f"agent '{subagent_type}' is disabled"}
            is_fork = False
        else:
            if self.parent_service.is_fork_child:
                return {"error": "fork is not available inside a forked worker (recursive fork guard)"}
            agent = _FORK_AGENT
            is_fork = True

        effective_async = run_in_background or agent.background

        if effective_async:
            return self._run_async(agent, is_fork, description, prompt)
        return self._run_sync(agent, is_fork, description, prompt)

    def _build_child_service(self, agent: AgentDefinition, is_fork: bool, child_agent_id: str = "") -> AgentService:
        """构造子 AgentService 实例。"""
        if not child_agent_id:
            child_agent_id = uuid.uuid4().hex[:12]
        child_llm = _make_child_llm(self.parent_service.llm)

        if is_fork:
            max_steps = self.parent_service.max_steps
        else:
            max_steps = agent.max_turns if agent.max_turns else self.parent_service.max_steps

        child = AgentService(
            llm=child_llm,
            source_root=self.source_root,
            confirmer=self.confirmer,
            session_memory=self.session_memory,
            max_steps=max_steps,
            token_budget=self.parent_service.token_budget,
            permission=self.parent_service.permission,
            allow_dirs=list(self.parent_service.allow_dirs),
            agent_id=child_agent_id,
            is_fork_child=is_fork,
            mcp_manager=self.mcp_manager,
            # NOTE: agents=[] — 子 agent 的 ToolRegistry 不会注册 AgentTool,物理防递归
            agents=[],
        )

        if is_fork:
            # fork 模式:深拷贝父 messages(含 system prompt),子 agent 复用父上下文
            parent_msgs = [dict(m) for m in self.parent_service.ctx.messages()]
            child.ctx.replace_messages(parent_msgs)
        else:
            # A 模式:把 agent.system_prompt 追加到默认 system prompt 后
            if agent.system_prompt:
                from ..agent_core.prompts import build_system_prompt
                new_system = build_system_prompt("", "") + "\n\n" + agent.system_prompt
                child.ctx.replace_system_prompt(new_system)

        return child

    def _run_sync(self, agent: AgentDefinition, is_fork: bool, description: str, prompt: str) -> dict:
        """sync 执行:阻塞等子 agent 跑完,返回 Answer.text。"""
        child_agent_id = uuid.uuid4().hex[:12]
        child = self._build_child_service(agent, is_fork, child_agent_id)
        # 子 agent 事件转发:加 agent_id
        parent_emit = getattr(self.parent_service, "_last_on_event", None)
        def child_on_event(evt: AgentEvent):
            evt.agent_id = child.agent_id
            if parent_emit:
                parent_emit(evt)
        answer = child.run(prompt, on_event=child_on_event)
        # 累加子 agent usage 进主 session
        self.parent_service._merge_child_usage(child._session_usage)
        return {"text": answer.text, "agent_type": agent.agent_type, "complete": answer.complete}

    def _run_async(self, agent: AgentDefinition, is_fork: bool, description: str, prompt: str) -> dict:
        """async 执行:起后台线程跑子 agent,立即返回 async_launched。"""
        child_agent_id = uuid.uuid4().hex[:12]
        def background_run():
            try:
                child = self._build_child_service(agent, is_fork, child_agent_id)
                answer = child.run(prompt, on_event=None)
                self.parent_service._merge_child_usage(child._session_usage)
                text = f"[子 agent '{description}' 完成]\n{answer.text}"
                self.parent_service._pending_async_notifications.append(text)
            except Exception as e:
                log.warning("async agent '%s' failed: %s", description, e)
                text = f"[子 agent '{description}' 失败]\n{e}"
                self.parent_service._pending_async_notifications.append(text)
        thread = threading.Thread(target=background_run, daemon=True)
        thread.start()
        return {
            "status": "async_launched",
            "agent_id": child_agent_id,
            "description": description,
        }