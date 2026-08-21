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
