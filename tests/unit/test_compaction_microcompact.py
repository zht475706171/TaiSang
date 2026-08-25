"""章节边界 microcompact 单测。

阶段 6:写完一个章节后,把该章节 write_doc 之前的 observation tool_result
替换为固定占位符,保留 boundary 工具自身的返回,以及 write_doc 之后的新章节内容。
"""

from code_reader.compaction.microcompact import (
    CLEARED_MESSAGE,
    clear_observations_before_section,
)


def test_clear_observations_replaces_with_placeholder():
    """章节边界 microcompact:把 write_doc 之前的 tool_result 替换为占位符。"""
    messages = [
        {"role": "user", "content": "开始写章节 1"},
        {
            "role": "assistant",
            "content": "读文件",
            "tool_calls": [{"id": "tc1", "function": {"name": "read_file"}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 5000},
        {
            "role": "assistant",
            "content": "写章节 1",
            "tool_calls": [{"id": "tc2", "function": {"name": "write_doc"}}],
        },
        {"role": "tool", "tool_call_id": "tc2", "name": "write_doc", "content": "ok"},
        {
            "role": "assistant",
            "content": "继续读下一个",
            "tool_calls": [{"id": "tc3", "function": {"name": "read_file"}}],
        },
        {"role": "tool", "tool_call_id": "tc3", "name": "read_file", "content": "y" * 3000},
    ]
    # 章节 1 的 write_doc 是 tc2,清掉它之前的 observation
    new_messages = clear_observations_before_section(messages, section_tool_call_id="tc2")
    # tc1 被清成占位符
    tc1_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc1")
    assert "Old tool result content cleared" in tc1_msg["content"]
    # tc3 保留(write_doc 之后的,属于新章节)
    tc3_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc3")
    assert tc3_msg["content"] == "y" * 3000
    # write_doc 自己不清
    tc2_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc2")
    assert tc2_msg["content"] == "ok"


def test_clear_observations_idempotent():
    """幂等性:对已经是占位符的消息再调一次,内容不变。"""
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": CLEARED_MESSAGE},
        {
            "role": "assistant",
            "content": "写章节",
            "tool_calls": [{"id": "tc2", "function": {"name": "write_doc"}}],
        },
        {"role": "tool", "tool_call_id": "tc2", "name": "write_doc", "content": "ok"},
    ]
    new_messages = clear_observations_before_section(messages, section_tool_call_id="tc2")
    tc1_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc1")
    # 已经是占位符,再调一次仍是占位符,不会变成别的
    assert tc1_msg["content"] == CLEARED_MESSAGE


def test_clear_observations_section_not_found():
    """section_tool_call_id 不存在时,原 messages 完全不变(返回 copy)。"""
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 100},
        {
            "role": "assistant",
            "content": "写章节",
            "tool_calls": [{"id": "tc2", "function": {"name": "write_doc"}}],
        },
        {"role": "tool", "tool_call_id": "tc2", "name": "write_doc", "content": "ok"},
    ]
    new_messages = clear_observations_before_section(messages, section_tool_call_id="not_exist")
    # 内容完全保留
    assert new_messages == messages
    # 而且是 copy,不是同一个对象
    assert new_messages is not messages


def test_clear_observations_preserves_other_boundary_tools():
    """多个 write_doc 时,指定其中一个作为边界,其他 write_doc 的结果也保留。"""
    messages = [
        {"role": "tool", "tool_call_id": "tc_read1", "name": "read_file", "content": "x" * 100},
        {"role": "tool", "tool_call_id": "tc_write1", "name": "write_doc", "content": "ok1"},
        {"role": "tool", "tool_call_id": "tc_read2", "name": "read_file", "content": "y" * 100},
        {
            "role": "assistant",
            "content": "写章节 2",
            "tool_calls": [{"id": "tc_write2", "function": {"name": "write_doc"}}],
        },
        {"role": "tool", "tool_call_id": "tc_write2", "name": "write_doc", "content": "ok2"},
    ]
    # 以第二个 write_doc(tc_write2)作为章节边界
    new_messages = clear_observations_before_section(messages, section_tool_call_id="tc_write2")
    # 第一个 write_doc 在边界之前,但属于 boundary 工具,保留
    w1 = next(m for m in new_messages if m.get("tool_call_id") == "tc_write1")
    assert w1["content"] == "ok1"
    # 边界之前的 read_file 被清
    r1 = next(m for m in new_messages if m.get("tool_call_id") == "tc_read1")
    assert r1["content"] == CLEARED_MESSAGE
    r2 = next(m for m in new_messages if m.get("tool_call_id") == "tc_read2")
    assert r2["content"] == CLEARED_MESSAGE
    # 边界 write_doc 自身保留
    w2 = next(m for m in new_messages if m.get("tool_call_id") == "tc_write2")
    assert w2["content"] == "ok2"
