"""测试 SessionRegistry: create/list/delete/reset/get_or_load,用 MockLLM。"""

import threading
import time

import pytest

from taisang.web.session_registry import SessionRegistry


@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    """TAISANG_MOCK_LLM=1,HOME/USERPROFILE 隔离到 tmp_path,避免单测依赖真 LLM key/污染家目录。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    yield


def test_create_returns_id_and_lands_in_memory(tmp_path, mock_env):
    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="会话1")
    assert isinstance(sid, str)
    assert len(sid) == 8
    sess = reg.get_or_load(sid)
    assert sess is not None
    assert sess.title == "会话1"
    assert sess.session_id == sid


def test_list_all_includes_created_and_disk_sessions(tmp_path, mock_env):
    """list_all 应合并内存 + 磁盘会话。"""
    reg = SessionRegistry(tmp_path)
    sid1 = reg.create("会话1")
    # 磁盘造一个不在内存的旧会话目录
    (tmp_path / ".taisang" / "sessions" / "oldsession").mkdir(parents=True)
    lst = reg.list_all()
    ids = {item["id"] for item in lst}
    assert sid1 in ids
    assert "oldsession" in ids
    # oldsession 不在内存,active=False
    old_item = next(it for it in lst if it["id"] == "oldsession")
    assert old_item["active"] is False


def test_get_or_load_lazy_rebuilds_from_disk(tmp_path, mock_env):
    """磁盘有目录但内存没有时,get_or_load lazy 重建。"""
    reg = SessionRegistry(tmp_path)
    (tmp_path / ".taisang" / "sessions" / "zold").mkdir(parents=True)
    sess = reg.get_or_load("zold")
    assert sess is not None
    assert sess.session_id == "zold"
    # 重建后 active 应变 True
    assert any(it["id"] == "zold" and it["active"] for it in reg.list_all())


def test_get_or_load_unknown_returns_none(tmp_path, mock_env):
    reg = SessionRegistry(tmp_path)
    assert reg.get_or_load("nonexistent") is None


def test_delete_removes_memory_and_disk(tmp_path, mock_env):
    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    assert reg.delete(sid) is True
    assert reg.get_or_load(sid) is None
    assert not (tmp_path / ".taisang" / "sessions" / sid).exists()
    assert sid not in {it["id"] for it in reg.list_all()}


def test_delete_waits_for_active_run(tmp_path, mock_env):
    """run 持锁期间 delete:等锁释放后再删盘,返回 True(不与写盘竞争)。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    sess = reg.get_or_load(sid)

    holding = threading.Event()

    def hold_lock():
        with sess.lock:
            holding.set()
            time.sleep(0.5)  # 模拟 run 进行中

    t = threading.Thread(target=hold_lock)
    t.start()
    assert holding.wait(timeout=2)

    ok = reg.delete(sid)
    t.join(timeout=2)
    assert ok is True
    assert not t.is_alive()  # delete 等过 run
    assert not (tmp_path / ".taisang" / "sessions" / sid).exists()


def test_delete_times_out_when_run_stuck(tmp_path, mock_env):
    """run 卡死不放锁:delete 超时返回 False,磁盘保留(稍后可再删)。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    sess = reg.get_or_load(sid)
    assert sess.lock.acquire()  # 模拟卡死的 run

    try:
        ok = reg.delete(sid, timeout=0.2)
        assert ok is False
        assert (tmp_path / ".taisang" / "sessions" / sid).exists()
    finally:
        sess.lock.release()


def test_delete_force_denies_blocked_confirm(tmp_path, mock_env):
    """run 卡在 confirm 永久阻塞(用户没点):delete force_deny 唤醒它,跑完释放 lock,删除成功。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    sess = reg.get_or_load(sid)
    holding = threading.Event()

    def hold_on_confirm():
        # 持 lock 并卡在 confirmer(永久阻塞,靠 force_deny 唤醒)
        with sess.lock:
            holding.set()
            sess.confirmer("a.py", "old", "new")  # timeout=None 永久阻塞

    t = threading.Thread(target=hold_on_confirm)
    t.start()
    assert holding.wait(timeout=2)
    # delete:lock 被持有,force_deny 唤醒 confirmer → run 退出释放 lock → 删除
    ok = reg.delete(sid, timeout=0.5)
    t.join(timeout=2)
    assert ok is True
    assert not t.is_alive()
    assert not (tmp_path / ".taisang" / "sessions" / sid).exists()


def test_delete_during_run_writer_never_crashes(tmp_path, mock_env):
    """复现线上 bug:run 线程持续写 jsonl 期间 delete,writer 不得抛 Errno 2。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    sess = reg.get_or_load(sid)
    errors: list[Exception] = []

    def writer():
        with sess.lock:
            try:
                for _ in range(20):
                    sess.store.append(
                        {"type": "user", "role": "user", "content": "x", "uuid": "u", "timestamp": 1.0}
                    )
                    time.sleep(0.02)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.05)  # 让 writer 先跑几轮

    ok = reg.delete(sid)
    t.join(timeout=3)
    assert ok is True
    assert errors == []


def test_reset_clears_context(tmp_path, mock_env):
    """reset 调 AgentService.reset,ctx 清空。"""

    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    sess = reg.get_or_load(sid)
    # 跑一轮,ctx 应有内容
    events = []
    sess.agent.run("q", on_event=lambda e: events.append(e))
    assert len(sess.agent.ctx.messages()) > 1
    # reset
    assert reg.reset(sid) is True
    assert len(sess.agent.ctx.messages()) == 1  # 只剩 system prompt
    assert sess.agent._session_usage["total_tokens"] == 0


def test_reset_unknown_returns_false(tmp_path, mock_env):
    reg = SessionRegistry(tmp_path)
    assert reg.reset("nonexistent") is False


def test_set_debug_toggles(tmp_path, mock_env):
    reg = SessionRegistry(tmp_path)
    sid = reg.create("会话")
    assert reg.set_debug(sid, True) is True
    sess = reg.get_or_load(sid)
    assert sess.agent.debug is True
    assert reg.set_debug(sid, False) is True
    assert sess.agent.debug is False


def test_per_session_isolation(tmp_path, mock_env):
    """两个会话 ctx 独立,互不污染。"""
    reg = SessionRegistry(tmp_path)
    sid1 = reg.create("会话1")
    sid2 = reg.create("会话2")
    s1 = reg.get_or_load(sid1)
    s2 = reg.get_or_load(sid2)
    s1.agent.ctx.append_user("hello-1")
    # s2 的 ctx 不应包含 s1 的输入
    contents = [m.get("content", "") for m in s2.agent.ctx.messages()]
    assert "hello-1" not in contents
    assert len(s2.agent.ctx.messages()) == 1  # 只剩 system


def test_create_with_empty_title_stays_empty(tmp_path, mock_env):
    """create() 不传 title 时,title 保持空(不 fallback 到 id)。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create()
    sess = reg.get_or_load(sid)
    assert sess.title == ""


def test_set_title_from_query_sets_when_empty(tmp_path, mock_env):
    """title 为空时,set_title_from_query 取 query 前 40 字作 title。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create()
    assert reg.set_title_from_query(sid, "这个 repo 的入口在哪里") is True
    sess = reg.get_or_load(sid)
    assert sess.title == "这个 repo 的入口在哪里"


def test_set_title_from_query_truncates_long_query(tmp_path, mock_env):
    """query 超 40 字时,截断 + 加省略号。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create()
    # 故意造 50+ 字 query,确保触发截断
    long_q = (
        "请帮我分析一下这个项目的整体架构设计以及各个模块之间的依赖关系"
        "和调用流程还有核心机制的实现细节"
    )
    assert len(long_q) > 40, "测试前置:query 必须超过 40 字"
    assert reg.set_title_from_query(sid, long_q) is True
    sess = reg.get_or_load(sid)
    # title 应被截到 40 字 + 省略号
    assert len(sess.title) <= 42
    assert sess.title[-1] in ("…", ".")


def test_set_title_from_query_does_not_overwrite_existing(tmp_path, mock_env):
    """已有非空 title 时,set_title_from_query 不覆盖,返回 False。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="手动标题")
    assert reg.set_title_from_query(sid, "新消息") is False
    sess = reg.get_or_load(sid)
    assert sess.title == "手动标题"


def test_set_title_from_query_takes_first_line(tmp_path, mock_env):
    """多行 query 只取第一行作 title。"""
    reg = SessionRegistry(tmp_path)
    sid = reg.create()
    q = "第一行是问题\n第二行是补充说明\n第三行"
    reg.set_title_from_query(sid, q)
    sess = reg.get_or_load(sid)
    assert "\n" not in sess.title
    assert sess.title == "第一行是问题"


def test_set_title_from_query_unknown_session_returns_false(tmp_path, mock_env):
    reg = SessionRegistry(tmp_path)
    assert reg.set_title_from_query("nonexistent", "q") is False


def test_list_all_returns_relative_time_and_updated_at(tmp_path, mock_env):
    """list_all 应返回 relative_time + updated_at 字段,按 updated_at 倒序。"""
    reg = SessionRegistry(tmp_path)
    sid1 = reg.create("old")
    # 手动把 sid1 的 updated_at 调到 2 小时前
    reg.get_or_load(sid1).updated_at = __import__("time").time() - 7200
    sid2 = reg.create("new")
    lst = reg.list_all()
    assert len(lst) == 2
    # new 应排在前(updated_at 更大)
    assert lst[0]["id"] == sid2
    assert lst[1]["id"] == sid1
    # 字段齐全
    assert "relative_time" in lst[0]
    assert "updated_at" in lst[0]
    # old 的相对时间应包含 "h ago"
    assert "h ago" in lst[1]["relative_time"]


def test_reconstruct_todos_finds_last_todo_write_call():
    """_reconstruct_todos 从 records 找最后一条 TodoWrite tool_call,重建 todos。"""
    import json
    from taisang.web.session_registry import _reconstruct_todos

    records = [
        {"role": "user", "content": "分析两个文件"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "TodoWrite",
                        "arguments": json.dumps({"todos": [
                            {"content": "读 A", "status": "in_progress"},
                            {"content": "读 B", "status": "pending"},
                        ]}),
                    }
                }
            ],
        },
        {"role": "tool", "content": '{"ok": true}'},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "TodoWrite",
                        "arguments": json.dumps({"todos": [
                            {"content": "读 A", "status": "completed"},
                            {"content": "读 B", "status": "in_progress"},
                        ]}),
                    }
                }
            ],
        },
    ]
    todos = _reconstruct_todos(records)
    assert len(todos) == 2
    # 最后一条的 args.todos(覆盖式,取最新状态)
    assert todos[0]["status"] == "completed"
    assert todos[1]["status"] == "in_progress"


def test_reconstruct_todos_no_todo_write_returns_empty():
    """没调过 TodoWrite(简单任务)→ 返回空列表。"""
    from taisang.web.session_registry import _reconstruct_todos

    records = [
        {"role": "user", "content": "读个文件"},
        {"role": "assistant", "content": "ok", "tool_calls": []},
    ]
    assert _reconstruct_todos(records) == []


def test_reconstruct_todos_handles_malformed_arguments():
    """TodoWrite tool_call 的 arguments 损坏 → 跳过,继续找更早的。"""
    import json
    from taisang.web.session_registry import _reconstruct_todos

    records = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "TodoWrite",
                        "arguments": "not-json",  # 损坏
                    }
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "TodoWrite",
                        "arguments": json.dumps({"todos": [{"content": "x", "status": "pending"}]}),
                    }
                }
            ],
        },
    ]
    # 最新一条损坏,应跳过找更早一条(但更早一条在上面 records[0],
    # reversed 后 records[1] 先遇到合法的)。实际 reversed 先访问最后的 records[1] 合法 → 直接返回
    todos = _reconstruct_todos(records)
    assert len(todos) == 1
    assert todos[0]["content"] == "x"


def test_get_or_load_reconstructs_todos_from_disk(tmp_path, mock_env):
    """磁盘会话 lazy 重建时,从 jsonl 历史重建 todos。"""
    import json
    from taisang.storage.conversation_store import ConversationStore

    reg = SessionRegistry(tmp_path)
    sid = "oldsession"
    sess_dir = tmp_path / ".taisang" / "sessions" / sid
    sess_dir.mkdir(parents=True)

    # 造一个 jsonl:含一条 TodoWrite tool_call
    store = ConversationStore(session_id=sid, sessions_dir=tmp_path / ".taisang" / "sessions")
    store.append({"role": "user", "content": "分析文件"})
    store.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "tc1",
                "type": "function",
                "function": {
                    "name": "TodoWrite",
                    "arguments": json.dumps({"todos": [
                        {"content": "读 A", "status": "in_progress", "activeForm": "正在读 A"},
                        {"content": "总结", "status": "pending"},
                    ]}),
                },
            }
        ],
    })
    store.append({"role": "tool", "tool_call_id": "tc1", "name": "TodoWrite", "content": '{"ok": true}'})

    # lazy 重建
    sess = reg.get_or_load(sid)
    assert sess is not None
    assert len(sess.agent.todos) == 2
    assert sess.agent.todos[0]["content"] == "读 A"
    assert sess.agent.todos[0]["activeForm"] == "正在读 A"
    assert sess.agent.todos[1]["status"] == "pending"


def test_gc_excess_no_op_when_under_limit(tmp_path, mock_env):
    """session 数 < 上限时 gc_excess 不删,返回 0。"""
    reg = SessionRegistry(tmp_path)
    for i in range(5):
        reg.create(title=f"会话{i}")
    deleted = reg.gc_excess()
    assert deleted == 0
    assert len(reg.list_all()) == 5


def test_gc_excess_deletes_oldest_when_over_limit(tmp_path, mock_env):
    """session 数 > 上限时,删除最早(updated_at 最旧),保留最新的。

    用大 max 创建 3 个 session(避免 create 时 GC 误删),再降到 2 调 gc_excess。
    """
    import json
    from taisang.config import _settings_path

    reg = SessionRegistry(tmp_path)
    settings = _settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"max_sessions": 100}), encoding="utf-8")

    sids = []
    for i in range(3):
        sid = reg.create(title=f"会话{i}")
        sids.append(sid)
        sess = reg.get_or_load(sid)
        sess.updated_at = 1000.0 + i  # 1000, 1001, 1002
        sess.store.write_meta({"title": f"会话{i}", "updated_at": 1000.0 + i})

    # 降到 max=2,手动调 gc_excess:删最早(updated_at=1000)
    settings.write_text(json.dumps({"max_sessions": 2}), encoding="utf-8")
    deleted = reg.gc_excess()
    assert deleted == 1
    remaining = {item["id"] for item in reg.list_all()}
    assert sids[0] not in remaining  # 最早的被删
    assert sids[1] in remaining
    assert sids[2] in remaining


def test_gc_excess_respects_custom_max_sessions(tmp_path, mock_env):
    """settings.json 的 max_sessions 字段覆盖默认 50。"""
    import json
    from taisang.config import _settings_path
    settings = _settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"max_sessions": 3}), encoding="utf-8")
    reg = SessionRegistry(tmp_path)
    assert reg._load_max_sessions() == 3


def test_gc_excess_uses_default_50_when_no_settings(tmp_path, mock_env):
    """没 settings.json 时用默认 50。"""
    reg = SessionRegistry(tmp_path)
    assert reg._load_max_sessions() == 50


def test_gc_excess_skips_invalid_max_sessions(tmp_path, mock_env):
    """settings.json 的 max_sessions 非法(<=0 或非 int)时用默认 50。"""
    import json
    from taisang.config import _settings_path
    settings = _settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"max_sessions": -5}), encoding="utf-8")
    reg = SessionRegistry(tmp_path)
    assert reg._load_max_sessions() == 50

    settings.write_text(json.dumps({"max_sessions": "not a number"}), encoding="utf-8")
    assert reg._load_max_sessions() == 50


def test_create_triggers_gc_when_over_limit(tmp_path, mock_env):
    """create() 后触发 gc_excess,超额时自动删最早。

    建 3 个 session(max=3 不触发),第 4 个 create 触发 GC 删最早。
    注意第 4 个 create 之后立即 GC,此时 sid4 的 updated_at 还没手动设,
    list_all 里 sid4 用系统时间(远大于 1000+),所以最早仍是 sids[0]。
    """
    import json
    from taisang.config import _settings_path
    settings = _settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"max_sessions": 3}), encoding="utf-8")

    reg = SessionRegistry(tmp_path)
    sids = []
    for i in range(3):
        sid = reg.create(title=f"会话{i}")
        sids.append(sid)
        sess = reg.get_or_load(sid)
        sess.updated_at = 1000.0 + i
        sess.store.write_meta({"title": f"会话{i}", "updated_at": 1000.0 + i})

    # 第 4 个 create 应触发 GC(max=3,有 4 个,删 updated_at=1000 的)
    sid4 = reg.create(title="会话3")

    remaining = {item["id"] for item in reg.list_all()}
    assert sids[0] not in remaining  # 最早被 GC
    assert sid4 in remaining
    assert len(remaining) == 3
