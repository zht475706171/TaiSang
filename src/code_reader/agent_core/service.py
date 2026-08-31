"""Agent 主循环:LLM 调工具 → 观察 → 继续,直到 LLM 给最终答案。

Task 1 简化后:
- 删除所有文档生成专用分支(_run_doc_mode / write_doc 触发 microcompact /
  finalize_doc 返回 / _render_section_content)
- 删除 session_memory / compaction_state 参数(Task 4 会重新加回压缩流水线)
- 保留 repo_map 参数(向后兼容旧 7 个基础 agent 测试)
- 保留 _try_autocompact / _recent_text / _extract_citations 方法(Task 4 会重新接上)

这是过渡状态:run() 是最基础的 `while steps < max_steps: LLM → 工具 → continue`。
Task 4 会重新加回 enforce_budget / autocompact / session_memory post-sampling。
"""

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
from .events import (
    COMPACTED,
    FINAL_ANSWER,
    LLM_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    AgentEvent,
)
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
    """Agent 主循环服务(Task 1 简化版)。

    参数:
        llm: LLM 客户端(真 LLMClient 或测试用 MockLLM)
        source_root: repo 根目录,工具用它做 path containment 校验
        call_graph: 调用图(symbol_id → CallGraphNode),给 TraceCallChainTool 用
        repo_map: RepoMap,保留参数为向后兼容旧测试;Task 1 后 ToolRegistry 不再
            注册 LookupMapTool,所以 run() 里不实际使用(Task 4 会重新接上)
        max_steps: 循环步数上限,防 LLM 一直调工具不回答
        token_budget: 上下文 token 预算(Task 4 接 enforce_budget / autocompact 时用)
    """

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

        Task 1 简化版:纯对话循环,LLM 决定调工具就执行,不调工具就返回最终答案。
        不接 enforce_budget / autocompact / session_memory(Task 4 会重新加回)。
        """
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)
        ctx.append_user(query)

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
            _emit(AgentEvent(type=LLM_THINKING))
            try:
                resp = self.llm.chat(messages=ctx.messages(), tools=registry.schemas())
            except LLMProtocolError as e:
                log.warning("LLM protocol error at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 协议错误: {e})",
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            except LLMTransientError as e:
                log.warning("LLM transient error at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 调用失败: {e})",
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            except LLMError as e:
                log.warning("LLM error at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 错误: {e})",
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )

            if not resp.tool_calls:
                citations = self._extract_citations(resp.text)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": resp.text}))
                return Answer(
                    text=resp.text,
                    citations=citations,
                    complete=True,
                    steps_used=steps,
                )

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

        return Answer(
            text="(达到最大步数,信息可能不全)",
            citations=[],
            complete=False,
            steps_used=steps,
        )

    def _try_autocompact(self, ctx: ContextManager, transcript_path: Path, _emit) -> bool:
        """先试 session memory,失败 fallback 到 autocompact LLM 摘要。

        Task 1 阶段 run() 不调用本方法(没接 session_memory / autocompact 触发点)。
        方法保留为 Task 4 重新接回压缩流水线时复用。
        """
        # Task 1 简化:session_memory 字段已删,直接走 LLM 摘要 fallback。
        from ..compaction.autocompact import autocompact as do_autocompact

        new_msgs = do_autocompact(ctx.messages(), self.llm, transcript_path)
        ctx.replace_messages(new_msgs)
        _emit(AgentEvent(type=COMPACTED, payload={"via": "llm"}))
        return True

    def _recent_text(self, ctx: ContextManager) -> str:
        """取最近几轮对话作为 session memory extract 输入。

        Task 1 阶段 run() 不调用本方法。方法保留为 Task 4 复用。
        """
        msgs = ctx.messages()
        return "\n".join(f"[{m['role']}]: {m.get('content', '')[:200]}" for m in msgs[-10:])

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
