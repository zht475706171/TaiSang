"""测试 LLM client + MockLLM(自研轻量 mock)。"""

from code_reader.llm_client import LLMClient, LLMResponse, MockLLM


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
            LLMResponse(text="", tool_calls=[{"name": "grep", "args": {"pattern": "foo"}}]),
        ]
    )
    r = mock.chat(messages=[], tools=[])
    assert r.tool_calls == [{"name": "grep", "args": {"pattern": "foo"}}]
    assert r.text == ""


def test_real_llm_client_constructs_with_config():
    """只测 client 能用 config 构造,不真发请求。"""
    from code_reader.config import LLMConfig

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


def test_llm_client_malformed_tool_call_json_raises_protocol_error():
    """LLMClient.chat 遇到畸形 tool_call arguments JSON,应抛 LLMProtocolError。"""
    import pytest

    from code_reader.config import LLMConfig
    from code_reader.llm_errors import LLMProtocolError

    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)

    # 构造假 openai 响应:tool_calls[0].function.arguments 是畸形 JSON
    class FakeFunction:
        name = "grep"
        arguments = "{bad json"

    class FakeToolCall:
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

    with pytest.raises(LLMProtocolError, match="malformed tool_call"):
        client.chat(messages=[{"role": "user", "content": "q"}], tools=[{"name": "grep"}])


def test_llm_client_openai_exception_wrapped_as_transient():
    """openai SDK 调用抛任何异常,LLMClient.chat 应包装成 LLMTransientError。"""
    import pytest

    from code_reader.config import LLMConfig
    from code_reader.llm_errors import LLMTransientError

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
