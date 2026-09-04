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


def test_list_all_reads_title_from_meta(tmp_path, monkeypatch):
    """list_all 从 meta.json 读 title(替代扫目录 mtime 兜底)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry
    from taisang.storage.conversation_store import ConversationStore

    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="")  # 空 title
    # 手动写 meta.json 模拟 turn 结束后的状态
    sess = reg.get_or_load(sid)
    sess.store.write_meta({
        "id": sid, "title": "最后问的问题", "last_prompt": "最后问的问题",
        "created_at": 1.0, "updated_at": 2.0,
    })
    # 释放内存实例,强制 list_all 从磁盘读
    reg._sessions.clear()

    items = reg.list_all()
    assert len(items) == 1
    assert items[0]["title"] == "最后问的问题"


def test_list_all_fallback_when_meta_missing(tmp_path, monkeypatch):
    """meta.json 不存在时 fallback 用 session_id 当 title。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry

    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="")
    reg._sessions.clear()  # 强制从磁盘读

    items = reg.list_all()
    assert len(items) == 1
    # title fallback 到 id(meta 没有)
    assert items[0]["title"] == sid


def test_send_message_updates_meta(tmp_path, monkeypatch):
    """POST /messages 后,meta.json 的 title 是 query 前 40 字。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"query": "帮我看看这个文件"})

    # 等后台 run 跑完(lock 释放)
    sess = app.state.registry.get_or_load(sid)
    import time
    deadline = time.time() + 5
    while sess.lock.locked() and time.time() < deadline:
        time.sleep(0.01)

    # 释放内存实例,强制从 meta.json 读
    app.state.registry._sessions.clear()
    items = app.state.registry.list_all()
    assert items[0]["title"] == "帮我看看这个文件"


def test_get_messages_returns_history(tmp_path, monkeypatch):
    """GET /api/sessions/{id}/messages 返回 conversation.jsonl 的所有 record。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    # 手动往 jsonl 写几条 record(通过 ctx.append 触发 on_append 落盘)
    sess = app.state.registry.get_or_load(sid)
    sess.agent.ctx.append_user("q1")
    sess.agent.ctx.append_assistant("a1", tool_calls=None)

    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    data = r.json()
    # 至少 2 条(user + assistant;SYSTEM_PROMPT 也可能算 1 条)
    roles = [m.get("role") for m in data]
    assert "user" in roles
    assert "assistant" in roles


def test_get_messages_unknown_session_404(tmp_path, monkeypatch):
    """GET 不存在的 session 返回 404。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/sessions/nonexistent/messages")
    assert r.status_code == 404


def test_spa_fallback_serves_index_html(client):
    """SPA 深链(/skills、/chat/xxx)GET 返回 index.html,前端路由接管。"""
    r = client.get("/skills")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    r2 = client.get("/chat/abc123")
    assert r2.status_code == 200
    assert "text/html" in r2.headers["content-type"]


def test_spa_fallback_unknown_api_404(client):
    """未知 /api 路径仍 404 JSON,不回 HTML。"""
    r = client.get("/api/nonexistent")
    assert r.status_code == 404


def test_autocompact_writes_boundary_and_resume_gets_compacted(tmp_path, monkeypatch):
    """autocompact 触发后,jsonl 里有 [compacted via ...] boundary record;
    新建 registry(模拟重启)后 get_or_load 灌回的是截断到最后一个 boundary 后的
    records(压缩前内容被丢弃,只保留压缩后快照)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry

    reg1 = SessionRegistry(tmp_path)
    sid = reg1.create(title="")
    sess1 = reg1.get_or_load(sid)

    # 模拟压缩前:ctx 有一些 messages,写进 jsonl
    sess1.agent.ctx.append_user("old message 1")
    sess1.agent.ctx.append_user("old message 2")

    # 模拟 autocompact 触发:replace_messages 带 compaction_via
    new_msgs = [
        {"role": "system", "content": "you are an agent"},
        {"role": "user", "content": "summary: 之前聊过 old message 1 和 2"},
    ]
    sess1.agent.ctx.replace_messages(new_msgs, compaction_via="llm")

    # 验证 jsonl 有 boundary record
    records = sess1.store.load_all()
    boundary_records = [r for r in records if r.get("role") == "system" and "[compacted" in r.get("content", "")]
    assert len(boundary_records) == 1
    assert "llm" in boundary_records[0]["content"]

    # 模拟重启:新建 registry
    reg2 = SessionRegistry(tmp_path)
    sess2 = reg2.get_or_load(sid)
    msgs = sess2.agent.ctx.messages()
    # 灌回的是截断到最后 boundary 之后的 records(= 压缩后快照)
    # 含 summary(压缩后内容),不含压缩前的独立 old message
    user_contents = [m.get("content", "") for m in msgs if m.get("role") == "user"]
    assert any("summary: 之前聊过" in c for c in user_contents)
    # 压缩前的 old message 1/2 是独立 user 消息,截断后不该作为独立消息存在
    assert "old message 1" not in user_contents
    assert "old message 2" not in user_contents


def test_apply_llm_config_replaces_all_non_mock_sessions(tmp_path, monkeypatch):
    """apply_llm_config 重建所有非 MockLLM session 的 LLMClient。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")  # 让 reg.create() 走 MockLLM
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.session_registry import SessionRegistry
    from taisang.config import LLMConfig
    from taisang.llm_client import LLMClient

    reg = SessionRegistry(tmp_path)
    sid1 = reg.create(title="")
    sid2 = reg.create(title="")
    sess1 = reg.get_or_load(sid1)
    sess2 = reg.get_or_load(sid2)
    # 构造时是 MockLLM,手动换成真 LLMClient 模拟生产
    old_cfg = LLMConfig(base_url="https://old", api_key="sk-old1234567890", model="old-m")
    sess1.agent.llm = LLMClient(old_cfg)
    sess2.agent.llm = LLMClient(old_cfg)

    new_cfg = LLMConfig(base_url="https://new", api_key="sk-new1234567890", model="new-m")
    reg.apply_llm_config(new_cfg)

    for sess in [sess1, sess2]:
        assert isinstance(sess.agent.llm, LLMClient)
        assert sess.agent.llm.model == "new-m"
        assert sess.agent.llm.cfg.base_url == "https://new"


def test_apply_llm_config_skips_mock_sessions(tmp_path, monkeypatch):
    """apply_llm_config 跳过 MockLLM 实例(测试场景不替换)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry
    from taisang.config import LLMConfig
    from taisang.llm_client import MockLLM

    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="")
    sess = reg.get_or_load(sid)
    assert isinstance(sess.agent.llm, MockLLM)
    reg.apply_llm_config(LLMConfig(base_url="x", api_key="y", model="z"))
    # 还是 MockLLM,没被替换
    assert isinstance(sess.agent.llm, MockLLM)


def test_get_config_returns_masked_api_key(tmp_path, monkeypatch):
    """GET /api/config 返回 model/base_url + api_key 打码。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, save_config
    from taisang.web.app import create_app

    save_config(LLMConfig(base_url="https://api.x.com", api_key="sk-abcdefghij1234567", model="m"))
    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "m"
    assert data["base_url"] == "https://api.x.com"
    assert data["api_key"] == "sk-***4567"  # 打码
    assert data["api_key_set"] is True


def test_post_config_saves_and_applies(tmp_path, monkeypatch):
    """POST /api/config 写文件 + apply 到所有 session。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "model": "new-model",
        "api_key": "sk-newkey1234567890",
        "base_url": "https://api.new.com",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # 文件被写
    import json
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["model"] == "new-model"
    assert data["llm"]["base_url"] == "https://api.new.com"
    assert data["llm"]["api_key"] == "sk-newkey1234567890"


def test_post_config_empty_api_key_allowed(tmp_path, monkeypatch):
    """POST /api/config 空 api_key 允许保存(本地 endpoint 如 ollama 不需要 key)。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "model": "m",
        "api_key": "",
        "base_url": "http://localhost:11434/v1",
    })
    assert r.status_code == 200


def test_post_config_unchanged_api_key_keeps_old(tmp_path, monkeypatch):
    """POST /api/config api_key='__unchanged__' 时保留原 api_key。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, save_config
    from taisang.web.app import create_app

    save_config(LLMConfig(base_url="https://api.x.com", api_key="sk-original123456789", model="m"))
    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "model": "new-m",
        "api_key": "__unchanged__",
        "base_url": "https://api.new.com",
    })
    assert r.status_code == 200
    import json
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "sk-original123456789"  # 保留
    assert data["llm"]["model"] == "new-m"  # 改了
