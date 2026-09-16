"""全链路追踪:trace_id + span_id 用 contextvars 贯穿调用链。

trace_id:一个用户请求(turn)的全局唯一 ID,从 HTTP 入口生成。
span_id:链路中某一步的 ID,parent_span_id 串起父子关系。

contextvars 自动在 asyncio task 间隔离传递,函数签名无需加 trace_id 参数。
跨线程边界(如 run_in_executor)需要显式 set,contextvars 默认不跨线程传递。

日志格式器配 %(trace_id)s / %(span_id)s 输出,_TraceFilter 给所有 LogRecord
补默认值 "-",避免 KeyError。
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger(__name__)

# contextvar:未 set 时返回默认值 "-"
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="-"
)
span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "span_id", default="-"
)
parent_span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "parent_span_id", default="-"
)


def new_trace_id() -> str:
    """生成 16 位 trace_id(无连字符,日志里更紧凑)。"""
    return uuid.uuid4().hex[:16]


def new_span_id() -> str:
    """生成 8 位 span_id。"""
    return uuid.uuid4().hex[:8]


@contextmanager
def span(name: str, **fields) -> Iterator[str]:
    """记一个 span:开始 + 结束日志,带 duration_ms。

    用法:
        with span("LLM call", model="deepseek-chat") as sid:
            ...

    parent_span_id 自动从 contextvar 取,span_id 期间在 contextvar 里 set,
    退出时 reset。异常路径也 reset(用 try/finally)。

    trace_id/span_id/parent_span_id 不在 extra 里传,由 cli.main 的
    LogRecordFactory 从 contextvar 自动补到 record;extra 只放业务字段。
    """
    sid = new_span_id()
    # 先 set span_id,再记 start 日志,这样 factory 会把新 span_id 写进 record
    token_span = span_id_var.set(sid)
    token_parent = parent_span_id_var.set(sid)  # 嵌套 span 用
    t0 = time.perf_counter()
    log.info(
        "span start: %s",
        name,
        extra={
            "span_name": name,
            **fields,
        },
    )
    try:
        yield sid
    finally:
        duration_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "span end: %s (%.1fms)",
            name,
            duration_ms,
            extra={
                "span_name": name,
                "duration_ms": round(duration_ms, 1),
                **fields,
            },
        )
        span_id_var.reset(token_span)
        parent_span_id_var.reset(token_parent)


class TraceLogFilter(logging.Filter):
    """给所有 LogRecord 补 trace_id/span_id 字段(默认取 contextvar)。

    formatter 用 %(trace_id)s / %(span_id)s 时,未 set 的 record 不会 KeyError。
    已有字段的 record(record 直接 extra={"trace_id":...})不覆盖。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = trace_id_var.get()
        if not hasattr(record, "span_id"):
            record.span_id = span_id_var.get()
        if not hasattr(record, "parent_span_id"):
            record.parent_span_id = parent_span_id_var.get()
        return True