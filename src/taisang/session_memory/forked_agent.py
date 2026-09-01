# src/taisang/session_memory/forked_agent.py
"""分支 agent:只能 Edit memory_path,其他工具 deny。

完全照搬 Claude Code 原文 createMemoryFileCanUseTool 的安全闸设计:
- LLM 只能调 Edit 工具(其他工具直接 deny)
- Edit 的 file_path 必须等于 memory_path(防越界编辑其他文件)
- _apply_edit 直接落盘,不经过 LLM 二次循环
"""

from __future__ import annotations

import json
from pathlib import Path

from ..llm_client import LLMClient, LLMResponse, MockLLM

ALLOWED_TOOL = "Edit"


def run_forked_agent(
    llm: LLMClient | MockLLM,
    memory_path: Path,
    update_prompt: str,
    max_turns: int = 1,
) -> LLMResponse:
    """跑分支 agent,只能调 Edit 改 memory_path。

    简化:只跑一轮,LLM 返回 tool_calls,逐个安全闸检查后执行。
    非 Edit 工具 / file_path 不匹配的 tool_call 一律 deny(跳过不执行)。

    tool_calls 用 OpenAI 标准结构:{"id":..., "type":"function",
    "function":{"name":..., "arguments": "<JSON 字符串>"}}。
    """
    messages = [
        {"role": "system", "content": "你是会话笔记维护助手。"},
        {"role": "user", "content": update_prompt},
    ]
    # 简化:只跑一轮,LLM 返回 tool_calls
    resp = llm.chat(messages=messages, tools=_allowed_tools_schema(memory_path))
    # 安全闸:执行 tool_calls 前检查
    for tc in resp.tool_calls:
        fn = tc.get("function", {})
        if fn.get("name") != ALLOWED_TOOL:
            continue  # deny 非 Edit 工具
        args_str = fn.get("arguments", "") or ""
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            continue  # 畸形 arguments,deny
        if args.get("file_path") != str(memory_path):
            continue  # deny 越界编辑别的文件
        # 真的执行 Edit
        _apply_edit(memory_path, args.get("old_string", ""), args.get("new_string", ""))
    return resp


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


def _apply_edit(file_path: Path, old: str, new: str) -> None:
    """直接落盘 Edit:在 file_path 内容里把第一个 old 替换成 new。"""
    content = file_path.read_text(encoding="utf-8")
    if old not in content:
        return  # old 找不到,不动
    file_path.write_text(content.replace(old, new, 1), encoding="utf-8")
