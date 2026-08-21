"""LLM 异常层级。

所有 LLM 相关错误统一根在 LLMError 下,调用方按需细分捕获:
- LLMProtocolError:协议层错误(畸形 JSON、tool_calls 结构异常)— 不可重试
- LLMTransientError:瞬时错误(网络、限流、超时)— 可重试
"""

from __future__ import annotations


class LLMError(Exception):
    """LLM 调用相关错误的基类。"""


class LLMProtocolError(LLMError):
    """协议层错误:畸形 JSON、tool_calls 结构异常等。不可重试。"""


class LLMTransientError(LLMError):
    """瞬时错误:网络、限流、超时等。可重试。"""
