"""FastAPI app:本地 Web UI 后端。

路由:
- GET  /                     → serve static/index.html
- POST /api/sessions         → 新建会话,返回 {id, title}
- GET  /api/sessions         → 列会话 [{id, title, active}]
- DELETE /api/sessions/{id}  → 删会话
- POST /api/sessions/{id}/reset   → 重置上下文
- POST /api/sessions/{id}/reset   → 重置上下文
- POST /api/sessions/{id}/debug   → 切 debug {on: bool}(已废弃,debug 改全局配置)
- POST /api/sessions/{id}/messages → 发消息 {query},后台 run,事件经 SSE 推
- GET  /api/sessions/{id}/messages → 取会话历史 messages(前端 resume 渲染用)
- GET  /api/sessions/{id}/info     → 取会话元信息(source_root 当前工作目录)
- POST /api/sessions/{id}/pick-directory  → 弹系统目录选择器(Windows tkinter)
- POST /api/sessions/{id}/switch-directory → 切换会话工作目录 {path}
- GET  /api/sessions/{id}/events   → SSE 流
- POST /api/sessions/{id}/confirm/{token} → {approve: bool} 回应确认
- POST /api/sessions/{id}/permission/{token} → {approve: bool} 回应权限请求
- GET  /api/config           → 取 LLM 配置(api_key 打码 + debug)
- POST /api/config           → 保存 LLM 配置 + debug + 立即应用到所有 session
- POST /api/config/test      → 测试 LLM 连通性(不持久化)

run 跑在线程池(AsyncExitStack + run_in_threadpool),on_event 回调把事件
push 到该会话 EventBroker,SSE 端点从 broker 订阅队列 get + yield。

每会话 per-session Lock 串行化并发 run(AgentService 非 thread-safe)。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import LLMConfig, load_config, mask_api_key, save_config
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


class ConfigReq(BaseModel):
    model: str
    api_key: str
    base_url: str
    debug: bool = False


class ConfigTestReq(BaseModel):
    """测试连接请求体。

    api_key = "__unchanged__" 表示用已存的 api_key(前端 readonly 提交这个 sentinel),
    否则用表单传入的明文。
    """

    model: str
    api_key: str
    base_url: str


class SwitchDirReq(BaseModel):
    """切换会话当前工作目录请求体。path 是用户通过目录选择器选定的绝对路径。"""

    path: str


def create_app(source_root: Path, allow_dirs: list[Path] | None = None) -> FastAPI:
    """构造 FastAPI app。source_root 是 agent 工作目录,allow_dirs 是允许访问的额外目录。"""
    registry = SessionRegistry(source_root, allow_dirs=allow_dirs or [])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时后台连接所有 enabled MCP server。
        # 用 create_task 而非 asyncio.run(同步阻塞):mcp SDK 1.x + anyio 在 stdio
        # 子进程启动失败时,async generator(stdio_client)在临时事件循环 shutdown
        # 阶段被 GC 清理,触发 anyio TaskGroup cancel scope 跨 task 退出抛 RuntimeError,
        # 这个异常在 asyncio 内部 Task 里抛,except 接不到,导致 asyncio.run 非零退出
        # 阻断服务启动。lifespan 在 FastAPI 主事件循环里 create_task,MCP 连接跑在
        # 主循环 task 上下文,失败时 connect_server 内部 except 已记 failed 状态,
        # 不阻断服务。失败的 server 前端 /mcp 页能看到,用户可手动重连。
        mcp_manager = registry._mcp_manager
        connect_task = asyncio.create_task(mcp_manager.connect_all())
        # 不 await:fire-and-forget,服务立即就绪,MCP 在后台连
        yield
        # shutdown:cancel 后台连接任务(若还在跑),避免 lingering task
        connect_task.cancel()
        try:
            await connect_task
        except (asyncio.CancelledError, Exception):
            pass

    app = FastAPI(title="taisang web", lifespan=lifespan)
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
        if not ok:
            # delete 返回 False 两种情况:run 卡死超时 / 会话本就不存在。
            # 再查一次:还在 → 409 busy;没了 → 幂等成功(前端照常移除)。
            if registry.get_or_load(session_id) is not None:
                raise HTTPException(409, "session busy: run still active, try again later")
        return {"deleted": True}

    @app.post("/api/sessions/{session_id}/reset")
    async def reset_session(session_id: str) -> dict:
        ok = registry.reset(session_id)
        if not ok:
            raise HTTPException(404, f"session not found: {session_id}")
        return {"reset": True}

    @app.post("/api/sessions/{session_id}/debug")
    async def set_debug(session_id: str, req: DebugReq) -> dict:
        """per-session debug toggle(已废弃,debug 改全局配置)。

        保留路由向后兼容旧前端,实际不动 session debug 状态。新前端走
        POST /api/config 的 debug 字段统一管理。
        """
        return {"debug": req.on, "deprecated": True}

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
                        # Task 14: 把 agent_id 合并进 payload,前端据 agent_id 路由子事件到
                        # 对应的 Agent 工具卡片嵌套数组。主 agent 的 agent_id="" 不影响路由。
                        on_event=lambda e: sess.broker.publish(
                            e.type, {**e.payload, "agent_id": e.agent_id}
                        ),
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

    @app.get("/api/sessions/{session_id}/info")
    async def get_session_info(session_id: str) -> dict:
        """返回会话元信息:当前工作目录 source_root。

        前端打开会话时调此接口拿 source_root 展示在输入栏上方。优先内存 sess.source_root
        (switch 后立即生效),其次 meta.json,最后 registry.source_root(全局默认)。
        """
        if registry.get_or_load(session_id) is None:
            raise HTTPException(404, f"session not found: {session_id}")
        sr = registry.get_source_root(session_id)
        return {"id": session_id, "source_root": str(sr) if sr else None}

    @app.post("/api/sessions/{session_id}/pick-directory")
    async def pick_directory(session_id: str) -> dict:
        """弹出系统目录选择器(Windows tkinter askdirectory),返回用户选定目录。

        用 run_in_executor 跑 tkinter(阻塞调用),不卡 asyncio 事件循环。
        用户取消返回 {cancelled: true};选定返回 {path: "..."}。
        session 不存在返回 404。tkinter 仅 Windows 兼容,非 Windows 返回 501。
        """
        if registry.get_or_load(session_id) is None:
            raise HTTPException(404, f"session not found: {session_id}")
        import sys

        if sys.platform != "win32":
            raise HTTPException(501, "directory picker only supported on Windows")

        def _pick() -> str | None:
            # tkinter 必须在主线程外跑;run_in_executor 用默认线程池,可满足。
            # 临时创建 + 销毁 Tk root,不污染进程全局 state。
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                path = filedialog.askdirectory(
                    title="选择项目目录",
                    parent=root,
                )
                return path or None
            finally:
                root.destroy()

        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _pick)
        if not path:
            return {"cancelled": True}
        return {"path": path}

    @app.post("/api/sessions/{session_id}/switch-directory")
    async def switch_directory(session_id: str, req: SwitchDirReq) -> dict:
        """切换会话当前工作目录到 req.path。

        调 registry.switch_source_root:更新 agent.source_root + permission.approve_dir
        + shell._cwd + _kill_and_restart + meta.json source_root。旧目录保留在
        permission._approved,用户切回还能访问。
        """
        if registry.get_or_load(session_id) is None:
            raise HTTPException(404, f"session not found: {session_id}")
        new_root = Path(req.path)
        if not new_root.is_dir():
            raise HTTPException(400, f"directory not found or not a directory: {req.path}")
        ok = registry.switch_source_root(session_id, new_root)
        if not ok:
            raise HTTPException(500, "switch failed")
        return {"ok": True, "source_root": str(new_root.resolve())}

    @app.get("/api/config")
    async def get_config() -> dict:
        """返回当前 LLM 配置。api_key 打码。"""
        cfg = load_config()
        return {
            "model": cfg.model,
            "base_url": cfg.base_url,
            "api_key": mask_api_key(cfg.api_key),
            "api_key_set": bool(cfg.api_key),
            "debug": cfg.debug,
        }

    @app.post("/api/config")
    async def save_config_route(req: ConfigReq) -> dict:
        """保存 LLM 配置 + 立即应用到所有 session。

        api_key = "__unchanged__" 时保留原 api_key(前端 readonly 提交这个 sentinel)。
        debug 字段一并持久化 + 应用到所有 session。
        """
        if req.api_key == "__unchanged__":
            old_cfg = load_config()
            api_key = old_cfg.api_key
        else:
            api_key = req.api_key
        cfg = LLMConfig(model=req.model, api_key=api_key, base_url=req.base_url, debug=req.debug)
        save_config(cfg)
        registry.apply_llm_config(cfg)
        return {"ok": True}

    @app.post("/api/config/test")
    async def test_config_route(req: ConfigTestReq) -> dict:
        """测试 LLM 连通性。用表单传入的 model/api_key/base_url 临时构造 client,
        发一个最小请求(messages=[{role:user, content:"hello"}],无 system prompt,
        无 tools,max_tokens=5),返回 {ok, latency_ms, reply} 或 {ok:false, error}。

        api_key = "__unchanged__" 时用已存的 api_key(前端 readonly 提交这个 sentinel)。
        不持久化任何配置,纯探测。
        """
        import time

        from ..llm_client import LLMClient
        from ..llm_errors import LLMError

        if req.api_key == "__unchanged__":
            old_cfg = load_config()
            api_key = old_cfg.api_key
        else:
            api_key = req.api_key
        probe_cfg = LLMConfig(model=req.model, api_key=api_key, base_url=req.base_url, debug=False)
        t0 = time.perf_counter()
        try:
            client = LLMClient(probe_cfg)
            resp = client.chat(messages=[{"role": "user", "content": "hello"}], tools=[])
        except LLMError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 — 任意未知错误也归为失败
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms, "reply": (resp.text or "")[:200]}

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

    @app.post("/api/sessions/{session_id}/interrupt")
    async def interrupt_session(session_id: str) -> dict:
        """请求中断当前 turn。set agent._cancel_event。

        幂等:turn 已结束或未开始时调用无副作用(返回 interrupted=False)。
        并发安全:threading.Event.set() thread-safe。
        不等中断生效就返回:前端通过 FINAL_ANSWER(interrupted=True) 事件知道中断生效。
        """
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        if not sess.lock.locked():
            return {"ok": True, "interrupted": False}
        sess.agent.interrupt()
        return {"ok": True, "interrupted": True}

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

    from .skills_api import register_skills_routes

    register_skills_routes(app, source_root)

    from .agents_api import register_agents_routes

    register_agents_routes(app, source_root)

    from .prompts_api import register_prompts_routes

    register_prompts_routes(app, registry)

    from .profile_api import register_profile_routes

    register_profile_routes(app)

    from .mcp_api import router as mcp_router

    app.include_router(mcp_router)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        """SPA fallback:非 /api、非 /static 的未知 GET 路径回 index.html。

        前端用 history 路由(/chat/:id、/skills),刷新或直链时服务端必须回
        index.html 让 vue-router 接管,否则 404。api/static 前缀仍走 404。
        """
        if full_path.startswith(("api/", "static/")):
            raise HTTPException(404, "not found")
        idx = _STATIC_DIR / "index.html"
        if not idx.exists():
            raise HTTPException(404, "index.html not found")
        return FileResponse(str(idx))

    return app


def _format(event_type: str, payload: dict[str, Any]) -> str:
    """SSE 编码(同 web/sse.format_sse,内联避免 import 循环风险)。"""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data}\n\n"
