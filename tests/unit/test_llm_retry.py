"""测试 LLM 调用重试机制(call_with_retry)。

参考 claude-code withRetry 简化版:
- 指数退避 + ±25% 抖动
- 可重试:LLMTransientError(网络/超时/429/5xx)
- 不可重试:LLMProtocolError(畸形 tool_call 结构)、4xx 非 429
- max 5 次,base 0.5s,max 16s
"""

from __future__ import annotations

import pytest

from taisang.llm_errors import LLMProtocolError, LLMTransientError
from taisang.llm_retry import (
    BASE_DELAY_SEC,
    MAX_DELAY_SEC,
    MAX_RETRIES,
    _is_retryable,
    _retry_delay,
    call_with_retry,
)


class _FakeStatusError(Exception):
    """模拟 openai APIStatusError 的 status_code 属性。

    _is_retryable 用 getattr(cause, "status_code", None) 读,不挑异常类型,
    所以用简单 fake 类避免在测试里造 httpx.Response 对象。
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"fake status {status_code}")
        self.status_code = status_code


class _FakeConnError(Exception):
    """模拟 openai APIConnectionError(无 status_code 属性)。"""

    pass


# ---------- _retry_delay ----------

def test_retry_delay_exponential_growth():
    """attempt 1=0.5, 2=1.0, 3=2.0, 4=4.0, 5=8.0(不含 jitter)。"""
    for attempt in range(1, 6):
        d = _retry_delay(attempt)
        base = min(BASE_DELAY_SEC * (2 ** (attempt - 1)), MAX_DELAY_SEC)
        # base <= d <= base * 1.25
        assert base <= d <= base * 1.25, f"attempt={attempt} d={d} base={base}"


def test_retry_delay_caps_at_max():
    """attempt 很大时不超过 MAX_DELAY_SEC * 1.25。"""
    d = _retry_delay(100)
    assert d <= MAX_DELAY_SEC * 1.25
    # base 已封顶到 MAX_DELAY_SEC
    assert d >= MAX_DELAY_SEC


def test_retry_delay_jitter_in_range():
    """抖动在 0-25% 之间。"""
    for attempt in range(1, 6):
        d = _retry_delay(attempt)
        base = min(BASE_DELAY_SEC * (2 ** (attempt - 1)), MAX_DELAY_SEC)
        jitter = d - base
        assert 0 <= jitter <= 0.25 * base


# ---------- _is_retryable ----------

def test_is_retryable_protocol_error_no():
    """LLMProtocolError 不可重试(畸形结构,重试没用)。"""
    assert _is_retryable(LLMProtocolError("bad tool_call")) is False


def test_is_retryable_transient_no_cause_yes():
    """LLMTransientError 无 cause → 保守重试。"""
    err = LLMTransientError("boom")
    assert _is_retryable(err) is True


def test_is_retryable_transient_with_connection_error_yes():
    """LLMTransientError 包装 APIConnectionError(无 status_code)→ 重试。"""
    err = LLMTransientError("conn failed")
    err.__cause__ = _FakeConnError("connection refused")
    assert _is_retryable(err) is True


def test_is_retryable_transient_with_429_yes():
    """429 Rate Limit → 重试。用 _FakeStatusError 模拟 openai APIStatusError 的
    status_code 属性(避免在测试里造 httpx.Response 对象)。"""
    err = LLMTransientError("rate")
    err.__cause__ = _FakeStatusError(429)
    assert _is_retryable(err) is True


def test_is_retryable_transient_with_500_yes():
    """5xx → 重试。"""
    err = LLMTransientError("5xx")
    err.__cause__ = _FakeStatusError(503)
    assert _is_retryable(err) is True


def test_is_retryable_transient_with_400_no():
    """400 Bad Request → 不重试(配置/请求问题,重试浪费)。"""
    err = LLMTransientError("400")
    err.__cause__ = _FakeStatusError(400)
    assert _is_retryable(err) is False


def test_is_retryable_transient_with_401_no():
    """401 Unauthorized → 不重试(key 问题,重试没用)。"""
    err = LLMTransientError("401")
    err.__cause__ = _FakeStatusError(401)
    assert _is_retryable(err) is False


def test_is_retryable_generic_exception_no():
    """普通 Exception 不在 LLMError 层级里 → 不重试。"""
    assert _is_retryable(ValueError("huh")) is False


# ---------- call_with_retry ----------

def test_call_with_retry_success_first_try(monkeypatch):
    """第一次就成功,不 sleep。"""
    sleeps: list[float] = []
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: sleeps.append(s))

    result = call_with_retry(lambda: "ok")
    assert result == "ok"
    assert sleeps == []


def test_call_with_retry_success_after_retries(monkeypatch):
    """前 2 次失败(LLMTransientError),第 3 次成功。"""
    sleeps: list[float] = []
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMTransientError("transient")
        return "success"

    result = call_with_retry(fn)
    assert result == "success"
    assert calls["n"] == 3
    assert len(sleeps) == 2  # 失败 2 次,sleep 2 次


def test_call_with_retry_protocol_error_no_retry(monkeypatch):
    """LLMProtocolError 立即抛,不 sleep。"""
    sleeps: list[float] = []
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: sleeps.append(s))

    def fn():
        raise LLMProtocolError("malformed")

    with pytest.raises(LLMProtocolError, match="malformed"):
        call_with_retry(fn)
    assert sleeps == []


def test_call_with_retry_all_attempts_fail(monkeypatch):
    """全部 5 次都失败 → 抛最后一个错,sleep 4 次(最后一次不 sleep)。"""
    sleeps: list[float] = []
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise LLMTransientError(f"fail {calls['n']}")

    with pytest.raises(LLMTransientError, match="fail 5"):
        call_with_retry(fn)
    assert calls["n"] == MAX_RETRIES  # 调了 MAX_RETRIES 次
    # attempt 1-4 失败后 sleep,attempt 5 失败直接抛(不 sleep)
    assert len(sleeps) == MAX_RETRIES - 1


def test_call_with_retry_on_retry_callback(monkeypatch):
    """on_retry 回调被调用,收到 (attempt, err, delay)。"""
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: None)

    calls = {"n": 0}
    callbacks: list[tuple[int, str, float]] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMTransientError(f"err {calls['n']}")
        return "ok"

    def on_retry(attempt, err, delay):
        callbacks.append((attempt, str(err), delay))

    call_with_retry(fn, on_retry=on_retry)
    assert len(callbacks) == 2
    assert callbacks[0][0] == 1
    assert "err 1" in callbacks[0][1]
    assert callbacks[1][0] == 2
    assert "err 2" in callbacks[1][1]
    # delay 是正数
    assert callbacks[0][2] > 0
    assert callbacks[1][2] > 0


def test_call_with_retry_on_retry_callback_exception_ignored(monkeypatch):
    """on_retry 回调自己抛异常,不影响重试流程。"""
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: None)

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise LLMTransientError("err")
        return "ok"

    def bad_on_retry(attempt, err, delay):
        raise RuntimeError("callback bug")

    # 不应该抛
    result = call_with_retry(fn, on_retry=bad_on_retry)
    assert result == "ok"
    assert calls["n"] == 2


def test_call_with_retry_non_retryable_exception_passes_through(monkeypatch):
    """普通 ValueError 不重试,直接抛。"""
    sleeps: list[float] = []
    monkeypatch.setattr("taisang.llm_retry.time.sleep", lambda s: sleeps.append(s))

    def fn():
        raise ValueError("not llm")

    with pytest.raises(ValueError, match="not llm"):
        call_with_retry(fn)
    assert sleeps == []