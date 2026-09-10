"""LLM client:OpenAI 兼容接口 + 自研 MockLLM。

MockLLM 约 50 行,按调用顺序返回预设响应,不依赖外部服务。
LLMClient 用 openai SDK,兼容任意 OpenAI 兼容 endpoint。

异常:所有 LLM 相关错误统一用 llm_errors.py 的 LLMError 层级。
- openai SDK 异常 → LLMTransientError
- 畸形 JSON / tool_calls 结构 → LLMProtocolError
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from .config import LLMConfig
from .llm_errors import LLMProtocolError, LLMTransientError

log = logging.getLogger(__name__)


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


class LLMClient:
    """真实 LLM client,基于 openai SDK。"""

    def __init__(self, cfg: LLMConfig) -> None:
        from openai import OpenAI

        self.cfg = cfg
        self.model = cfg.model
        # openai SDK 拒绝空 api_key(抛 OpenAIError)。ollama 等本地 endpoint
        # 不需要 key,但 SDK 强制要求非空,传 placeholder "not-set" 让 SDK 不报错。
        # 实际 endpoint 不会校验这个值。self.cfg.api_key 仍保留原始空值。
        sdk_key = cfg.api_key if cfg.api_key else "not-set"
        self._client = OpenAI(base_url=cfg.base_url, api_key=sdk_key)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """发 chat completion 请求,返回 LLMResponse。

        tools 是工具 schema 列表(OpenAI tool 格式)。

        Raises:
            LLMTransientError: openai SDK 异常(网络/限流/超时等)
            LLMProtocolError: tool_calls 畸形 JSON 或结构异常
        """
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "timeout": 60}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            # openai SDK 异常(APIError/RateLimitError/APITimeoutError 等)统一包装
            # 打原始异常类型 + cause + __cause__,辅助诊断间歇性连接问题
            cause = getattr(e, "__cause__", None)
            cause_repr = repr(cause) if cause else "(none)"
            log.warning(
                "LLM chat failed: type=%s msg=%s cause=%s",
                type(e).__name__,
                e,
                cause_repr,
                exc_info=True,
            )
            raise LLMTransientError(f"LLM API call failed: {e}") from e

        msg = resp.choices[0].message
        tool_calls: list[dict] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                # 透传 OpenAI 标准 tool_call 结构(arguments 保持 OpenAI 给的 JSON 字符串,
                # 不在这里 json.loads;由调用方 service.py 解析,畸形 JSON 在那里降级处理)。
                try:
                    tc_id = tc.id
                    fn_name = tc.function.name
                    fn_args = tc.function.arguments or ""
                except AttributeError as e:
                    raise LLMProtocolError(f"malformed tool_call structure: {e}") from e
                tool_calls.append(
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {"name": fn_name, "arguments": fn_args},
                    }
                )
        # 透传 usage(prompt_tokens/completion_tokens/total_tokens)。
        # endpoint 不返回时 usage=None(MockLLM 也不返回)。用 getattr 兼容测试
        # FakeResp(不挂 usage 属性)以及 openai SDK 返回 usage=None 的情况。
        raw_usage = getattr(resp, "usage", None)
        usage = None
        if raw_usage is not None:
            try:
                usage = {
                    "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(raw_usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(raw_usage, "total_tokens", 0) or 0,
                }
            except AttributeError:
                usage = None
        return LLMResponse(text=msg.content or "", tool_calls=tool_calls, usage=usage)

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

        # 暴露 raw stream 给外部:cancel 时 service.py 调 self.llm._last_raw_stream.close()
        # 关 HTTP 连接(httpx response.close,线程安全),让 pump 线程的 next() 抛异常退出。
        # 不能靠 gen.close() 触发 GeneratorExit:generator 绑定创建线程,跨线程 close
        # 会抛 "generator already executing"。
        self._last_raw_stream = stream

        acc_tool_calls: dict[int, dict] = {}
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
                if chunk.usage:
                    last_usage = {
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                    }
        except Exception as e:
            # GeneratorExit(generator 被 close)/ 正常异常都走这里
            cause = getattr(e, "__cause__", None)
            cause_repr = repr(cause) if cause else "(none)"
            log.warning(
                "LLM stream chunk failed: type=%s msg=%s cause=%s",
                type(e).__name__, e, cause_repr, exc_info=True,
            )
            # GeneratorExit 不包装,直接抛(让 generator 正常终止)
            if type(e).__name__ == "GeneratorExit":
                raise
            raise LLMTransientError(f"LLM stream failed: {e}") from e
        finally:
            # 确保 HTTP 连接释放:正常完成 / 异常 / 外部 raw stream.close() 都走这里
            try:
                stream.close()
            except Exception:  # noqa: BLE001 — close 失败不致命,连接已断
                pass
            self._last_raw_stream = None

        yield StreamChunk(
            tool_calls=list(acc_tool_calls.values()),
            usage=last_usage,
            is_final=True,
        )


class MockLLM:
    """测试用 mock LLM。按调用顺序返回预设响应,记录所有调用。

    calls 用 deepcopy 存储消息,防止 caller 后续 mutate 污染记录。

    用法:
        mock = MockLLM([resp1, resp2])
        mock.chat(messages=[...], tools=[...])  # 返回 resp1
        mock.chat(messages=[...], tools=[...])  # 返回 resp2
        mock.calls  # 查看所有调用记录(deepcopy,不受 caller mutate 影响)
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        # deepcopy 防 caller 后续 mutate messages/tools 污染记录
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self._responses:
            raise RuntimeError("no more mock responses prescribed")
        return self._responses.pop(0)

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
        chunk_size = 5
        for i in range(0, len(resp.text or ""), chunk_size):
            yield StreamChunk(text_delta=resp.text[i:i + chunk_size])
        for i in range(0, len(resp.reasoning or ""), chunk_size):
            yield StreamChunk(reasoning_delta=resp.reasoning[i:i + chunk_size])
        yield StreamChunk(
            tool_calls=resp.tool_calls,
            usage=resp.usage,
            is_final=True,
        )
