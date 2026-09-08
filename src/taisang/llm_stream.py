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