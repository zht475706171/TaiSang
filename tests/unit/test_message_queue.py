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
