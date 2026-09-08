"""LLM 调用重试:指数退避 + 抖动,参考 claude-code withRetry 简化版。

可重试(LLMTransientError 全部 + openai SDK 特定 status):
- APIConnectionError / APITimeoutError(无 status_code)→ 无条件重试
- 429 Rate Limit / 408 Request Timeout → 重试
- 5xx → 重试

不重试:
- LLMProtocolError(畸形 tool_call 结构,重试没用)
- 4xx 非 429/408(401/403/400 — 配置/key 问题,重试浪费)
- 非 LLMError 层级的异常(直接抛)

参数(简化 claude-code):
- MAX_RETRIES = 5  (claude-code 10,我们够用)
- BASE_DELAY_SEC = 0.5
- MAX_DELAY_SEC = 16.0  (claude-code 32s,我们够用)
- jitter = 0-25% of base

退避序列(不含 jitter):
- attempt 1: 0.5s
- attempt 2: 1.0s
- attempt 3: 2.0s
- attempt 4: 4.0s
- attempt 5: 8.0s
最坏情况(5 次全失败):0.5+1+2+4+8 = 15.5s + jitter
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

from .llm_errors import LLMProtocolError, LLMTransientError

log = logging.getLogger(__name__)

T = TypeVar("T")

MAX_RETRIES = 5
BASE_DELAY_SEC = 0.5
MAX_DELAY_SEC = 16.0


def _retry_delay(attempt: int) -> float:
    """计算重试延迟(秒)。attempt 从 1 开始。

    base = min(BASE_DELAY_SEC * 2^(attempt-1), MAX_DELAY_SEC)
    jitter = random() * 0.25 * base   # 0-25% 抖动
    return base + jitter
    """
    base = min(BASE_DELAY_SEC * (2 ** (attempt - 1)), MAX_DELAY_SEC)
    jitter = random.random() * 0.25 * base
    return base + jitter


def _is_retryable(err: Exception) -> bool:
    """是否值得重试。

    - LLMProtocolError → False(畸形结构,重试没用)
    - LLMTransientError:
        - cause 是 openai APIStatusError → 看 status_code(429/408/5xx 重试)
        - cause 是 APIConnectionError/APITimeoutError(无 status_code)→ True
        - 无 cause → True(保守重试)
    - 其他异常 → False
    """
    if isinstance(err, LLMProtocolError):
        return False
    if isinstance(err, LLMTransientError):
        cause = err.__cause__
        if cause is None:
            return True
        # openai SDK 的 APIStatusError 有 status_code 属性
        status = getattr(cause, "status_code", None)
        if status is None:
            return True  # 纯连接错误(APIConnectionError/APITimeoutError 无 status),重试
        # 429 / 408 / 5xx 重试,其他 4xx 不重试
        return status in (408, 429) or 500 <= status < 600
    return False


def call_with_retry(
    fn: Callable[[], T],
    *,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """调用 fn,失败按策略重试。

    on_retry(attempt, err, delay_sec):重试前回调,给 UI/日志通知用。
    回调自己抛异常不影响重试流程(吞掉)。

    最多重试 MAX_RETRIES 次,即 fn 总共最多调 MAX_RETRIES 次。
    全部失败抛最后一个错误。
    """
    last_err: Exception | None = None
    # range(1, MAX_RETRIES + 1) = 1..MAX_RETRIES,共 MAX_RETRIES 次
    # (MAX_RETRIES=5 → 调 5 次,失败 4 次会 sleep,第 5 次失败抛)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            # attempt == MAX_RETRIES 表示最后一次,不再重试
            if not _is_retryable(e) or attempt >= MAX_RETRIES:
                raise
            delay = _retry_delay(attempt)
            log.warning(
                "LLM call failed (attempt %d/%d), retry in %.2fs: %s: %s",
                attempt,
                MAX_RETRIES,
                delay,
                type(e).__name__,
                e,
            )
            if on_retry is not None:
                try:
                    on_retry(attempt, e, delay)
                except Exception as cb_err:
                    log.warning("on_retry callback failed: %s: %s", type(cb_err).__name__, cb_err)
            time.sleep(delay)
    # 理论上走不到这里(for 循环要么 return 要么 raise)
    raise last_err  # type: ignore[misc]