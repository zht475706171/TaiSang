"""autocompact 三道压缩流水线最后一道:9 章节摘要 测试。"""

from code_reader.compaction.autocompact import (
    _extract_summary,
    _messages_to_text,
    autocompact,
)
from code_reader.llm_client import LLMResponse, MockLLM


def test_autocompact_generates_summary_and_replaces_messages(tmp_path):
    """autocompact:调 LLM 生成 9 章节摘要,替换 state.messages。"""
    summary_text = """<analysis>分析对话</analysis>
<summary>
1. 已完成的章节列表:
   - 00_项目是什么.md
2. 当前在写的章节: 01_架构总览.md
3. 待写章节清单: 02_核心机制/01_xxx.md
4. 已挖出来的机制候选: foo, bar
5. 已挖出来的流程候选: main → foo
6. 已读过的关键文件: a.py, b.py
7. 关键决策点: foo 被引用最多
8. 当前章节的草稿要点: 写到一半
9. 可选的下一步: 完成 01_架构总览.md
</summary>"""
    mock = MockLLM([LLMResponse(text=summary_text, tool_calls=[])])
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "开始"},
        {
            "role": "assistant",
            "content": "调用工具",
            "tool_calls": [{"id": "tc1", "function": {"name": "read_file"}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 200_000},
        {"role": "assistant", "content": "继续"},
    ]
    result = autocompact(
        messages=messages,
        llm=mock,
        transcript_path=tmp_path / "transcript.jsonl",
    )
    # 新 messages 第一条是 boundaryMarker
    assert "compacted" in result[0]["content"].lower() or "boundary" in result[0]["content"].lower()
    # <analysis> 块被删掉了
    summary_msg = next(
        m for m in result if m["role"] == "user" and m["content"] != result[0]["content"]
    )
    assert "<analysis>" not in summary_msg["content"]
    assert "已完成的章节" in summary_msg["content"]
    # 原对话没了
    assert not any(m["content"] == "x" * 200_000 for m in result if m["role"] == "tool")


def test_autocompact_extracts_summary_block(tmp_path):
    """LLM 返回 <analysis>...</analysis><summary>...</summary>,
    最终 summary msg 不含 <analysis> 标签、含 <summary> 块内容。"""
    raw = """<analysis>这里是分析过程,应该被丢弃</analysis>
<summary>
1. 已完成的章节列表: 00_项目是什么.md
2. 当前在写的章节: 01_架构总览.md
</summary>"""
    mock = MockLLM([LLMResponse(text=raw, tool_calls=[])])
    result = autocompact(
        messages=[{"role": "user", "content": "hi"}],
        llm=mock,
    )
    # 取最后一条 user 消息作为 summary
    summary_msg = result[-1]
    assert "<analysis>" not in summary_msg["content"]
    assert "这里是分析过程" not in summary_msg["content"]
    assert "已完成的章节列表" in summary_msg["content"]
    assert "01_架构总览.md" in summary_msg["content"]


def test_autocompact_fallback_when_no_summary_tag():
    """LLM 没返回 <summary> 标签时,_extract_summary 走 fallback:
    删 <analysis> 块后剩下的全部当 summary。"""
    raw = """<analysis>分析过程</analysis>
散乱文本1
散乱文本2"""
    summary = _extract_summary(raw)
    assert "<analysis>" not in summary
    assert "分析过程" not in summary
    assert "散乱文本1" in summary
    assert "散乱文本2" in summary


def test_autocompact_transcript_path_appended(tmp_path):
    """传 transcript_path,最终 summary_msg 的 content 里有 transcript 路径字符串。"""
    transcript = tmp_path / "transcript.jsonl"
    mock = MockLLM([LLMResponse(text="<summary>内容</summary>", tool_calls=[])])
    result = autocompact(
        messages=[{"role": "user", "content": "hi"}],
        llm=mock,
        transcript_path=transcript,
    )
    summary_msg = result[-1]
    assert "transcript.jsonl" in summary_msg["content"]
    # 完整路径出现的形态:read the full transcript at: <path>
    assert str(transcript) in summary_msg["content"]


def test_messages_to_text_handles_non_string_content():
    """messages 里有 content 是 None 或非字符串的,_messages_to_text 应跳过不报错。"""
    messages = [
        {"role": "user", "content": "正常文本"},
        {"role": "assistant", "content": None},
        {"role": "tool", "content": 12345},
        {"role": "assistant", "content": ""},
    ]
    text = _messages_to_text(messages)
    assert "[user]: 正常文本" in text
    # None / 非字符串 / 空串都跳过
    assert "None" not in text
    assert "12345" not in text
