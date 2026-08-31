"""SSE(Server-Sent Events)编码工具。

把 AgentEvent 编码成 `text/event-stream` 格式行:
    event: <type>\n
    data: <json>\n\n

每会话一个 threading.Queue,AgentService.on_event 回调 push 事件,
GET /events 端点从队列读 + yield 编码后的字符串。
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any


def format_sse(event_type: str, data: dict[str, Any]) -> str:
    """编码一条 SSE 事件。

    event_type 写到 `event:` 行,前端 EventSource 用 addEventListener(type, ...) 分发。
    data 序列化成单行 JSON(multiline data 需要多行 `data:`,这里一条够用)。
    返回的字符串已含末尾空行,直接 yield 即可。
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


class EventBroker:
    """每会话一个事件队列 + 多 SSE 订阅者支持。

    设计:
    - 一个会话可能有多个 SSE 订阅者(用户开了多个 tab,或断线重连后旧连接还在)。
      用 broadcast 模式:每个订阅者一个独立 queue,publish 时往所有队列 push。
    - 订阅者断开时 unsubscribe 清理,避免内存泄漏。
    - 队列无上限(单会话事件量小;极端情况 OOM 风险可接受,后续可加上限)。
    """

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        """新建一个订阅队列,返回它。SSE 端点从它 get(timeout=...) 取事件。"""
        q: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        """订阅者断开时清理。"""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """向所有订阅者 push 一条事件。AgentService.on_event 回调调本方法。"""
        evt = {"type": event_type, "payload": payload}
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(evt)
