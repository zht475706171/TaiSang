"""Agent 主循环:LLM 调工具 → 观察 → 继续,直到 LLM 给最终答案。

Task 4 重写:从 doc 生成专用循环改成通用 coding agent 循环。
- 删除 call_graph / repo_map 参数(工具集不再依赖)
- 新增 confirmer 参数(Edit/Write 必须经用户确认)
- 新增 session_memory / compaction_state 参数(三道压缩流水线)
- 主循环按 plan 接 enforce_budget / autocompact / session_memory post-sampling
- 保留 _try_autocompact / _recent_text / _extract_citations 方法
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from ..compaction.tool_result_budget import ContentReplacementState, enforce_budget
from ..llm_client import LLMClient, MockLLM
from ..llm_errors import LLMError, LLMProtocolError, LLMTransientError
from ..storage.paths import PathManager
from ..types import Answer, Citation
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
    """Agent 主循环服务(通用 coding agent)。

    参数:
        llm: LLM 客户端(真 LLMClient 或测试用 MockLLM)
        source_root: repo 根目录,工具用它做 path containment 校验
        confirmer: Edit/Write 确认器,callable(file_path, old, new) -> bool
        session_memory: SessionMemoryService 实例(可选);为 None 则跳过 session
            memory post-sampling
        compaction_state: ContentReplacementState 实例(可选);为 None 则
            __init__ 里建默认实例
        max_steps: 循环步数上限,防 LLM 一直调工具不回答
        token_budget: 上下文 token 预算(用于 ctx should_compact / enforce_budget)
    """

    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        confirmer,
        session_memory=None,
        compaction_state: ContentReplacementState | None = None,
        max_steps: int = 50,
        token_budget: int = 32_000,
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.confirmer = confirmer
        self.session_memory = session_memory
        self.compaction_state = (
            compaction_state if compaction_state is not None else ContentReplacementState()
        )
        self.max_steps = max_steps
        self.token_budget = token_budget

    def run(self, query: str, on_event: EventCallback | None = None) -> Answer:
        """执行 Agent 循环,返回 Answer。

        每轮:
        1. enforce_budget(tool_result 持久化预算)
        2. ctx.should_compact() 时调 _try_autocompact(LLM 摘要)
        3. LLM 调工具就执行,append observation
        4. session_memory post-sampling(达到阈值就 extract + 注入主 prompt)
        """
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)
        ctx.append_user(query)

        registry = ToolRegistry(
            source_root=self.source_root,
            confirmer=self.confirmer,
        )
        observations_dir = PathManager.observations_dir(self.source_root)
        transcript_path = self.source_root / ".code-reader" / "sessions" / "current.jsonl"

        def _emit(evt: AgentEvent) -> None:
            if on_event is not None:
                on_event(evt)

        steps = 0
        tool_calls_since_last_extract = 0
        while steps < self.max_steps:
            steps += 1
            # 阶段 5: apply-tool-result-budget
            new_msgs, _ = enforce_budget(ctx.messages(), self.compaction_state, observations_dir)
            ctx.replace_messages(new_msgs)
            # 阶段 7: autocompact
            if ctx.should_compact():
                if self._try_autocompact(ctx, transcript_path, _emit):
                    tool_calls_since_last_extract = 0
                    continue
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
                tool_calls_since_last_extract += 1

            # session memory post-sampling
            if self.session_memory and self.session_memory.should_extract(
                ctx.total_tokens(), tool_calls_since_last_extract
            ):
                self.session_memory._do_extract(recent_conversation=self._recent_text(ctx))
                summary = self.session_memory.read_for_compaction()
                if summary:
                    ctx._messages.insert(
                        1, {"role": "user", "content": f"[session memory]\n{summary}"}
                    )
                tool_calls_since_last_extract = 0

        return Answer(
            text="(达到最大步数,信息可能不全)",
            citations=[],
            complete=False,
            steps_used=steps,
        )

    def _try_autocompact(
        self, ctx: ContextManager, transcript_path: Path, _emit: EventCallback
    ) -> bool:
        """先试 session memory,失败 fallback 到 autocompact LLM 摘要。

        返回 True 表示做了压缩(messages 已替换),调用方应重置 tool_calls 计数并 continue。
        """
        # 先试 session memory(零 LLM 调用)
        if self.session_memory is not None:
            summary = self.session_memory.read_for_compaction()
            if summary:
                boundary = {
                    "role": "user",
                    "content": "[boundary: session memory compaction occurred here]",
                }
                summary_msg = {
                    "role": "user",
                    "content": (
                        "This session is being continued from a previous conversation "
                        "that ran out of context.\nThe summary below covers the earlier "
                        f"portion.\n\nSummary:\n{summary}"
                    ),
                }
                ctx.replace_messages([boundary, summary_msg])
                _emit(AgentEvent(type=COMPACTED, payload={"via": "session_memory"}))
                return True

        # fallback: LLM 摘要
        from ..compaction.autocompact import autocompact as do_autocompact

        new_msgs = do_autocompact(ctx.messages(), self.llm, transcript_path)
        ctx.replace_messages(new_msgs)
        _emit(AgentEvent(type=COMPACTED, payload={"via": "llm"}))
        return True

    def _recent_text(self, ctx: ContextManager) -> str:
        """取最近几轮对话作为 session memory extract 输入。"""
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
