"""trace 模块单元测试:contextvar 贯穿 + span 嵌套 + 跨线程边界。"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from taisang.agent_core.trace import (
    TraceLogFilter,
    new_span_id,
    new_trace_id,
    parent_span_id_var,
    span,
    span_id_var,
    trace_id_var,
)


def test_new_trace_id_16_chars():
    tid = new_trace_id()
    assert len(tid) == 16
    # hex only
    assert all(c in "0123456789abcdef" for c in tid)


def test_new_trace_id_unique():
    ids = {new_trace_id() for _ in range(100)}
    assert len(ids) == 100


def test_new_span_id_8_chars():
    sid = new_span_id()
    assert len(sid) == 8


def test_contextvar_default_is_dash():
    assert trace_id_var.get() == "-"
    assert span_id_var.get() == "-"
    assert parent_span_id_var.get() == "-"


def test_span_sets_span_id_during_context():
    with span("test") as sid:
        assert span_id_var.get() == sid
        # parent_span_id 也被 set 为 sid(支持嵌套)
        assert parent_span_id_var.get() == sid


def test_span_resets_on_normal_exit():
    span_id_before = span_id_var.get()
    parent_before = parent_span_id_var.get()
    with span("test"):
        pass
    assert span_id_var.get() == span_id_before
    assert parent_span_id_var.get() == parent_before


def test_span_resets_on_exception():
    span_id_before = span_id_var.get()
    with pytest.raises(RuntimeError):
        with span("test"):
            raise RuntimeError("boom")
    assert span_id_var.get() == span_id_before


def test_nested_span_parent_chain():
    """嵌套 span:内层 parent_span_id 应等于外层 span_id(在 span 期间)。"""
    with span("outer") as outer_sid:
        # 在 outer 期间,parent_span_id_var 应该是 outer_sid
        assert parent_span_id_var.get() == outer_sid
        with span("inner") as inner_sid:
            # 内层 span 期间,span_id = inner,parent_span_id_var = inner
            assert span_id_var.get() == inner_sid
            assert parent_span_id_var.get() == inner_sid
        # 退出 inner 后,恢复到 outer
        assert span_id_var.get() == outer_sid
        assert parent_span_id_var.get() == outer_sid


def test_trace_id_propagates_into_span():
    """set trace_id 后,span 内的日志/读取都能拿到。"""
    token = trace_id_var.set("mytrace12345678")
    try:
        with span("op"):
            assert trace_id_var.get() == "mytrace12345678"
    finally:
        trace_id_var.reset(token)
    assert trace_id_var.get() == "-"


def test_trace_id_does_not_leak_between_threads():
    """contextvars 不跨线程:主线程 set trace_id,新 Thread 默认看不到。

    threading.Thread 不会自动 copy 父线程的 contextvar(除非显式用
    contextvars.copy_context().run())。这正是 app.py 跨 executor 时
    必须显式 set trace_id 的原因。
    """
    token = trace_id_var.set("mainthread0001")
    try:
        result = {}

        def _worker():
            result["worker_trace"] = trace_id_var.get()

        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        # 新线程默认看到 contextvar 的 default "-",不是主线程 set 的值
        assert result["worker_trace"] == "-", (
            "新线程不应继承主线程 set 的 contextvar; "
            "跨线程必须显式 set(如 app.py 的 _run)"
        )
    finally:
        trace_id_var.reset(token)


def test_executor_thread_does_not_see_post_set_trace_id():
    """ThreadPoolExecutor:线程池里的线程看不到主线程 set 之后的值。

    这是 contextvars 跨线程的关键限制——set 在主线程不会传播到
    已经在 executor 里的工作线程。app.py 的 _run_next 通过显式 set
    在 _run 内重新设 trace_id 来解决这个限制。
    """
    pool = ThreadPoolExecutor(max_workers=1)

    # 先 warm up 一个线程,让它进入池里
    pool.submit(lambda: None).result()

    # 主线程 set trace_id(线程池里的线程看不到)
    token = trace_id_var.set("postset000001234")
    try:
        future = pool.submit(lambda: trace_id_var.get())
        worker_val = future.result()
        # 工作线程要么看到默认 "-"
        assert worker_val != "postset000001234", (
            "executor 线程不应看到主线程 set 之后的 trace_id; "
            "app.py 必须在 _run 内显式 set"
        )
    finally:
        trace_id_var.reset(token)
        pool.shutdown()


def test_trace_log_filter_fills_defaults():
    """TraceLogFilter 给未设字段的 record 补默认值。"""
    import logging as _logging

    record = _logging.LogRecord(
        name="test",
        level=_logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    # 未设字段时 filter 补 contextvar 当前值
    filt = TraceLogFilter()
    assert filt.filter(record) is True
    assert record.trace_id == trace_id_var.get()
    assert record.span_id == span_id_var.get()


def test_trace_log_filter_does_not_overwrite_existing():
    """record 已设字段时 filter 不覆盖。"""
    import logging as _logging

    record = _logging.LogRecord(
        name="test",
        level=_logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.trace_id = "preset1234567890"
    record.span_id = "preset12"
    filt = TraceLogFilter()
    filt.filter(record)
    assert record.trace_id == "preset1234567890"
    assert record.span_id == "preset12"