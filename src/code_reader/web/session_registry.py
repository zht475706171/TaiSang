"""会话注册表:session_id → AgentService 实例 + EventBroker + WebConfirmer。

多会话隔离:
- 每会话一个 AgentService 实例(ctx / compaction_state / token 计数器实例级隔离)
- session_memory 按 session_id 落到 .code-reader/sessions/<id>/session-memory/
- EventBroker 每会话一个,SSE 流隔离
- WebConfirmer 每会话一个,emit 回调注入到该会话的 EventBroker

会话列表 = 扫 .code-reader/sessions/*/ 目录 + 内存活跃实例(二者并集)。
内存实例可能因重启丢失,但磁盘目录还在,重启后 list_all 仍能列出来
(打开旧会话时 lazy 重建 AgentService 实例)。

并发:AgentService 非 thread-safe,同会话并发 run 用 per-session Lock 串行化。
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..agent_core.service import AgentService
from ..config import load_config
from ..llm_client import LLMClient, MockLLM
from ..session_memory.service import SessionMemoryService
from ..storage.paths import PathManager
from .confirm import WebConfirmer
from .sse import EventBroker


@dataclass
class _Session:
    """单个会话的运行时态:AgentService + 事件总线 + 确认器 + 并发锁。"""

    session_id: str
    agent: AgentService
    broker: EventBroker
    confirmer: WebConfirmer
    lock: threading.Lock = field(default_factory=threading.Lock)
    title: str = ""  # 显示名;首版用首句截断或时间戳


class SessionRegistry:
    """会话注册表。单例语义(一个 web 进程一个 registry)。"""

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.resolve()
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def _make_llm(self) -> LLMClient | MockLLM:
        """同 cli/main.py._make_llm:env 控制 MockLLM,否则真 LLM。"""
        if os.environ.get("CODE_READER_MOCK_LLM") == "1":
            from ..llm_client import LLMResponse

            return MockLLM([LLMResponse(text="(mock) ok", tool_calls=[])] * 50)
        cfg = load_config()
        return LLMClient(cfg)

    def _build_session(self, session_id: str) -> _Session:
        """构造一个 _Session(AgentService + broker + confirmer 串起来)。"""
        broker = EventBroker()
        # WebConfirmer 的 emit 回调:推到本会话 broker
        confirmer = WebConfirmer(emit=broker.publish)
        llm = self._make_llm()
        session_mem = SessionMemoryService(
            llm=llm,
            memory_path=PathManager.session_memory_path(self.source_root, session_id),
        )
        session_mem.ensure_file()
        agent = AgentService(
            llm=llm,
            source_root=self.source_root,
            confirmer=confirmer,
            session_memory=session_mem,
        )
        return _Session(session_id=session_id, agent=agent, broker=broker, confirmer=confirmer)

    def create(self, title: str = "") -> str:
        """新建会话,返回 session_id。落盘 sessions/<id>/ 目录。"""
        session_id = uuid.uuid4().hex[:8]
        sess = self._build_session(session_id)
        sess.title = title or session_id
        with self._lock:
            self._sessions[session_id] = sess
        return session_id

    def get_or_load(self, session_id: str) -> _Session | None:
        """取会话。内存没有但磁盘有目录则 lazy 重建;都没有返回 None。"""
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is not None:
            return sess
        # 磁盘有目录则 lazy 重建(重启后恢复历史会话)
        sess_dir = self.source_root / ".code-reader" / "sessions" / session_id
        if not sess_dir.is_dir():
            return None
        sess = self._build_session(session_id)
        sess.title = session_id
        with self._lock:
            # 并发下可能已被另一线程建了,保留先到那个
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing
            self._sessions[session_id] = sess
        return sess

    def list_all(self) -> list[dict]:
        """列会话(内存 + 磁盘并集),返回 [{id, title, active}],按 id 倒序。"""
        # 磁盘会话
        sessions_dir = self.source_root / ".code-reader" / "sessions"
        disk_ids: set[str] = set()
        if sessions_dir.is_dir():
            for p in sessions_dir.iterdir():
                if p.is_dir():
                    disk_ids.add(p.name)
        # 内存会话
        with self._lock:
            mem_items = list(self._sessions.items())
        mem_ids = {sid for sid, _ in mem_items}
        all_ids = disk_ids | mem_ids
        result = []
        for sid in sorted(all_ids, reverse=True):
            with self._lock:
                sess = self._sessions.get(sid)
            title = sess.title if sess is not None else sid
            result.append({"id": sid, "title": title, "active": sess is not None})
        return result

    def delete(self, session_id: str) -> bool:
        """删会话:内存移除 + 磁盘目录删除。返回是否删过。"""
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
        sess_dir = self.source_root / ".code-reader" / "sessions" / session_id
        if sess_dir.is_dir():
            import shutil

            shutil.rmtree(sess_dir, ignore_errors=True)
            existed = True
        return existed

    def reset(self, session_id: str) -> bool:
        """重置会话上下文(AgentService.reset)。返回会话是否存在。"""
        sess = self.get_or_load(session_id)
        if sess is None:
            return False
        sess.agent.reset()
        return True

    def set_debug(self, session_id: str, on: bool) -> bool:
        sess = self.get_or_load(session_id)
        if sess is None:
            return False
        sess.agent.set_debug(on)
        return True
