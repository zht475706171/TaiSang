"""会话注册表:session_id → AgentService 实例 + EventBroker + WebConfirmer。

多会话隔离:
- 每会话一个 AgentService 实例(ctx / compaction_state / token 计数器实例级隔离)
- session_memory 按 session_id 落到 .taisang/sessions/<id>/session-memory/
- EventBroker 每会话一个,SSE 流隔离
- WebConfirmer 每会话一个,emit 回调注入到该会话的 EventBroker

会话列表 = 扫 .taisang/sessions/*/ 目录 + 内存活跃实例(二者并集)。
内存实例可能因重启丢失,但磁盘目录还在,重启后 list_all 仍能列出来
(打开旧会话时 lazy 重建 AgentService 实例)。

并发:AgentService 非 thread-safe,同会话并发 run 用 per-session Lock 串行化。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..agent_core.permission import WebPermissionManager
from ..agent_core.service import AgentService
from ..config import LLMConfig, load_config
from ..llm_client import LLMClient, MockLLM
from ..session_memory.service import SessionMemoryService
from ..storage.conversation_store import ConversationStore
from ..storage.paths import PathManager
from .confirm import WebConfirmer
from .mcp_api import get_mcp_manager
from .skills_api import load_skills_with_state
from .sse import EventBroker


@dataclass
class _Session:
    """单个会话的运行时态:AgentService + 事件总线 + 确认器 + 权限器 + 并发锁。"""

    session_id: str
    agent: AgentService
    broker: EventBroker
    confirmer: WebConfirmer
    permission: WebPermissionManager
    store: ConversationStore
    lock: threading.Lock = field(default_factory=threading.Lock)
    title: str = ""  # 空 → 首条消息发出时自动取 query 前 40 字
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_root: Path = None  # 当前工作目录(可被 switch_source_root 切换;None 时 fallback 到 registry.source_root)


class SessionRegistry:
    """会话注册表。单例语义(一个 web 进程一个 registry)。"""

    def __init__(self, source_root: Path, allow_dirs: list[Path] | None = None) -> None:
        self.source_root = source_root.resolve()
        self.allow_dirs = allow_dirs or []
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        # MCPManager:进程级单例,启动时连接所有 enabled server。
        # 无 enabled server 时 connect_all 是 no-op;连接失败的 server 标 failed 不阻塞。
        # 用 mcp_api.get_mcp_manager() 拿模块级单例,保证 API 路由和 agent 用同一个 manager。
        self._mcp_manager = get_mcp_manager()
        asyncio.run(self._mcp_manager.connect_all())

    def _make_llm(self) -> LLMClient | MockLLM:
        """同 cli/main.py._make_llm:env 控制 MockLLM,否则真 LLM。"""
        if os.environ.get("TAISANG_MOCK_LLM") == "1":
            from ..llm_client import LLMResponse

            return MockLLM([LLMResponse(text="(mock) ok", tool_calls=[])] * 50)
        cfg = load_config()
        return LLMClient(cfg)

    def _build_session(self, session_id: str) -> _Session:
        """构造一个 _Session(AgentService + broker + confirmer + permission 串起来)。"""
        broker = EventBroker()
        # WebConfirmer 的 emit 回调:推到本会话 broker
        confirmer = WebConfirmer(emit=broker.publish)
        # WebPermissionManager 同样 emit 到本会话 broker,前端弹权限卡片
        permission = WebPermissionManager(
            emit=broker.publish,
            initial_dirs=[self.source_root] + self.allow_dirs,
        )
        llm = self._make_llm()
        cfg = load_config()
        session_mem = SessionMemoryService(
            llm=llm,
            memory_path=PathManager.session_memory_path(self.source_root, session_id),
        )
        # ConversationStore + on_append 回调:ctx 每次 append 同步写 jsonl
        sessions_dir = self.source_root / ".taisang" / "sessions"
        store = ConversationStore(session_id=session_id, sessions_dir=sessions_dir)
        # 不在启动时 ensure_file:让 should_extract 的 init 分支(10000 token)
        # 自己创建笔记。否则笔记一开始就存在,init 分支永远走不到,
        # 直接走 update 分支(5000 token)门槛太低。extract worker 里有 ensure_file。
        # Skill 加载:user_dirs(~/.taisang/skills 默认)+ project_dirs(配置的)
        # 再拼上 source_root/.taisang/skills(项目级,自动,不用用户配)。
        # 用 skills_api 的共享 helper:同时应用 skills_state.json 的 disabled
        # 状态,保证 UI 上的开关对新会话的 agent 生效。
        skills = load_skills_with_state(self.source_root)
        # Agent 加载:三源(user/project/system) + agents_state.json 的 disabled 状态
        # 跟 skill 同构,用 agents.loader 的共享 helper
        from ..agents.loader import load_agents_with_state
        agents = load_agents_with_state(self.source_root)
        agent = AgentService(
            llm=llm,
            source_root=self.source_root,
            confirmer=confirmer,
            session_memory=session_mem,
            permission=permission,
            allow_dirs=[self.source_root] + self.allow_dirs,
            on_append=store.append,
            skills=skills,
            mcp_manager=self._mcp_manager,
            agents=agents,
            debug=cfg.debug,
        )
        return _Session(
            session_id=session_id,
            agent=agent,
            broker=broker,
            confirmer=confirmer,
            permission=permission,
            store=store,
            source_root=self.source_root,
        )

    def create(self, title: str = "") -> str:
        """新建会话,返回 session_id。落盘 sessions/<id>/ 目录。

        title 留空 → 前端显示"新会话",首条消息发出时由
        set_title_from_query 自动取 query 前 40 字替换。
        """
        session_id = uuid.uuid4().hex[:8]
        sess = self._build_session(session_id)
        sess.title = title  # 空就是空,不 fallback 到 id
        with self._lock:
            self._sessions[session_id] = sess
        return session_id

    def set_title_from_query(self, session_id: str, query: str) -> bool:
        """首条消息发出时调:若当前 title 为空,取 query 前 40 字作 title。

        避免会话列表全是 id — 像 ChatGPT/Claude 那样用首句作标题。
        已有非空 title 时不覆盖(用户可能手动设过或已自动生成过)。
        """
        sess = self.get_or_load(session_id)
        if sess is None:
            return False
        if sess.title:  # 已有 title,不覆盖
            return False
        # 取首句(按换行/句号切),截 40 字,去空白
        first_line = query.strip().split("\n")[0].strip()
        if len(first_line) > 40:
            first_line = first_line[:40] + "…"
        sess.title = first_line or "新会话"
        sess.updated_at = time.time()
        return True

    def get_or_load(self, session_id: str) -> _Session | None:
        """取会话。内存没有但磁盘有目录则 lazy 重建;都没有返回 None。

        lazy 重建时从 conversation.jsonl 读历史灌回 ctx(resume)。
        """
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is not None:
            return sess
        # 磁盘有目录则 lazy 重建(重启后恢复历史会话)
        sess_dir = self.source_root / ".taisang" / "sessions" / session_id
        if not sess_dir.is_dir():
            return None
        sess = self._build_session(session_id)
        # 从 jsonl 灌回历史到 ctx(resume)
        records = sess.store.load_all()
        if records:
            sess.agent.ctx.load_from_records(records)
            # 重建 todos:扫最后一条 TodoWrite tool_call,把它的 args.todos 灌回 service.todos。
            # TodoWrite 是普通 tool_call,observation 自然在 jsonl 里,不需要额外建表。
            sess.agent.todos = _reconstruct_todos(records)
        # title 优先从 meta.json 读(重启后恢复动态 title);meta 不存在才 fallback id
        meta = sess.store.load_meta()
        if meta is not None and meta.get("title"):
            sess.title = meta["title"]
        else:
            sess.title = session_id
        # resume source_root:meta.json 有 source_root 就切到该目录(用户上次导入的项目)
        if meta is not None and meta.get("source_root"):
            try:
                sr = Path(meta["source_root"])
                if sr.is_dir():
                    sess.agent.source_root = sr.resolve()
                    sess.agent.permission.approve_dir(sr.resolve())
                    if hasattr(sess.agent.shell, "_cwd"):
                        sess.agent.shell._cwd = sr.resolve()
                        try:
                            sess.agent.shell._kill_and_restart()
                        except Exception:  # noqa: BLE001
                            pass
                    sess.source_root = sr.resolve()
            except (OSError, ValueError):
                pass  # 路径无效,fallback 到 registry.source_root
        with self._lock:
            # 并发下可能已被另一线程建了,保留先到那个
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing
            self._sessions[session_id] = sess
        return sess

    def list_all(self) -> list[dict]:
        """列会话(内存 + 磁盘并集),按 updated_at 倒序。

        title / updated_at / last_prompt 从 meta.json 读;meta.json 不存在或损坏
        时 fallback 用目录 mtime + session_id 当 title。

        返回 [{id, title, active, updated_at, relative_time}]。
        """
        sessions_dir = self.source_root / ".taisang" / "sessions"
        disk_ids: set[str] = set()
        if sessions_dir.is_dir():
            for p in sessions_dir.iterdir():
                if p.is_dir():
                    disk_ids.add(p.name)
        with self._lock:
            mem_items = list(self._sessions.items())
        mem_ids = {sid for sid, _ in mem_items}
        all_ids = disk_ids | mem_ids
        now = time.time()
        items: list[dict] = []
        for sid in all_ids:
            with self._lock:
                sess = self._sessions.get(sid)
            # 优先:内存实例的 title(刚更新过,最准)
            # 其次:meta.json(重启后或别的进程写的)
            # 最后:fallback 用 session_id
            if sess is not None:
                title = sess.title
                ts = sess.updated_at
            else:
                # lazy 重建前从 meta.json 读
                store = ConversationStore(session_id=sid, sessions_dir=sessions_dir)
                meta = store.load_meta()
                if meta is not None:
                    title = meta.get("title") or sid
                    ts = meta.get("updated_at", now)
                else:
                    title = sid
                    d = sessions_dir / sid
                    ts = d.stat().st_mtime if d.exists() else now
            items.append(
                {
                    "id": sid,
                    "title": title,
                    "active": sess is not None,
                    "updated_at": ts,
                    "relative_time": _relative_time(now - ts),
                }
            )
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def update_meta_after_turn(self, session_id: str, last_user_query: str) -> None:
        """turn 结束后更新 meta.json。title 取 last_user_query 前 40 字。

        在 app.py 的 send_message 路由里,agent.run() 返回后调用。
        """
        sess = self.get_or_load(session_id)
        if sess is None:
            return
        first_line = last_user_query.strip().split("\n")[0].strip()
        if first_line:
            title = first_line[:40] + ("…" if len(first_line) > 40 else "")
        else:
            title = "新会话"
        sess.title = title
        sess.updated_at = time.time()
        sess.store.write_meta({
            "id": session_id,
            "title": title,
            "last_prompt": last_user_query[:200],
            "created_at": sess.created_at,
            "updated_at": sess.updated_at,
        })

    def delete(self, session_id: str, timeout: float = 5.0) -> bool:
        """删会话:内存移除 → 等在跑的 run 结束 → 磁盘目录删除。

        先 pop 内存(get_or_load 找不到,新 run 进不来);但已在跑的 run
        还持着 sess.lock,直接 rmtree 会让它的 on_append 写已删目录炸
        Errno 2,故等锁释放再删盘。等不到(run 卡死)返回 False,磁盘
        保留,前端提示稍后再删。
        """
        with self._lock:
            sess = self._sessions.pop(session_id, None)
        if sess is not None:
            if not sess.lock.acquire(timeout=timeout):
                return False
            sess.lock.release()
        sess_dir = self.source_root / ".taisang" / "sessions" / session_id
        if sess_dir.is_dir():
            shutil.rmtree(sess_dir, ignore_errors=True)
            return True
        return sess is not None

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

    def switch_source_root(self, session_id: str, new_root: Path) -> bool:
        """切换 session 的当前工作目录到 new_root。

        影响:
        - agent.source_root(文件工具 cwd 跟随,下一轮 run 的 ToolRegistry cwd 用新 root)
        - permission.approve_dir(new_root)(agent 直接能读写新 root,不需首次问批准)
        - shell._cwd + _kill_and_restart(Bash 持久 shell 重启到新 cwd)
        - sess.source_root(供 API 返回)
        - meta.json 加 source_root 字段(resume 时恢复)

        不影响:
        - skills/agents 加载(仍用 registry 启动时的全局配置 + registry.source_root 的 .taisang/skills)
        - store 历史记录位置(仍在 registry.source_root/.taisang/sessions/<id>/)
        - 已批准的旧目录(保留在 permission._approved,用户切回还能访问)
        """
        sess = self.get_or_load(session_id)
        if sess is None:
            return False
        new_root_resolved = new_root.resolve()
        sess.agent.source_root = new_root_resolved
        sess.agent.permission.approve_dir(new_root_resolved)
        # Bash 持久 shell 重启到新 cwd:更新 _cwd + _kill_and_restart 内部会重启进程
        if hasattr(sess.agent.shell, "_cwd"):
            sess.agent.shell._cwd = new_root_resolved
            try:
                sess.agent.shell._kill_and_restart()
            except Exception:  # noqa: BLE001 — 重启失败不致命,下次 run 会 _ensure_alive
                pass
        sess.source_root = new_root_resolved
        # 写 meta.json(保留现有字段 + 加 source_root)
        meta = sess.store.load_meta() or {}
        meta["source_root"] = str(new_root_resolved)
        sess.store.write_meta(meta)
        return True

    def get_source_root(self, session_id: str) -> Path | None:
        """返回 session 的当前工作目录。优先内存 sess.source_root,否则 meta.json,
        否则 registry.source_root(全局默认)。
        """
        sess = self.get_or_load(session_id)
        if sess is None:
            return None
        if sess.source_root is not None:
            return sess.source_root
        meta = sess.store.load_meta()
        if meta is not None and meta.get("source_root"):
            return Path(meta["source_root"])
        return self.source_root

    def apply_llm_config(self, cfg: LLMConfig) -> None:
        """所有内存 session 应用新 cfg:LLMClient 重建 + debug 同步。

        MockLLM 实例跳过 LLM 重建(测试场景),但 debug 仍 apply(测试也
        需要观察 debug 输出)。
        正在跑的 run 持有 sess.lock,run 内部用旧 llm 跑完当前 LLM 调用;
        下一次 LLM 调用用新 llm —— 这是可接受的边界(model 中途切换)。
        debug 是 set_debug() 改实例字段,立即生效,不影响正在跑的 LLM 调用
        (下一个 emit 点才看新值)。
        """
        with self._lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            if not isinstance(sess.agent.llm, MockLLM):
                sess.agent.llm = LLMClient(cfg)
            sess.agent.set_debug(cfg.debug)

    def apply_prompts_config(self, key: str) -> None:
        """改 prompt 后广播到所有内存 session。

        - key == "system_prompt":
            重新调 build_system_prompt(skills_section, mcp_section),
            替换每个 session 的 ctx 第一条 system 消息的 content。
            skills/mcp 段从该 session 现有 agent 取,不丢。
        - 其他 key(autocompact / session_memory_*):
            触发时才读 config,不需要 broadcast,直接返回。
        - 正在跑的 run 持有 sess.lock,等它跑完下一次 LLM 调用自然用新 system
          —— 与 apply_llm_config 同语义。
        - MockLLM session 也替换 system prompt(与 llm 类型无关)。
        """
        if key != "system_prompt":
            return
        with self._lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            agent = sess.agent
            # 重新组装 system prompt,保留 skills/mcp 段(与 service.__init__/reset 同逻辑)
            from ..skills.listing import format_skill_listing
            from ..agents.listing import format_agent_listing
            from ..agent_core.prompts import build_system_prompt, format_mcp_section

            skills_section = format_skill_listing(agent.skills)
            agents_section = format_agent_listing(agent.agents) if agent.agents else ""
            mcp_section = format_mcp_section(agent._mcp_manager) if getattr(agent, "_mcp_manager", None) else ""
            new_system = build_system_prompt(skills_section, mcp_section, agents_section)
            agent.ctx.replace_system_prompt(new_system)


def _reconstruct_todos(records: list[dict]) -> list[dict]:
    """从历史 records 找最后一条 TodoWrite tool_call,重建 todos。

    TodoWrite 是覆盖式更新,最后一条的 args.todos 就是当前状态。
    找不到 TodoWrite 调用(简单任务没拆 todo)返回空列表。

    records 结构:ConversationStore.load_all() 返回的 dict 列表,
    assistant 消息带 tool_calls 字段(OpenAI function call 格式)。
    """
    import json

    for r in reversed(records):
        if r.get("role") != "assistant":
            continue
        for tc in r.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "TodoWrite":
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                continue
            todos = args.get("todos", [])
            if isinstance(todos, list):
                return todos
    return []


def _relative_time(seconds: float) -> str:
    """秒数 → 相对时间字符串(英文短形式,git commit 风格)。"""
    s = int(seconds)
    if s < 30:
        return "刚刚"
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}min ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    if s < 86400 * 7:
        return f"{s // 86400}d ago"
    return f"{s // (86400 * 7)}w ago"
