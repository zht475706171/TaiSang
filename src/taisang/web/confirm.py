"""Web UI 异步确认器。

AgentService.run 是同步阻塞调用,内部调 confirmer(file_path, old, new) -> bool。
CLI chat 路径用 default_confirmer(stdin 阻塞 input),Web UI 不能阻塞主线程,
但 run 跑在线程池里,所以 WebConfirmer 阻塞 run 线程等前端回应是安全的。

机制:
1. WebConfirmer 被调用时,生成 token,emit CONFIRM_REQUEST 事件给前端
2. 阻塞 threading.Event.wait(timeout),run 线程挂起
3. 前端弹卡片,POST /api/sessions/{id}/confirm/{token} {approve: bool}
4. 端点调 WebConfirmer.resolve(token, approve),set event
5. confirmer 返回 approve;超时(默认 30s)返回 False(deny)

每会话一个 WebConfirmer 实例(同时只可能有一个确认在等,因为 AgentService
单线程串行 run;并发同会话 run 由 SessionRegistry 的 Lock 串行化)。
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from ..agent_core.events import CONFIRM_REQUEST


class WebConfirmer:
    """异步确认器:emit CONFIRM_REQUEST → 阻塞 → 前端 POST resolve → 返回。

    __call__ 契约同 default_confirmer: (file_path, old, new) -> bool。
    emit 回调由 SessionRegistry 注入(把事件推到该会话的 EventBroker)。
    """

    def __init__(
        self,
        emit: Callable[[str, dict[str, Any]], None],
        timeout: float = 30.0,
    ) -> None:
        """emit: 推事件到 EventBroker 的回调,签名 (event_type, payload) -> None。"""
        self._emit = emit
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._results: dict[str, bool] = {}

    def __call__(self, file_path: str, old: str, new: str) -> bool:
        """AgentService 调用入口。阻塞当前线程直到前端回应或超时。"""
        token = uuid.uuid4().hex[:12]
        evt = threading.Event()
        with self._lock:
            self._pending[token] = evt
        # 通知前端弹确认卡片
        self._emit(
            CONFIRM_REQUEST,
            {
                "token": token,
                "file_path": file_path,
                "old": old,
                "new": new,
            },
        )
        ok = evt.wait(timeout=self._timeout)
        with self._lock:
            self._pending.pop(token, None)
            result = self._results.pop(token, False)
        return ok and result

    def resolve(self, token: str, approve: bool) -> bool:
        """前端 POST 确认结果时调用。返回 True 表示 token 有效已处理。"""
        with self._lock:
            evt = self._pending.get(token)
            if evt is None:
                return False
            self._results[token] = approve
        evt.set()
        return True
