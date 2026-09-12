"""消息队列单元测试: _run_next / send_message / interrupt / GET /queue"""
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from taisang.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    app = create_app(tmp_path)
    return TestClient(app)


def test_run_next_empty_queue_noop(client, tmp_path):
    """queue 空,_run_next 不拿锁直接 return。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    registry = client.app.state.registry
    sess = registry.get_or_load(sid)
    from taisang.web.app import _run_next
    # queue 空,不拿锁
    _run_next(registry, sess, sid)
    assert not sess.lock.locked()
    assert sess.queue == []


def test_send_message_no_409_when_busy(client, tmp_path):
    """思考时 POST /messages 不再返回 409,改为排队。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    # 模拟 lock 已锁(turn 在跑)
    sess.lock.acquire(blocking=False)
    try:
        r = client.post(f"/api/sessions/{sid}/messages", json={"query": "排队消息"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["queued"] is True
        assert "排队消息" in sess.queue
    finally:
        sess.lock.release()


def test_send_message_triggers_run_when_idle(client, tmp_path):
    """lock 未锁时 POST /messages → append + _run_next 拿锁跑 turn。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"query": "直接跑"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # lock 已被 _run_next 拿走(跑完会 release)
    sess = client.app.state.registry.get_or_load(sid)
    # 等 run 跑完
    deadline = time.time() + 5
    while sess.lock.locked() and time.time() < deadline:
        time.sleep(0.01)
    # queue 已被清空(flush 了)
    assert sess.queue == []


def test_interrupt_clears_queue_then_interrupts(client, tmp_path):
    """queue 有 2 条 + lock 已锁,POST interrupt 后 queue 空 + agent.interrupt() 被调。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    # 模拟 turn 在跑: 拿锁 + 往 queue 塞 2 条
    sess.lock.acquire(blocking=False)
    try:
        sess.queue.append("排队1")
        sess.queue.append("排队2")
        with patch.object(sess.agent, "interrupt") as mock_interrupt:
            r = client.post(f"/api/sessions/{sid}/interrupt")
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["interrupted"] is True
        assert sess.queue == []  # 队列已清空
        mock_interrupt.assert_called_once()
    finally:
        sess.lock.release()


def test_interrupt_clears_queue_even_when_idle(client, tmp_path):
    """queue 有 2 条 + lock 未锁(turn 刚结束),POST interrupt 后 queue 空, agent.interrupt() 不调。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    sess.queue.append("排队1")
    sess.queue.append("排队2")
    with patch.object(sess.agent, "interrupt") as mock_interrupt:
        r = client.post(f"/api/sessions/{sid}/interrupt")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["interrupted"] is False  # lock 未锁,没中断
    assert sess.queue == []  # 队列仍清空
    mock_interrupt.assert_not_called()
