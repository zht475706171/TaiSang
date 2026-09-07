"""prompts API 单测:GET/PUT/RESET + apply_prompts_config 广播。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from taisang.config import reset_prompt_override
from taisang.web.app import create_app
from taisang.web.session_registry import SessionRegistry


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    yield fake_home / ".taisang" / "settings.json"
    # 清理:monkeypatch 还 active,reset 写到 tmp_path 不污染真实 home
    for key in ["system_prompt", "autocompact_prompt", "session_memory_template", "session_memory_update_prompt"]:
        try:
            reset_prompt_override(key)
        except Exception:
            pass


@pytest.fixture
def app(tmp_settings, tmp_path, monkeypatch):
    """创建 app,source_root 指向 tmp_path,Mock LLM 避免真调用。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    # 隔离 MCP 单例 state,避免读取真实 ~/.taisang/mcp_servers.json
    import taisang.mcp.manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "_STATE_FILE", tmp_path / "mcp_servers.json")
    import taisang.web.mcp_api as api_mod

    api_mod._manager = None
    return create_app(source_root=tmp_path, allow_dirs=[tmp_path])


@pytest.fixture
def client(app):
    return TestClient(app)


def test_get_prompts_returns_four_keys_with_defaults(client):
    """GET 返回四个 key,每个有 current/default/use_default。"""
    r = client.get("/api/prompts")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {
        "system_prompt",
        "autocompact_prompt",
        "session_memory_template",
        "session_memory_update_prompt",
    }
    for key, item in data.items():
        assert "current" in item and "default" in item and "use_default" in item
        assert item["use_default"] is True
        assert item["current"] == item["default"]  # 默认时 current=default


def test_put_prompt_saves_value(client, tmp_settings):
    """PUT 保存 value,use_default=false。"""
    r = client.put("/api/prompts", json={"key": "system_prompt", "value": "自定义 system"})
    assert r.status_code == 200
    body = r.json()
    assert body["system_prompt"]["use_default"] is False
    assert body["system_prompt"]["value"] == "自定义 system"
    # GET 反映新值
    r2 = client.get("/api/prompts")
    assert r2.json()["system_prompt"]["current"] == "自定义 system"


def test_reset_prompt_restores_default(client, tmp_settings):
    """POST reset 后 use_default=true,current=default。"""
    client.put("/api/prompts", json={"key": "system_prompt", "value": "自定义"})
    r = client.post("/api/prompts/reset", json={"key": "system_prompt"})
    assert r.status_code == 200
    body = r.json()
    assert body["system_prompt"]["use_default"] is True
    assert body["system_prompt"]["current"] == body["system_prompt"]["default"]


def test_put_invalid_key_returns_400(client):
    r = client.put("/api/prompts", json={"key": "nonexistent", "value": "x"})
    assert r.status_code == 400


def test_put_empty_value_returns_400(client):
    r = client.put("/api/prompts", json={"key": "system_prompt", "value": ""})
    assert r.status_code == 400


def test_put_autocompact_missing_conversation_placeholder_returns_400(client):
    """autocompact_prompt 自定义文本缺 {conversation} → 400。"""
    r = client.put("/api/prompts", json={"key": "autocompact_prompt", "value": "没有占位符的文本"})
    assert r.status_code == 400
    assert "{conversation}" in r.json()["detail"]


def test_put_autocompact_with_placeholder_succeeds(client, tmp_settings):
    """autocompact_prompt 含 {conversation} → 保存成功。"""
    r = client.put("/api/prompts", json={"key": "autocompact_prompt", "value": "前缀\n{conversation}\n后缀"})
    assert r.status_code == 200


def test_reset_invalid_key_returns_400(client):
    r = client.post("/api/prompts/reset", json={"key": "nonexistent"})
    assert r.status_code == 400


def test_put_system_prompt_broadcasts_to_active_session(client, app, tmp_path):
    """PUT system_prompt 后,活跃 session 的 messages[0] 被替换为新 system(含 skills/mcp 段)。"""
    registry: SessionRegistry = app.state.registry
    sid = registry.create(title="test")
    sess = registry.get_or_load(sid)
    original_system = sess.agent.ctx.messages()[0]["content"]

    # 保存自定义 system prompt
    client.put("/api/prompts", json={"key": "system_prompt", "value": "全新 system prompt"})

    # 验证 messages[0] 被替换
    new_system = sess.agent.ctx.messages()[0]["content"]
    assert new_system != original_system
    assert new_system.startswith("全新 system prompt")


def test_put_autocompact_does_not_broadcast(client, app, tmp_path):
    """PUT autocompact_prompt 不触发 broadcast(不需要,触发时才读 config)。"""
    registry: SessionRegistry = app.state.registry
    sid = registry.create(title="test")
    sess = registry.get_or_load(sid)
    original_system = sess.agent.ctx.messages()[0]["content"]

    client.put("/api/prompts", json={"key": "autocompact_prompt", "value": "前缀\n{conversation}\n后缀"})

    # messages[0] 不变
    assert sess.agent.ctx.messages()[0]["content"] == original_system


def test_reset_system_prompt_broadcasts_default(client, app, tmp_path):
    """RESET system_prompt 后,活跃 session 的 messages[0] 恢复为默认 system。"""
    registry: SessionRegistry = app.state.registry
    sid = registry.create(title="test")
    sess = registry.get_or_load(sid)

    # 先自定义,再 reset
    client.put("/api/prompts", json={"key": "system_prompt", "value": "临时 system"})
    assert sess.agent.ctx.messages()[0]["content"].startswith("临时 system")

    client.post("/api/prompts/reset", json={"key": "system_prompt"})
    # 恢复为默认 SYSTEM_PROMPT
    from taisang.agent_core.prompts import SYSTEM_PROMPT
    assert sess.agent.ctx.messages()[0]["content"].startswith(SYSTEM_PROMPT)