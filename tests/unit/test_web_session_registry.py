"""测试 SessionRegistry: create/list/delete/reset/get_or_load,用 MockLLM。"""

import pytest

from code_reader.web.session_registry import SessionRegistry


@pytest.fixture
def mock_env(monkeypatch):
    """CODE_READER_MOCK_LLM=1,避免单测依赖真 LLM key。"""
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
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
    (tmp_path / ".code-reader" / "sessions" / "oldsession").mkdir(parents=True)
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
    (tmp_path / ".code-reader" / "sessions" / "zold").mkdir(parents=True)
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
    assert not (tmp_path / ".code-reader" / "sessions" / sid).exists()
    assert sid not in {it["id"] for it in reg.list_all()}


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
