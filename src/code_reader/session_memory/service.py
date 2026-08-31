# src/code_reader/session_memory/service.py
"""SessionMemoryService:平时异步维护笔记,autocompact 触发时零 LLM 调用读笔记。

3 道阈值门控(完全照搬 Claude Code 原文):
- 累积到 MIN_TOKENS_TO_INIT 才初始化笔记
- 上次提取后新增 MIN_TOKENS_BETWEEN_UPDATE tokens 才再提取
- 至少 TOOL_CALLS_BETWEEN_UPDATES 次工具调用才再提取
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..llm_client import LLMClient, MockLLM
from .template import get_template, get_update_prompt

# 3 道阈值门控(完全照搬 Claude Code)
MIN_TOKENS_TO_INIT = 10_000  # 累积到 10K tokens 才初始化笔记
MIN_TOKENS_BETWEEN_UPDATE = 5_000  # 上次提取后新增 5K tokens 才再提取
TOOL_CALLS_BETWEEN_UPDATES = 3  # 至少 3 次工具调用才再提取

# 等待提取完成
EXTRACTION_WAIT_TIMEOUT_MS = 15_000
EXTRACTION_STALE_THRESHOLD_MS = 60_000


class SessionMemoryService:
    """session memory:平时异步维护笔记,autocompact 触发时零 LLM 调用读笔记。"""

    def __init__(self, llm: LLMClient | MockLLM, memory_path: Path) -> None:
        self.llm = llm
        self.memory_path = memory_path
        self._lock = threading.Lock()  # sequential 串行化
        self._last_extracted_tokens = 0
        self._last_extracted_tool_calls = 0
        self._extracting = False

    def ensure_file(self) -> None:
        """笔记文件不存在则写默认模板。"""
        if not self.memory_path.exists():
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.memory_path.write_text(get_template(), encoding="utf-8")

    def should_extract(self, current_tokens: int, tool_calls_since_last: int) -> bool:
        """3 道阈值门控:笔记不存在走 init 门控,存在走 update 门控。"""
        if not self.memory_path.exists():
            return current_tokens >= MIN_TOKENS_TO_INIT
        delta_tokens = current_tokens - self._last_extracted_tokens
        return (
            delta_tokens >= MIN_TOKENS_BETWEEN_UPDATE
            and tool_calls_since_last >= TOOL_CALLS_BETWEEN_UPDATES
        )

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
        """调分支 agent 更新笔记(串行化执行,避免并发踩踏)。

        步骤:
        1. 拿锁(sequential 串行化)
        2. ensure_file(笔记不存在先建模板)
        3. 读当前笔记 → 拼 update_prompt
        4. run_forked_agent(LLM 用 Edit 工具改 memory_path)
        """
        with self._lock:  # sequential 串行化
            self._extracting = True
            try:
                self.ensure_file()
                current_notes = self.memory_path.read_text(encoding="utf-8")
                prompt = get_update_prompt(current_notes, recent_conversation, self.memory_path)
                # 函数内 import 避免循环依赖
                from .forked_agent import run_forked_agent

                run_forked_agent(self.llm, self.memory_path, prompt)
            finally:
                self._extracting = False
