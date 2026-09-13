"""Web UI 异步确认器。

AgentService.run 是同步阻塞调用,内部调 confirmer(file_path, old, new) -> bool。
CLI chat 路径用 default_confirmer(stdin 阻塞 input),Web UI 不能阻塞主线程,
但 run 跑在线程池里,所以 WebConfirmer 阻塞 run 线程等前端回应是安全的。

机制:
1. WebConfirmer 被调用时,生成 token,emit CONFIRM_REQUEST 事件给前端
2. 阻塞 threading.Event.wait(timeout),run 线程挂起
3. 前端弹卡片,POST /api/sessions/{id}/confirm/{token} {approve: bool}
4. 端点调 WebConfirmer.resolve(token, approve),set event
5. confirmer 返回 approve;timeout=None 永久阻塞(靠 force_deny_all / interrupt / delete 唤醒)

每会话一个 WebConfirmer 实例(同时只可能有一个确认在等,因为 AgentService
单线程串行 run;并发同会话 run 由 SessionRegistry 的 Lock 串行化)。

切 session 不丢卡片:payload 存 _pending_payload,前端切回时 GET /pending 恢复。
死锁消除:delete/interrupt 调 force_deny_all 唤醒阻塞线程,让其跑完释放 lock。
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
        timeout: float | None = None,
    ) -> None:
        """emit: 推事件到 EventBroker 的回调,签名 (event_type, payload) -> None。
        timeout: None(默认)= 永久阻塞,靠 force_deny_all / interrupt / delete 唤醒;
                 传具体秒数则超时自动 deny(向后兼容现有测试)。
        """
        self._emit = emit
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._results: dict[str, bool] = {}
        # 当前阻塞中的 confirm payload(含 token),供 GET /pending 恢复卡片用。
        # 同时只可能有一个 pending(AgentService 单线程串行),用 dict 便于 force_deny_all 快照。
        self._pending_payload: dict[str, dict[str, Any]] = {}

    def __call__(self, file_path: str, old: str, new: str) -> bool:
        """AgentService 调用入口。阻塞当前线程直到前端回应或被 force_deny_all 唤醒。"""
        token = uuid.uuid4().hex[:12]
        evt = threading.Event()
        payload = {"token": token, "file_path": file_path, "old": old, "new": new}
        with self._lock:
            self._pending[token] = evt
            self._pending_payload[token] = payload
        # 通知前端弹确认卡片
        self._emit(CONFIRM_REQUEST, payload)
        evt.wait(timeout=self._timeout)
        with self._lock:
            self._pending.pop(token, None)
            self._pending_payload.pop(token, None)
            result = self._results.pop(token, False)
        return result

    def resolve(self, token: str, approve: bool) -> bool:
        """前端 POST 确认结果时调用。返回 True 表示 token 有效已处理。"""
        with self._lock:
            evt = self._pending.get(token)
            if evt is None:
                return False
            self._results[token] = approve
        evt.set()
        return True

    def get_pending_payload(self) -> dict[str, Any] | None:
        """返回当前阻塞中的 confirm payload(含 token),无则 None。

        供 GET /api/sessions/{id}/pending 查询,前端切回 session 时恢复卡片。
        """
        with self._lock:
            if not self._pending_payload:
                return None
            # 同时只有一个 pending,返回它的副本
            return dict(next(iter(self._pending_payload.values())))

    def force_deny_all(self) -> None:
        """强制把所有 pending confirm 置为 deny 并唤醒阻塞线程。

        用途:delete/interrupt 收尾——run 线程卡在 confirm 阻塞,
        force_deny 唤醒它 → confirm 返回 False → 工具 denied → run 继续 →
        下个检查点 cancel_event 生效 / 跑完释放 lock。
        """
        with self._lock:
            tokens = list(self._pending.keys())
        for token in tokens:
            self.resolve(token, False)