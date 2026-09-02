"""FastAPI app:本地 Web UI 后端。

路由:
- GET  /                     → serve static/index.html
- POST /api/sessions         → 新建会话,返回 {id, title}
- GET  /api/sessions         → 列会话 [{id, title, active}]
- DELETE /api/sessions/{id}  → 删会话
- POST /api/sessions/{id}/reset   → 重置上下文
- POST /api/sessions/{id}/debug   → 切 debug {on: bool}
- POST /api/sessions/{id}/messages → 发消息 {query},后台 run,事件经 SSE 推
- GET  /api/sessions/{id}/messages → 取会话历史 messages(前端 resume 渲染用)
- GET  /api/sessions/{id}/events   → SSE 流
- POST /api/sessions/{id}/confirm/{token} → {approve: bool} 回应确认
- POST /api/sessions/{id}/permission/{token} → {approve: bool} 回应权限请求

run 跑在线程池(AsyncExitStack + run_in_threadpool),on_event 回调把事件
push 到该会话 EventBroker,SSE 端点从 broker 订阅队列 get + yield。

每会话 per-session Lock 串行化并发 run(AgentService 非 thread-safe)。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .session_registry import SessionRegistry

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class CreateSessionReq(BaseModel):
    title: str = ""


class SendMessageReq(BaseModel):
    query: str


class DebugReq(BaseModel):
    on: bool


class ConfirmReq(BaseModel):
    approve: bool


def create_app(source_root: Path, allow_dirs: list[Path] | None = None) -> FastAPI:
    """构造 FastAPI app。source_root 是 agent 工作目录,allow_dirs 是允许访问的额外目录。"""
    app = FastAPI(title="taisang web")
    registry = SessionRegistry(source_root, allow_dirs=allow_dirs or [])
    # app.state 挂载,方便测试 + lifespan 访问
    app.state.registry = registry

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        idx = _STATIC_DIR / "index.html"
        if not idx.exists():
            raise HTTPException(404, "index.html not found")
        return FileResponse(str(idx))

    @app.post("/api/sessions")
    async def create_session(req: CreateSessionReq) -> dict:
        sid = registry.create(title=req.title)
        return {"id": sid, "title": req.title or sid}

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict]:
        return registry.list_all()

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        ok = registry.delete(session_id)
        return {"deleted": ok}

    @app.post("/api/sessions/{session_id}/reset")
    async def reset_session(session_id: str) -> dict:
        ok = registry.reset(session_id)
        if not ok:
            raise HTTPException(404, f"session not found: {session_id}")
        return {"reset": True}

    @app.post("/api/sessions/{session_id}/debug")
    async def set_debug(session_id: str, req: DebugReq) -> dict:
        ok = registry.set_debug(session_id, req.on)
        if not ok:
            raise HTTPException(404, f"session not found: {session_id}")
        return {"debug": req.on}

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageReq) -> dict:
        """发消息:后台线程跑 agent.run,事件经 SSE 推。立即返回 {ok: true}。

        前端 POST 后立刻去订阅 /events 收事件流。run 异步,不阻塞此响应。
        turn 结束(成功或异常)后更新 meta.json(title=最后 query 前40字)。
        """
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        if sess.lock.locked():
            raise HTTPException(409, "session busy: previous run still active")

        # 后台线程跑 run。on_event 把事件 push 到 broker。
        def _run():
            with sess.lock:
                try:
                    sess.agent.run(
                        req.query,
                        on_event=lambda e: sess.broker.publish(e.type, e.payload),
                    )
                except Exception as e:  # noqa: BLE001
                    log.exception("agent run failed: %s", e)
                    sess.broker.publish("run_error", {"error": f"agent run failed: {e}"})
                finally:
                    # turn 结束更新 meta.json(title=最后 query 前40字)
                    try:
                        registry.update_meta_after_turn(session_id, req.query)
                    except Exception as e:  # noqa: BLE001
                        log.warning("update_meta_after_turn failed: %s", e)
                    # 通知前端更新顶栏 + 会话列表项(title 可能变了)
                    sess.broker.publish(
                        "session_title_updated",
                        {"id": session_id, "title": sess.title},
                    )
                    # run 结束哨兵:前端据此停止 thinking 动画
                    sess.broker.publish("run_end", {})

        asyncio.get_running_loop().run_in_executor(None, _run)
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/messages")
    async def get_messages(session_id: str) -> list[dict]:
        """返回会话历史 messages(给前端 resume 渲染用)。"""
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        return sess.store.load_all()

    @app.get("/api/sessions/{session_id}/events")
    async def event_stream(session_id: str) -> StreamingResponse:
        """SSE 流。订阅 broker,从队列读事件 + yield 编码后的 SSE 字符串。"""
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        q = sess.broker.subscribe()

        async def stream():
            loop = asyncio.get_running_loop()
            try:
                while True:
                    try:
                        evt = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                    except Exception:
                        # 超时发 heartbeat 保活(EventSource 默认 45s 断)
                        yield ": heartbeat\n\n"
                        continue
                    yield _format(evt["type"], evt["payload"])
            finally:
                sess.broker.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/sessions/{session_id}/confirm/{token}")
    async def confirm(session_id: str, token: str, req: ConfirmReq) -> dict:
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        ok = sess.confirmer.resolve(token, req.approve)
        if not ok:
            raise HTTPException(404, "confirm token not found or expired")
        return {"resolved": True}

    @app.post("/api/sessions/{session_id}/permission/{token}")
    async def permission(session_id: str, token: str, req: ConfirmReq) -> dict:
        """前端 POST 回应权限请求(approve/deny)。token 对应一次 permission_request 事件。"""
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        ok = sess.permission.resolve(token, req.approve)
        if not ok:
            raise HTTPException(404, "permission token not found or expired")
        return {"resolved": True}

    return app


def _format(event_type: str, payload: dict[str, Any]) -> str:
    """SSE 编码(同 web/sse.format_sse,内联避免 import 循环风险)。"""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data}\n\n"
