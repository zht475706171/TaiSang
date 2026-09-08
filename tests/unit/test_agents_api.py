# tests/unit/test_agents_api.py
"""Agent 管理 API 单测。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from taisang.web.agents_api import register_agents_routes


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    register_agents_routes(app, source_root=tmp_path)
    return app


def test_list_agents_returns_builtin(tmp_path: Path, monkeypatch) -> None:
    """GET /api/agents 返回 4 个内置 agent。"""
    # 隔离 state 文件
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "agents_state.json")
    app = _make_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    names = {a["agent_type"] for a in data["agents"]}
    assert {"general-purpose", "explore", "plan", "verification"} <= names
    # 字段齐全
    for a in data["agents"]:
        assert "agent_type" in a
        assert "when_to_use" in a
        assert "source" in a
        assert "tools" in a
        assert "disallowed_tools" in a
        assert "disabled" in a
        assert "background" in a


def test_toggle_agent_persists_state(tmp_path: Path, monkeypatch) -> None:
    """POST /api/agents/{name}/toggle 翻转 disabled 并持久化。"""
    state_file = tmp_path / "agents_state.json"
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", state_file)
    app = _make_app(tmp_path)
    client = TestClient(app)
    # 第一次 toggle:False → True
    r = client.post("/api/agents/explore/toggle")
    assert r.status_code == 200
    assert r.json()["disabled"] is True
    # state 文件写入
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["explore"] is True
    # 第二次 toggle:True → False
    r = client.post("/api/agents/explore/toggle")
    assert r.json()["disabled"] is False


def test_toggle_nonexistent_returns_404(tmp_path: Path, monkeypatch) -> None:
    """toggle 不存在的 agent → 404。"""
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "agents_state.json")
    app = _make_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/agents/nonexistent/toggle")
    assert r.status_code == 404


def test_reload_agents(tmp_path: Path, monkeypatch) -> None:
    """POST /api/agents/reload 返回 {ok: true}(loader 无缓存,no-op)。"""
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "agents_state.json")
    app = _make_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/agents/reload")
    assert r.status_code == 200
    assert r.json() == {"ok": True}