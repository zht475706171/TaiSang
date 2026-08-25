"""Agent 主循环:plan → act → observe → reflect。

Task 12 重写:
- 接入三道压缩流水线(enforce_budget / microcompact / autocompact)
- 接入 session memory(平时异步维护笔记,autocompact 时零 LLM 读笔记)
- 任务级 prompt:为 repo 生成 markdown 文档树(替代旧"读懂代码库"问答)

向后兼容:
- 新参数 idx/outline/doc_dir/all_sections/session_memory/compaction_state 全部默认 None
- outline 为 None 时走旧简化路径(只调 5 工具,不接压缩流水线 + session memory)
- 初始 user message 在 outline 缺省时不引用 outline.selected_mechanisms
- 旧 7 个 test_agent_core.py 测试走简化路径,行为完全不变
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
    DOC_WRITTEN,
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
    """Agent 主循环服务。

    新增参数(全部默认 None,向后兼容):
        idx: RepoIndex,索引产物(简化路径下不用)
        outline: Outline,outliner 产物(初始 user message 引用其 selected_mechanisms)
        doc_dir: Path,文档落盘目录(给 WriteDoc / ListPending / Finalize 用)
        all_sections: list[str],章节清单(给 ListPendingSections 用)
        session_memory: SessionMemoryService,平时异步维护笔记
        compaction_state: ContentReplacementState,跨 turn 持有替换决策
    """

    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
        idx: object | None = None,
        outline: object | None = None,
        doc_dir: Path | None = None,
        all_sections: list[str] | None = None,
        session_memory: object | None = None,
        compaction_state: object | None = None,
        max_steps: int = 10,
        token_budget: int = 32_000,
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.call_graph = call_graph
        self.repo_map = repo_map
        self.idx = idx
        self.outline = outline
        self.doc_dir = doc_dir
        self.all_sections = all_sections
        self.session_memory = session_memory
        # compaction_state 容错:None 时构造空 state(只在 doc 模式下用)
        self.compaction_state = compaction_state
        self.max_steps = max_steps
        self.token_budget = token_budget

    def run(self, query: str, on_event: EventCallback | None = None) -> Answer:
        """执行 Agent 循环,返回 Answer。

        outline / doc_dir / all_sections 任一为 None → 走旧简化路径(只调 5 工具,
        不接三道压缩流水线 + session memory),向后兼容 Task 1-11 测试。
        全齐 → 走 Task 12 完整路径。
        """
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)

        # 初始 user message:outline 在场时引用 selected_mechanisms + all_sections,
        # 否则退化到旧版"全局摘要 + 用户问题"。
        if self.outline is not None and self.all_sections is not None:
            sel_count = len(getattr(self.outline, "selected_mechanisms", []))
            flow_count = len(getattr(self.outline, "flow_candidates", []))
            ctx.append_user(
                f"代码库全局摘要:\n{self.repo_map.global_summary.dependency_summary}\n\n"
                f"已选出的核心机制:{sel_count} 个\n"
                f"已挖出的关键流程:{flow_count} 条\n"
                f"文档树章节清单:{self.all_sections}\n\n"
                f"任务: {query}"
            )
        else:
            ctx.append_user(
                f"代码库全局摘要:\n{self.repo_map.global_summary.dependency_summary}\n\n"
                f"用户问题: {query}"
            )

        registry = ToolRegistry(
            source_root=self.source_root,
            call_graph=self.call_graph,
            repo_map=self.repo_map,
            doc_dir=self.doc_dir,
            all_sections=self.all_sections,
        )

        def _emit(evt: AgentEvent) -> None:
            if on_event is not None:
                on_event(evt)

        # doc 模式(三道流水线 + session memory 全开)
        doc_mode = (
            self.outline is not None and self.doc_dir is not None and self.all_sections is not None
        )

        if doc_mode:
            return self._run_doc_mode(ctx, registry, _emit)
        return self._run_legacy_mode(ctx, registry, _emit)

    def _run_legacy_mode(self, ctx, registry, _emit) -> Answer:
        """旧简化路径:只调 5 工具,不接压缩流水线。向后兼容 Task 1-11 测试。"""
        steps = 0
        while steps < self.max_steps:
            steps += 1
            if ctx.should_compact():
                ctx.compact()

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

    def _run_doc_mode(self, ctx, registry, _emit) -> Answer:
        """Task 12 完整路径:三道压缩流水线 + session memory。"""
        from ..compaction.microcompact import clear_observations_before_section
        from ..compaction.tool_result_budget import ContentReplacementState, enforce_budget
        from ..storage.paths import PathManager

        observations_dir = PathManager.observations_dir(self.source_root)
        transcript_path = PathManager.index_dir(self.source_root) / "sessions" / "current.jsonl"
        if self.compaction_state is None:
            self.compaction_state = ContentReplacementState()

        steps = 0
        tool_calls_since_last_extract = 0
        while steps < self.max_steps:
            steps += 1
            # 阶段 5:apply-tool-result-budget(单轮 tool_result 总字节超预算时持久化大的)
            new_msgs, _ = enforce_budget(ctx.messages(), self.compaction_state, observations_dir)
            ctx.replace_messages(new_msgs)
            # 阶段 7/7a:autocompact 检查(超 token 预算先试 session memory,再 LLM 摘要)
            if ctx.should_compact():
                if self._try_autocompact(ctx, transcript_path, _emit):
                    tool_calls_since_last_extract = 0
                    continue
            _emit(AgentEvent(type=LLM_THINKING))
            try:
                resp = self.llm.chat(messages=ctx.messages(), tools=registry.schemas())
            except (LLMProtocolError, LLMTransientError, LLMError) as e:
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
                # write_doc 成功 → 触发章节边界 microcompact(阶段 6)
                if name == "write_doc" and isinstance(result, dict) and result.get("ok"):
                    new_msgs = clear_observations_before_section(ctx.messages(), f"{name}-{i}")
                    ctx.replace_messages(new_msgs)
                    _emit(
                        AgentEvent(
                            type=DOC_WRITTEN,
                            payload={"path": args.get("section_path")},
                        )
                    )
                # finalize_doc → 结束任务
                if name == "finalize_doc":
                    _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": "文档生成完成"}))
                    return Answer(
                        text="文档生成完成",
                        citations=[],
                        complete=True,
                        steps_used=steps,
                    )
                tool_calls_since_last_extract += 1
            # session memory 后台提取(post-sampling,简化为同步)
            if self.session_memory and self.session_memory.should_extract(
                ctx.total_tokens(), tool_calls_since_last_extract
            ):
                try:
                    self.session_memory._do_extract(recent_conversation=self._recent_text(ctx))
                    tool_calls_since_last_extract = 0
                except Exception as e:
                    log.warning("session memory extract failed: %s", e)

        return Answer(
            text="(达到最大步数,信息可能不全)",
            citations=[],
            complete=False,
            steps_used=steps,
        )

    def _try_autocompact(self, ctx: ContextManager, transcript_path: Path, _emit) -> bool:
        """先试 session memory,失败 fallback 到 autocompact LLM 摘要。"""
        if self.session_memory:
            summary = self.session_memory.read_for_compaction()
            if summary:
                new_msgs = [
                    {"role": "user", "content": "[boundary: autocompact via session memory]"},
                    {"role": "user", "content": f"会话摘要:\n{summary}"},
                ]
                ctx.replace_messages(new_msgs)
                _emit(AgentEvent(type=COMPACTED, payload={"via": "session_memory"}))
                return True
        # fallback 到 LLM 摘要
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
