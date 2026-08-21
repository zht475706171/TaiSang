"""LLM client:OpenAI 兼容接口 + 自研 MockLLM。

MockLLM 约 50 行,按调用顺序返回预设响应,不依赖外部服务。
LLMClient 用 openai SDK,兼容任意 OpenAI 兼容 endpoint。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import LLMConfig


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
        """
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            import json

            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments),
                    }
                )
        return LLMResponse(text=msg.content or "", tool_calls=tool_calls)


class MockLLM:
    """测试用 mock LLM。按调用顺序返回预设响应,记录所有调用。

    用法:
        mock = MockLLM([resp1, resp2])
        mock.chat(messages=[...], tools=[...])  # 返回 resp1
        mock.chat(messages=[...], tools=[...])  # 返回 resp2
        mock.calls  # 查看所有调用记录
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            raise RuntimeError("no more mock responses prescribed")
        return self._responses.pop(0)
