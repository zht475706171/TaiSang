"""Agent 循环事件类型,用于向 UI 层实时推送中间步骤。

AgentService.run 可选接收 on_event 回调,在 4 个点发事件:
- LLM_THINKING:开始调 LLM
- TOOL_CALL:工具被调(name + args)
- TOOL_RESULT:工具返回(截断后的预览 + 总字节数)
- FINAL_ANSWER:最终答案

UI 层(cli/main.py 的 _render_event)把 event 渲染成 emoji + 缩进文本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 事件类型常量
LLM_THINKING = "llm_thinking"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
FINAL_ANSWER = "final_answer"
# Task 12 追加:文档写完 + 上下文压缩
DOC_WRITTEN = "doc_written"
COMPACTED = "compacted"


@dataclass
class AgentEvent:
    """Agent 循环一个步骤的事件。

    type:见上面 4 个常量 + Task 12 追加的 DOC_WRITTEN / COMPACTED。
    payload:事件特定数据,结构按 type 而定:
        - LLM_THINKING: {} (空)
        - TOOL_CALL: {"name": str, "args": dict}
        - TOOL_RESULT: {"name": str, "preview": str, "total_bytes": int}
        - FINAL_ANSWER: {"text": str}
        - DOC_WRITTEN: {"path": str}  # Task 12:write_doc 落盘后
        - COMPACTED: {"via": "llm" | "session_memory"}  # Task 12:autocompact 后
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
