"""Agent 主循环:plan → act → observe → reflect。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from ..indexer.linker import CallGraphNode
from ..llm_client import LLMClient, MockLLM
from ..llm_errors import LLMError, LLMProtocolError, LLMTransientError
from ..types import Answer, Citation, RepoMap
from .context import ContextManager
from .events import FINAL_ANSWER, LLM_THINKING, TOOL_CALL, TOOL_RESULT, AgentEvent
from .prompts import SYSTEM_PROMPT
from .tools import ToolRegistry

log = logging.getLogger(__name__)

# observation 单条上限(字节)。超长截断以保护上下文预算。
_MAX_OBSERVATION_BYTES = 32_000

# citation 抽取正则,模块级预编译。
_CITATION_RE = re.compile(r"\[([^\]\s]+\.py)(?::(\d+)(?:-(\d+))?)?\]")

# on_event 回调类型
EventCallback = Callable[[AgentEvent], None]


class AgentService:
    """Agent 主循环服务。"""

    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
        max_steps: int = 10,
        token_budget: int = 32_000,
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.call_graph = call_graph
        self.repo_map = repo_map
        self.max_steps = max_steps
        self.token_budget = token_budget

    def run(self, query: str, on_event: EventCallback | None = None) -> Answer:
        """执行 Agent 循环,返回 Answer。

        on_event:可选回调,Agent 循环每一步(LLM 思考/工具调用/工具返回/最终答案)
        都会调用它,UI 层用它实时渲染中间过程。None 表示不推送(向后兼容)。
        """
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)
        # 初始注入:全局地图摘要(让 Agent 有起点)
        ctx.append_user(
            f"代码库全局摘要:\n{self.repo_map.global_summary.dependency_summary}\n\n"
            f"用户问题: {query}"
        )

        registry = ToolRegistry(
            source_root=self.source_root,
            call_graph=self.call_graph,
            repo_map=self.repo_map,
        )

        def _emit(evt: AgentEvent) -> None:
            if on_event is not None:
                on_event(evt)

        steps = 0
        while steps < self.max_steps:
            steps += 1
            if ctx.should_compact():
                ctx.compact()

            _emit(AgentEvent(type=LLM_THINKING))
            try:
                resp = self.llm.chat(messages=ctx.messages(), tools=registry.schemas())
            except LLMProtocolError as e:
                # 协议层错误:不可重试,直接结束并报告
                log.warning("LLM protocol error at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 协议错误: {e})",
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            except LLMTransientError as e:
                # 瞬时错误:网络/限流/超时,v1 不做重试,直接结束
                log.warning("LLM transient error at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 调用失败: {e})",
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            except LLMError as e:
                # 其他 LLM 错误兜底
                log.warning("LLM error at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 错误: {e})",
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )

            if not resp.tool_calls:
                # 给出最终答案
                citations = self._extract_citations(resp.text)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": resp.text}))
                return Answer(
                    text=resp.text,
                    citations=citations,
                    complete=True,
                    steps_used=steps,
                )

            # 有 tool calls:执行每个
            ctx.append_assistant(text=resp.text, tool_calls=resp.tool_calls)
            for i, tc in enumerate(resp.tool_calls):
                name = tc.get("name", "<unknown>")
                args = tc.get("args") or {}
                _emit(AgentEvent(type=TOOL_CALL, payload={"name": name, "args": args}))
                try:
                    result = registry.call(name, args)
                except Exception as e:
                    log.warning("tool %s dispatch failed: %s", name, e)
                    result = {"error": f"tool {name} failed: {e}"}
                observation = json.dumps(result, ensure_ascii=False)
                total_bytes = len(observation.encode("utf-8"))
                if total_bytes > _MAX_OBSERVATION_BYTES:
                    observation = observation[:_MAX_OBSERVATION_BYTES] + '...{"_truncated": true}'
                _emit(
                    AgentEvent(
                        type=TOOL_RESULT,
                        payload={
                            "name": name,
                            "preview": observation[:30],
                            "total_bytes": total_bytes,
                        },
                    )
                )
                ctx.append_tool_result(observation, name=name, tool_call_id=f"{name}-{i}")

        # 超 max_steps
        return Answer(
            text="(达到最大步数,信息可能不全)",
            citations=[],
            complete=False,
            steps_used=steps,
        )

    def _extract_citations(self, text: str) -> list[Citation]:
        """从答案文本抽 [file.py:line] 格式引用。"""
        citations: list[Citation] = []
        seen: set[str] = set()
        for m in _CITATION_RE.finditer(text):
            file = m.group(1)
            start = int(m.group(2)) if m.group(2) else 1
            end = int(m.group(3)) if m.group(3) else start
            key = f"{file}:{start}-{end}"
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(file=file, line_range=(start, end)))
        return citations
