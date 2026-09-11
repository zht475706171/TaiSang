"""autocompact:三道压缩流水线最后一道,9 章节摘要。

旁路 LLM(不带 tools)读整个对话,输出 <analysis> + <summary>,
我们只留 <summary> 块作为压缩后的对话记忆,替换 state.messages。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..llm_client import LLMClient, MockLLM
from .prompts import get_autocompact_prompt

# 熔断器:后续接入 agent loop 时启用,连续失败 N 次后停止 autocompact 重试。
MAX_CONSECUTIVE_FAILURES = 3


def autocompact(
    messages: list[dict],
    llm: LLMClient | MockLLM,
    transcript_path: Path | None = None,
) -> list[dict]:
    """调旁路 LLM 生成 9 章节摘要,替换 state.messages。

    流程:
    1. 把 system 消息摘出来不压(配置类内容:人设/工具/skill/mcp/agents/画像,
       可重建、固定开销,压它没意义还丢能力清单)
    2. 只把 non_system 消息拼成 user prompt,加 preamble + BASE_COMPACT_PROMPT + trailer
    3. 调 LLM(不带 tools,纯文本回复)
    4. 删 <analysis> 块,只留 <summary> 块
    5. 构造新 messages:system_msgs 原样 + [boundaryMarker, summaryUserMessage]
    6. transcript 路径提示加到 summary 末尾(供后续 read 回查)
    """
    # 1. 摘出 system(不参与摘要),只压对话历史
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    # 2. 拼 prompt(只用 non_system,读 config 支持用户自定义)
    conversation_text = _messages_to_text(non_system)
    full_prompt = get_autocompact_prompt(conversation_text)
    # 3. 调 LLM(不带 tools)
    resp = llm.chat(
        messages=[
            {"role": "system", "content": "你是对话摘要助手。"},
            {"role": "user", "content": full_prompt},
        ],
        tools=[],  # 强制不调工具
    )
    raw = resp.text
    # 4. 删 <analysis> 块,抽 <summary> 块
    summary = _extract_summary(raw)
    # 5. 构造新 messages:system 原样放最前 + boundary + summary
    boundary_marker = {
        "role": "user",
        "content": "[boundary: autocompact occurred here]",
    }
    summary_content = (
        "This session is being continued from a previous conversation that ran out of context.\n"
        "The summary below covers the earlier portion of the conversation.\n\n"
        f"Summary:\n{summary}"
    )
    # 6. transcript 路径提示
    if transcript_path:
        summary_content += (
            f"\n\nIf you need specific details from before compaction, "
            f"read the full transcript at: {transcript_path}"
        )
    summary_msg = {"role": "user", "content": summary_content}
    return system_msgs + [boundary_marker, summary_msg]


def _messages_to_text(messages: list[dict]) -> str:
    """把 messages 拼成可读文本(供 LLM 摘要)。

    跳过 content 为 None / 非字符串 / 空串的消息,避免把 tool 调用结构当成文本拼。
    """
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


def _extract_summary(raw: str) -> str:
    """从 LLM 输出里抽 <summary> 块,删 <analysis> 块。

    优先匹配 <summary>...</summary>;没有就 fallback:
    删掉 <analysis>...</analysis> 后剩下全部当 summary。
    """
    # 优先 <summary>...</summary>
    m = re.search(r"<summary>(.*?)</summary>", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback:删 <analysis> 块,剩下全要
    cleaned = re.sub(r"<analysis>.*?</analysis>", "", raw, flags=re.DOTALL)
    return cleaned.strip()
