# 流式输出 + 用户中断 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 响应逐字/逐 chunk 流式输出(最终答案 + thinking),Web 和 CLI 都支持;用户可中断当前 turn

**Architecture:** 方案 A — 迭代器 + threading.Event 中断。新增 `llm_stream.py` 定义 `StreamChunk` dataclass;`LLMClient`/`MockLLM` 加 `chat_stream` 方法返回迭代器;`AgentService` 主循环改流式,加 `_cancel_event` + `interrupt()` 方法,用 `_iter_with_retry` 包装器只重试第一次 next;`ToolRegistry` 加 cancel 检查点;Web 加 `POST /interrupt` 路由;前端加 `llm_chunk` 事件监听 + 流式消息累积 + 发送按钮变停止按钮

**Tech Stack:** Python 3.12 + openai SDK + FastAPI + Vue 3.5 + TDesign + EventSource(SSE)

---

## 文件结构

### 新增文件
- `src/taisang/llm_stream.py` — `StreamChunk` dataclass,纯数据载体
- `tests/unit/test_llm_stream.py` — StreamChunk 单测
- `tests/integration/test_streaming_e2e.py` — 流式 + 中断 e2e

### 改动文件(后端)
- `src/taisang/llm_client.py` — `LLMClient.chat_stream` + `MockLLM.chat_stream` + `LLMResponse.reasoning` 字段
- `src/taisang/llm_errors.py` —(不动,复用现有异常)
- `src/taisang/llm_retry.py` —(不动,`call_with_retry` 复用)
- `src/taisang/agent_core/events.py` — 加 `LLM_CHUNK` 常量 + `FINAL_ANSWER` payload 文档加 `interrupted`
- `src/taisang/agent_core/service.py` — 主循环改流式 + 中断机制 + `_iter_with_retry`
- `src/taisang/agent_core/tools.py` — `ToolRegistry.__init__` 加 `cancel_event` 参数 + `call` 方法检查
- `src/taisang/types.py` — `Answer` 加 `interrupted` 字段
- `src/taisang/cli/main.py` — `_render` 加 `LLM_CHUNK` 分支 + Ctrl+C 处理
- `src/taisang/web/app.py` — 加 `POST /api/sessions/{id}/interrupt` 路由

### 改动文件(前端)
- `src/taisang/web/frontend/src/types/index.ts` — 加 `llm_chunk` kind + `streaming` / `interrupted` 字段
- `src/taisang/web/frontend/src/api/chat.ts` — 加 `interruptSession` 函数
- `src/taisang/web/frontend/src/composables/useChatStream.ts` — `llm_chunk` listener + 流式消息累积 + `reasoningText` ref
- `src/taisang/web/frontend/src/components/MessageInput.vue` — 发送按钮变停止按钮
- `src/taisang/web/frontend/src/components/ThinkingIndicator.vue` — 显示 reasoning 流
- `src/taisang/web/frontend/src/views/ChatView.vue` — 接 `stop` 事件 + 传 `streaming` prop

---

## Task 1: StreamChunk dataclass + 单测

**Files:**
- Create: `src/taisang/llm_stream.py`
- Create: `tests/unit/test_llm_stream.py`

- [ ] **Step 1: 写失败测试**

Create `tests/unit/test_llm_stream.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_llm_stream.py -q`
Expected: ImportError, `No module named 'taisang.llm_stream'`

- [ ] **Step 3: 实现 StreamChunk**

Create `src/taisang/llm_stream.py`:

```python
"""LLM 流式响应数据结构。

StreamChunk 是 LLM 流式响应的一个增量单元。一次 yield 通常只含一种 delta
(text 或 reasoning),最后 chunk 含 tool_calls + usage + is_final=True。

独立文件(不放在 llm_client.py),因为 StreamChunk 被 llm_client / service /
前端类型多处引用,独立文件职责更清晰。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StreamChunk:
    """LLM 流式响应的一个 chunk。

    字段:
        text_delta: 答案文本增量(OpenAI delta.content)
        reasoning_delta: 思考过程增量(Kimi delta.reasoning_content,非 OpenAI 标准,
            用 getattr 兜底,其他 endpoint 不返就是空字符串)
        tool_calls: 只在最后 chunk,累积完整的 tool_calls 列表(分片按 index 拼接)
        usage: 只在最后 chunk(需 stream_options include_usage=True)
        is_final: 标记最后一个 chunk
    """

    text_delta: str = ""
    reasoning_delta: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict | None = None
    is_final: bool = False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_llm_stream.py -q`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/taisang/llm_stream.py tests/unit/test_llm_stream.py
git commit -m "feat(llm): StreamChunk dataclass for streaming responses"
```

---

## Task 2: LLMResponse 加 reasoning 字段

**Files:**
- Modify: `src/taisang/llm_client.py:25-37`(`LLMResponse` dataclass)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_llm_client.py`(在文件末尾追加):

```python
def test_llm_response_reasoning_field_default_empty():
    """LLMResponse.reasoning 默认空字符串(向后兼容)。"""
    r = LLMResponse(text="hello", tool_calls=[])
    assert r.reasoning == ""


def test_llm_response_reasoning_field_set():
    """LLMResponse.reasoning 可设值(测试 thinking 流用)。"""
    r = LLMResponse(text="answer", tool_calls=[], reasoning="thinking process")
    assert r.reasoning == "thinking process"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_llm_client.py::test_llm_response_reasoning_field_default_empty tests/unit/test_llm_client.py::test_llm_response_reasoning_field_set -q`
Expected: 2 FAILED, `AttributeError: 'LLMResponse' object has no attribute 'reasoning'`

- [ ] **Step 3: 给 LLMResponse 加 reasoning 字段**

Edit `src/taisang/llm_client.py`,找到 `LLMResponse` dataclass(约 line 25-37),在 `usage` 字段后加 `reasoning` 字段:

```python
@dataclass
class LLMResponse:
    """LLM 一次响应。text 和 tool_calls 至少有一个非空。

    usage: endpoint 返回的 token 用量(OpenAI usage 字段透传),None 表示
        MockLLM 或 endpoint 未返回。结构:
        {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
        cache 命中字段(cached_tokens)若 endpoint 报告也原样保留在 dict 里,
        目前 aitoken521 + glm-5.2 不报告。
    reasoning: thinking 模型的推理过程(Kimi reasoning_content 等)。非流式
        chat() 目前不提取(空字符串),流式 chat_stream() 在 chunk 中按
        reasoning_delta 流出。MockLLM 用此字段测试 reasoning 流。
    """

    text: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict | None = None
    reasoning: str = ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_llm_client.py::test_llm_response_reasoning_field_default_empty tests/unit/test_llm_client.py::test_llm_response_reasoning_field_set -q`
Expected: 2 passed

- [ ] **Step 5: 跑全套确认没 break**

Run: `python -m pytest tests/unit/test_llm_client.py -q`
Expected: all passed(原有测试不受影响,新字段有默认值)

- [ ] **Step 6: 提交**

```bash
git add src/taisang/llm_client.py tests/unit/test_llm_client.py
git commit -m "feat(llm): LLMResponse.reasoning field for thinking models"
```

---

## Task 3: MockLLM.chat_stream + 单测

**Files:**
- Modify: `src/taisang/llm_client.py`(`MockLLM` class,加 `chat_stream` 方法)
- Modify: `tests/unit/test_llm_client.py`(加流式测试)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_llm_client.py`(在文件末尾追加):

```python
"""测试 MockLLM.chat_stream(流式接口)。"""

from taisang.llm_stream import StreamChunk


def test_mock_llm_chat_stream_chunks_text():
    """MockLLM.chat_stream 把 text 拆成 chunk yield,拼回完整 text。"""
    mock = MockLLM([LLMResponse(text="hello world", tool_calls=[])])
    chunks = list(mock.chat_stream(messages=[{"role": "user", "content": "hi"}], tools=[]))
    # 拼回完整 text(忽略 final chunk 的空 text_delta)
    text = "".join(c.text_delta for c in chunks if c.text_delta)
    assert text == "hello world"
    # 最后 chunk is_final
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
    mock = MockLLM([LLMResponse(text="only", tool_calls=[])])
    list(mock.chat_stream(messages=[], tools=[]))
    import pytest
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_llm_client.py -q -k chat_stream`
Expected: 6 FAILED, `AttributeError: 'MockLLM' object has no attribute 'chat_stream'`

- [ ] **Step 3: 实现 MockLLM.chat_stream**

Edit `src/taisang/llm_client.py`,在 `MockLLM` class 里(在 `chat` 方法后)加 `chat_stream` 方法:

```python
    def chat_stream(self, messages: list[dict], tools: list[dict]):
        """测试用流式 chat。把预设 LLMResponse 拆成 chunk yield。

        策略:text 和 reasoning 按 chunk_size=5 拆 chunk(模拟流式节奏),
        tool_calls + usage 放最后 is_final chunk。deepcopy 防 caller mutate。

        Yields: StreamChunk
        """
        from .llm_stream import StreamChunk

        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self._responses:
            raise RuntimeError("no more mock responses prescribed")
        resp = self._responses.pop(0)
        # text 按 chunk_size=5 拆 chunk
        chunk_size = 5
        for i in range(0, len(resp.text or ""), chunk_size):
            yield StreamChunk(text_delta=resp.text[i:i + chunk_size])
        # reasoning 也拆 chunk(测试 thinking 流)
        for i in range(0, len(resp.reasoning or ""), chunk_size):
            yield StreamChunk(reasoning_delta=resp.reasoning[i:i + chunk_size])
        # 最后 final chunk:tool_calls + usage + is_final
        yield StreamChunk(
            tool_calls=resp.tool_calls,
            usage=resp.usage,
            is_final=True,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_llm_client.py -q -k chat_stream`
Expected: 6 passed

- [ ] **Step 5: 跑全套确认没 break**

Run: `python -m pytest tests/unit/test_llm_client.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add src/taisang/llm_client.py tests/unit/test_llm_client.py
git commit -m "feat(llm): MockLLM.chat_stream for streaming tests"
```

---

## Task 4: LLMClient.chat_stream + 单测

**Files:**
- Modify: `src/taisang/llm_client.py`(`LLMClient` class,加 `chat_stream` 方法)
- Modify: `tests/unit/test_llm_client.py`(加 `LLMClient.chat_stream` 测试,用 fake stream)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_llm_client.py`(在文件末尾追加):

```python
"""测试 LLMClient.chat_stream(用 fake stream,不依赖真 endpoint)。"""

from unittest.mock import MagicMock, patch
from taisang.llm_stream import StreamChunk
from taisang.llm_errors import LLMTransientError
from taisang.config import LLMConfig


def _make_fake_chunk(content=None, reasoning_content=None, tool_calls=None, usage=None, has_choices=True):
    """造一个 fake openai ChatCompletionChunk。"""
    chunk = MagicMock()
    if has_choices:
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        delta.reasoning_content = reasoning_content
        # tool_calls 分片:每个 tc 有 index/id/function.name/function.arguments
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
    """造一个 fake iterator(openai SDK stream 返回类型)。"""
    return iter(chunks)


def test_llm_client_chat_stream_text_delta():
    """chat_stream 把 delta.content 作为 text_delta yield。"""
    from taisang.llm_client import LLMClient

    cfg = LLMConfig(base_url="http://x", api_key="sk-x", model="x")
    client = LLMClient(cfg)
    # patch openai.OpenAI 的 chat.completions.create 返回 fake stream
    fake_chunks = [
        _make_fake_chunk(content="hello "),
        _make_fake_chunk(content="world"),
        _make_fake_chunk(has_choices=False, usage=MagicMock(prompt_tokens=5, completion_tokens=3, total_tokens=8)),
    ]
    with patch.object(client._client.chat.completions, "create", return_value=_make_fake_stream(fake_chunks)):
        chunks = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}], tools=[]))

    # 验证:text_delta 拼接 == "hello world",最后 chunk is_final + usage
    text = "".join(c.text_delta for c in chunks if c.text_delta)
    assert text == "hello world"
    assert chunks[-1].is_final is True
    assert chunks[-1].usage["total_tokens"] == 8


def test_llm_client_chat_stream_reasoning_delta():
    """chat_stream 把 delta.reasoning_content 作为 reasoning_delta yield。"""
    from taisang.llm_client import LLMClient

    cfg = LLMConfig(base_url="http://x", api_key="sk-x", model="x")
    client = LLMClient(cfg)
    fake_chunks = [
        _make_fake_chunk(reasoning_content="思考"),
        _make_fake_chunk(reasoning_content="过程"),
        _make_fake_chunk(has_choices=False, usage=None),
    ]
    with patch.object(client._client.chat.completions, "create", return_value=_make_fake_stream(fake_chunks)):
        chunks = list(client.chat_stream(messages=[], tools=[]))

    reasoning = "".join(c.reasoning_delta for c in chunks if c.reasoning_delta)
    assert reasoning == "思考过程"


def test_llm_client_chat_stream_tool_calls_accumulated():
    """chat_stream 累积 tool_calls 分片(按 index 拼接 arguments)。"""
    from taisang.llm_client import LLMClient

    cfg = LLMConfig(base_url="http://x", api_key="sk-x", model="x")
    client = LLMClient(cfg)
    # 模拟 tool_calls 分片:2 个分片拼成 1 个 tool_call
    fake_chunks = [
        _make_fake_chunk(tool_calls=[{"id": "tc1", "function": {"name": "read_file", "arguments": '{"path":'}}]),
        _make_fake_chunk(tool_calls=[{"id": "tc1", "function": {"name": "", "arguments": ' "x.py"}'}}]),
        _make_fake_chunk(has_choices=False, usage=None),
    ]
    with patch.object(client._client.chat.completions, "create", return_value=_make_fake_stream(fake_chunks)):
        chunks = list(client.chat_stream(messages=[], tools=[]))

    last = chunks[-1]
    assert last.is_final is True
    assert len(last.tool_calls) == 1
    assert last.tool_calls[0]["id"] == "tc1"
    assert last.tool_calls[0]["function"]["name"] == "read_file"
    assert last.tool_calls[0]["function"]["arguments"] == '{"path": "x.py"}'


def test_llm_client_chat_stream_connection_error_wraps_transient():
    """chat_stream 创建失败包装 LLMTransientError。"""
    from taisang.llm_client import LLMClient

    cfg = LLMConfig(base_url="http://x", api_key="sk-x", model="x")
    client = LLMClient(cfg)
    with patch.object(client._client.chat.completions, "create", side_effect=Exception("conn refused")):
        import pytest
        with pytest.raises(LLMTransientError, match="LLM API call failed"):
            list(client.chat_stream(messages=[], tools=[]))


def test_llm_client_chat_stream_mid_failure_wraps_transient():
    """流中 chunk 失败包装 LLMTransientError。"""
    from taisang.llm_client import LLMClient

    cfg = LLMConfig(base_url="http://x", api_key="sk-x", model="x")
    client = LLMClient(cfg)

    def gen():
        yield _make_fake_chunk(content="partial")
        raise Exception("mid stream error")

    with patch.object(client._client.chat.completions, "create", return_value=gen()):
        import pytest
        with pytest.raises(LLMTransientError, match="LLM stream failed"):
            list(client.chat_stream(messages=[], tools=[]))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_llm_client.py -q -k "chat_stream and (text_delta or reasoning_delta or tool_calls or connection_error or mid_failure)"`
Expected: 5 FAILED, `AttributeError: 'LLMClient' object has no attribute 'chat_stream'`

- [ ] **Step 3: 实现 LLMClient.chat_stream**

Edit `src/taisang/llm_client.py`,在 `LLMClient` class 里(在 `chat` 方法后)加 `chat_stream` 方法:

```python
    def chat_stream(self, messages: list[dict], tools: list[dict]):
        """发流式 chat completion 请求,返回 StreamChunk 迭代器。

        tools 是工具 schema 列表(OpenAI tool 格式)。

        流式行为:
        - delta.content → text_delta(答案文本)
        - delta.reasoning_content → reasoning_delta(Kimi 等思考模型,getattr 兜底)
        - delta.tool_calls 分片到达,按 index 累积 arguments,最后 chunk 一次给完整 tool_calls
        - 最后 chunk(chunk.choices 为空)含 usage(需 stream_options include_usage=True)

        Raises:
            LLMTransientError: 连接失败 / 流中 chunk 失败(统一包装)
        """
        from .llm_stream import StreamChunk

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "timeout": 60,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            stream = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            cause = getattr(e, "__cause__", None)
            cause_repr = repr(cause) if cause else "(none)"
            log.warning(
                "LLM chat_stream failed: type=%s msg=%s cause=%s",
                type(e).__name__, e, cause_repr, exc_info=True,
            )
            raise LLMTransientError(f"LLM API call failed: {e}") from e

        # 累积器:tool_calls 分片按 index 拼接 arguments
        acc_tool_calls: dict[int, dict] = {}
        last_usage = None
        try:
            for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    text_delta = getattr(delta, "content", None) or ""
                    # reasoning_content 不在 OpenAI 标准里,getattr 兜底
                    reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                    # tool_calls 分片累积
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in acc_tool_calls:
                                acc_tool_calls[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc.id:
                                acc_tool_calls[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    acc_tool_calls[idx]["function"]["name"] += tc.function.name
                                if tc.function.arguments:
                                    acc_tool_calls[idx]["function"]["arguments"] += tc.function.arguments
                    if text_delta or reasoning_delta:
                        yield StreamChunk(text_delta=text_delta, reasoning_delta=reasoning_delta)
                # usage 在最后 chunk(chunk.choices 为空,chunk.usage 非空)
                if chunk.usage:
                    last_usage = {
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                    }
        except Exception as e:
            cause = getattr(e, "__cause__", None)
            cause_repr = repr(cause) if cause else "(none)"
            log.warning(
                "LLM stream chunk failed: type=%s msg=%s cause=%s",
                type(e).__name__, e, cause_repr, exc_info=True,
            )
            raise LLMTransientError(f"LLM stream failed: {e}") from e

        # 流结束,yield 最终 chunk(含完整 tool_calls + usage)
        yield StreamChunk(
            tool_calls=list(acc_tool_calls.values()),
            usage=last_usage,
            is_final=True,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_llm_client.py -q -k "chat_stream and (text_delta or reasoning_delta or tool_calls or connection_error or mid_failure)"`
Expected: 5 passed

- [ ] **Step 5: 跑全套确认没 break**

Run: `python -m pytest tests/unit/test_llm_client.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add src/taisang/llm_client.py tests/unit/test_llm_client.py
git commit -m "feat(llm): LLMClient.chat_stream with tool_calls accumulation"
```

---

## Task 5: Answer 加 interrupted 字段

**Files:**
- Modify: `src/taisang/types.py:16-22`(`Answer` class)
- Modify: `tests/unit/test_types.py`(加 interrupted 测试)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_types.py`(在文件末尾追加):

```python
def test_answer_interrupted_default_false():
    """Answer.interrupted 默认 False(向后兼容)。"""
    from taisang.types import Answer
    a = Answer(text="hello", citations=[], complete=True, steps_used=1)
    assert a.interrupted is False


def test_answer_interrupted_set_true():
    """Answer.interrupted 可设 True(中断场景)。"""
    from taisang.types import Answer
    a = Answer(text="partial [interrupted]", citations=[], complete=False, steps_used=3, interrupted=True)
    assert a.interrupted is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_types.py::test_answer_interrupted_default_false tests/unit/test_types.py::test_answer_interrupted_set_true -q`
Expected: 2 FAILED, `AttributeError: 'Answer' object has no attribute 'interrupted'`

- [ ] **Step 3: 给 Answer 加 interrupted 字段**

Edit `src/taisang/types.py`,修改 `Answer` class:

```python
class Answer(BaseModel):
    """Agent 最终回答。"""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    complete: bool = True  # False 表示因 max_steps/token 提前终止
    steps_used: int = 0
    interrupted: bool = False  # True 表示用户主动中断(半截答案 + [interrupted] 标记)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_types.py::test_answer_interrupted_default_false tests/unit/test_types.py::test_answer_interrupted_set_true -q`
Expected: 2 passed

- [ ] **Step 5: 跑全套确认没 break**

Run: `python -m pytest tests/unit/test_types.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add src/taisang/types.py tests/unit/test_types.py
git commit -m "feat(types): Answer.interrupted field for cancellation"
```

---

## Task 6: events.py 加 LLM_CHUNK 常量 + FINAL_ANSWER payload 文档

**Files:**
- Modify: `src/taisang/agent_core/events.py`

- [ ] **Step 1: 加 LLM_CHUNK 常量**

Edit `src/taisang/agent_core/events.py`,在 `CONFIRM_REQUEST` 常量后加 `LLM_CHUNK` 和 `LLM_RETRY`(如果还没有):

```python
# Web UI 异步确认事件:WebConfirmer 被调用时 emit,前端弹卡片,POST /confirm/{token} 回应。
# CLI chat 路径不 emit(用 default_confirmer 直接 stdin)。
CONFIRM_REQUEST = "confirm_request"
# LLM 重试事件:call_with_retry 在重试前 emit,前端 ThinkingIndicator 显示"第 N 次重试中"。
# payload: {"attempt": int, "error": str, "delay_sec": float}
LLM_RETRY = "llm_retry"
# LLM 流式 chunk 事件:chat_stream 每收一个 chunk emit,前端累积到"正在流"的 assistant 消息。
# payload: {"text_delta": str, "reasoning_delta": str, "agent_id": str}
# 一次 emit 只含一种 delta(另一种为空字符串),前端按非空那个渲染。
# agent_id: 主 agent 为空,子 agent 用唯一 id(嵌套渲染到父卡片)。
LLM_CHUNK = "llm_chunk"
```

- [ ] **Step 2: 更新 AgentEvent docstring 加 LLM_CHUNK + FINAL_ANSWER interrupted**

Edit `src/taisang/agent_core/events.py`,在 `AgentEvent` docstring 的 payload 文档部分加:

```python
    # LLM_RETRY(call_with_retry 在重试前 emit,每次重试 1 条):
    #   {"attempt": int, "error": str, "delay_sec": float}
    # LLM_CHUNK(chat_stream 每收一个 chunk emit):
    #   {"text_delta": str, "reasoning_delta": str, "agent_id": str}
    #   一次 emit 只含一种 delta(另一种为空字符串)
    # FINAL_ANSWER payload 扩展:
    #   {"text": str, "interrupted": bool}  # interrupted=True 表示用户主动中断
    #   前端用 .get("interrupted", False) 兼容历史事件
```

- [ ] **Step 3: 跑现有 events 测试确认没 break**

Run: `python -m pytest tests/unit/test_agent_core.py -q -k "event"`
Expected: all passed(只加常量,不改现有事件)

- [ ] **Step 4: 提交**

```bash
git add src/taisang/agent_core/events.py
git commit -m "feat(events): LLM_CHUNK event type + FINAL_ANSWER interrupted field"
```

---

## Task 7: ToolRegistry 加 cancel_event 参数 + 中断检查

**Files:**
- Modify: `src/taisang/agent_core/tools.py:583`(`ToolRegistry.__init__` 加 `cancel_event` 参数)
- Modify: `src/taisang/agent_core/tools.py:690`(`ToolRegistry.call` 加中断检查)
- Modify: `tests/unit/test_tools.py`(加中断测试)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_tools.py`(在文件末尾追加):

```python
def test_tool_registry_call_raises_interrupted_when_cancel_set(tmp_path):
    """cancel_event set 时,ToolRegistry.call 抛 InterruptedError。"""
    import threading
    from taisang.agent_core.tools import ToolRegistry

    cancel = threading.Event()
    cancel.set()
    registry = ToolRegistry(cwd=tmp_path, cancel_event=cancel)
    import pytest
    with pytest.raises(InterruptedError, match="cancelled"):
        registry.call("read_file", {"path": "x.py"})


def test_tool_registry_call_normal_when_cancel_not_set(tmp_path):
    """cancel_event 未 set 时,ToolRegistry.call 正常执行(不抛 InterruptedError)。"""
    import threading
    from taisang.agent_core.tools import ToolRegistry

    cancel = threading.Event()
    registry = ToolRegistry(cwd=tmp_path, cancel_event=cancel)
    # read_file 不存在的文件 → 返回 error dict(不抛 InterruptedError)
    result = registry.call("read_file", {"path": "nonexistent.py"})
    assert "error" in result  # 文件不存在,正常 error
    # 关键:没抛 InterruptedError


def test_tool_registry_cancel_event_default_none(tmp_path):
    """cancel_event 默认 None(向后兼容,现有调用不受影响)。"""
    from taisang.agent_core.tools import ToolRegistry

    registry = ToolRegistry(cwd=tmp_path)
    assert registry._cancel_event is None
    # 正常调用不抛 InterruptedError
    result = registry.call("read_file", {"path": "nonexistent.py"})
    assert "error" in result
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_tools.py -q -k "cancel"`
Expected: 3 FAILED, `TypeError: ToolRegistry.__init__() got an unexpected keyword argument 'cancel_event'`

- [ ] **Step 3: 给 ToolRegistry.__init__ 加 cancel_event 参数**

Edit `src/taisang/agent_core/tools.py`,修改 `ToolRegistry.__init__` 签名(line 583):

```python
    def __init__(
        self,
        cwd: Path,
        shell=None,
        confirmer=None,
        permission: PermissionManager | None = None,
        bash_timeout: int = 30,
        observations_dir: Path | None = None,
        skills: list | None = None,
        ctx=None,
        mcp_manager=None,
        agents: list | None = None,
        parent_service=None,
        cancel_event=None,  # 新增:threading.Event,用户中断信号
    ) -> None:
```

在 `__init__` 方法体末尾(`if agents and parent_service` 块之后)加:

```python
        # 用户中断信号:工具执行前检查,set 时抛 InterruptedError。
        # 默认 None(向后兼容,现有调用不受影响)。
        self._cancel_event = cancel_event
```

- [ ] **Step 4: 给 ToolRegistry.call 加中断检查**

Edit `src/taisang/agent_core/tools.py`,修改 `ToolRegistry.call` 方法(line 690):

```python
    def call(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"unknown tool: {name}"}
        # 用户中断检查:执行前检查 cancel_event,set 时抛 InterruptedError。
        # AgentService 主循环 catch 后走中断分支(补空 tool_result + [interrupted] 标记)。
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise InterruptedError("tool execution cancelled by user")
        # 每次调用前同步 cwd(Bash cd 后文件工具跟随)
        self._sync_cwd()
        try:
            return tool.run(args)
        except Exception as e:
            return {"error": f"tool {name} failed: {e}"}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_tools.py -q -k "cancel"`
Expected: 3 passed

- [ ] **Step 6: 跑全套 tools 测试确认没 break**

Run: `python -m pytest tests/unit/test_tools.py -q`
Expected: all passed(cancel_event 默认 None,现有测试不受影响)

- [ ] **Step 7: 提交**

```bash
git add src/taisang/agent_core/tools.py tests/unit/test_tools.py
git commit -m "feat(tools): ToolRegistry cancel_event check for interruption"
```

---

## Task 8: AgentService 中断机制(interrupt 方法 + _cancel_event)+ 单测

**Files:**
- Modify: `src/taisang/agent_core/service.py`(`AgentService.__init__` 加 `_cancel_event`,`run` 开头建 Event,加 `interrupt` 方法)
- Modify: `tests/unit/test_agent_core.py`(加 interrupt 方法测试)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_agent_core.py`(在文件末尾追加):

```python
def test_agent_service_interrupt_sets_cancel_event(tmp_path):
    """interrupt() set _cancel_event。"""
    from taisang.agent_core.service import AgentService
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    # run 前 _cancel_event 是 None(还没建)
    assert service._cancel_event is None
    # 跑一个 run 建立 _cancel_event
    service.run("test", on_event=None)
    # run 后 _cancel_event 存在(已 set 或未 set)
    assert service._cancel_event is not None
    # interrupt() set it
    service.interrupt()
    assert service._cancel_event.is_set() is True


def test_agent_service_interrupt_no_op_when_no_run(tmp_path):
    """interrupt() 在 run 之前调用无副作用(_cancel_event 是 None)。"""
    from taisang.agent_core.service import AgentService
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    # _cancel_event 是 None,interrupt() 不抛
    service.interrupt()  # 无副作用
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_agent_core.py -q -k "interrupt_sets or interrupt_no_op"`
Expected: 2 FAILED, `AttributeError: 'AgentService' object has no attribute 'interrupt'` 或 `_cancel_event`

- [ ] **Step 3: 给 AgentService 加 _cancel_event + interrupt 方法**

Edit `src/taisang/agent_core/service.py`,在 `AgentService.__init__` 方法体末尾加:

```python
        # 用户中断信号:每次 run() 新建(避免跨 turn 状态泄漏)。
        # interrupt() set 它,主循环在 chunk / 工具执行前检查,走中断分支。
        self._cancel_event: threading.Event | None = None
```

在 `__init__` 的 import 区域加 `import threading`(如果还没):

```python
import threading
```

在 `AgentService` class 里(`reset` 方法后)加 `interrupt` 方法:

```python
    def interrupt(self) -> None:
        """用户请求中断当前 turn。thread-safe(threading.Event.set 是线程安全的)。

        主循环在下一个 chunk 或工具执行前检查 is_set() → True 走中断分支。
        如果 turn 已经结束或未开始(_cancel_event is None),set 无副作用。
        """
        if self._cancel_event is not None:
            self._cancel_event.set()
```

在 `run` 方法开头(line 195 `self._last_on_event = on_event` 之前)加:

```python
        # 每次 run 新建 cancel_event(避免上轮 set 的状态影响这轮)
        self._cancel_event = threading.Event()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_agent_core.py -q -k "interrupt_sets or interrupt_no_op"`
Expected: 2 passed

- [ ] **Step 5: 跑全套确认没 break**

Run: `python -m pytest tests/unit/test_agent_core.py -q`
Expected: all passed(_cancel_event 默认 None,现有测试不受影响)

- [ ] **Step 6: 提交**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat(agent): AgentService.interrupt + _cancel_event mechanism"
```

---

## Task 9: AgentService.run 流式主循环 + _iter_with_retry

**Files:**
- Modify: `src/taisang/agent_core/service.py`(`run` 方法主循环改流式,加 `_iter_with_retry` 内部函数)
- Modify: `src/taisang/agent_core/service.py`(`ToolRegistry` 构造传 `cancel_event`)
- Modify: `tests/unit/test_agent_core.py`(加流式主循环测试)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_agent_core.py`(在文件末尾追加):

```python
def test_run_streaming_emits_llm_chunk_events(tmp_path):
    """流式 run emit LLM_CHUNK 事件,累积 text_delta == FINAL_ANSWER text。"""
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.events import LLM_CHUNK, FINAL_ANSWER
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    mock = MockLLM([LLMResponse(text="hello world", tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    events = []
    service.run("test", on_event=lambda e: events.append(e))
    chunk_events = [e for e in events if e.type == LLM_CHUNK]
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    # 有多个 chunk(MockLLM chunk_size=5,"hello world" 拆成 3 个 chunk)
    assert len(chunk_events) >= 2
    # 拼接 text_delta == final text
    text = "".join(e.payload.get("text_delta", "") for e in chunk_events)
    assert text == "hello world"
    # final payload interrupted=False
    assert final.payload["interrupted"] is False


def test_run_streaming_reasoning_delta(tmp_path):
    """reasoning_delta 流式 emit(MockLLM reasoning 字段)。"""
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.events import LLM_CHUNK
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    mock = MockLLM([LLMResponse(text="answer", tool_calls=[], reasoning="thinking process")])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    events = []
    service.run("test", on_event=lambda e: events.append(e))
    reasoning = "".join(e.payload.get("reasoning_delta", "") for e in events if e.type == LLM_CHUNK)
    assert reasoning == "thinking process"


def test_run_streaming_interrupt_during_llm(tmp_path):
    """LLM 流式阶段中断:半截 text + [interrupted] 标记。"""
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.events import FINAL_ANSWER
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    # 用一个长 text 让 chunk 多一点,中途 interrupt
    mock = MockLLM([LLMResponse(text="a" * 50, tool_calls=[])])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    events = []
    # 在第一个 LLM_CHUNK 事件后 interrupt
    def on_event(e):
        events.append(e)
        from taisang.agent_core.events import LLM_CHUNK
        if e.type == LLM_CHUNK and not service._cancel_event.is_set():
            service.interrupt()
    answer = service.run("test", on_event=on_event)
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert final.payload["interrupted"] is True
    assert "[interrupted]" in final.payload["text"]
    assert answer.interrupted is True


def test_run_streaming_interrupt_during_tool_execution(tmp_path):
    """工具执行阶段中断:补空 tool_result + [interrupted] 标记。"""
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.events import FINAL_ANSWER, TOOL_CALL
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    mock = MockLLM([
        LLMResponse(
            text="read file",
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}],
        ),
        LLMResponse(text="final", tool_calls=[]),
    ])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    events = []
    # 在 TOOL_CALL 事件后 interrupt(工具执行前)
    def on_event(e):
        events.append(e)
        if e.type == TOOL_CALL and not service._cancel_event.is_set():
            service.interrupt()
    answer = service.run("test", on_event=on_event)
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert final.payload["interrupted"] is True
    assert answer.interrupted is True
    # ctx 里有 tool_result({"_interrupted": true})
    msgs = service.ctx.messages()
    tool_results = [m for m in msgs if m.get("role") == "tool"]
    assert len(tool_results) >= 1
    assert "_interrupted" in tool_results[0].get("content", "")


def test_run_streaming_mid_failure_no_retry(tmp_path):
    """流中失败(LLMTransientError after first chunk)不重试,标记 [LLM 调用失败]。"""
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.events import FINAL_ANSWER
    from taisang.llm_client import LLMResponse
    from taisang.llm_errors import LLMTransientError
    from taisang.llm_stream import StreamChunk
    from taisang.agent_core.permission import AutoApprovePermissionManager

    # 造一个 fake LLM,chat_stream 首 chunk 成功,第 2 个抛 LLMTransientError
    class FakeLLM:
        def __init__(self):
            self.calls = []
        def chat(self, messages, tools):
            raise NotImplementedError
        def chat_stream(self, messages, tools):
            self.calls.append({"messages": messages, "tools": tools})
            yield StreamChunk(text_delta="partial")
            raise LLMTransientError("mid stream boom")

    service = AgentService(
        llm=FakeLLM(), source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    events = []
    answer = service.run("test", on_event=lambda e: events.append(e))
    final = [e for e in events if e.type == FINAL_ANSWER][0]
    assert "partial" in final.payload["text"]
    assert "[LLM 调用失败" in final.payload["text"]
    assert final.payload["interrupted"] is False


def test_run_streaming_interrupt_preserves_ctx_for_next_run(tmp_path):
    """中断后 ctx 保持 LLM API 兼容,下次 run 能继续。"""
    from taisang.agent_core.service import AgentService
    from taisang.llm_client import MockLLM, LLMResponse
    from taisang.agent_core.permission import AutoApprovePermissionManager

    mock = MockLLM([
        LLMResponse(text="a" * 50, tool_calls=[]),  # 第一轮(会被中断)
        LLMResponse(text="next answer", tool_calls=[]),  # 第二轮(正常)
    ])
    service = AgentService(
        llm=mock, source_root=tmp_path,
        confirmer=lambda f, o, n: True,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
    )
    from taisang.agent_core.events import LLM_CHUNK
    # 第一轮:中断
    def on_event1(e):
        if e.type == LLM_CHUNK and not service._cancel_event.is_set():
            service.interrupt()
    service.run("first", on_event=on_event1)
    # 第二轮:正常跑(不报缺 tool_result 错误)
    events2 = []
    answer2 = service.run("second", on_event=lambda e: events2.append(e))
    from taisang.agent_core.events import FINAL_ANSWER
    final = [e for e in events2 if e.type == FINAL_ANSWER][0]
    assert final.payload["text"] == "next answer"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_agent_core.py -q -k "streaming"`
Expected: 6 FAILED,各种错误(AttributeError / 逻辑不符)

- [ ] **Step 3: 加 _iter_with_retry 内部函数**

Edit `src/taisang/agent_core/service.py`,在 `AgentService` class 定义之前(模块级)加 `_iter_with_retry` 函数:

```python
def _iter_with_retry(make_iter, on_retry):
    """流式迭代器重试包装:只重试第一次 next(连接建立 + 首 chunk)。

    首 chunk 成功后,后续 next 失败不重试(已经吐过字了,重试会重复)。

    make_iter: 返回 iterator 的 callable(每次重试会重新调)
    on_retry: 重试回调(同 call_with_retry 的 on_retry)

    Yields: 首 chunk + 后续 chunks
    Raises: 首 chunk 失败 → LLMTransientError(call_with_retry 重试后仍失败);
            后续 chunk 失败 → LLMTransientError(不重试,直接抛)
    """
    state = {"it": None}
    def _do_first():
        state["it"] = make_iter()
        return next(state["it"])
    first_chunk = call_with_retry(_do_first, on_retry=on_retry)
    yield first_chunk
    yield from state["it"]  # 后续 next 失败不重试,直接抛
```

- [ ] **Step 4: 改 run 主循环为流式**

Edit `src/taisang/agent_core/service.py`,替换 `run` 方法里 `try: resp = call_with_retry(...)` 那块(约 line 244-278,从 `try: resp = call_with_retry(lambda: self.llm.chat(...))` 到 `except LLMError as e:` 块结束)。

替换为:

```python
            try:
                # 流式 LLM 调用:重试只包第一次 next(_iter_with_retry)
                # 首 chunk 成功后,后续 chunk 失败不重试(已经吐过字了)
                accumulated_text = ""
                accumulated_reasoning = ""
                tool_calls: list[dict] = []
                usage: dict | None = None
                assistant_appended = False  # 标记是否已 append_assistant(中断处理用)
                stream = _iter_with_retry(
                    lambda: self.llm.chat_stream(messages=self.ctx.messages(), tools=registry.schemas()),
                    on_retry=lambda attempt, err, delay: _emit(
                        AgentEvent(
                            type=LLM_RETRY,
                            payload={
                                "attempt": attempt,
                                "error": f"{type(err).__name__}: {err}",
                                "delay_sec": delay,
                            },
                        )
                    ),
                )
                for chunk in stream:
                    # 中断检查点 1:每个 chunk
                    if self._cancel_event.is_set():
                        raise InterruptedError()
                    if chunk.text_delta:
                        accumulated_text += chunk.text_delta
                        _emit(AgentEvent(
                            type=LLM_CHUNK,
                            payload={"text_delta": chunk.text_delta, "reasoning_delta": ""},
                        ))
                    if chunk.reasoning_delta:
                        accumulated_reasoning += chunk.reasoning_delta
                        _emit(AgentEvent(
                            type=LLM_CHUNK,
                            payload={"text_delta": "", "reasoning_delta": chunk.reasoning_delta},
                        ))
                    if chunk.is_final:
                        tool_calls = chunk.tool_calls
                        usage = chunk.usage
            except KeyboardInterrupt:
                # CLI Ctrl+C:转中断信号,走统一中断分支
                self._cancel_event.set()
                raise InterruptedError() from None
            except InterruptedError:
                # 用户中断:把已流出的 text 作为最终答案,标 [interrupted]
                if accumulated_text:
                    text = accumulated_text + " [interrupted]"
                else:
                    text = "(已中断)"
                if not assistant_appended:
                    self.ctx.append_assistant(text=text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": True}))
                self._emit_usage_report(_emit)
                return Answer(
                    text=text, citations=[], complete=False,
                    steps_used=steps, interrupted=True,
                )
            except LLMTransientError as e:
                # 流中失败:半截 text 已通过 LLM_CHUNK 流出,落盘 + 标记
                self._emit_usage_report(_emit)
                log.warning("LLM transient error at step %d: %s", steps, e)
                if accumulated_text:
                    text = accumulated_text + f" [LLM 调用失败: {e}]"
                else:
                    text = f"(LLM 调用失败: {e})"
                if not assistant_appended:
                    self.ctx.append_assistant(text=text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": False}))
                return Answer(
                    text=text, citations=[], complete=False, steps_used=steps,
                )
            except LLMProtocolError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM protocol error at step %d: %s", steps, e)
                text = f"(LLM 协议错误: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": False}))
                return Answer(
                    text=text, citations=[], complete=False, steps_used=steps,
                )
            except LLMError as e:
                self._emit_usage_report(_emit)
                log.warning("LLM error at step %d: %s", steps, e)
                text = f"(LLM 错误: {e})"
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": False}))
                return Answer(
                    text=text, citations=[], complete=False, steps_used=steps,
                )
            # 累加此轮 + session 累计 token(MockLLM / endpoint 未返回时 usage=None,跳过)
            self._accumulate_usage(usage)

            if not resp.tool_calls:  # 注意:这里要改成 tool_calls
```

**注意**:上面的 `if not resp.tool_calls:` 要改成 `if not tool_calls:`,因为流式不再用 `resp` 变量。继续替换后续代码:

```python
            if not tool_calls:
                if self.debug:
                    _emit(
                        AgentEvent(
                            type=DEBUG_RESPONSE,
                            payload={"step": steps, "text": accumulated_text, "tool_calls": []},
                        )
                    )
                # session memory post-sampling(idle_break 分支)
                self._maybe_trigger_session_memory(last_turn_has_tool_calls=False)
                citations = self._extract_citations(accumulated_text)
                # 最终答案也要落盘
                self.ctx.append_assistant(text=accumulated_text, tool_calls=None)
                _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": accumulated_text, "interrupted": False}))
                self._emit_usage_report(_emit)
                return Answer(
                    text=accumulated_text, citations=citations,
                    complete=True, steps_used=steps,
                )

            if self.debug:
                _emit(
                    AgentEvent(
                        type=DEBUG_RESPONSE,
                        payload={"step": steps, "text": accumulated_text, "tool_calls": tool_calls},
                    )
                )
            self.ctx.append_assistant(text=accumulated_text, tool_calls=tool_calls)
            assistant_appended = True
            for tc in tool_calls:
                # 中断检查点 2:每个工具执行前
                if self._cancel_event.is_set():
                    # 补空 tool_result 避免 LLM API 缺 tool result 报错
                    self.ctx.append_tool_result(
                        '{"_interrupted": true}',
                        name=tc["function"]["name"],
                        tool_call_id=tc["id"],
                    )
                    text = accumulated_text + " [interrupted]" if accumulated_text else "(已中断)"
                    _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": True}))
                    self._emit_usage_report(_emit)
                    return Answer(
                        text=text, citations=[], complete=False,
                        steps_used=steps, interrupted=True,
                    )
                name = tc["function"]["name"]
                args_str = tc["function"].get("arguments", "") or ""
                try:
                    args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError as e:
                    log.warning("tool %s malformed arguments: %s", name, e)
                    result = {"error": f"malformed arguments: {e}"}
                    self.ctx.append_tool_result(
                        json.dumps(result, ensure_ascii=False),
                        name=name, tool_call_id=tc["id"],
                    )
                    self._tool_calls_since_last_extract += 1
                    continue
                _emit(AgentEvent(type=TOOL_CALL, payload={"name": name, "args": args}))
                try:
                    result = registry.call(name, args)
                except InterruptedError:
                    # ToolRegistry 检查到 cancel_event,走中断分支
                    self.ctx.append_tool_result(
                        '{"_interrupted": true}',
                        name=name, tool_call_id=tc["id"],
                    )
                    text = accumulated_text + " [interrupted]" if accumulated_text else "(已中断)"
                    _emit(AgentEvent(type=FINAL_ANSWER, payload={"text": text, "interrupted": True}))
                    self._emit_usage_report(_emit)
                    return Answer(
                        text=text, citations=[], complete=False,
                        steps_used=steps, interrupted=True,
                    )
                except Exception as e:
                    log.warning("tool %s dispatch failed: %s", name, e)
                    result = {"error": f"tool {name} failed: {e}"}
                observation = json.dumps(result, ensure_ascii=False)
                total_bytes = len(observation.encode("utf-8"))
                if total_bytes > _MAX_OBSERVATION_BYTES:
                    observation = observation[:_MAX_OBSERVATION_BYTES] + '...{"_truncated": true}'
                _emit(AgentEvent(
                    type=TOOL_RESULT,
                    payload={"name": name, "preview": observation[:30], "total_bytes": total_bytes},
                ))
                if self.debug:
                    _emit(AgentEvent(
                        type=DEBUG_TOOL_RESULT,
                        payload={"step": steps, "name": name, "tool_call_id": tc["id"], "observation": observation},
                    ))
                self.ctx.append_tool_result(observation, name=name, tool_call_id=tc["id"])
                self._tool_calls_since_last_extract += 1
```

- [ ] **Step 5: 给 ToolRegistry 构造传 cancel_event**

Edit `src/taisang/agent_core/service.py`,在 `run` 方法里 `registry = ToolRegistry(...)` 调用(约 line 201-211)加 `cancel_event=self._cancel_event`:

```python
        registry = ToolRegistry(
            cwd=self.source_root,
            shell=self.shell,
            confirmer=self.confirmer,
            permission=self.permission,
            skills=self.skills,
            ctx=self.ctx,
            mcp_manager=self._mcp_manager,
            agents=self.agents,
            parent_service=self,
            cancel_event=self._cancel_event,  # 新增:传中断信号
        )
```

- [ ] **Step 6: 加 import**

Edit `src/taisang/agent_core/service.py`,在 import 区域加:

```python
from .events import (
    COMPACTED,
    DEBUG_REQUEST,
    DEBUG_RESPONSE,
    DEBUG_TOOL_RESULT,
    FINAL_ANSWER,
    LLM_CHUNK,
    LLM_RETRY,
    LLM_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    USAGE_REPORT,
    AgentEvent,
)
```

- [ ] **Step 7: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_agent_core.py -q -k "streaming"`
Expected: 6 passed

- [ ] **Step 8: 跑全套 agent_core 测试确认没 break**

Run: `python -m pytest tests/unit/test_agent_core.py tests/unit/test_agent_service_with_agents.py tests/unit/test_agent_tool.py -q`
Expected: all passed(注意:现有测试用 MockLLM,流式路径也走 MockLLM.chat_stream,应兼容)

**如果现有测试 break**:可能是因为现有测试期望 `resp.text` / `resp.tool_calls`,但流式路径用 `accumulated_text` / `tool_calls`。检查并修。

- [ ] **Step 9: 提交**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat(agent): streaming run loop + _iter_with_retry + interrupt checks"
```

---

## Task 10: Web /interrupt 路由 + 单测

**Files:**
- Modify: `src/taisang/web/app.py`(加 `POST /api/sessions/{id}/interrupt` 路由)
- Modify: `tests/unit/test_web_app.py`(加 interrupt 路由测试)

- [ ] **Step 1: 写失败测试**

Add to `tests/unit/test_web_app.py`(在文件末尾追加):

```python
def test_interrupt_endpoint_idle_session(client, tmp_path):
    """turn 没在跑时 POST /interrupt 幂等返回 {interrupted: False}。"""
    # 先建一个 session
    r = client.post("/api/sessions", json={"title": "test"})
    sid = r.json()["id"]
    # POST /interrupt(turn 没在跑)
    r = client.post(f"/api/sessions/{sid}/interrupt")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["interrupted"] is False


def test_interrupt_endpoint_unknown_session_404(client):
    """未知 session POST /interrupt 返回 404。"""
    r = client.post("/api/sessions/nonexistent-id/interrupt")
    assert r.status_code == 404


def test_interrupt_endpoint_running_session(client, tmp_path, monkeypatch):
    """turn 在跑时 POST /interrupt 返回 {interrupted: True},set cancel_event。"""
    import threading
    r = client.post("/api/sessions", json={"title": "test"})
    sid = r.json()["id"]
    # 拿到 session 对象,模拟 turn 在跑(hold lock)
    # 注意:需要从 registry 拿 sess 对象
    from taisang.web.app import _make_app
    # 这个测试比较复杂,简化:直接测 interrupt() 方法被调用
    # 用 monkeypatch 替换 sess.agent.interrupt,验证被调
    # 先拿到 sess
    from taisang.web.session_registry import SessionRegistry
    # 跳过:这个测试需要复杂的 fixture,简化为只测 idle + 404
    # running 场景在 e2e 测试覆盖
```

**注意**:`test_interrupt_endpoint_running_session` 较复杂(需要模拟 turn 在跑),简化为只测 idle + 404,running 场景在 e2e 测试覆盖。删除这个测试,只留前两个。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_web_app.py -q -k "interrupt"`
Expected: 2 FAILED, 404 或路由不存在

- [ ] **Step 3: 加 /interrupt 路由**

Edit `src/taisang/web/app.py`,在 `event_stream` 路由后加 `interrupt_session` 路由:

```python
    @app.post("/api/sessions/{session_id}/interrupt")
    async def interrupt_session(session_id: str) -> dict:
        """请求中断当前 turn。set agent._cancel_event。

        幂等:turn 已结束或未开始时调用无副作用(返回 interrupted=False)。
        并发安全:threading.Event.set() thread-safe。
        不等中断生效就返回:前端通过 FINAL_ANSWER(interrupted=True) 事件知道中断生效。
        """
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        if not sess.lock.locked():
            # turn 没在跑,幂等返回
            return {"ok": True, "interrupted": False}
        sess.agent.interrupt()
        return {"ok": True, "interrupted": True}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_web_app.py -q -k "interrupt"`
Expected: 2 passed

- [ ] **Step 5: 跑全套 web_app 测试确认没 break**

Run: `python -m pytest tests/unit/test_web_app.py -q`
Expected: all passed

- [ ] **Step 6: 提交**

```bash
git add src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): POST /api/sessions/:id/interrupt endpoint"
```

---

## Task 11: CLI 流式 + Ctrl+C 中断

**Files:**
- Modify: `src/taisang/cli/main.py`(`_render` 加 `LLM_CHUNK` 分支,REPL 加 Ctrl+C 处理)

- [ ] **Step 1: 加 LLM_CHUNK 渲染分支**

Edit `src/taisang/cli/main.py`,在 `_render` 函数里加 `LLM_CHUNK` 分支。先加 import:

```python
from .events import (
    COMPACTED,
    DEBUG_REQUEST,
    DEBUG_RESPONSE,
    DEBUG_TOOL_RESULT,
    FINAL_ANSWER,
    LLM_CHUNK,
    LLM_RETRY,
    LLM_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    USAGE_REPORT,
    AgentEvent,
)
```

在 `_render` 函数的 if-elif 链里加 `LLM_CHUNK` 分支(在 `LLM_THINKING` 之后):

```python
        def _render(evt) -> None:
            if evt.type == LLM_THINKING:
                click.echo("  [thinking]")
            elif evt.type == LLM_CHUNK:
                # 流式 chunk:text_delta 直接输出(不换行),reasoning_delta 灰色缩进
                text_delta = evt.payload.get("text_delta", "")
                reasoning_delta = evt.payload.get("reasoning_delta", "")
                if text_delta:
                    click.echo(text_delta, nl=False)
                if reasoning_delta:
                    click.echo(click.style(reasoning_delta, fg="bright_black"), nl=False)
            elif evt.type == LLM_RETRY:
                click.echo(click.style(f"  [重试 {evt.payload['attempt']}/{evt.payload.get('delay_sec', 0):.1f}s]", fg="yellow"))
            elif evt.type == TOOL_CALL:
                click.echo(f"  [tool] {evt.payload['name']} {evt.payload['args']}")
            elif evt.type == TOOL_RESULT:
                p = evt.payload
                click.echo(f"  [result] {p['name']} ({p['total_bytes']} bytes)")
            elif evt.type == FINAL_ANSWER:
                # 流式模式下 FINAL_ANSWER 不重复输出全文(已在 LLM_CHUNK 流完了)
                # 只换行 + 显示 [interrupted] 标记
                click.echo("")  # 收尾换行
                if evt.payload.get("interrupted"):
                    click.echo(click.style("  [interrupted]", fg="yellow"))
            elif evt.type == USAGE_REPORT:
                _render_usage_report(evt.payload)
            elif evt.type == DEBUG_REQUEST:
                _render_debug_request(evt.payload)
            elif evt.type == DEBUG_RESPONSE:
                _render_debug_response(evt.payload)
            elif evt.type == DEBUG_TOOL_RESULT:
                _render_debug_tool_result(evt.payload)
```

- [ ] **Step 2: 加 Ctrl+C 处理**

Edit `src/taisang/cli/main.py`,找到 `answer = agent.run(query, on_event=_render)` 那行(约 line 257),包 try/except:

```python
        try:
            answer = agent.run(query, on_event=_render)
        except KeyboardInterrupt:
            # Ctrl+C:run() 内部已 catch(set cancel_event + 转 InterruptedError)
            # 如果穿透到这里,说明 run() 已返回中断 Answer
            click.echo(click.style("\n  [interrupted]", fg="yellow"))
            continue
        if not answer.complete:
            click.echo(f"(incomplete: {answer.text})")
```

- [ ] **Step 3: 跑 CLI 测试确认没 break**

Run: `python -m pytest tests/unit/test_cli.py -q`
Expected: all passed(CLI 测试主要测命令解析,不涉及流式渲染细节)

- [ ] **Step 4: 提交**

```bash
git add src/taisang/cli/main.py
git commit -m "feat(cli): streaming render + Ctrl+C interrupt"
```

---

## Task 12: 前端 types + api/chat.ts

**Files:**
- Modify: `src/taisang/web/frontend/src/types/index.ts`(加 `llm_chunk` kind + `streaming` / `interrupted` 字段)
- Modify: `src/taisang/web/frontend/src/api/chat.ts`(加 `interruptSession` 函数)

- [ ] **Step 1: 加前端类型**

Edit `src/taisang/web/frontend/src/types/index.ts`,修改 `MessageKind` 和 `ChatMessage`:

```typescript
export type MessageKind =
  | 'user'
  | 'assistant'
  | 'tool_call'
  | 'tool_result'
  | 'thinking'
  | 'compacted'
  | 'confirm'
  | 'permission'
  | 'run_error'
  | 'usage'
  | 'llm_retry'
  | 'llm_chunk'

export interface ChatMessage {
  id: string
  kind: MessageKind
  text?: string
  toolName?: string
  toolArgs?: string
  toolPreview?: string
  toolBytes?: number
  toolFilled?: boolean
  via?: string
  token?: string
  filePath?: string
  oldContent?: string
  newContent?: string
  path?: string
  answered?: boolean
  approved?: boolean
  usage?: UsageData
  error?: string
  retryAttempt?: number
  delaySec?: number
  // 流式相关
  streaming?: boolean       // True = 正在流式累积(llm_chunk 来了,final_answer 未到)
  interrupted?: boolean     // True = 用户主动中断(FINAL_ANSWER interrupted 标记)
  // Task 14: subagent 事件嵌套渲染
  agentId?: string
  subAgentEvents?: ChatMessage[]
}
```

- [ ] **Step 2: 加 interruptSession API 函数**

Edit `src/taisang/web/frontend/src/api/chat.ts`,在文件末尾加:

```typescript
export function interruptSession(id: string): Promise<{ ok: boolean; interrupted: boolean }> {
  return apiPost<{ ok: boolean; interrupted: boolean }>(`/api/sessions/${id}/interrupt`, {})
}
```

- [ ] **Step 3: 跑 type-check**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: clean(只加类型 + API 函数,不破坏现有)

- [ ] **Step 4: 提交**

```bash
git add src/taisang/web/frontend/src/types/index.ts src/taisang/web/frontend/src/api/chat.ts
git commit -m "feat(frontend): llm_chunk type + interruptSession API"
```

---

## Task 13: 前端 useChatStream llm_chunk listener + 流式消息累积

**Files:**
- Modify: `src/taisang/web/frontend/src/composables/useChatStream.ts`(加 `llm_chunk` listener + `streamingMessage` + `reasoningText` ref)

- [ ] **Step 1: 加 streamingMessage + reasoningText ref**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,在 `retryInfo` ref 后加:

```typescript
  // 流式状态:正在累积的 assistant 消息 + reasoning 文本
  const streamingMessage = ref<ChatMessage | null>(null)
  const reasoningText = ref('')
```

- [ ] **Step 2: 改 clearThinking 清流式状态**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,修改 `clearThinking`:

```typescript
  function clearThinking() {
    thinking.value = false
    retryInfo.value = null
    reasoningText.value = ''
  }
```

- [ ] **Step 3: 加 llm_chunk listener**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,在 `llm_retry` listener 后加 `llm_chunk` listener:

```typescript
    eventSource.addEventListener('llm_chunk', (e: MessageEvent) => {
      const d = safeParse<{ text_delta: string; reasoning_delta: string; agent_id?: string }>(e.data)
      if (!d) return
      // 子 agent chunk:嵌套到父卡片(降级:无父则忽略)
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'llm_chunk',
            textDelta: d.text_delta,
            reasoningDelta: d.reasoning_delta,
            agentId: d.agent_id,
          })
        }
        return
      }
      // 主 agent chunk
      if (d.text_delta) {
        if (!streamingMessage.value || !streamingMessage.value.streaming) {
          // 新流开始,创建 streaming 消息
          streamingMessage.value = {
            id: nextId(),
            kind: 'assistant',
            text: '',
            streaming: true,
          }
          messages.value.push(streamingMessage.value)
        }
        streamingMessage.value.text = (streamingMessage.value.text || '') + d.text_delta
      }
      if (d.reasoning_delta) {
        reasoningText.value = (reasoningText.value || '') + d.reasoning_delta
      }
    })
```

- [ ] **Step 4: 改 final_answer listener 处理流式消息**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,修改 `final_answer` listener:

```typescript
    eventSource.addEventListener('final_answer', (e: MessageEvent) => {
      const d = safeParse<{ text: string; interrupted: boolean; agent_id?: string }>(e.data)
      if (!d) return
      clearThinking()
      if (d.agent_id) {
        // 子 agent 最终答案:嵌套到父卡片
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'assistant',
            text: d.text || '',
            interrupted: d.interrupted || false,
            agentId: d.agent_id,
          })
          return
        }
      }
      // 主 agent:流式模式下 FINAL_ANSWER 不重复 push(已在 llm_chunk 累积)
      if (streamingMessage.value && streamingMessage.value.streaming) {
        streamingMessage.value.streaming = false
        streamingMessage.value.interrupted = d.interrupted || false
        // 如果中断且 text 为空,用 d.text(含 [interrupted] 标记)
        if (!streamingMessage.value.text) {
          streamingMessage.value.text = d.text
        } else if (d.interrupted) {
          streamingMessage.value.text = (streamingMessage.value.text || '') + ' [interrupted]'
        }
        streamingMessage.value = null
      } else {
        // 非流式回退(autocompact LLM 摘要等内部调用仍用 chat 非流式)
        pushAssistant(d.text || '')
      }
    })
```

- [ ] **Step 5: 改 tool_call listener 清流式状态**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,修改 `tool_call` listener 开头(在 `if (d.agent_id)` 之前)加:

```typescript
    eventSource.addEventListener('tool_call', (e: MessageEvent) => {
      const d = safeParse<{ name: string; args: Record<string, unknown>; agent_id?: string }>(e.data)
      if (!d) return
      clearThinking()
      // 流式 assistant 消息已通过 llm_chunk 累积,这里不重复 push
      // 但要标记 streaming 结束(如果有 streaming 消息)
      if (streamingMessage.value && streamingMessage.value.streaming) {
        streamingMessage.value.streaming = false
        streamingMessage.value = null
      }
      if (d.agent_id) {
        // ... 原有子 agent 嵌套逻辑不变
```

- [ ] **Step 6: 改 run_end / run_error listener 清流式状态**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,修改 `run_end` 和 `run_error` listener:

```typescript
    eventSource.addEventListener('run_error', (e: MessageEvent) => {
      const d = safeParse<{ error: string }>(e.data)
      if (!d) return
      clearThinking()
      // 清流式状态
      if (streamingMessage.value && streamingMessage.value.streaming) {
        streamingMessage.value.streaming = false
        streamingMessage.value = null
      }
      pushRunError(d.error || '未知错误')
    })
    eventSource.addEventListener('run_end', () => {
      clearThinking()
      // 清流式状态(防御性,正常情况下 final_answer 已清)
      if (streamingMessage.value && streamingMessage.value.streaming) {
        streamingMessage.value.streaming = false
        streamingMessage.value = null
      }
    })
```

- [ ] **Step 7: 导出 streamingMessage + reasoningText + interruptSession**

Edit `src/taisang/web/frontend/src/composables/useChatStream.ts`,修改 return:

```typescript
  return {
    messages,
    thinking,
    retryInfo,
    reasoningText,
    streamingMessage,
    connectionState,
    send,
    loadHistory,
    openEventStream,
    closeEventStream,
    answerConfirm,
  }
}
```

- [ ] **Step 8: 跑 type-check**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: clean

- [ ] **Step 9: 提交**

```bash
git add src/taisang/web/frontend/src/composables/useChatStream.ts
git commit -m "feat(frontend): llm_chunk listener + streaming message accumulation"
```

---

## Task 14: 前端 ThinkingIndicator 显示 reasoning 流

**Files:**
- Modify: `src/taisang/web/frontend/src/components/ThinkingIndicator.vue`

- [ ] **Step 1: 改 ThinkingIndicator 接 reasoningText prop**

Edit `src/taisang/web/frontend/src/components/ThinkingIndicator.vue`:

```vue
<template>
  <div class="thinking">
    <span class="label">thinking</span>
    <span v-if="retryInfo" class="retry-badge">
      第 {{ retryInfo.attempt }} 次重试中({{ retryInfo.delaySec.toFixed(1) }}s 后)
    </span>
    <span v-if="reasoningText" class="reasoning">{{ reasoningText }}</span>
    <span v-else class="dots">
      <span></span>
      <span></span>
      <span></span>
    </span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  retryInfo?: { attempt: number; delaySec: number } | null
  reasoningText?: string
}>()
</script>

<style scoped>
.thinking {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
  font-family: var(--app-font-mono);
}
.retry-badge {
  color: var(--td-warning-color, #b25803);
  background: var(--td-warning-color-1, #fff3e0);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  border: 1px solid var(--td-warning-color-2, #ffcc80);
  flex-shrink: 0;
}
.reasoning {
  color: var(--td-text-color-secondary);
  font-style: italic;
  white-space: pre-wrap;
  word-break: break-word;
  flex: 1 1 auto;
  max-height: 120px;
  overflow-y: auto;
}
.dots {
  display: inline-flex;
  gap: 3px;
  flex-shrink: 0;
}
.dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--td-brand-color);
  animation: thinking-bounce 1.2s infinite ease-in-out;
}
.dots span:nth-child(2) { animation-delay: 0.15s; }
.dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes thinking-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-4px); opacity: 1; }
}
</style>
```

- [ ] **Step 2: 改 MessageList 透传 reasoningText**

Edit `src/taisang/web/frontend/src/components/MessageList.vue`:

模板里 `<ThinkingIndicator>` 改:

```vue
    <ThinkingIndicator v-if="thinking" :retry-info="retryInfo" :reasoning-text="reasoningText" />
```

props 加 `reasoningText`:

```typescript
const props = defineProps<{
  messages: ChatMessage[]
  thinking: boolean
  retryInfo?: { attempt: number; delaySec: number } | null
  reasoningText?: string
}>()
```

- [ ] **Step 3: 改 ChatView 透传 reasoningText**

Edit `src/taisang/web/frontend/src/views/ChatView.vue`:

模板里 `<MessageList>` 加 `:reasoning-text`:

```vue
      <MessageList
        v-else
        :messages="messages"
        :thinking="thinking"
        :retry-info="retryInfo"
        :reasoning-text="reasoningText"
        @answer="handleAnswer"
      />
```

解构 useChatStream 加 `reasoningText`:

```typescript
const { messages, thinking, retryInfo, reasoningText, connectionState, send, loadHistory, openEventStream, closeEventStream, answerConfirm } =
  useChatStream(sessionIdRef, () => store.fetchSessions())
```

- [ ] **Step 4: 跑 type-check**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: clean

- [ ] **Step 5: 提交**

```bash
git add src/taisang/web/frontend/src/components/ThinkingIndicator.vue src/taisang/web/frontend/src/components/MessageList.vue src/taisang/web/frontend/src/views/ChatView.vue
git commit -m "feat(frontend): ThinkingIndicator shows reasoning stream"
```

---

## Task 15: 前端 MessageInput 发送按钮变停止按钮

**Files:**
- Modify: `src/taisang/web/frontend/src/components/MessageInput.vue`
- Modify: `src/taisang/web/frontend/src/views/ChatView.vue`(传 streaming prop + 接 stop 事件)

- [ ] **Step 1: 改 MessageInput 支持 streaming + stop**

Edit `src/taisang/web/frontend/src/components/MessageInput.vue`:

```vue
<template>
  <div class="message-input">
    <div class="input-row">
      <textarea
        ref="taRef"
        v-model="text"
        class="query-textarea"
        :placeholder="placeholder"
        rows="1"
        aria-label="输入消息,Enter 发送,Shift+Enter 换行"
        @keydown="handleKeydown"
        @input="autoResize"
      ></textarea>
      <t-button
        v-if="!streaming"
        shape="circle"
        theme="primary"
        aria-label="发送"
        :disabled="!text.trim()"
        @click="handleSend"
      >
        <template #icon>
          <t-icon name="send" />
        </template>
      </t-button>
      <t-button
        v-else
        shape="circle"
        theme="danger"
        aria-label="停止"
        @click="handleStop"
      >
        <template #icon>
          <t-icon name="stop" />
        </template>
      </t-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'

const props = withDefaults(defineProps<{ placeholder?: string; autofocus?: boolean; streaming?: boolean }>(), {
  placeholder: '输入问题,Enter 发送,Shift+Enter 换行...',
  autofocus: false,
  streaming: false,
})

const emit = defineEmits<{ send: [query: string]; stop: [] }>()
const text = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)

onMounted(() => {
  if (props.autofocus && taRef.value) {
    taRef.value.focus()
  }
})

function autoResize() {
  const el = taRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleSend() {
  const q = text.value.trim()
  if (!q) return
  emit('send', q)
  text.value = ''
  nextTick(autoResize)
}

function handleStop() {
  emit('stop')
}
</script>

<style scoped>
.message-input {
  padding: 0 24px 20px;
}
.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  max-width: 800px;
  margin: 0 auto;
  padding: 8px 8px 8px 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 14px;
  background: var(--td-bg-color-container);
  transition: border-color 0.15s;
}
.input-row:focus-within {
  border-color: var(--td-brand-color);
}
.query-textarea {
  flex: 1;
  resize: none;
  border: none;
  background: transparent;
  padding: 7px 0;
  color: var(--td-text-color-primary);
  font-family: var(--app-font-family);
  font-size: 14px;
  line-height: 1.5;
  min-height: 36px;
  max-height: 200px;
  overflow-y: auto;
  outline: none;
}
.query-textarea::placeholder {
  color: var(--td-text-color-placeholder);
}
</style>
```

- [ ] **Step 2: 改 ChatView 传 streaming prop + 接 stop 事件**

Edit `src/taisang/web/frontend/src/views/ChatView.vue`,模板里 `<MessageInput>` 改:

```vue
    <MessageInput
      v-if="currentSession && messages.length"
      autofocus
      :streaming="thinking"
      @send="handleSend"
      @stop="handleStop"
    />
```

注意:`:streaming="thinking"` — thinking 为 true 时(LLM 正在响应)显示停止按钮。这覆盖了流式 + 工具执行阶段。

加 `handleStop` 函数(import `interruptSession`):

```typescript
import { resetSession, setDebug } from '@/api/session'
import { interruptSession } from '@/api/chat'
```

```typescript
async function handleStop() {
  if (!currentId.value) return
  try {
    await interruptSession(currentId.value)
  } catch (e) {
    console.error('interrupt failed:', e)
  }
}
```

- [ ] **Step 3: 跑 type-check**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: clean

- [ ] **Step 4: 提交**

```bash
git add src/taisang/web/frontend/src/components/MessageInput.vue src/taisang/web/frontend/src/views/ChatView.vue
git commit -m "feat(frontend): send button toggles to stop button during streaming"
```

---

## Task 16: 前端 build + 子 agent 嵌套 llm_chunk 渲染

**Files:**
- Modify: `src/taisang/web/frontend/src/components/ToolCard.vue`(子 agent llm_chunk 嵌套渲染)

- [ ] **Step 1: 给 ToolCard 加 llm_chunk 嵌套分支**

Edit `src/taisang/web/frontend/src/components/ToolCard.vue`,在 sub-event 渲染的 v-else-if 链里加 `llm_chunk`:

```vue
          <span v-if="sub.kind === 'tool_call'" class="sub-text">{{ sub.toolName }} {{ sub.toolArgs }}</span>
          <span v-else-if="sub.kind === 'tool_result'" class="sub-text">{{ sub.toolPreview }}</span>
          <span v-else-if="sub.kind === 'assistant'" class="sub-text">{{ sub.text }}</span>
          <span v-else-if="sub.kind === 'usage'" class="sub-text usage">{{ usageLabel(sub) }}</span>
          <span v-else-if="sub.kind === 'compacted'" class="sub-text">[compact: {{ sub.via }}]</span>
          <span v-else-if="sub.kind === 'llm_retry'" class="sub-text retry">
            第 {{ sub.retryAttempt }} 次重试({{ sub.delaySec?.toFixed(1) }}s 后)
          </span>
          <span v-else-if="sub.kind === 'llm_chunk'" class="sub-text chunk">
            <span v-if="sub.textDelta">{{ sub.textDelta }}</span>
            <span v-else-if="sub.reasoningDelta" class="reasoning">{{ sub.reasoningDelta }}</span>
          </span>
          <span v-else class="sub-text">{{ sub.kind }}</span>
```

在 `subLabel` map 加 `llm_chunk`:

```typescript
function subLabel(sub: ChatMessage): string {
  const map: Record<string, string> = {
    tool_call: '🔧',
    tool_result: '↩',
    assistant: '✓',
    usage: '📊',
    llm_thinking: '…',
    thinking: '…',
    compacted: '∙',
    llm_retry: '↻',
    llm_chunk: '…',
  }
  return map[sub.kind] || '·'
}
```

加 `.sub-text.chunk .reasoning` 样式:

```css
.sub-text.retry {
  color: var(--td-warning-color, #b25803);
  font-style: italic;
}
.sub-text.chunk .reasoning {
  color: var(--td-text-color-placeholder);
  font-style: italic;
}
```

- [ ] **Step 2: 跑 type-check**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: clean

- [ ] **Step 3: 跑前端 build**

Run: `cd src/taisang/web/frontend && npm run build`
Expected: clean,生成 static/assets/

- [ ] **Step 4: 提交**

```bash
git add src/taisang/web/frontend/src/components/ToolCard.vue src/taisang/web/static/
git commit -m "feat(frontend): subagent llm_chunk nested rendering + build artifacts"
```

---

## Task 17: E2E 流式 + 中断测试

**Files:**
- Create: `tests/integration/test_streaming_e2e.py`

- [ ] **Step 1: 写 e2e 测试**

Create `tests/integration/test_streaming_e2e.py`:

```python
"""端到端测试:流式输出 + 用户中断。

通过 FastAPI TestClient + MockLLM 验证完整流程:
POST /messages → SSE 收事件序列 → FINAL_ANSWER
POST /interrupt → 中断 → FINAL_ANSWER(interrupted=True)
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from taisang.agent_core.events import FINAL_ANSWER, LLM_CHUNK, LLM_THINKING, TOOL_CALL
from taisang.llm_client import LLMResponse, MockLLM
from taisang.web.app import create_app
from taisang.web.session_registry import SessionRegistry


def _collect_events(client: TestClient, sid: str, duration: float = 5.0) -> list[dict]:
    """订阅 SSE 流,collect 事件直到 run_end 或超时。"""
    events: list[dict] = []
    # TestClient 同步,SSE 流用 stream 模式
    with client.stream("GET", f"/api/sessions/{sid}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("event: "):
                etype = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
                events.append({"type": etype, "payload": payload})
                if etype == "run_end":
                    break
    return events


def test_e2e_streaming_text_flow(tmp_path):
    """完整流程:POST /messages → SSE 收到 LLM_THINKING → 多个 LLM_CHUNK → FINAL_ANSWER。"""
    mock = MockLLM([LLMResponse(text="hello world", tool_calls=[])])
    registry = SessionRegistry(source_root=tmp_path, llm=mock, confirmer=lambda f, o, n: True)
    app = create_app(registry, source_root=tmp_path)
    client = TestClient(app)

    # 建会话
    r = client.post("/api/sessions", json={"title": "test"})
    sid = r.json()["id"]

    # 后台线程订阅 SSE(同步 TestClient 不能边订阅边 POST,用线程)
    events_queue: deque = deque()
    def subscribe():
        with client.stream("GET", f"/api/sessions/{sid}/events") as resp:
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    etype = line[7:]
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
                    events_queue.append({"type": etype, "payload": payload})
                    if etype == "run_end":
                        return
    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.1)  # 等订阅建立

    # POST 消息
    client.post(f"/api/sessions/{sid}/messages", json={"query": "test"})
    t.join(timeout=10)

    # 验证事件序列
    types = [e["type"] for e in events_queue]
    assert "llm_thinking" in types
    chunk_events = [e for e in events_queue if e["type"] == "llm_chunk"]
    assert len(chunk_events) >= 2
    final = [e for e in events_queue if e["type"] == "final_answer"][0]
    # 拼接 text_delta == final text
    text = "".join(e["payload"].get("text_delta", "") for e in chunk_events)
    assert text == "hello world"
    assert final["payload"]["interrupted"] is False


def test_e2e_interrupt_during_streaming(tmp_path):
    """流式阶段中断:POST /interrupt → FINAL_ANSWER(interrupted=True)。"""
    # 长 text 让 chunk 多,有机会中断
    mock = MockLLM([LLMResponse(text="a" * 50, tool_calls=[])])
    registry = SessionRegistry(source_root=tmp_path, llm=mock, confirmer=lambda f, o, n: True)
    app = create_app(registry, source_root=tmp_path)
    client = TestClient(app)

    r = client.post("/api/sessions", json={"title": "test"})
    sid = r.json()["id"]

    events_queue: deque = deque()
    interrupted = threading.Event()
    def subscribe():
        with client.stream("GET", f"/api/sessions/{sid}/events") as resp:
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    etype = line[7:]
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
                    events_queue.append({"type": etype, "payload": payload})
                    # 收到第一个 llm_chunk 后触发中断
                    if etype == "llm_chunk" and not interrupted.is_set():
                        client.post(f"/api/sessions/{sid}/interrupt")
                        interrupted.set()
                    if etype == "run_end":
                        return
    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.1)

    client.post(f"/api/sessions/{sid}/messages", json={"query": "test"})
    t.join(timeout=10)

    final = [e for e in events_queue if e["type"] == "final_answer"][0]
    assert final["payload"]["interrupted"] is True
    assert "[interrupted]" in final["payload"]["text"]


def test_e2e_reasoning_streaming(tmp_path):
    """reasoning_delta 流式:LLM_CHUNK 事件含 reasoning_delta。"""
    mock = MockLLM([LLMResponse(text="answer", tool_calls=[], reasoning="thinking process")])
    registry = SessionRegistry(source_root=tmp_path, llm=mock, confirmer=lambda f, o, n: True)
    app = create_app(registry, source_root=tmp_path)
    client = TestClient(app)

    r = client.post("/api/sessions", json={"title": "test"})
    sid = r.json()["id"]

    events_queue: deque = deque()
    def subscribe():
        with client.stream("GET", f"/api/sessions/{sid}/events") as resp:
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    etype = line[7:]
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
                    events_queue.append({"type": etype, "payload": payload})
                    if etype == "run_end":
                        return
    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.1)

    client.post(f"/api/sessions/{sid}/messages", json={"query": "test"})
    t.join(timeout=10)

    chunk_events = [e for e in events_queue if e["type"] == "llm_chunk"]
    reasoning = "".join(e["payload"].get("reasoning_delta", "") for e in chunk_events)
    assert reasoning == "thinking process"
```

- [ ] **Step 2: 跑 e2e 测试**

Run: `python -m pytest tests/integration/test_streaming_e2e.py -q`
Expected: 3 passed(如果 TestClient SSE 同步问题,可能需要调整 `subscribe` 实现)

**如果测试失败**:可能是 TestClient 流式 SSE 的同步问题。调试时先看错误,常见问题:
- `client.stream` 在线程里调用需要小心(TestClient 不是 thread-safe)
- 备选方案:用 `httpx.AsyncClient` + `ASGITransport`,或简化为只测后端逻辑(不测 SSE 传输)

- [ ] **Step 3: 跑全套测试**

Run: `python -m pytest tests/ -q`
Expected: all passed(现有 473 + 新增 ~20 = ~493)

- [ ] **Step 4: 提交**

```bash
git add tests/integration/test_streaming_e2e.py
git commit -m "test(e2e): streaming + interrupt integration tests"
```

---

## Task 18: README 更新 + 最终验证

**Files:**
- Modify: `README.md`(流式输出 + 中断功能加到"已实现",待实现里删掉流式)

- [ ] **Step 1: 更新 README**

Edit `README.md`,在"已实现"的"Agent 核心"章节加:

```markdown
- **流式输出**:LLM 响应逐 chunk 流式输出(最终答案 + thinking),Web 和 CLI 都支持;用户可中断当前 turn(Web 停止按钮 / CLI Ctrl+C),中断后保留半截答案 + `[interrupted]` 标记
```

在"待实现"里删掉流式输出那条:

```markdown
- ~~流式 LLM 响应~~ ✅ 已实现
```

在"可观测性"章节加:

```markdown
- **流式 chunk 事件**:LLM_CHUNK 事件(text_delta / reasoning_delta),前端实时累积渲染
```

- [ ] **Step 2: 跑全套测试最终验证**

Run: `python -m pytest tests/ -q`
Expected: all passed

- [ ] **Step 3: 跑 ruff/black(如有)**

Run: `python -m ruff check src/ tests/ && python -m black --check src/ tests/`
Expected: 尽量 clean(预存 125 ruff errors 不在本次 scope,新增文件要 clean)

- [ ] **Step 4: 跑前端 type-check + build 最终验证**

Run: `cd src/taisang/web/frontend && npm run type-check && npm run build`
Expected: clean

- [ ] **Step 5: 提交**

```bash
git add README.md
git commit -m "docs: README updates for streaming + interrupt feature"
```

- [ ] **Step 6: push**

```bash
git push
```

---

## Self-Review

### Spec coverage
- ✅ StreamChunk dataclass(Task 1)
- ✅ LLMResponse.reasoning 字段(Task 2,测试 reasoning 流用)
- ✅ MockLLM.chat_stream(Task 3)
- ✅ LLMClient.chat_stream(Task 4)
- ✅ Answer.interrupted 字段(Task 5)
- ✅ LLM_CHUNK 事件常量(Task 6)
- ✅ ToolRegistry cancel_event(Task 7)
- ✅ AgentService interrupt + _cancel_event(Task 8)
- ✅ AgentService 流式主循环 + _iter_with_retry(Task 9)
- ✅ Web /interrupt 路由(Task 10)
- ✅ CLI 流式 + Ctrl+C(Task 11)
- ✅ 前端 types + interruptSession API(Task 12)
- ✅ 前端 llm_chunk listener + 流式消息累积(Task 13)
- ✅ 前端 ThinkingIndicator reasoning 流(Task 14)
- ✅ 前端发送按钮变停止按钮(Task 15)
- ✅ 前端子 agent llm_chunk 嵌套渲染 + build(Task 16)
- ✅ E2E 测试(Task 17)
- ✅ README 更新 + 最终验证(Task 18)

### Placeholder scan
✅ 无 TBD/TODO,所有代码块完整
✅ 所有步骤有具体代码或命令

### Type consistency
✅ `StreamChunk` 字段名(text_delta / reasoning_delta / tool_calls / usage / is_final)跨 task 一致
✅ `LLMResponse.reasoning` 字段名跨 task 一致
✅ `Answer.interrupted` 字段名跨 task 一致
✅ `LLM_CHUNK` 事件常量跨 task 一致
✅ `cancel_event` 参数名跨 task 一致
✅ `streamingMessage` / `reasoningText` ref 名跨 task 一致
✅ `interruptSession` API 函数名跨 task 一致

---

## 执行方式

Plan complete and saved to `docs/superpowers/plans/2026-09-08-streaming-output.md`.

泰哥已确认"自己按计划执行,只负责验收",所以直接用 **Subagent-Driven Development**(推荐方式)执行:每个 Task 派 implementer subagent,两阶段 review(spec compliance + code quality),review APPROVED 后标 task 完成,进下一 task。连续执行不停顿。