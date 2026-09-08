# 流式输出 + 用户中断 设计

**日期**:2026-09-08
**状态**:已确认,准备出实施计划
**目标**:LLM 响应逐字/逐 chunk 流式输出(最终答案 + thinking),Web 和 CLI 都支持;用户可中断当前 turn

## 决策汇总(10 项)

| # | 决策点 | 选择 |
|---|--------|------|
| 1 | 流式范围 | 最终答案 + thinking 都流式 |
| 2 | thinking 兼容 | 只读 `reasoning_content`(Kimi 等),getattr 兜底 |
| 3 | tool_calls 处理 | 仍一次 emit(累积完整再发) |
| 4 | LLMClient 接口 | 新增 `chat_stream` 方法,`chat` 原样不动 |
| 5 | 重试+流式 | `_iter_with_retry` 包装器,只重试第一次 next |
| 6 | CLI | 也流式,Ctrl+C 中断 |
| 7 | usage | 开 `stream_options: {include_usage: true}` |
| 8 | 中断范围 | 只中断当前 turn,工具执行中也能中断 |
| 9 | 中断 UI | Web 发送按钮变停止按钮(同位置切换);CLI Ctrl+C |
| 10 | 中断后处理 | 保留半截答案 + `[interrupted]` 标记,落盘 + emit FINAL_ANSWER |

## 架构总览

### 新增/改动文件

**后端新增**:
- `src/taisang/llm_stream.py`(~30 行):`StreamChunk` dataclass,纯数据载体

**后端改动**:
- `src/taisang/llm_client.py`:`LLMClient` 加 `chat_stream`;`MockLLM` 加 `chat_stream`;`LLMResponse` 加 `reasoning: str = ""` 字段(测试用)
- `src/taisang/agent_core/events.py`:加 `LLM_CHUNK = "llm_chunk"` 常量;`FINAL_ANSWER` payload 加 `interrupted: bool` 字段
- `src/taisang/agent_core/service.py`:主循环改流式;加 `self._cancel_event` + `interrupt()` 方法;加 `_iter_with_retry` 内部函数;`InterruptedError` + `KeyboardInterrupt` 处理
- `src/taisang/agent_core/tools/registry.py`:`ToolRegistry.__init__` 加 `cancel_event` 参数;`call` 方法执行前检查
- `src/taisang/types.py`:`Answer` dataclass 加 `interrupted: bool = False` 字段
- `src/taisang/cli/main.py`:`_render` 加 `LLM_CHUNK` 分支;Ctrl+C 处理
- `src/taisang/web/app.py`:加 `POST /api/sessions/{id}/interrupt` 路由

**前端改动**:
- `src/types/index.ts`:加 `'llm_chunk'` MessageKind + `textDelta` / `reasoningDelta` 字段;`interrupted` 字段
- `composables/useChatStream.ts`:加 `llm_chunk` listener,累积到"正在流"的 assistant 消息;`final_answer` 处理 `interrupted` 标记;导出 `interrupt` API 调用
- `components/MessageInput.vue`:发送按钮发送后变停止按钮,停止时 emit `interrupt`
- `components/ThinkingIndicator.vue`:显示 reasoning 流(累积 reasoning_delta)
- `views/ChatView.vue`:接 `interrupt` 事件,调 `POST /interrupt` API
- `api/chat.ts`:加 `interruptSession` 函数

### 模块职责边界

- `LLMClient`:暴露 `chat`(非流式,保留)和 `chat_stream`(流式)两接口,各管各的,职责单一
- `AgentService`:主循环 + 中断管理(`_cancel_event` + `interrupt()`),不关心流式细节
- `llm_retry`:只包"迭代器第一次 next"那一行,流中失败不重试
- `EventBroker` / SSE:完全不动,只多一种事件类型
- `tools/registry`:加 cancel 检查点,不侵入工具实现

### 不做的事(YAGNI)
- 不改 `chat` 原接口(向后兼容)
- 不支持并发中断(同一时刻只能 1 个 turn 在跑)
- 不做流中重试
- 不做"中断后恢复"(中断即结束本轮,下轮重新问)
- 不做 o1/o3 推理流 / `&lt;think&gt;` 标签解析
- 不做工具内部中断(Bash 跑着没法 kill 命令本身,要 SIGTERM,工程量大)

## StreamChunk 数据结构

```python
# src/taisang/llm_stream.py
@dataclass
class StreamChunk:
    """LLM 流式响应的一个 chunk。

    一次 yield 通常只含一种 delta(text 或 reasoning),最后 chunk 含
    tool_calls + usage + is_final=True。
    """
    text_delta: str = ""           # 答案文本增量(OpenAI delta.content)
    reasoning_delta: str = ""      # 思考过程增量(Kimi reasoning_content,getattr 兜底)
    tool_calls: list[dict] = field(default_factory=list)  # 只在最后 chunk,累积完整
    usage: dict | None = None      # 只在最后 chunk(需 stream_options include_usage)
    is_final: bool = False         # 标记最后一个 chunk
```

## LLMClient.chat_stream 流程

```python
def chat_stream(self, messages, tools) -> Iterator[StreamChunk]:
    kwargs = {"model": self.model, "messages": messages, "timeout": 60,
              "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
    try:
        stream = self._client.chat.completions.create(**kwargs)
    except Exception as e:
        log.warning("LLM chat_stream failed: ...", exc_info=True)
        raise LLMTransientError(f"LLM API call failed: {e}") from e

    acc_tool_calls: dict[int, dict] = {}  # {index: {id, name, arguments_str}}
    last_usage = None
    try:
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                text_delta = getattr(delta, "content", None) or ""
                reasoning_delta = getattr(delta, "reasoning_content", None) or ""
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in acc_tool_calls:
                            acc_tool_calls[idx] = {
                                "id": tc.id or "",
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
            if chunk.usage:
                last_usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }
    except Exception as e:
        log.warning("LLM stream chunk failed: ...", exc_info=True)
        raise LLMTransientError(f"LLM stream failed: {e}") from e

    yield StreamChunk(
        tool_calls=list(acc_tool_calls.values()),
        usage=last_usage,
        is_final=True,
    )
```

**关键点**:
- `tool_calls` 分片到达,每个分片带 `index`,arguments 按 index 拼接(OpenAI 流式协议标准)
- `reasoning_content` 用 `getattr` 兜底,OpenAI 标准 endpoint 不返就是 None
- 最后 chunk `choices` 为空,只有 `usage`(开了 `include_usage` 后的标准行为)
- 流中失败包装 `LLMTransientError` 抛出(调用方不重试)

## MockLLM.chat_stream

```python
def chat_stream(self, messages, tools) -> Iterator[StreamChunk]:
    self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
    if not self._responses:
        raise RuntimeError("no more mock responses prescribed")
    resp = self._responses.pop(0)
    # text 按 chunk_size=5 拆 chunk
    chunk_size = 5
    for i in range(0, len(resp.text or ""), chunk_size):
        yield StreamChunk(text_delta=resp.text[i:i+chunk_size])
    # reasoning 也拆 chunk(测试用)
    for i in range(0, len(resp.reasoning or ""), chunk_size):
        yield StreamChunk(reasoning_delta=resp.reasoning[i:i+chunk_size])
    # 最后 final chunk
    yield StreamChunk(tool_calls=resp.tool_calls, usage=resp.usage, is_final=True)
```

## AgentService.run 流式主循环

```python
def run(self, query, on_event=None):
    self._cancel_event = threading.Event()  # 每次 run 新建
    ...
    while steps < self.max_steps:
        steps += 1
        # enforce_budget / autocompact 不变
        _emit(AgentEvent(LLM_THINKING))
        accumulated_text = ""
        accumulated_reasoning = ""
        tool_calls = []
        usage = None
        assistant_appended = False  # 标记是否已 append_assistant(中断处理用)
        try:
            stream = _iter_with_retry(
                lambda: self.llm.chat_stream(messages=..., tools=...),
                on_retry=lambda a, e, d: _emit(AgentEvent(LLM_RETRY, ...)),
            )
            for chunk in stream:
                if self._cancel_event.is_set():
                    raise InterruptedError()
                if chunk.text_delta:
                    accumulated_text += chunk.text_delta
                    _emit(AgentEvent(LLM_CHUNK, payload={"text_delta": chunk.text_delta, "reasoning_delta": ""}))
                if chunk.reasoning_delta:
                    accumulated_reasoning += chunk.reasoning_delta
                    _emit(AgentEvent(LLM_CHUNK, payload={"text_delta": "", "reasoning_delta": chunk.reasoning_delta}))
                if chunk.is_final:
                    tool_calls = chunk.tool_calls
                    usage = chunk.usage
        except KeyboardInterrupt:
            # CLI Ctrl+C:转中断信号
            self._cancel_event.set()
            raise InterruptedError() from None
        except InterruptedError:
            # 中断:把已流出的 text 作为最终答案
            text = accumulated_text + " [interrupted]" if accumulated_text else "(已中断)"
            if not assistant_appended:
                self.ctx.append_assistant(text=text, tool_calls=None)
            _emit(AgentEvent(FINAL_ANSWER, payload={"text": text, "interrupted": True}))
            self._emit_usage_report(_emit)
            return Answer(text=text, citations=[], complete=False, steps_used=steps, interrupted=True)
        except LLMTransientError as e:
            # 流中失败:半截 text 已流出
            text = accumulated_text + f" [LLM 调用失败: {e}]" if accumulated_text else f"(LLM 调用失败: {e})"
            self.ctx.append_assistant(text=text, tool_calls=None)
            _emit(AgentEvent(FINAL_ANSWER, payload={"text": text, "interrupted": False}))
            self._emit_usage_report(_emit)
            return Answer(text=text, citations=[], complete=False, steps_used=steps)
        except LLMProtocolError as e:
            # 同原逻辑
            ...
        except LLMError as e:
            # 同原逻辑
            ...

        self._accumulate_usage(usage)

        if not tool_calls:
            # 最终答案(正常完成)
            self.ctx.append_assistant(text=accumulated_text, tool_calls=None)
            _emit(AgentEvent(FINAL_ANSWER, payload={"text": accumulated_text, "interrupted": False}))
            # session memory / citations 不变
            return Answer(text=accumulated_text, citations=citations, complete=True, steps_used=steps)

        # 有 tool_calls:append_assistant + 执行工具
        self.ctx.append_assistant(text=accumulated_text, tool_calls=tool_calls)
        assistant_appended = True
        for tc in tool_calls:
            if self._cancel_event.is_set():
                # 工具阶段中断:补空 tool_result
                self.ctx.append_tool_result('{"_interrupted": true}', name=tc["function"]["name"], tool_call_id=tc["id"])
                raise InterruptedError()
            _emit(AgentEvent(TOOL_CALL, ...))
            result = registry.call(name, args)
            ...
        # flush_skill_injections / flush_async_notifications / session_memory 不变
```

## _iter_with_retry 包装器

```python
# service.py 内部函数
def _iter_with_retry(make_iter, on_retry):
    """重试只覆盖迭代器第一次 next(连接建立 + 首 chunk)。

    首 chunk 成功后,后续 next 失败不重试(已经吐过字了)。
    make_iter: 返回 iterator 的 callable(每次重试会重新调)
    on_retry: 重试回调
    """
    it = call_with_retry(make_iter, on_retry=on_retry)
    try:
        first_chunk = next(it)
    except StopIteration:
        # 空 iterator(只有 final chunk 也不 yield?不会,final chunk 总会 yield)
        return
    yield first_chunk
    yield from it
```

**关键点**:`call_with_retry` 包 `make_iter` — 这个 callable 返回 iterator,但还没开始迭代。`next(it)` 才真正发 HTTP 请求。`call_with_retry` 重试的是 `make_iter()` 调用 + 第一次 `next()`(因为 `next` 在 `try` 块外,不会触发 `call_with_retry` 的重试)。

**修正**:更精确的实现 — 把第一次 `next` 也包进 `call_with_retry`:

```python
def _iter_with_retry(make_iter, on_retry):
    """重试覆盖:make_iter() + 第一次 next()。"""
    state = {"it": None, "first": None}
    def _do_first():
        state["it"] = make_iter()
        state["first"] = next(state["it"])
        return state["first"]
    first_chunk = call_with_retry(_do_first, on_retry=on_retry)
    yield first_chunk
    yield from state["it"]  # 后续 next 失败不重试,直接抛
```

## 中断机制

### AgentService.interrupt()

```python
def interrupt(self) -> None:
    """用户请求中断当前 turn。thread-safe。

    主循环在下一个 chunk 或工具执行前检查 is_set() → True 走中断分支。
    turn 已结束或未开始时 set 无副作用(下次 run 会建新 event)。
    """
    if self._cancel_event is not None:
        self._cancel_event.set()
```

### ToolRegistry 中断检查

```python
class ToolRegistry:
    def __init__(self, ..., cancel_event: threading.Event | None = None):
        ...
        self._cancel_event = cancel_event

    def call(self, name: str, args: dict) -> dict:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise InterruptedError("tool execution cancelled by user")
        # 原有调度逻辑
        ...
```

### 3 个中断检查点

1. **每个 chunk**:`for chunk in stream:` 后立即检查
2. **每个工具执行前**:`for tc in tool_calls:` 后检查,中断时补空 tool_result
3. **max_steps**(原有,不变)

### 中断后 ctx 一致性

**情况 A:LLM 流式阶段中断**(还没 `append_assistant`)
- ctx: `[user(query)]`
- 处理:`append_assistant(text=半截 + " [interrupted]", tool_calls=None)`
- 下次 run:LLM 看到 `[user, assistant(半截 [interrupted])]`,正常继续

**情况 B:工具执行阶段中断**(已 `append_assistant(tool_calls)`,缺 tool_result)
- ctx: `[user, assistant(text, tool_calls)]` + 缺 tool_result
- 处理:为未执行的工具补 `{"_interrupted": true}` tool_result,不重复 `append_assistant`
- 下次 run:LLM 看到 `[user, assistant(tool_calls), tool_result({"_interrupted": true})]`,正常继续

## 事件协议

### 新增 LLM_CHUNK

```python
# events.py
LLM_CHUNK = "llm_chunk"
# payload: {"text_delta": str, "reasoning_delta": str, "agent_id": str}
# 一次 emit 只含一种 delta(另一种为空字符串)
# agent_id: 主 agent 为空,子 agent 用唯一 id(嵌套渲染到父卡片)
```

### FINAL_ANSWER payload 扩展

```python
# 原: {"text": str}
# 新: {"text": str, "interrupted": bool}
# 前端用 .get("interrupted", False) 兼容历史事件
```

## Web 端中断 API

```python
# web/app.py
@app.post("/api/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str) -> dict:
    sess = registry.get_or_load(session_id)
    if sess is None:
        raise HTTPException(404, f"session not found: {session_id}")
    if not sess.lock.locked():
        return {"ok": True, "interrupted": False}  # 幂等,turn 没在跑
    sess.agent.interrupt()
    return {"ok": True, "interrupted": True}
```

**关键点**:幂等(turn 没在跑返回 200),不等中断生效就返回(前端通过 FINAL_ANSWER 事件知道中断生效)。

## CLI Ctrl+C 处理

```python
# cli/main.py
try:
    answer = agent.run(query, on_event=_render)
except KeyboardInterrupt:
    # Ctrl+C 在 run() 内部已被 catch(set cancel_event + 转 InterruptedError)
    # 如果穿透到这里,说明 run() 已返回(中断分支已处理)
    click.echo(style("\n  [interrupted]", fg="yellow"))
    continue

# service.py run() 主循环加:
except KeyboardInterrupt:
    self._cancel_event.set()
    raise InterruptedError() from None
```

**关键点**:`KeyboardInterrupt` 继承 `BaseException`,`except Exception` 不 catch,需显式处理。run() 内部转 `InterruptedError` 走统一中断分支,REPL 不退出。

## 前端改动

### types/index.ts

```typescript
export type MessageKind =
  | ...
  | 'llm_chunk'

export interface ChatMessage {
  ...
  textDelta?: string       // LLM_CHUNK 累积的 text
  reasoningDelta?: string  // LLM_CHUNK 累积的 reasoning
  interrupted?: boolean    // FINAL_ANSWER 中断标记
  streaming?: boolean      // 标记"正在流"的 assistant 消息
}
```

### useChatStream.ts

```typescript
const streamingMessage = ref<ChatMessage | null>(null)

eventSource.addEventListener('llm_chunk', (e) => {
  const d = safeParse<{ text_delta: string; reasoning_delta: string; agent_id?: string }>(e.data)
  if (!d) return
  // 子 agent chunk:嵌套(同 Task 14 逻辑)
  if (d.agent_id) { ... return }
  // 主 agent chunk
  if (d.text_delta) {
    if (!streamingMessage.value || !streamingMessage.value.streaming) {
      // 新流开始,创建 streaming 消息
      streamingMessage.value = { id: nextId(), kind: 'assistant', text: '', streaming: true }
      messages.value.push(streamingMessage.value)
    }
    streamingMessage.value.text += d.text_delta
  }
  if (d.reasoning_delta) {
    // reasoning 流到 ThinkingIndicator(单独 ref)
    reasoningText.value += d.reasoning_delta
  }
})

eventSource.addEventListener('final_answer', (e) => {
  const d = safeParse<{ text: string; interrupted: boolean; agent_id?: string }>(e.data)
  if (!d) return
  clearThinking()
  if (d.agent_id) { ... return }
  // 流式模式:FINAL_ANSMARY 不重复 push(已在 llm_chunk 累积)
  if (streamingMessage.value && streamingMessage.value.streaming) {
    streamingMessage.value.streaming = false
    streamingMessage.value.interrupted = d.interrupted || false
    // 如果中断且 text 为空,用 d.text(含 [interrupted] 标记)
    if (!streamingMessage.value.text) {
      streamingMessage.value.text = d.text
    } else if (d.interrupted) {
      streamingMessage.value.text += ' [interrupted]'
    }
    streamingMessage.value = null
  } else {
    // 非流式回退(autocompact LLM 摘要等仍用 chat 非流式)
    pushAssistant(d.text)
  }
})
```

### MessageInput.vue

```vue
<template>
  <div class="message-input">
    <textarea v-model="text" @keydown.enter="handleSend" />
    <button v-if="!streaming" @click="handleSend">发送</button>
    <button v-else class="stop-btn" @click="handleStop">停止</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ streaming: boolean }>()
const emit = defineEmits<{ send: [text: string]; stop: [] }>()
function handleStop() { emit('stop') }
</script>
```

### ThinkingIndicator.vue

```vue
<template>
  <div class="thinking">
    <span class="label">thinking</span>
    <span v-if="retryInfo" class="retry-badge">第 {{ retryInfo.attempt }} 次重试中</span>
    <span v-if="reasoningText" class="reasoning">{{ reasoningText }}</span>
    <span v-else class="dots"><span></span><span></span><span></span></span>
  </div>
</template>
```

## 错误处理矩阵

| 错误类型 | 触发点 | 重试 | 用户看到 | 状态影响 |
|---------|--------|------|---------|---------|
| `LLMTransientError`(连接失败) | `chat_stream` 创建或首 next | ✅ | LLM_RETRY 事件 | 无 |
| `LLMTransientError`(流中 chunk 失败) | `next(it)` 第 2+ 次 | ❌ | FINAL_ANSWER 带 `[LLM 调用失败: ...]` | 半截 text 落盘 |
| `LLMProtocolError` | tool_call 解析 | ❌ | FINAL_ANSWER 带 `(LLM 协议错误)` | 同原逻辑 |
| `InterruptedError`(用户中断) | chunk / 工具检查点 | ❌ | FINAL_ANSWER 带 `[interrupted]` | 半截 text + 补空 tool_result |
| `LLMError`(其他) | 任意 | ❌ | FINAL_ANSWER 带 `(LLM 错误)` | 同原逻辑 |
| `KeyboardInterrupt`(CLI Ctrl+C) | 任意 | ❌ | 转 InterruptedError | 同中断 |

## 测试策略

### 测试文件

| 文件 | 测什么 | 新增/改动 |
|------|--------|----------|
| `tests/unit/test_llm_stream.py` | StreamChunk dataclass | 新增 |
| `tests/unit/test_llm_client.py` | chat_stream + MockLLM.chat_stream | 改 |
| `tests/unit/test_llm_retry.py` | _iter_with_retry 包装器 | 改 |
| `tests/unit/test_agent_core.py` | 流式主循环 + 中断机制 | 改 |
| `tests/unit/test_web_app.py` | /interrupt 路由 | 改 |
| `tests/integration/test_streaming_e2e.py` | 流式 + 中断端到端 | 新增 |

### 关键用例

**test_llm_stream.py**(3):defaults / text_delta / final chunk

**test_llm_client.py 流式**(5):
- MockLLM.chat_stream 拆 text chunk
- 最后 chunk 含 tool_calls + usage + is_final
- 记录 calls(deepcopy)
- 预设用完抛 RuntimeError
- 空 text 只 yield final chunk

**test_llm_retry.py 流式**(3):
- 第一次 next 失败重试
- 首 chunk 后失败不重试
- 全 chunks yield

**test_agent_core.py 流式+中断**(8):
- 流式累积 text 成 FINAL_ANSWER
- LLM_CHUNK 事件 payload 正确
- reasoning_delta 流式(MockLLM 加 reasoning 字段)
- LLM 流式阶段中断
- 工具阶段中断(补空 tool_result)
- 中断后 ctx 兼容下次 run
- 流中失败不重试 + 标记
- Answer.interrupted 默认 False

**test_web_app.py interrupt**(3):
- turn 在跑时 POST /interrupt
- turn 没在跑时幂等返回
- 未知 session 404

**test_streaming_e2e.py**(3):
- 完整流式 text flow
- 流式阶段中断
- 工具阶段中断

### MockLLM 扩展

`LLMResponse` 加 `reasoning: str = ""` 字段,`MockLLM.chat_stream` 把 reasoning 也拆 chunk yield,覆盖 reasoning 流测试。

### 不测的部分
- 真 endpoint 流式(网络依赖)
- Windows Ctrl+C 信号(CI 跑 Linux)
- 前端流式渲染(手动 + type-check)
- 流中和连接失败边界时序

### 测试数量
新增 ~20 用例。现有 473 + 新增 ~20 = ~493 passed。

## 已知 gap(v1)

- **流中失败不重试**:用户看到中断提示,需重新发消息。可接受(真实场景少)
- **工具内部不可中断**:Bash 跑着没法 kill 命令本身,只能等命令跑完在下一个工具前中断。v1 接受
- **reasoning_content 兼容**:只支持 Kimi 风格 `delta.reasoning_content`。OpenAI o1/o3 推理流不支持(YAGNI)
- **前端非流式回退**:autocompact LLM 摘要等内部调用仍用 `chat` 非流式,不 emit LLM_CHUNK(只 emit COMPACTED 事件)。符合现状
- **并发中断不支持**:同一时刻只能 1 个 turn 在跑(per-session lock),中断也只能针对当前 turn