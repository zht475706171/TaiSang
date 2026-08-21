"""LLM client:OpenAI 兼容接口 + 自研 MockLLM。

MockLLM 约 50 行,按调用顺序返回预设响应,不依赖外部服务。
LLMClient 用 openai SDK,兼容任意 OpenAI 兼容 endpoint。

异常:所有 LLM 相关错误统一用 llm_errors.py 的 LLMError 层级。
- openai SDK 异常 → LLMTransientError
- 畸形 JSON / tool_calls 结构 → LLMProtocolError
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from .config import LLMConfig
from .llm_errors import LLMProtocolError, LLMTransientError


@dataclass
class LLMResponse:
    """LLM 一次响应。text 和 tool_calls 至少有一个非空。"""

    text: str
    tool_calls: list[dict] = field(default_factory=list)


class LLMClient:
    """真实 LLM client,基于 openai SDK。"""

    def __init__(self, cfg: LLMConfig) -> None:
        from openai import OpenAI

        self.cfg = cfg
        self.model = cfg.model
        self._client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """发 chat completion 请求,返回 LLMResponse。

        tools 是工具 schema 列表(OpenAI tool 格式)。

        Raises:
            LLMTransientError: openai SDK 异常(网络/限流/超时等)
            LLMProtocolError: tool_calls 畸形 JSON 或结构异常
        """
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            # openai SDK 异常(APIError/RateLimitError/APITimeoutError 等)统一包装
            raise LLMTransientError(f"LLM API call failed: {e}") from e

        msg = resp.choices[0].message
        tool_calls: list[dict] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    name = tc.function.name
                    args_raw = tc.function.arguments
                    args = json.loads(args_raw) if args_raw else {}
                except json.JSONDecodeError as e:
                    raise LLMProtocolError(f"malformed tool_call arguments JSON: {e}") from e
                except AttributeError as e:
                    raise LLMProtocolError(f"malformed tool_call structure: {e}") from e
                tool_calls.append({"name": name, "args": args})
        return LLMResponse(text=msg.content or "", tool_calls=tool_calls)


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
