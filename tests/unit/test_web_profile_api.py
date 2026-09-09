from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from taisang.user_profile.types import DEFAULT_PROFILE_TEMPLATE
from taisang.web.profile_api import register_profile_routes


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    settings_path = tmp_path / "settings.json"
    history_path = tmp_path / "history.jsonl"
    register_profile_routes(app, settings_path=settings_path, history_path=history_path)
    return TestClient(app)


def test_get_profile_empty(client):
    """无画像 → content 空 + total=0。"""
    r = client.get("/api/profile")
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == ""
    assert data["total_chars"] == 0


def test_put_profile_updates_content(client):
    """PUT 整篇覆盖 + history。"""
    r = client.put("/api/profile", json={"content": "### 技术栈\nPython/Go"})
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "### 技术栈\nPython/Go"
    assert data["total_chars"] > 0

    # GET 验证
    r2 = client.get("/api/profile")
    assert r2.json()["content"] == "### 技术栈\nPython/Go"


def test_put_profile_missing_content_422(client):
    """缺 content 字段 → 422。"""
    r = client.put("/api/profile", json={})
    assert r.status_code == 422


def test_post_reset_default_restores_template(client):
    """reset-default → 恢复默认模板。"""
    client.put("/api/profile", json={"content": "custom"})
    r = client.post("/api/profile/reset-default")
    assert r.status_code == 200
    assert r.json()["content"] == DEFAULT_PROFILE_TEMPLATE


def test_post_clear_empties_content(client):
    """clear → 整篇置空。"""
    client.put("/api/profile", json={"content": "custom"})
    r = client.post("/api/profile/clear")
    assert r.status_code == 200
    assert r.json()["content"] == ""


def test_get_history_returns_records(client):
    """改几次后 GET history 返回记录。"""
    client.put("/api/profile", json={"content": "### 技术栈\nPython"})
    client.put("/api/profile", json={"content": "### 技术栈\nGo"})
    r = client.get("/api/profile/history")
    assert r.status_code == 200
    records = r.json()
    assert len(records) == 2
    assert records[0]["field"] == "content"
    assert records[0]["source"] == "user"
    assert "snapshot_before" in records[0]


def test_post_rollback_restores_previous(client):
    """回滚 → 恢复到上一版本。"""
    client.put("/api/profile", json={"content": "### 技术栈\nPython"})
    client.put("/api/profile", json={"content": "### 技术栈\nGo"})
    r = client.post("/api/profile/rollback")
    assert r.status_code == 200
    assert r.json()["content"] == "### 技术栈\nPython"


def test_post_rollback_no_history_409(client):
    """无历史 → 409。"""
    r = client.post("/api/profile/rollback")
    assert r.status_code == 409


def test_put_profile_history_capped_at_5(client):
    """history 最近 5 条。"""
    for i in range(7):
        client.put("/api/profile", json={"content": str(i)})
    r = client.get("/api/profile/history")
    assert len(r.json()) == 5
