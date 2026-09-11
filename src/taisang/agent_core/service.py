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
import queue
import re
import threading
from collections.abc import Callable
from pathlib import Path

from ..compaction.tool_result_budget import ContentReplacementState, enforce_budget
from ..llm_client import LLMClient, MockLLM
from ..llm_errors import LLMError, LLMProtocolError, LLMTransientError
from ..llm_retry import call_with_retry
from ..skills.listing import format_skill_listing
from ..skills.types import Skill
from ..storage.paths import PathManager
from ..types import Answer, Citation
from .context import ContextManager
from .context_window import (
    DEFAULT_CONTEXT_WINDOW,
    MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
    get_context_window,
)
from .events import (
    COMPACTED,
    DEBUG_REQUEST,
    DEBUG_RESPONSE,
    DEBUG_TOOL_RESULT,
    FINAL_ANSWER,
    LLM_CHUNK,
    LLM_RETRY,
    LLM_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    USAGE_REPORT,
    AgentEvent,
)
from .permission import AutoApprovePermissionManager, PermissionManager
from .prompts import build_system_prompt, format_mcp_section
from ..user_profile.format import format_profile_section
from ..user_profile.store import load_profile
from .tools import ToolRegistry

log = logging.getLogger(__name__)

# citation 抽取正则,模块级预编译。
_CITATION_RE = re.compile(r"\[([^\]\s]+\.py)(?::(\d+)(?:-(\d+))?)?\]")

# on_event 回调类型
EventCallback = Callable[[AgentEvent], None]


def _iter_with_retry(make_iter, on_retry):
    """流式迭代器重试包装:只重试第一次 next(连接建立 + 首 chunk)。

    首 chunk 成功后,后续 next 失败不重试(已经吐过字了,重试会重复)。

    make_iter: 返回 iterator 的 callable(每次重试会重新调)
    on_retry: 重试回调(同 call_with_retry 的 on_retry)

    Yields: 首 chunk + 后续 chunks
    Raises: 首 chunk 失败 → LLMTransientError(call_with_retry 重试后仍失败);
            后续 chunk 失败 → LLMTransientError(不重试,直接抛)
    """
    state = {"it": None}
    def _do_first():
        state["it"] = make_iter()
        return next(state["it"])
    first_chunk = call_with_retry(_do_first, on_retry=on_retry)
    yield first_chunk
    yield from state["it"]  # 后续 next 失败不重试,直接抛


def _consume_stream_with_cancel(gen, cancel_event, on_chunk, get_raw_stream=None):
    """pump 线程消费 generator + 主线程周期检查 cancel,真关 HTTP 连接。

    对标 Claude Code abort signal:cancel 不只是设 flag 等下一个 chunk,
    要主动关 raw stream 让阻塞中的 next() 抛异常退出,中断延迟 ms 级。

    流程:
    - pump 线程:for chunk in gen → q.put(chunk),异常存 pump_error
    - 主线程:while True:
        - cancel_event.is_set() → get_raw_stream().close() 关连接 + raise InterruptedError
        - q.get(timeout=0.05) → on_chunk(item) / None 结束 / 异常抛出

    get_raw_stream: callable () -> raw stream | None。LLMClient.chat_stream 把
    raw stream 挂在 self._last_raw_stream,service.py 调用时传
    lambda: getattr(self.llm, "_last_raw_stream", None)。MockLLM 没有该属性,
    getattr 兜底 None,cancel 时仅靠 flag 在 chunk 之间检查(mock chunk 间隔为 0)。

    gen: chat_stream 返回的 generator
    cancel_event: threading.Event
    on_chunk: 收到 chunk 调 on_chunk(chunk),异常时主循环 catch
    get_raw_stream: callable () -> stream | None,cancel 时调 stream.close()
    """
    q: queue.Queue = queue.Queue()
    pump_error: list = []

    def _pump():
        try:
            for chunk in gen:
                q.put(chunk)
        except Exception as e:
            pump_error.append(e)
        finally:
            q.put(None)  # sentinel

    t = threading.Thread(target=_pump, daemon=True)
    t.start()

    while True:
        if cancel_event.is_set():
            # 真取消:关 raw HTTP 连接,让 pump 线程的 next() 抛异常退出
            if get_raw_stream is not None:
                raw_stream = get_raw_stream()
                if raw_stream is not None:
                    try:
                        raw_stream.close()
                    except Exception:  # noqa: BLE001
                        pass
            raise InterruptedError()
        try:
            item = q.get(timeout=0.05)
        except queue.Empty:
            continue
        if item is None:
            if pump_error:
                raise pump_error[0]
            break
        on_chunk(item)


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
        token_budget: 上下文 token 预算(用于 ctx should_compact / enforce_budget)。
            None 时按 settings.json 的 model_context_window 解析,兜底 200K。
    """

    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        confirmer,
        session_memory=None,
        compaction_state: ContentReplacementState | None = None,
        max_steps: int = 50,
        token_budget: int | None = None,
        debug: bool = False,
        permission: PermissionManager | None = None,
        allow_dirs: list[Path] | None = None,
        on_append: Callable[[dict], None] | None = None,
        skills: list[Skill] | None = None,
        mcp_manager=None,
        agent_id: str = "",
        is_fork_child: bool = False,
        agents: list | None = None,
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.confirmer = confirmer
        self.session_memory = session_memory
        self.compaction_state = (
            compaction_state if compaction_state is not None else ContentReplacementState()
        )
        self.max_steps = max_steps
        # token_budget 默认 None:按 settings.json 的 model_context_window 解析
        # (按 llm.model 精确匹配,没配走 default key,再没走环境变量,最后兜底 200K)。
        # 显式传值时跳过解析(测试场景用小 budget 触发 autocompact)。
        if token_budget is None:
            settings_path = Path.home() / ".taisang" / "settings.json"
            model = getattr(llm, "model", "") or ""
            token_budget = get_context_window(model, settings_path)
        self.token_budget = token_budget
        # autocompact 熔断器:连续失败计数,跨 run() 保留(reset 不清零)。
        # 达到 MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES 后跳过后续 autocompact 尝试,
        # 避免不可恢复的 context(如 prompt_too_long)反复浪费 API 调用。
        # resume/重启时在 get_or_load 清零(新进程 = 重新计数)。
        self._consecutive_compact_failures = 0
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
        self._mcp_manager = mcp_manager
        # 多 agent 支持:agent_id 用于事件流区分主/子;is_fork_child 用于
        # AgentTool 调用入口防递归(fork 内不能再 fork)。
        self.agent_id = agent_id
        self.is_fork_child = is_fork_child
        self.agents = agents or []
        self._pending_async_notifications: list[str] = []
        skills_section = format_skill_listing(self.skills)
        mcp_section = format_mcp_section(mcp_manager) if mcp_manager else ""
        from ..agents.listing import format_agent_listing
        agents_section = format_agent_listing(self.agents) if self.agents else ""
        profile_section = format_profile_section(load_profile())
        self.ctx.append_system(
            build_system_prompt(skills_section, mcp_section, agents_section, profile_section)
        )
        # session memory post-sampling 计数器:跨 run() 累计工具调用次数。
        self._tool_calls_since_last_extract = 0
        # token 用量累计:跨 run() 累加,reset() 清零。结构同 LLMResponse.usage。
        self._session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        # 此轮 run() 的 token 用量临时累加器(每次 run 开始前重置)。
        self._turn_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        # 用户中断信号:每次 run() 新建(避免跨 turn 状态泄漏)。
        # interrupt() set 它,主循环在 chunk / 工具执行前检查,走中断分支。
        self._cancel_event: threading.Event | None = None
        # TodoWrite 维护的任务列表:LLM 调 TodoWriteTool 覆盖式更新,跨 run() 保留
        # (用户能看到上一轮的任务状态;reset 清空)。resume 时从 jsonl 重建。
        self.todos: list[dict] = []

    def set_debug(self, on: bool) -> None:
        """REPL /debug 命令切换开关。"""
        self.debug = on

    def interrupt(self) -> None:
        """用户请求中断当前 turn。thread-safe(threading.Event.set 是线程安全的)。

        主循环在下一个 chunk 或工具执行前检查 is_set() → True 走中断分支。
        如果 turn 已经结束或未开始(_cancel_event is None),set 无副作用。
        """
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _emit_todo_update(self, todos: list[dict], agent_id: str = "") -> None:
        """TodoWriteTool 调用后,通过 _last_on_event emit TODO_UPDATE 事件。

        _last_on_event 是 per-run 的 on_event 回调(run() 开头存到实例),
        让 TodoWriteTool 能拿到当前 run 的事件流。agent_id 默认空(主 agent),
        子 agent 传自己的 id(前端嵌套渲染到父 Agent 卡片)。
        """
        from .events import AgentEvent, TODO_UPDATE

        on_event = getattr(self, "_last_on_event", None)
        if on_event is not None:
            on_event(AgentEvent(type=TODO_UPDATE, payload={"todos": todos}, agent_id=agent_id))

    def _emit_profile_update(
        self, content: str, agent_id: str = ""
    ) -> None:
        """UpdateProfileTool 调用后 emit PROFILE_UPDATE 事件,前端 toast。

        对标 _emit_todo_update:通过 _last_on_event 回调发事件。
        agent_id 默认空(主 agent),子 agent 传自己的 id(前端 toast 统一「agent」)。
        """
        from .events import AgentEvent, PROFILE_UPDATE

        on_event = getattr(self, "_last_on_event", None)
        if on_event is not None:
            on_event(
                AgentEvent(
                    type=PROFILE_UPDATE,
                    payload={"content": content, "source": "agent"},
                    agent_id=agent_id,
                )
            )

    def reset(self) -> None:
        """清空对话上下文 + 重置压缩状态。

        设计选择:**不重置 session_memory**(它是跨 session 的长期笔记,reset 只清短期
        对话历史,长期笔记保留以便下次对话继续利用)。compaction_state 一起重置,
        因为决策冻结表是针对当前 ctx 的 tool_call_id 的,ctx 换了旧决策作废。
        """
        on_append = self.ctx.on_append  # 保留原 on_append(reset 不丢持久化回调)
        self.ctx = ContextManager(token_budget=self.token_budget, on_append=on_append)
        skills_section = format_skill_listing(self.skills)
        mcp_section = format_mcp_section(self._mcp_manager) if self._mcp_manager else ""
        from ..agents.listing import format_agent_listing
        agents_section = format_agent_listing(self.agents) if self.agents else ""
        profile_section = format_profile_section(load_profile())
        self.ctx.append_system(
            build_system_prompt(skills_section, mcp_section, agents_section, profile_section)
        )
        self.compaction_state = ContentReplacementState()
        self._tool_calls_since_last_extract = 0
        self._session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._turn_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        # async 通知队列也清空(reset 清短期状态,通知是短期状态)
        self._pending_async_notifications = []
        # todos 清空(reset 清短期任务状态,新对话从空开始)
        self.todos = []

    def flush_async_notifications(self) -> None:
        """把 _pending_async_notifications 队列里的通知依次 append_user 注入 ctx 并清空。

        AgentService 主循环在本轮所有 tool_result append 完之后调用(紧跟
        flush_skill_injections 之后),保证 async 子 agent 完成通知以 user-role
        消息注入,下轮 LLM 自然看到。OpenAI 协议:user 消息排在 tool 消息之后。
        """
        for text in self._pending_async_notifications:
            self.ctx.append_user(text)
        self._pending_async_notifications = []

    def _merge_child_usage(self, child_session_usage: dict) -> None:
        """把子 agent 的 _session_usage 累加进本 agent(主 agent 用)。

        子 agent 跑完(sync 或 async)后调,保证主 session 累计 token 含子 agent。
        子 agent 自己也 emit USAGE_REPORT 事件(带 agent_id),前端可看子单独用量。
        """
        for k in self._session_usage:
            self._session_usage[k] += child_session_usage.get(k, 0)

    def run(self, query: str, on_event: EventCallback | None = None) -> Answer:
        """执行 Agent 循环,返回 Answer。

        每次:
        1. enforce_budget(tool_result 持久化预算)
        2. ctx.should_compact() 时调 _try_autocompact(LLM 摘要)
        3. LLM 调工具就执行,append observation
        4. session_memory post-sampling(达到阈值就 extract + 注入主 prompt)

        注意:self.ctx 跨 run() 保留,多轮对话有短期记忆;reset() 清空。
        """
        # Task 14: 保存 on_event 到实例,让子 agent 的 AgentTool 能转发子事件到主 SSE 流。
        # agent_tool._run_sync 通过 getattr(self, "_last_on_event", None) 拿到 parent_emit。
        # 不需要清理:下次 run() 会覆盖;无 run 就没有子事件需要转发。
        self._last_on_event = on_event
        # 每次 run 新建 cancel_event(避免上轮 set 的状态影响这轮)
        self._cancel_event = threading.Event()
        # 重置此轮 token 累加器(session 累计不清,跨 run 保留)
        self._turn_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        # 本轮是否已 compact 过:防 autocompact 死循环(system 超预算时压对话降不下来)。
        # 每次 run() 新建,跨 turn 不保留(下一轮可以再 compact)。
        self._compacted_this_turn = False
        self.ctx.append_user(query)

        registry = ToolRegistry(
            cwd=self.source_root,
            shell=self.shell,
            confirmer=self.confirmer,
            permission=self.permission,
            skills=self.skills,
            ctx=self.ctx,
            mcp_manager=self._mcp_manager,
            agents=self.agents,
            parent_service=self,
            cancel_event=self._cancel_event,
            service=self,
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
            # 收集 ToolRegistry 里所有工具的 max_result_size_chars,传给 enforce_budget
            # 让 ReadFileTool(Infinity) opt-out 持久化,BashTool(30K) 等按各自阈值判断。
            tool_size_limits = {
                tool_name: getattr(tool, "max_result_size_chars", 100_000)
                for tool_name, tool in registry._tools.items()
            }
            new_msgs, newly_replaced = enforce_budget(
                self.ctx.messages(),
                self.compaction_state,
                observations_dir,
                tool_size_limits=tool_size_limits,
            )
            self.ctx.replace_messages(new_msgs)
            # stage 1 压缩事件:enforce_budget 持久化了 tool_result 时 emit
            # (newly_replaced 非空 = 本轮有新持久化决策;空 = 未超预算 or 全 frozen)
            if newly_replaced:
                _emit(AgentEvent(
                    type=COMPACTED,
                    payload={
                        "via": "tool_result_budget",
                        "replaced": [
                            {"tool_call_id": r["tool_call_id"], "path": r["path"]}
                            for r in newly_replaced
                        ],
                    },
                ))
            # 阶段 7: autocompact
            # _compacted_this_turn 防死循环:本轮已 compact 过就不再 compact,
            # 哪怕 should_compact 还 True(可能是 system prompt 本身就超 budget,
            # 压对话历史降不下来)。直接放行到 LLM 调用,让用户拿到回复。
            if self.ctx.should_compact() and not self._compacted_this_turn:
                result = self._try_autocompact(transcript_path, _emit)
                if result:
                    self._tool_calls_since_last_extract = 0
                    self._compacted_this_turn = True
                    continue
                else:
                    # 压缩失败(或熔断器 tripped):本轮不再尝试,
                    # 放行到 LLM 调用让用户拿到回复/API 报错。
                    # 熔断器计数会在后续轮次继续累积,达到 3 次后彻底跳过。
                    self._compacted_this_turn = True
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
                # 流式 LLM 调用:重试只包第一次 next(_iter_with_retry)
                # 首 chunk 成功后,后续 chunk 失败不重试(已经吐过字了)
                # _consume_stream_with_cancel: pump 线程消费 stream + 主线程周期检查 cancel,
                # cancel 时调 raw_stream.close() 真关 HTTP 连接(对标 Claude Code abort signal),
                # 让阻塞中的 next() 抛异常退出,中断延迟 ms 级(不等下一个 chunk)
                accumulated_text = ""
                accumulated_reasoning = ""
                tool_calls: list[dict] = []
                usage: dict | None = None
                assistant_appended = False  # 标记是否已 append_assistant(中断处理用)
                stream = _iter_with_retry(
                    lambda: self.llm.chat_stream(messages=self.ctx.messages(), tools=registry.schemas()),
                    on_retry=lambda attempt, err, delay: _emit(
                        AgentEvent(
                            type=LLM_RETRY,
                            payload={
                                "attempt": attempt,
                                "error": f"{type(err).__name__}: {err}",
                                "delay_sec": delay,
                            },
                        )
                    ),
                )

                def _on_chunk(chunk):
                    nonlocal accumulated_text, accumulated_reasoning, tool_calls, usage
                    if chunk.text_delta:
                        accumulated_text += chunk.text_delta
                        _emit(AgentEvent(
                            type=LLM_CHUNK,
                            payload={"text_delta": chunk.text_delta, "reasoning_delta": ""},
                        ))
                    if chunk.reasoning_delta:
                        accumulated_reasoning += chunk.reasoning_delta
                        _emit(AgentEvent(
                            type=LLM_CHUNK,
                            payload={"text_delta": "", "reasoning_delta": chunk.reasoning_delta},
                        ))
                    if chunk.is_final:
                        tool_calls = chunk.tool_calls
                        usage = chunk.usage

                _consume_stream_with_cancel(
                    stream,
                    self._cancel_event,
                    on_chunk=_on_chunk,
                    get_raw_stream=lambda: getattr(self.llm, "_last_raw_stream", None),
                )
            except KeyboardInterrupt:
                # CLI Ctrl+C:转中断信号,走统一中断分支
                self._cancel_event.set()
                raise InterruptedError() from None
            except InterruptedError:
                # 用户中断:把已流出的 text 作为最终答案,标 [interrupted]
                if accumulated_text:
                    text = accumulated_text + " [interrupted]"
                else:
                    text = "(已中断)"
                if not assistant_appended:
                    self.ctx.append_assistant(text=text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": True}))
                self._emit_usage_report(_emit)
                return Answer(
                    text=text, citations=[], complete=False,
                    steps_used=steps, interrupted=True,
                )
            except LLMTransientError as e:
                # 流中失败:半截 text 已通过 LLM_CHUNK 流出,落盘 + 标记
                self._emit_usage_report(_emit)
                log.warning("LLM transient error at step %d: %s", steps, e)
                if accumulated_text:
                    text = accumulated_text + f" [LLM 调用失败: {e}]"
                else:
                    text = f"(LLM 调用失败: {e})"
                if not assistant_appended:
                    self.ctx.append_assistant(text=text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": False}))
                return Answer(
                    text=text, citations=[], complete=False, steps_used=steps,
                )
            except LLMProtocolError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM protocol error at step %d: %s", steps, e)
                text = f"(LLM 协议错误: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": False}))
                return Answer(
                    text=text, citations=[], complete=False, steps_used=steps,
                )
            except LLMError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM error at step %d: %s", steps, e)
                text = f"(LLM 错误: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": False}))
                return Answer(
                    text=text, citations=[], complete=False, steps_used=steps,
                )
            # 累加此轮 + session 累计 token(MockLLM / endpoint 未返回时 usage=None,跳过)
            self._accumulate_usage(usage)

            if not tool_calls:
                if self.debug:
                    _emit(
                        AgentEvent(
                            type=DEBUG_RESPONSE,
                            payload={"step": steps, "text": accumulated_text, "tool_calls": []},
                        )
                    )
                # session memory post-sampling(idle_break 分支):
                # LLM 给最终答案(无 tool_call)是自然对话断点,此时触发 extract。
                # 对齐 Claude Code shouldExtractMemory 的 hasToolCallsInLastTurn=False 分支。
                self._maybe_trigger_session_memory(last_turn_has_tool_calls=False, _emit=_emit)
                citations = self._extract_citations(accumulated_text)
                # 最终答案也要落盘(走 on_append 写 jsonl),否则 resume 缺 assistant 回复
                self.ctx.append_assistant(text=accumulated_text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": accumulated_text, "interrupted": False}))
                self._emit_usage_report(_emit)
                return Answer(
                    text=accumulated_text, citations=citations,
                    complete=True, steps_used=steps,
                )

            if self.debug:
                _emit(
                    AgentEvent(
                        type=DEBUG_RESPONSE,
                        payload={"step": steps, "text": accumulated_text, "tool_calls": tool_calls},
                    )
                )
            self.ctx.append_assistant(text=accumulated_text, tool_calls=tool_calls)
            assistant_appended = True
            for tc in tool_calls:
                # 中断检查点 2:每个工具执行前
                if self._cancel_event.is_set():
                    # 补空 tool_result 避免 LLM API 缺 tool result 报错
                    self.ctx.append_tool_result(
                        '{"_interrupted": true}',
                        name=tc["function"]["name"],
                        tool_call_id=tc["id"],
                    )
                    text = accumulated_text + " [interrupted]" if accumulated_text else "(已中断)"
                    _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": True}))
                    self._emit_usage_report(_emit)
                    return Answer(
                        text=text, citations=[], complete=False,
                        steps_used=steps, interrupted=True,
                    )
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
                except InterruptedError:
                    # ToolRegistry 检查到 cancel_event,走中断分支
                    self.ctx.append_tool_result(
                        '{"_interrupted": true}',
                        name=name, tool_call_id=tc["id"],
                    )
                    text = accumulated_text + " [interrupted]" if accumulated_text else "(已中断)"
                    _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": True}))
                    self._emit_usage_report(_emit)
                    return Answer(
                        text=text, citations=[], complete=False,
                        steps_used=steps, interrupted=True,
                    )
                except Exception as e:
                    log.warning("tool %s dispatch failed: %s", name, e)
                    result = {"error": f"tool {name} failed: {e}"}
                observation = json.dumps(result, ensure_ascii=False)
                total_bytes = len(observation.encode("utf-8"))
                # 移除 _MAX_OBSERVATION_BYTES 硬截断:
                # 工具自己管截断/抛错(ReadFileTool 256KB 抛 error, BashTool 30KB 落盘),
                # enforce_budget 50K 阈值在每轮 LLM 调用前持久化大 observation。
                # service.py 不再加第二道 32KB 截断(会让 enforce_budget 50K 阈值永远触发不到)。
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
            # async 子 agent 完成通知:同样延迟到这里统一 flush(user-role
            # 消息排在 tool 之后,下轮 LLM 自然看到)。
            self.flush_async_notifications()

            # session memory post-sampling(update 分支):
            # 工具执行完,此时本轮 resp 一定有 tool_calls(无 tool_calls 已在上面的 return 分支)。
            # 传 last_turn_has_tool_calls=True,走 update 触发分支(tokens + tool_calls 双满足)。
            self._maybe_trigger_session_memory(last_turn_has_tool_calls=True, _emit=_emit)

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
        返回 False 表示未压缩(熔断器 tripped 或压缩失败),调用方应放行到 LLM 调用。
        操作 self.ctx(实例属性,跨 run() 保留)。

        熔断器:连续失败 MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES(3) 次后跳过后续尝试,
        避免不可恢复的 context(如 prompt_too_long)反复浪费 API 调用。成功时重置计数。

        system prompt 保留策略:压缩前先 _refresh_system_prompt() 刷成最新
        (画像/skill/mcp/agents 可能运行中更新过),刷好的 system 留在 ctx.messages()[0],
        autocompact/session_memory 路径都会把它原样带回来。配置类内容不参与压缩。
        """
        # 熔断器:连续失败达上限直接跳过,让主循环放行到 LLM 调用
        # (API 会返回 prompt_too_long 错误,用户看到明确报错,比死循环重试好)
        if self._consecutive_compact_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
            log.warning(
                "autocompact circuit breaker tripped: %d consecutive failures, skipping",
                self._consecutive_compact_failures,
            )
            return False
        before_tokens = self.ctx.total_tokens()
        # 压缩前先把 system prompt 刷成最新(画像/skill 可能更新过)
        # 刷完后 ctx.messages()[0] 是最新 system,后面 autocompact/session_memory
        # 都会把 system 原样保留,不再丢能力清单。
        self._refresh_system_prompt()
        # 先试 session memory(零 LLM 调用,不会失败,不走熔断器)
        if self.session_memory is not None:
            summary = self.session_memory.read_for_compaction()
            if summary:
                # system 原样带回来:从当前 ctx 摘出 system_msgs
                system_msgs = [m for m in self.ctx.messages() if m.get("role") == "system"]
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
                new_msgs = system_msgs + [boundary, summary_msg]
                self.ctx.replace_messages(new_msgs, compaction_via="session_memory")
                after_tokens = self.ctx.total_tokens()
                _emit(AgentEvent(type=COMPACTED, payload={
                    "via": "session_memory",
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "summary_messages": len(new_msgs),
                }))
                # session_memory 路径零 LLM 调用,视为成功,重置熔断器
                self._consecutive_compact_failures = 0
                return True

        # fallback: LLM 摘要(do_autocompact 内部会把 system 原样带回来)
        from ..compaction.autocompact import autocompact as do_autocompact

        try:
            new_msgs = do_autocompact(self.ctx.messages(), self.llm, transcript_path)
            self.ctx.replace_messages(new_msgs, compaction_via="llm")
            after_tokens = self.ctx.total_tokens()
            _emit(AgentEvent(type=COMPACTED, payload={
                "via": "llm",
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "summary_messages": len(new_msgs),
            }))
            # 成功:重置熔断器
            self._consecutive_compact_failures = 0
            return True
        except Exception as e:  # noqa: BLE001 — 熔断器要捕获所有异常
            self._consecutive_compact_failures += 1
            log.warning(
                "autocompact failed (%d/%d): %s",
                self._consecutive_compact_failures,
                MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
                e,
            )
            if self._consecutive_compact_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
                log.error(
                    "autocompact circuit breaker tripped after %d consecutive failures, "
                    "future attempts will be skipped",
                    self._consecutive_compact_failures,
                )
            return False

    def _refresh_system_prompt(self) -> None:
        """重建最新 system prompt 并原地替换 ctx 里第一条 system 消息。

        用途:
        - autocompact 触发前调一次:保证压缩时 ctx.messages()[0] 是最新 system
          (画像/skill/mcp/agents 运行中可能更新过),autocompact 把它原样带回来,
          不丢能力清单。
        - prompt 配置变更广播到活跃 session 时也可调。

        与旧 _reinject_profile_into_system 的区别:
        - 旧方法在 replace_messages 之后调,此时 ctx 里已无 system,replace_system_prompt
          找不到 system 可替换 → no-op,system 永远丢。
        - 新方法在 replace_messages 之前调,ctx 里还有 system,replace_system_prompt
          能成功替换。
        """
        skills_section = format_skill_listing(self.skills)
        mcp_section = format_mcp_section(self._mcp_manager) if self._mcp_manager else ""
        from ..agents.listing import format_agent_listing
        agents_section = format_agent_listing(self.agents) if self.agents else ""
        profile_section = format_profile_section(load_profile())
        new_system = build_system_prompt(skills_section, mcp_section, agents_section, profile_section)
        self.ctx.replace_system_prompt(new_system)

    def _maybe_trigger_session_memory(
        self, last_turn_has_tool_calls: bool, _emit: EventCallback | None = None
    ) -> None:
        """session memory post-sampling:检查阈值,达标就异步触发后台 extract。

        两个触发点:
        - idle_break:LLM 给最终答案(无 tool_call)→ last_turn_has_tool_calls=False
        - update:工具执行完(本轮有 tool_call)→ last_turn_has_tool_calls=True

        触发后重置 _tool_calls_since_last_extract 计数器。
        emit COMPACTED 事件(若 _emit 给定),payload: {via, trigger, current_tokens, delta_tokens}。
        """
        if not self.session_memory:
            return
        current_tokens = self.ctx.total_tokens()
        trigger = self.session_memory.should_extract(
            current_tokens,
            self._tool_calls_since_last_extract,
            last_turn_has_tool_calls=last_turn_has_tool_calls,
        )
        if trigger:
            delta_tokens = (
                current_tokens - self.session_memory._last_extracted_tokens
                if self.session_memory.memory_path.exists()
                else current_tokens
            )
            self.session_memory._do_extract(
                recent_conversation=self._recent_text(),
                current_tokens=current_tokens,
            )
            self._tool_calls_since_last_extract = 0
            if _emit is not None:
                _emit(AgentEvent(
                    type=COMPACTED,
                    payload={
                        "via": "session_memory",
                        "trigger": trigger,
                        "current_tokens": current_tokens,
                        "delta_tokens": delta_tokens,
                    },
                ))

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
