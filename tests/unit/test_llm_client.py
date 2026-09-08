"""测试 LLM client + MockLLM(自研轻量 mock)。"""

from taisang.llm_client import LLMClient, LLMResponse, MockLLM


def test_mock_llm_returns_prescribed_responses_in_order():
    mock = MockLLM(
        [
            LLMResponse(text="第一个响应", tool_calls=[]),
            LLMResponse(text="第二个响应", tool_calls=[]),
        ]
    )
    r1 = mock.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    r2 = mock.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert r1.text == "第一个响应"
    assert r2.text == "第二个响应"


def test_mock_llm_records_calls():
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    mock.chat(messages=[{"role": "user", "content": "q"}], tools=[{"name": "grep"}])
    assert len(mock.calls) == 1
    assert mock.calls[0]["messages"][0]["content"] == "q"
    assert mock.calls[0]["tools"][0]["name"] == "grep"


def test_mock_llm_raises_when_run_out():
    import pytest

    mock = MockLLM([LLMResponse(text="only", tool_calls=[])])
    mock.chat(messages=[], tools=[])
    with pytest.raises(RuntimeError, match="no more mock responses"):
        mock.chat(messages=[], tools=[])


def test_mock_llm_tool_call_response():
    mock = MockLLM(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "grep", "arguments": '{"pattern": "foo"}'},
                    }
                ],
            ),
        ]
    )
    r = mock.chat(messages=[], tools=[])
    assert r.tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "grep", "arguments": '{"pattern": "foo"}'},
        }
    ]
    assert r.text == ""


def test_real_llm_client_constructs_with_config():
    """只测 client 能用 config 构造,不真发请求。"""
    from taisang.config import LLMConfig

    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)
    assert client.model == "m"


def test_mock_llm_calls_not_mutated_by_caller():
    """MockLLM.calls 用 deepcopy 存,caller 后续 mutate messages 不应污染记录。"""
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    messages = [{"role": "user", "content": "原始问题"}]
    mock.chat(messages=messages, tools=[])
    # caller 后续 mutate
    messages[0]["content"] = "被改了"
    messages.append({"role": "user", "content": "新增的"})
    # 记录里的 messages 应保持原始
    assert mock.calls[0]["messages"] == [{"role": "user", "content": "原始问题"}]


def test_llm_client_malformed_tool_call_structure_raises_protocol_error():
    """LLMClient.chat 遇到畸形 tool_call 结构(缺 function.name/id),应抛 LLMProtocolError。

    注意:畸形 arguments JSON 不在此处抛——LLMClient 只透传 arguments 字符串,
    由 service.py 解析时降级处理。这里测结构异常(AttrError 路径)。
    """
    import pytest

    from taisang.config import LLMConfig
    from taisang.llm_errors import LLMProtocolError

    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)

    # 构造假 openai 响应:tool_calls[0] 缺 function 属性 → AttributeError
    class FakeToolCall:
        # 没有 .function 属性
        pass

    class FakeMessage:
        content = None
        tool_calls = [FakeToolCall()]

    class FakeChoice:
        message = FakeMessage()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeInner:
        chat = FakeChat()

    client._client = FakeInner()

    with pytest.raises(LLMProtocolError, match="malformed tool_call"):
        client.chat(messages=[{"role": "user", "content": "q"}], tools=[{"name": "grep"}])


def test_llm_client_passes_through_standard_tool_call_structure():
    """LLMClient.chat 应透传 OpenAI 标准 tool_call 结构(arguments 保持 JSON 字符串)。"""
    from taisang.config import LLMConfig

    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)

    class FakeFunction:
        name = "grep"
        arguments = '{"pattern": "foo"}'

    class FakeToolCall:
        id = "call_abc"
        function = FakeFunction()

    class FakeMessage:
        content = None
        tool_calls = [FakeToolCall()]

    class FakeChoice:
        message = FakeMessage()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeInner:
        chat = FakeChat()

    client._client = FakeInner()

    resp = client.chat(messages=[{"role": "user", "content": "q"}], tools=[])
    assert resp.tool_calls == [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "grep", "arguments": '{"pattern": "foo"}'},
        }
    ]


def test_llm_client_empty_arguments_kept_as_empty_string():
    """LLMClient.chat:OpenAI 返回 arguments 为空时,保留空串(不 json.loads)。"""
    from taisang.config import LLMConfig

    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)

    class FakeFunction:
        name = "grep"
        arguments = ""  # 空

    class FakeToolCall:
        id = "call_x"
        function = FakeFunction()

    class FakeMessage:
        content = None
        tool_calls = [FakeToolCall()]

    class FakeChoice:
        message = FakeMessage()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeInner:
        chat = FakeChat()

    client._client = FakeInner()

    resp = client.chat(messages=[], tools=[])
    assert resp.tool_calls[0]["function"]["arguments"] == ""


def test_llm_client_openai_exception_wrapped_as_transient():
    """openai SDK 调用抛任何异常,LLMClient.chat 应包装成 LLMTransientError。"""
    import pytest

    from taisang.config import LLMConfig
    from taisang.llm_errors import LLMTransientError

    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)

    class FakeCompletions:
        def create(self, **kwargs):
            raise RuntimeError("network down")

    class FakeChat:
        completions = FakeCompletions()

    class FakeInner:
        chat = FakeChat()

    client._client = FakeInner()

    with pytest.raises(LLMTransientError, match="LLM API call failed"):
        client.chat(messages=[{"role": "user", "content": "q"}], tools=[])


def test_llm_response_reasoning_field_default_empty():
    """LLMResponse.reasoning 默认空字符串(向后兼容)。"""
    r = LLMResponse(text="hello", tool_calls=[])
    assert r.reasoning == ""


def test_llm_response_reasoning_field_set():
    """LLMResponse.reasoning 可设值(测试 thinking 流用)。"""
    r = LLMResponse(text="answer", tool_calls=[], reasoning="thinking process")
    assert r.reasoning == "thinking process"


# --- MockLLM.chat_stream(流式接口)---

from taisang.llm_stream import StreamChunk  # noqa: E402


def test_mock_llm_chat_stream_chunks_text():
    """MockLLM.chat_stream 把 text 拆成 chunk yield,拼回完整 text。"""
    mock = MockLLM([LLMResponse(text="hello world", tool_calls=[])])
    chunks = list(mock.chat_stream(messages=[{"role": "user", "content": "hi"}], tools=[]))
    text = "".join(c.text_delta for c in chunks if c.text_delta)
    assert text == "hello world"
    assert chunks[-1].is_final


def test_mock_llm_chat_stream_final_chunk_has_tool_calls_and_usage():
    """最后 chunk 含 tool_calls + usage + is_final。"""
    mock = MockLLM([
        LLMResponse(
            text="ok",
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    ])
    chunks = list(mock.chat_stream(messages=[{"role": "user", "content": "q"}], tools=[]))
    last = chunks[-1]
    assert last.is_final is True
    assert last.tool_calls[0]["function"]["name"] == "read_file"
    assert last.usage["total_tokens"] == 15


def test_mock_llm_chat_stream_records_calls():
    """chat_stream 也记录调用(deepcopy)。"""
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    list(mock.chat_stream(messages=[{"role": "user", "content": "q"}], tools=[{"name": "grep"}]))
    assert len(mock.calls) == 1
    assert mock.calls[0]["messages"][0]["content"] == "q"
    assert mock.calls[0]["tools"][0]["name"] == "grep"


def test_mock_llm_chat_stream_raises_when_run_out():
    """预设响应用完抛 RuntimeError。"""
    import pytest

    mock = MockLLM([LLMResponse(text="only", tool_calls=[])])
    list(mock.chat_stream(messages=[], tools=[]))
    with pytest.raises(RuntimeError, match="no more mock responses"):
        list(mock.chat_stream(messages=[], tools=[]))


def test_mock_llm_chat_stream_empty_text():
    """空 text 只 yield final chunk(无 text chunk)。"""
    mock = MockLLM([LLMResponse(text="", tool_calls=[])])
    chunks = list(mock.chat_stream(messages=[], tools=[]))
    assert len(chunks) == 1
    assert chunks[0].is_final is True
    assert chunks[0].text_delta == ""


def test_mock_llm_chat_stream_reasoning_chunks():
    """reasoning 字段也拆 chunk yield(测试 thinking 流)。"""
    mock = MockLLM([LLMResponse(text="answer", tool_calls=[], reasoning="thinking process")])
    chunks = list(mock.chat_stream(messages=[], tools=[]))
    reasoning = "".join(c.reasoning_delta for c in chunks if c.reasoning_delta)
    assert reasoning == "thinking process"
    text = "".join(c.text_delta for c in chunks if c.text_delta)
    assert text == "answer"


# --- LLMClient.chat_stream(用 fake stream,不依赖真 endpoint)---

from unittest.mock import MagicMock  # noqa: E402

from taisang.config import LLMConfig  # noqa: E402
from taisang.llm_errors import LLMTransientError  # noqa: E402


def _make_fake_chunk(content=None, reasoning_content=None, tool_calls=None, usage=None, has_choices=True):
    """造一个 fake openai ChatCompletionChunk。"""
    chunk = MagicMock()
    if has_choices:
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        delta.reasoning_content = reasoning_content
        if tool_calls:
            delta.tool_calls = []
            for idx, tc in enumerate(tool_calls):
                tc_mock = MagicMock()
                tc_mock.index = idx
                tc_mock.id = tc.get("id")
                fn_mock = MagicMock()
                fn_mock.name = tc.get("function", {}).get("name")
                fn_mock.arguments = tc.get("function", {}).get("arguments")
                tc_mock.function = fn_mock
                delta.tool_calls.append(tc_mock)
        else:
            delta.tool_calls = None
        choice.delta = delta
        chunk.choices = [choice]
    else:
        chunk.choices = []
    chunk.usage = usage
    return chunk


def _make_fake_stream(chunks):
    """造 fake stream:迭代器 + close() 方法(模拟 openai Stream)。

    close 被调时记录到 close_calls,供测试验证 cancel 时真关流。
    """
    class FakeStream:
        def __init__(self, items):
            self._it = iter(items)
            self.close_calls = 0

        def __iter__(self):
            return self

        def __next__(self):
            # 阻塞模拟:next() 永远阻塞,直到外部 close() 触发 GeneratorExit
            # 用于 cancel 测试:主线程 next() 卡住,外部 gen.close() 让其退出
            return next(self._it)

        def close(self):
            self.close_calls += 1

    return FakeStream(chunks)


def _make_llm_client():
    cfg = LLMConfig(base_url="http://x", api_key="sk-x", model="x")
    return LLMClient(cfg)


def test_llm_client_chat_stream_text_delta():
    """chat_stream 把 delta.content 作为 text_delta yield。"""
    import pytest

    client = _make_llm_client()
    fake_chunks = [
        _make_fake_chunk(content="hello "),
        _make_fake_chunk(content="world"),
        _make_fake_chunk(has_choices=False, usage=MagicMock(prompt_tokens=5, completion_tokens=3, total_tokens=8)),
    ]
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(client._client.chat.completions, "create", lambda **kw: _make_fake_stream(fake_chunks))
        chunks = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}], tools=[]))
    text = "".join(c.text_delta for c in chunks if c.text_delta)
    assert text == "hello world"
    assert chunks[-1].is_final is True
    assert chunks[-1].usage["total_tokens"] == 8


def test_llm_client_chat_stream_reasoning_delta():
    """chat_stream 把 delta.reasoning_content 作为 reasoning_delta yield。"""
    import pytest

    client = _make_llm_client()
    fake_chunks = [
        _make_fake_chunk(reasoning_content="思考"),
        _make_fake_chunk(reasoning_content="过程"),
        _make_fake_chunk(has_choices=False, usage=None),
    ]
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(client._client.chat.completions, "create", lambda **kw: _make_fake_stream(fake_chunks))
        chunks = list(client.chat_stream(messages=[], tools=[]))
    reasoning = "".join(c.reasoning_delta for c in chunks if c.reasoning_delta)
    assert reasoning == "思考过程"


def test_llm_client_chat_stream_tool_calls_accumulated():
    """chat_stream 累积 tool_calls 分片(按 index 拼接 arguments)。"""
    import pytest

    client = _make_llm_client()
    fake_chunks = [
        _make_fake_chunk(tool_calls=[{"id": "tc1", "function": {"name": "read_file", "arguments": '{"path":'}}]),
        _make_fake_chunk(tool_calls=[{"id": "tc1", "function": {"name": "", "arguments": ' "x.py"}'}}]),
        _make_fake_chunk(has_choices=False, usage=None),
    ]
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(client._client.chat.completions, "create", lambda **kw: _make_fake_stream(fake_chunks))
        chunks = list(client.chat_stream(messages=[], tools=[]))
    last = chunks[-1]
    assert last.is_final is True
    assert len(last.tool_calls) == 1
    assert last.tool_calls[0]["id"] == "tc1"
    assert last.tool_calls[0]["function"]["name"] == "read_file"
    assert last.tool_calls[0]["function"]["arguments"] == '{"path": "x.py"}'


def test_llm_client_chat_stream_connection_error_wraps_transient():
    """chat_stream 创建失败包装 LLMTransientError。"""
    import pytest

    client = _make_llm_client()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(client._client.chat.completions, "create", lambda **kw: (_ for _ in ()).throw(Exception("conn refused")))
        with pytest.raises(LLMTransientError, match="LLM API call failed"):
            list(client.chat_stream(messages=[], tools=[]))


def test_llm_client_chat_stream_mid_failure_wraps_transient():
    """流中 chunk 失败包装 LLMTransientError。"""
    import pytest

    client = _make_llm_client()

    def gen():
        yield _make_fake_chunk(content="partial")
        raise Exception("mid stream error")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(client._client.chat.completions, "create", lambda **kw: gen())
        with pytest.raises(LLMTransientError, match="LLM stream failed"):
            list(client.chat_stream(messages=[], tools=[]))


def test_llm_client_chat_stream_close_releases_stream_on_normal_completion():
    """正常完成时 finally 块调 stream.close(),连接释放。"""
    import pytest

    client = _make_llm_client()
    fake_chunks = [
        _make_fake_chunk(content="hi"),
        _make_fake_chunk(has_choices=False, usage=None),
    ]
    with pytest.MonkeyPatch().context() as mp:
        stream = _make_fake_stream(fake_chunks)
        mp.setattr(client._client.chat.completions, "create", lambda **kw: stream)
        list(client.chat_stream(messages=[], tools=[]))
    assert stream.close_calls == 1


def test_llm_client_chat_stream_close_releases_stream_on_external_close():
    """外部调 stream.close()(从另一线程)→ pump 线程 next() 抛异常 → finally 块执行。

    这是 cancel 的核心:service.py 主线程 cancel 时调 self.llm._last_raw_stream.close(),
    pump 线程的 next(stream) 因连接关闭抛异常,generator 的 finally 块再次 close(幂等)。
    """
    import pytest
    import threading
    import time

    client = _make_llm_client()
    # 阻塞 stream:next() 永远阻塞(模拟 LLM 长时间不吐 chunk)
    class BlockingStream:
        def __init__(self):
            self.close_calls = 0
            self._closed = False
        def __iter__(self): return self
        def __next__(self):
            # 模拟阻塞:close 后抛 RuntimeError(像 httpx 连接关闭后 next 抛异常)
            while not self._closed:
                time.sleep(0.05)
            raise RuntimeError("connection closed")
        def close(self):
            self._closed = True
            self.close_calls += 1

    stream = BlockingStream()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(client._client.chat.completions, "create", lambda **kw: stream)
        gen = client.chat_stream(messages=[], tools=[])
        chunks_received = []
        error_seen = []
        def consume():
            try:
                for c in gen:
                    chunks_received.append(c)
            except Exception as e:
                error_seen.append(e)
        t = threading.Thread(target=consume, daemon=True)
        t.start()
        time.sleep(0.2)  # 等 pump 线程进入 next() 阻塞
        # 主线程 cancel:直接 close raw stream(service.py 会这么做)
        assert client._last_raw_stream is stream
        client._last_raw_stream.close()
        t.join(timeout=2)
    # stream.close 被调至少 1 次(主线程 1 次 + finally 块 1 次,幂等)
    assert stream.close_calls >= 1
    # pump 线程因连接关闭抛异常,generator 包装成 LLMTransientError
    assert any(LLMTransientError.__name__ in type(e).__name__ for e in error_seen) or chunks_received == []
