"""测试 FastAPI app 的 CRUD 路由(不测 SSE 流本身,那需要异步时序)。

SSE 流的编码逻辑在 test_web_sse.py 已覆盖;这里只验证路由连通 + 错误处理。
"""

import pytest
from fastapi.testclient import TestClient

from taisang.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    app = create_app(tmp_path)
    return TestClient(app)


def test_create_session_route(client):
    r = client.post("/api/sessions", json={"title": "会话1"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["id"]) == 8
    assert data["title"] == "会话1"


def test_list_sessions_route(client):
    client.post("/api/sessions", json={"title": "a"})
    client.post("/api/sessions", json={"title": "b"})
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_send_message_to_unknown_session_404(client):
    r = client.post("/api/sessions/nonexistent/messages", json={"query": "hi"})
    assert r.status_code == 404


def test_reset_unknown_session_404(client):
    r = client.post("/api/sessions/nonexistent/reset")
    assert r.status_code == 404


def test_debug_toggle_route(client):
    sid = client.post("/api/sessions", json={"title": "s"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/debug", json={"on": True})
    assert r.status_code == 200
    assert r.json()["debug"] is True


def test_confirm_unknown_token_404(client):
    sid = client.post("/api/sessions", json={"title": "s"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/confirm/badtoken", json={"approve": True})
    assert r.status_code == 404


def test_delete_session_route(client):
    sid = client.post("/api/sessions", json={"title": "s"}).json()["id"]
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    # 删后再列应没了
    assert sid not in {it["id"] for it in client.get("/api/sessions").json()}
