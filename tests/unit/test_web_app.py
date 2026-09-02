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


def test_get_or_load_restores_history_after_restart(tmp_path, monkeypatch):
    """模拟进程重启:registry1 跑对话 → 新建 registry2 → get_or_load 灌回历史。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry

    # 进程 1:创建 session,跑一轮对话(写 jsonl)
    reg1 = SessionRegistry(tmp_path)
    sid = reg1.create(title="")
    sess1 = reg1.get_or_load(sid)
    # 模拟 agent 跑了一轮:手动往 ctx 加 messages(on_append 会写到 jsonl)
    sess1.agent.ctx.append_user("你好")
    sess1.agent.ctx.append_assistant("你好!", tool_calls=None)

    # 进程 2:新建 registry(模拟重启,内存实例全丢)
    reg2 = SessionRegistry(tmp_path)
    sess2 = reg2.get_or_load(sid)
    # ctx 应该被灌回,包含刚才的两条 message(加 SYSTEM_PROMPT 是 3 条)
    msgs = sess2.agent.ctx.messages()
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    # 找到 user message 内容是"你好"
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert any(m["content"] == "你好" for m in user_msgs)
