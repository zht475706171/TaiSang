# src/taisang/session_memory/service.py
"""SessionMemoryService:平时异步维护笔记,autocompact 触发时零 LLM 调用读笔记。

3 道阈值门控(完全照搬 Claude Code 原文):
- 累积到 MIN_TOKENS_TO_INIT 才初始化笔记
- 上次提取后新增 MIN_TOKENS_BETWEEN_UPDATE tokens 才再提取
- 至少 TOOL_CALLS_BETWEEN_UPDATES 次工具调用才再提取(主路径)
- 补充分支:tokens 够 + 最后一轮无 tool_call(自然对话断点)也触发
  —— 覆盖纯聊天场景(用户没用工具,但聊了很多内容)

异步执行(类 Claude Code):extract 在后台 daemon 线程跑,不阻塞主 agent 循环。
- _do_extract 启动后台线程立即返回,主流程继续 emit 事件/跑工具
- 并发:已经在跑(_extracting=True)就跳过本次触发,不等不排队
- 错误处理:后台线程内部 try/except 全包,任何异常只 log warning,
  主流程不受影响(用户不会看到 extract 失败导致的 error)
- 超时:LLM 调用超时由 LLMClient 控制(30s),异步下不阻塞用户,
  超时只让本次 extract 跳过,下次触发重试
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from ..llm_client import LLMClient, MockLLM
from .template import get_template, get_update_prompt

log = logging.getLogger("session_memory")

# 3 道阈值门控(完全照搬 Claude Code)
MIN_TOKENS_TO_INIT = 10_000  # 累积到 10K tokens 才初始化笔记
MIN_TOKENS_BETWEEN_UPDATE = 5_000  # 上次提取后新增 5K tokens 才再提取
TOOL_CALLS_BETWEEN_UPDATES = 3  # 至少 3 次工具调用才再提取


class SessionMemoryService:
    """session memory:平时异步维护笔记,autocompact 触发时零 LLM 调用读笔记。"""

    def __init__(self, llm: LLMClient | MockLLM, memory_path: Path) -> None:
        self.llm = llm
        self.memory_path = memory_path
        self._lock = threading.Lock()  # 保护 _extracting 标志
        self._last_extracted_tokens = 0
        self._last_extracted_tool_calls = 0
        self._extracting = False

    def ensure_file(self) -> None:
        """笔记文件不存在则写默认模板。"""
        if not self.memory_path.exists():
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.memory_path.write_text(get_template(), encoding="utf-8")

    def should_extract(
        self,
        current_tokens: int,
        tool_calls_since_last: int,
        last_turn_has_tool_calls: bool = True,
    ) -> bool:
        """3 道阈值门控 + idle_break 分支:笔记不存在走 init,存在走 update/idle_break。

        参数:
            current_tokens: 当前 ctx 总 token 数
            tool_calls_since_last: 上次提取后累计工具调用次数
            last_turn_has_tool_calls: 最后一轮 LLM 响应是否包含 tool_call
                True=有工具调用(还在干活);False=没有(自然对话断点)
                默认 True(保守:不知道就当有,不触发 idle_break)

        已在提取中(_extracting=True)时直接返回 False,避免并发触发。

        触发条件(对齐 Claude Code shouldExtractMemory):
        1. 笔记不存在 + current_tokens >= MIN_TOKENS_TO_INIT → init 触发
        2. 笔记存在 + delta_tokens >= MIN_TOKENS_BETWEEN_UPDATE
           + tool_calls_since_last >= TOOL_CALLS_BETWEEN_UPDATES → update 触发
        3. 笔记存在 + delta_tokens >= MIN_TOKENS_BETWEEN_UPDATE
           + last_turn_has_tool_calls=False → idle_break 触发(自然断点)
        """
        if self._extracting:
            log.info("session memory TRIGGER skipped: already running")
            return False

        if not self.memory_path.exists():
            if current_tokens >= MIN_TOKENS_TO_INIT:
                log.info(
                    "session memory TRIGGER init: tokens=%d (>= %d), memory=%s",
                    current_tokens,
                    MIN_TOKENS_TO_INIT,
                    self.memory_path.name,
                )
                return True
            return False

        delta_tokens = current_tokens - self._last_extracted_tokens
        has_met_token = delta_tokens >= MIN_TOKENS_BETWEEN_UPDATE
        has_met_tools = tool_calls_since_last >= TOOL_CALLS_BETWEEN_UPDATES

        # 分支 2: 满足 token + 工具调用次数
        if has_met_token and has_met_tools:
            log.info(
                "session memory TRIGGER update: delta_tokens=%d (>= %d), "
                "tool_calls=%d (>= %d), memory=%s",
                delta_tokens,
                MIN_TOKENS_BETWEEN_UPDATE,
                tool_calls_since_last,
                TOOL_CALLS_BETWEEN_UPDATES,
                self.memory_path.name,
            )
            return True

        # 分支 3: 满足 token + 最后一轮无工具调用(自然对话断点)
        if has_met_token and not last_turn_has_tool_calls:
            log.info(
                "session memory TRIGGER idle_break: delta_tokens=%d (>= %d), "
                "last_turn_no_tool_calls, memory=%s",
                delta_tokens,
                MIN_TOKENS_BETWEEN_UPDATE,
                self.memory_path.name,
            )
            return True

        return False

    def read_for_compaction(self) -> str | None:
        """autocompact 触发时调用:读笔记内容作为摘要。返回 None 则 fallback 到 LLM 摘要。"""
        if not self.memory_path.exists():
            return None
        content = self.memory_path.read_text(encoding="utf-8")
        # 空模板检测:内容等于默认模板(去掉首尾空白后)就判为空
        if content.strip() == get_template().strip():
            return None  # 还是空模板,没维护过
        return content

    def _do_extract(self, recent_conversation: str) -> None:
        """启动后台线程异步提取笔记(立即返回,不阻塞主流程)。

        机制:
        - 检查 _extracting 标志:已在跑就跳过(不排队)
        - 启动 daemon 线程跑 _extract_worker
        - _extract_worker 内部 try/except 全包,失败只 log warning

        主流程调本方法后立即拿到控制权,不用等 LLM 调用完成。
        """
        with self._lock:
            if self._extracting:
                log.info(
                    "session memory extract SKIPPED: already running, memory=%s",
                    self.memory_path.name,
                )
                return
            self._extracting = True
        log.info("session memory extract STARTED: memory=%s", self.memory_path.name)
        # 启动后台 daemon 线程(主进程退出时不等)
        t = threading.Thread(
            target=self._extract_worker,
            args=(recent_conversation,),
            daemon=True,
            name="session-memory-extract",
        )
        t.start()

    def _extract_worker(self, recent_conversation: str) -> None:
        """后台线程主体:调 forked agent 多轮更新笔记。

        全程 try/except 包裹,任何异常(超时/网络/协议错)只 log warning,
        不让主流程受影响。finally 清 _extracting 标志。
        """
        try:
            self.ensure_file()
            current_notes = self.memory_path.read_text(encoding="utf-8")
            prompt = get_update_prompt(current_notes, recent_conversation, self.memory_path)
            # 函数内 import 避免循环依赖
            from .forked_agent import run_forked_agent

            run_forked_agent(self.llm, self.memory_path, prompt)
            log.info(
                "session memory extract DONE: memory=%s",
                self.memory_path.name,
            )
        except Exception as e:  # noqa: BLE001 — 后台任务兜底,任何异常都不影响主流程
            log.warning(
                "session memory extract FAILED (non-fatal): %s, memory=%s",
                e,
                self.memory_path.name,
            )
        finally:
            with self._lock:
                self._extracting = False
