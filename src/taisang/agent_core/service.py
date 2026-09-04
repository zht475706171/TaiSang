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
    DEBUG_REQUEST,
    DEBUG_RESPONSE,
    DEBUG_TOOL_RESULT,
    FINAL_ANSWER,
    LLM_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    USAGE_REPORT,
    AgentEvent,
)
from .permission import AutoApprovePermissionManager, PermissionManager
from .prompts import SYSTEM_PROMPT, build_system_prompt
from .tools import ToolRegistry
from ..skills.listing import format_skill_listing
from ..skills.types import Skill

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
        debug: bool = False,
        permission: PermissionManager | None = None,
        allow_dirs: list[Path] | None = None,
        on_append: "Callable[[dict], None] | None" = None,
        skills: list[Skill] | None = None,
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
        self.debug = debug  # /debug 模式:emit DEBUG_REQUEST/DEBUG_RESPONSE/DEBUG_TOOL_RESULT
        # 权限管理:首次访问新目录问用户批准。默认 None 时用 AutoApprove
        # (测试场景);CLI 传 CliPermissionManager,Web 传 WebPermissionManager。
        # allow_dirs 仍保留:作为初始已批准目录列表传给 PermissionManager。
        initial_approved = allow_dirs if allow_dirs else [source_root]
        self.permission = (
            permission if permission is not None else AutoApprovePermissionManager(initial_approved)
        )
        # 兼容旧代码读取 self.allow_dirs(已批准目录集合)
        self.allow_dirs = initial_approved
        # 持久 shell(claude code 风格):跨 Bash 调用复用,cd 持久化。
        # shell 跟 AgentService 实例生命周期绑定:实例创建时起,reset 不重启,实例销毁时关。
        from .shell import PipeShell

        self.shell = PipeShell(cwd=source_root)
        # ContextManager 提到实例属性:跨 run() 调用保留对话历史(多轮记忆)。
        # 每次 run() 只 append_user(query),不重建 ctx,REPL 多轮对话才能看到上一轮。
        # on_append 透传给 ContextManager:每条 append 触发回调(ConversationStore 落盘)。
        self.ctx = ContextManager(token_budget=self.token_budget, on_append=on_append)
        self.skills = skills or []
        skills_section = format_skill_listing(self.skills)
        self.ctx.append_system(build_system_prompt(skills_section))
        # session memory post-sampling 计数器:跨 run() 累计工具调用次数。
        self._tool_calls_since_last_extract = 0
        # token 用量累计:跨 run() 累加,reset() 清零。结构同 LLMResponse.usage。
        self._session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        # 此轮 run() 的 token 用量临时累加器(每次 run 开始前重置)。
        self._turn_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def set_debug(self, on: bool) -> None:
        """REPL /debug 命令切换开关。"""
        self.debug = on

    def reset(self) -> None:
        """清空对话上下文 + 重置压缩状态。

        设计选择:**不重置 session_memory**(它是跨 session 的长期笔记,reset 只清短期
        对话历史,长期笔记保留以便下次对话继续利用)。compaction_state 一起重置,
        因为决策冻结表是针对当前 ctx 的 tool_call_id 的,ctx 换了旧决策作废。
        """
        on_append = self.ctx.on_append  # 保留原 on_append(reset 不丢持久化回调)
        self.ctx = ContextManager(token_budget=self.token_budget, on_append=on_append)
        skills_section = format_skill_listing(self.skills)
        self.ctx.append_system(build_system_prompt(skills_section))
        self.compaction_state = ContentReplacementState()
        self._tool_calls_since_last_extract = 0
        self._session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._turn_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def run(self, query: str, on_event: EventCallback | None = None) -> Answer:
        """执行 Agent 循环,返回 Answer。

        每次:
        1. enforce_budget(tool_result 持久化预算)
        2. ctx.should_compact() 时调 _try_autocompact(LLM 摘要)
        3. LLM 调工具就执行,append observation
        4. session_memory post-sampling(达到阈值就 extract + 注入主 prompt)

        注意:self.ctx 跨 run() 保留,多轮对话有短期记忆;reset() 清空。
        """
        # 重置此轮 token 累加器(session 累计不清,跨 run 保留)
        self._turn_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.ctx.append_user(query)

        registry = ToolRegistry(
            cwd=self.source_root,
            shell=self.shell,
            confirmer=self.confirmer,
            permission=self.permission,
            skills=self.skills,
            ctx=self.ctx,
        )
        observations_dir = PathManager.observations_dir(self.source_root)
        transcript_path = self.source_root / ".taisang" / "sessions" / "current.jsonl"

        def _emit(evt: AgentEvent) -> None:
            if on_event is not None:
                on_event(evt)

        steps = 0
        while steps < self.max_steps:
            steps += 1
            # 阶段 5: apply-tool-result-budget
            new_msgs, _ = enforce_budget(
                self.ctx.messages(), self.compaction_state, observations_dir
            )
            self.ctx.replace_messages(new_msgs)
            # 阶段 7: autocompact
            if self.ctx.should_compact():
                if self._try_autocompact(transcript_path, _emit):
                    self._tool_calls_since_last_extract = 0
                    continue
            _emit(AgentEvent(type=LLM_THINKING))
            if self.debug:
                _emit(
                    AgentEvent(
                        type=DEBUG_REQUEST,
                        payload={
                            "step": steps,
                            "messages": self.ctx.messages(),
                            "tools": registry.schemas(),
                        },
                    )
                )
            try:
                resp = self.llm.chat(messages=self.ctx.messages(), tools=registry.schemas())
            except LLMProtocolError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM protocol error at step %d: %s", steps, e)
                text = f"(LLM 协议错误: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text}))
                return Answer(
                    text=text,
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            except LLMTransientError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM transient error at step %d: %s", steps, e)
                text = f"(LLM 调用失败: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text}))
                return Answer(
                    text=text,
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            except LLMError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM error at step %d: %s", steps, e)
                text = f"(LLM 错误: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text}))
                return Answer(
                    text=text,
                    citations=[],
                    complete=False,
                    steps_used=steps,
                )
            # 累加此轮 + session 累计 token(MockLLM / endpoint 未返回时 usage=None,跳过)
            self._accumulate_usage(resp.usage)

            if not resp.tool_calls:
                if self.debug:
                    _emit(
                        AgentEvent(
                            type=DEBUG_RESPONSE,
                            payload={"step": steps, "text": resp.text, "tool_calls": []},
                        )
                    )
                # session memory post-sampling(idle_break 分支):
                # LLM 给最终答案(无 tool_call)是自然对话断点,此时触发 extract。
                # 对齐 Claude Code shouldExtractMemory 的 hasToolCallsInLastTurn=False 分支。
                self._maybe_trigger_session_memory(last_turn_has_tool_calls=False)
                citations = self._extract_citations(resp.text)
                # 最终答案也要落盘(走 on_append 写 jsonl),否则 resume 缺 assistant 回复
                self.ctx.append_assistant(text=resp.text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": resp.text}))
                self._emit_usage_report(_emit)
                return Answer(
                    text=resp.text,
                    citations=citations,
                    complete=True,
                    steps_used=steps,
                )

            if self.debug:
                _emit(
                    AgentEvent(
                        type=DEBUG_RESPONSE,
                        payload={"step": steps, "text": resp.text, "tool_calls": resp.tool_calls},
                    )
                )
            self.ctx.append_assistant(text=resp.text, tool_calls=resp.tool_calls)
            for tc in resp.tool_calls:
                name = tc["function"]["name"]
                args_str = tc["function"].get("arguments", "") or ""
                try:
                    args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError as e:
                    log.warning("tool %s malformed arguments: %s", name, e)
                    result = {"error": f"malformed arguments: {e}"}
                    # 仍然要 append tool_result,否则 LLM API 会因缺 tool result 报错
                    self.ctx.append_tool_result(
                        json.dumps(result, ensure_ascii=False),
                        name=name,
                        tool_call_id=tc["id"],
                    )
                    self._tool_calls_since_last_extract += 1
                    continue
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
                if self.debug:
                    _emit(
                        AgentEvent(
                            type=DEBUG_TOOL_RESULT,
                            payload={
                                "step": steps,
                                "name": name,
                                "tool_call_id": tc["id"],
                                "observation": observation,
                            },
                        )
                    )
                self.ctx.append_tool_result(observation, name=name, tool_call_id=tc["id"])
                self._tool_calls_since_last_extract += 1

            # SKILL.md 注入必须排在全部 tool_result 之后(OpenAI 协议要求
            # assistant(tool_calls) 后紧跟 tool 消息,user 注入放最后),由
            # SkillTool 的 pending 队列延迟到这里统一 flush。
            registry.flush_skill_injections()

            # session memory post-sampling(update 分支):
            # 工具执行完,此时本轮 resp 一定有 tool_calls(无 tool_calls 已在上面的 return 分支)。
            # 传 last_turn_has_tool_calls=True,走 update 触发分支(tokens + tool_calls 双满足)。
            self._maybe_trigger_session_memory(last_turn_has_tool_calls=True)

        self._emit_usage_report(_emit)
        return Answer(
            text="(达到最大步数,信息可能不全)",
            citations=[],
            complete=False,
            steps_used=steps,
        )

    def _try_autocompact(self, transcript_path: Path, _emit: EventCallback) -> bool:
        """先试 session memory,失败 fallback 到 autocompact LLM 摘要。

        返回 True 表示做了压缩(messages 已替换),调用方应重置 tool_calls 计数并 continue。
        操作 self.ctx(实例属性,跨 run() 保留)。
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
                self.ctx.replace_messages([boundary, summary_msg], compaction_via="session_memory")
                _emit(AgentEvent(type=COMPACTED, payload={"via": "session_memory"}))
                return True

        # fallback: LLM 摘要
        from ..compaction.autocompact import autocompact as do_autocompact

        new_msgs = do_autocompact(self.ctx.messages(), self.llm, transcript_path)
        self.ctx.replace_messages(new_msgs, compaction_via="llm")
        _emit(AgentEvent(type=COMPACTED, payload={"via": "llm"}))
        return True

    def _maybe_trigger_session_memory(self, last_turn_has_tool_calls: bool) -> None:
        """session memory post-sampling:检查阈值,达标就异步触发后台 extract。

        两个触发点:
        - idle_break:LLM 给最终答案(无 tool_call)→ last_turn_has_tool_calls=False
        - update:工具执行完(本轮有 tool_call)→ last_turn_has_tool_calls=True

        触发后重置 _tool_calls_since_last_extract 计数器。
        """
        if not self.session_memory:
            return
        current_tokens = self.ctx.total_tokens()
        if self.session_memory.should_extract(
            current_tokens,
            self._tool_calls_since_last_extract,
            last_turn_has_tool_calls=last_turn_has_tool_calls,
        ):
            self.session_memory._do_extract(
                recent_conversation=self._recent_text(),
                current_tokens=current_tokens,
            )
            self._tool_calls_since_last_extract = 0

    def _recent_text(self) -> str:
        """取完整对话历史作为 session memory extract 输入。读 self.ctx。

        对齐 Claude Code:forkContextMessages 传完整 messages,不截断。
        不用担心过大 —— autocompact 触发后 ctx 会被替换成 [boundary, summary_msg],
        所以 ctx 最多也就 token_budget(32K)左右,且 session_memory 触发阈值
        (init 10000 / update delta 5000)保证了积累量,不会发空内容。
        每条原样拼接 role + content(content 是字符串就直接用,
        是 list 就 JSON 序列化以保留 tool_calls 结构)。
        """
        msgs = self.ctx.messages()
        lines: list[str] = []
        for m in msgs:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False)
            elif not isinstance(content, str):
                content = str(content)
            lines.append(f"[{role}]: {content}")
        return "\n".join(lines)

    def _accumulate_usage(self, usage: dict | None) -> None:
        """把单次 LLM 响应的 usage 累加到 turn + session 计数器。

        usage 为 None(MockLLM 或 endpoint 未返回)时跳过,计数器保持 0。
        """
        if usage is None:
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = usage.get(key, 0) or 0
            self._turn_usage[key] += val
            self._session_usage[key] += val

    def _emit_usage_report(self, _emit: EventCallback) -> None:
        """run() 结束时 emit USAGE_REPORT 事件。

        turn: 此轮 run() 累加的 usage(可能全 0,若用 MockLLM 或 endpoint 不返回)。
        session: 跨 run() 累计(含此轮),reset() 清零。
        cache: endpoint 是否报告 cached_tokens。aitoken521 + glm-5.2 目前不报告,
            available=False, cached_tokens=None。
        """
        turn = {
            "prompt": self._turn_usage["prompt_tokens"],
            "completion": self._turn_usage["completion_tokens"],
            "total": self._turn_usage["total_tokens"],
        }
        session = {
            "prompt": self._session_usage["prompt_tokens"],
            "completion": self._session_usage["completion_tokens"],
            "total": self._session_usage["total_tokens"],
        }
        # cache 字段:当前 endpoint 不报告,固定 available=False。
        # 若未来 endpoint 返回 prompt_tokens_details.cached_tokens,可在这里解析。
        cache = {"available": False, "cached_tokens": None}
        _emit(
            AgentEvent(
                type=USAGE_REPORT,
                payload={"turn": turn, "session": session, "cache": cache},
            )
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
