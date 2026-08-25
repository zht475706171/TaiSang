"""章节边界 microcompact。

阶段 6:在写完一个章节(write_doc 工具成功调用)后,把该章节之前累积的
observation 类 tool_result(read_file 等)替换为固定占位符,从而在保留
上下文结构的同时压掉大块历史 observation,避免上下文无限膨胀。
"""

from __future__ import annotations

# 占位符(36 字节,固定)
CLEARED_MESSAGE = "[Old tool result content cleared]"

# 章节 boundary 工具(成功调用后,清掉它之前的 observation)
SECTION_BOUNDARY_TOOLS = {"write_doc"}


def clear_observations_before_section(
    messages: list[dict],
    section_tool_call_id: str,
) -> list[dict]:
    """章节边界 microcompact:把 section_tool_call_id 之前的所有 tool_result(非 boundary 工具)
    替换为占位符。保留 boundary 工具自己的结果。

    Args:
        messages: OpenAI 风格的 message 列表。
        section_tool_call_id: 作为章节边界的 tool_call_id(通常是某次 write_doc 的 id)。

    Returns:
        新的 message 列表(浅拷贝),边界之前的非 boundary tool_result 被替换为 CLEARED_MESSAGE。
        若找不到对应 tool message,返回原列表的 copy。
    """
    # 找 section_tool_call_id 在 messages 里的位置(作为 tool message 的位置)
    section_idx = None
    for i, m in enumerate(messages):
        if m.get("role") == "tool" and m.get("tool_call_id") == section_tool_call_id:
            section_idx = i
            break
    if section_idx is None:
        return list(messages)
    # 在 section_idx 之前的 tool messages,如果 name 不在 boundary 集合,清
    new_messages = list(messages)
    for i in range(section_idx):
        m = new_messages[i]
        if m.get("role") != "tool":
            continue
        name = m.get("name", "")
        if name in SECTION_BOUNDARY_TOOLS:
            continue
        # 已是占位符的不再压(幂等性保护)
        content = m.get("content", "")
        if isinstance(content, str) and content != CLEARED_MESSAGE:
            new_messages[i] = {**m, "content": CLEARED_MESSAGE}
    return new_messages
