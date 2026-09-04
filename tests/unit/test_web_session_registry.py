"""测试 SessionRegistry: create/list/delete/reset/get_or_load,用 MockLLM。"""

import threading
import time

import pytest

from taisang.web.session_registry import SessionRegistry


@pytest.fixture
def mock_env(monkeypatch):
    """TAISANG_MOCK_LLM=1,避免单测依赖真 LLM key。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
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
