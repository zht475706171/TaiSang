"""autocompact 三道压缩流水线最后一道:7 项通用对话摘要 测试。"""

from taisang.compaction.autocompact import (
    _extract_summary,
    _messages_to_text,
    autocompact,
)
from taisang.llm_client import LLMResponse, MockLLM


def test_autocompact_generates_summary_and_replaces_messages(tmp_path):
    """autocompact:调 LLM 生成 7 项通用摘要,替换 state.messages。"""
    summary_text = """<analysis>分析对话</analysis>
<summary>
1. 用户的目标:给 repo 加一个新功能
2. 已经完成的步骤:改了 a.py、b.py,跑了 pytest
3. 还没完成的步骤:写测试、更新 README
4. 关键文件清单: a.py(入口)、b.py(工具函数)
5. 关键决策点:用 foo 而不是 bar,因为更简单
6. 当前状态:下一步该写测试
7. 注意事项:用户偏好函数式风格、不要加注释
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
    assert "用户的目标" in summary_msg["content"]
    # 原对话没了
    assert not any(m["content"] == "x" * 200_000 for m in result if m["role"] == "tool")


def test_autocompact_extracts_summary_block(tmp_path):
    """LLM 返回 <analysis>...</analysis><summary>...</summary>,
    最终 summary msg 不含 <analysis> 标签、含 <summary> 块内容。"""
    raw = """<analysis>这里是分析过程,应该被丢弃</analysis>
<summary>
1. 用户的目标:给 repo 加新功能
2. 已经完成的步骤:改了 a.py
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
    assert "用户的目标" in summary_msg["content"]
    assert "已经完成的步骤" in summary_msg["content"]


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
