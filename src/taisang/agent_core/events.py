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
# debug 事件:/debug 模式下,把发给 LLM 的 messages / LLM 返回的响应 / 工具完整结果 dump 出来
DEBUG_REQUEST = "debug_request"
DEBUG_RESPONSE = "debug_response"
DEBUG_TOOL_RESULT = "debug_tool_result"
# token 用量事件:run() 结束时 emit,UI 渲染此轮 + session 累计 token
USAGE_REPORT = "usage_report"
# Web UI 异步确认事件:WebConfirmer 被调用时 emit,前端弹卡片,POST /confirm/{token} 回应。
# CLI chat 路径不 emit(用 default_confirmer 直接 stdin)。
CONFIRM_REQUEST = "confirm_request"
# LLM 重试事件:call_with_retry 在重试前 emit,前端 ThinkingIndicator 显示"第 N 次重试中"。
# payload: {"attempt": int, "error": str, "delay_sec": float}
LLM_RETRY = "llm_retry"
# LLM 流式 chunk 事件:chat_stream 每收一个 chunk emit,前端累积到"正在流"的 assistant 消息。
# payload: {"text_delta": str, "reasoning_delta": str, "agent_id": str}
# 一次 emit 只含一种 delta(另一种为空字符串),前端按非空那个渲染。
# agent_id: 主 agent 为空,子 agent 用唯一 id(嵌套渲染到父卡片)。
LLM_CHUNK = "llm_chunk"
# TodoWrite 任务追踪事件:LLM 调 TodoWriteTool 后 emit,前端顶部 sticky 区渲染 todo 列表。
# payload: {"todos": list[dict]}  全量快照(覆盖式,不是增量)
# 每个 todo: {"content": str, "status": "pending"|"in_progress"|"completed", "activeForm": str}
# agent_id: 主 agent 为空(渲染到顶部),子 agent 用 id(嵌套到父 Agent 卡片,不冒泡顶部)。
TODO_UPDATE = "todo_update"


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
    agent_id: str = ""  # 主 agent 为空,子 agent 用唯一 id(SSE 区分嵌套渲染)
    # NOTE:debug 事件(DEBUG_REQUEST/DEBUG_RESPONSE/DEBUG_TOOL_RESULT)只在 /debug
    # 模式下 emit,payload 结构:
    #   DEBUG_REQUEST: {"step": int, "messages": list[dict], "tools": list[dict]}
    #   DEBUG_RESPONSE: {"step": int, "text": str, "tool_calls": list[dict]}
    #   DEBUG_TOOL_RESULT: {"step": int, "name": str, "tool_call_id": str, "observation": str}
    # USAGE_REPORT(每次 run 结束都 emit,不受 debug 开关影响):
    #   {"turn": {"prompt": int, "completion": int, "total": int} | None,
    #    "session": {"prompt": int, "completion": int, "total": int},
    #    "cache": {"available": bool, "cached_tokens": int | None}}
    # CONFIRM_REQUEST(仅 Web UI 路径 emit):
    #   {"token": str, "file_path": str, "old": str, "new": str}
    # LLM_RETRY(call_with_retry 在重试前 emit,每次重试 1 条):
    #   {"attempt": int, "error": str, "delay_sec": float}
    # LLM_CHUNK(chat_stream 每收一个 chunk emit):
    #   {"text_delta": str, "reasoning_delta": str, "agent_id": str}
    #   一次 emit 只含一种 delta(另一种为空字符串)
    # FINAL_ANSWER payload 扩展:
    #   {"text": str, "interrupted": bool}  # interrupted=True 表示用户主动中断
    #   前端用 .get("interrupted", False) 兼容历史事件
