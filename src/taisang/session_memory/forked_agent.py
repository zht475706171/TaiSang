# src/taisang/session_memory/forked_agent.py
"""分支 agent:只能 Edit memory_path,其他工具 deny。

照搬 Claude Code `createMemoryFileCanUseTool` 的安全闸设计:
- LLM 只能调 Edit 工具(其他工具直接 deny)
- Edit 的 file_path 必须等于 memory_path(防越界编辑其他文件)
- 多轮 loop:LLM 调 Edit → 回喂 tool_result → 继续,直到 LLM 不再调工具或达 max_turns
- 终止靠 prompt 约束("并行 Edit 然后停止")+ max_turns 硬上限(防失控)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..llm_client import LLMClient, LLMResponse, MockLLM

log = logging.getLogger("session_memory")

ALLOWED_TOOL = "Edit"
MAX_TURNS = 10  # 多轮 loop 硬上限,防 LLM 一直调工具不停


def run_forked_agent(
    llm: LLMClient | MockLLM,
    memory_path: Path,
    recent_conversation: str,
    update_prompt: str,
    max_turns: int = MAX_TURNS,
) -> LLMResponse:
    """跑分支 agent,多轮 loop 调 Edit 改 memory_path。

    机制(对齐 Claude Code runForkedAgent + query loop):
    - initialMessages = [recent_conversation 作为 user, assistant 占位, update_prompt 作为 user]
      —— 对齐原版 [...forkContextMessages, ...promptMessages] 结构,
      让 update 指令里的 "Based on the user conversation above" 指向前面的对话历史。
    - 循环 max_turns 次:
      - 发 messages 给 LLM
      - LLM 没返回 tool_calls → 终止(它说停了)
      - 逐个安全闸检查 tool_calls:
        - 非 Edit 工具 → deny(跳过,不执行,回喂 deny tool_result)
        - file_path 不匹配 → deny
        - 畸形 arguments → deny
        - 通过 → 执行 _apply_edit,回喂 ok/fail tool_result
      - 把 assistant tool_calls + 所有 tool_result append 到 messages,进下一轮
    - 达 max_turns 强制终止

    tool_calls 用 OpenAI 标准结构:{"id":..., "type":"function",
    "function":{"name":..., "arguments": "<JSON 字符串>"}}。
    """
    messages: list[dict] = [
        {"role": "system", "content": "你是会话笔记维护助手。"},
        # 把最近对话作为 user 消息(update 指令之前的 "above")
        {"role": "user", "content": recent_conversation},
        # assistant 占位回应,让 update 指令出现在新 user turn 里
        {"role": "assistant", "content": "(以上是最近的用户对话历史,请基于此更新笔记)"},
        {"role": "user", "content": update_prompt},
    ]
    tools = _allowed_tools_schema(memory_path)

    total_applied = 0
    total_denied = 0
    last_resp: LLMResponse | None = None

    for turn in range(1, max_turns + 1):
        resp = llm.chat(messages=messages, tools=tools)
        last_resp = resp

        # log LLM 响应(无论有没有 tool_calls),方便诊断 LLM 为啥跳过/调啥工具
        text_preview = (resp.text or "")[:300]
        log.info(
            "session memory forked agent: turn %d/%d LLM response: " "text=%r tool_calls=%d",
            turn,
            max_turns,
            text_preview,
            len(resp.tool_calls),
        )

        if not resp.tool_calls:
            log.info(
                "session memory forked agent: turn %d/%d done (LLM stopped, no more tool_calls), "
                "total applied=%d denied=%d memory=%s",
                turn,
                max_turns,
                total_applied,
                total_denied,
                memory_path.name,
            )
            return resp

        # 本轮 tool_calls 安全闸 + 执行
        turn_applied = 0
        turn_denied = 0
        tool_results: list[dict] = []
        for tc in resp.tool_calls:
            fn = tc.get("function", {})
            tc_id = tc.get("id") or fn.get("name", "tool")
            name = fn.get("name", "")
            args_str = fn.get("arguments", "") or ""

            # 安全闸 1: 只允许 Edit
            if name != ALLOWED_TOOL:
                turn_denied += 1
                log.warning(
                    "session memory forked agent: deny non-Edit tool %r (only Edit allowed)",
                    name,
                )
                tool_results.append(_tool_result_msg(tc_id, name, {"error": "only Edit allowed"}))
                continue

            # 安全闸 2: arguments 必须是合法 JSON
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError as e:
                turn_denied += 1
                log.warning(
                    "session memory forked agent: deny malformed arguments: %s",
                    e,
                )
                tool_results.append(
                    _tool_result_msg(tc_id, name, {"error": f"malformed arguments: {e}"})
                )
                continue

            # 安全闸 3: file_path 必须等于 memory_path
            if args.get("file_path") != str(memory_path):
                turn_denied += 1
                log.warning(
                    "session memory forked agent: deny Edit on wrong file: %r != %s",
                    args.get("file_path"),
                    memory_path,
                )
                tool_results.append(_tool_result_msg(tc_id, name, {"error": "file_path mismatch"}))
                continue

            # 执行 Edit
            ok = _apply_edit(memory_path, args.get("old_string", ""), args.get("new_string", ""))
            if ok:
                turn_applied += 1
                tool_results.append(_tool_result_msg(tc_id, name, {"ok": True}))
            else:
                turn_denied += 1
                tool_results.append(
                    _tool_result_msg(tc_id, name, {"error": "old_string not found in file"})
                )

        # append assistant + 所有 tool_result 到 messages,进下一轮
        messages.append(
            {
                "role": "assistant",
                "content": resp.text or "",
                "tool_calls": resp.tool_calls,
            }
        )
        for tr in tool_results:
            messages.append(tr)

        total_applied += turn_applied
        total_denied += turn_denied
        log.info(
            "session memory forked agent: turn %d/%d, applied=%d denied=%d "
            "(cumulative applied=%d denied=%d)",
            turn,
            max_turns,
            turn_applied,
            turn_denied,
            total_applied,
            total_denied,
        )

    log.warning(
        "session memory forked agent: reached max_turns=%d (forced stop), "
        "total applied=%d denied=%d memory=%s",
        max_turns,
        total_applied,
        total_denied,
        memory_path.name,
    )
    return last_resp  # type: ignore[return-value]


def _tool_result_msg(tool_call_id: str, name: str, payload: dict) -> dict:
    """构造 OpenAI 风格 tool result message。"""
    return {
        "role": "tool",
        "name": name,
        "content": json.dumps(payload, ensure_ascii=False),
        "tool_call_id": tool_call_id,
    }


def _allowed_tools_schema(memory_path: Path) -> list[dict]:
    """分支 agent 唯一可用工具:Edit,且 file_path 锁定 memory_path。"""
    return [
        {
            "name": "Edit",
            "description": f"编辑 {memory_path}。只能编辑这个文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": str(memory_path)},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        }
    ]


def _apply_edit(file_path: Path, old: str, new: str) -> bool:
    """直接落盘 Edit:在 file_path 内容里把第一个 old 替换成 new。

    返回 True 表示成功;False 表示 old_string 找不到(静默失败,已 log warning)。
    """
    content = file_path.read_text(encoding="utf-8")
    if old not in content:
        log.warning(
            "session memory forked agent: Edit old_string not found in %s "
            "(LLM 给的 old_string 跟实际文件对不上,笔记没更新这处)",
            file_path.name,
        )
        return False
    file_path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True
