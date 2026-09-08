"""测试 StreamChunk dataclass。"""

from taisang.llm_stream import StreamChunk


def test_stream_chunk_defaults():
    """StreamChunk 默认值:空字符串 / 空列表 / None / False。"""
    c = StreamChunk()
    assert c.text_delta == ""
    assert c.reasoning_delta == ""
    assert c.tool_calls == []
    assert c.usage is None
    assert c.is_final is False


def test_stream_chunk_text_delta():
    """text_delta 字段可设值。"""
    c = StreamChunk(text_delta="hello")
    assert c.text_delta == "hello"
    assert c.reasoning_delta == ""  # 其他字段保持默认


def test_stream_chunk_final():
    """最后 chunk 含 tool_calls + usage + is_final。"""
    c = StreamChunk(
        tool_calls=[{"id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        is_final=True,
    )
    assert c.is_final is True
    assert c.tool_calls[0]["id"] == "tc1"
    assert c.usage["total_tokens"] == 15


def test_stream_chunk_reasoning_delta():
    """reasoning_delta 字段可设值。"""
    c = StreamChunk(reasoning_delta="思考中...")
    assert c.reasoning_delta == "思考中..."
    assert c.text_delta == ""