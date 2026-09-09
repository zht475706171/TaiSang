from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from taisang.web.profile_api import register_profile_routes


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    settings_path = tmp_path / "settings.json"
    history_path = tmp_path / "history.jsonl"
    register_profile_routes(app, settings_path=settings_path, history_path=history_path)
    return TestClient(app)


def test_get_profile_empty(client):
    """无画像 → 5 栏全空 + total=0。"""
    r = client.get("/api/profile")
    assert r.status_code == 200
    data = r.json()
    assert data["tech_stack"] == ""
    assert data["taboos"] == ""
    assert data["total_chars"] == 0


def test_put_profile_updates_one_field(client):
    """PUT 单栏 → 更新 + history。"""
    r = client.put("/api/profile", json={"field": "tech_stack", "content": "Python/Go"})
    assert r.status_code == 200
    data = r.json()
    assert data["tech_stack"] == "Python/Go"
    assert data["code_style"] == ""  # 别栏不动

    # GET 验证
    r2 = client.get("/api/profile")
    assert r2.json()["tech_stack"] == "Python/Go"


def test_put_profile_invalid_field_422(client):
    """非法 field → 422。"""
    r = client.put("/api/profile", json={"field": "invalid", "content": "x"})
    assert r.status_code == 422


def test_post_reset_clears_field(client):
    """reset 清空单栏。"""
    client.put("/api/profile", json={"field": "tech_stack", "content": "Python"})
    r = client.post("/api/profile/reset", json={"field": "tech_stack"})
    assert r.status_code == 200
    assert r.json()["tech_stack"] == ""


def test_get_history_returns_records(client):
    """改几次后 GET history 返回记录。"""
    client.put("/api/profile", json={"field": "tech_stack", "content": "Python"})
    client.put("/api/profile", json={"field": "code_style", "content": "4 空格"})
    r = client.get("/api/profile/history")
    assert r.status_code == 200
    records = r.json()
    assert len(records) == 2
    assert records[0]["field"] == "tech_stack"
    assert records[0]["source"] == "user"
    assert records[1]["field"] == "code_style"
    # snapshot_before 存在
    assert "snapshot_before" in records[0]


def test_post_rollback_restores_previous(client):
    """回滚 → 恢复到上一版本。"""
    client.put("/api/profile", json={"field": "tech_stack", "content": "Python"})
    client.put("/api/profile", json={"field": "tech_stack", "content": "Go"})
    # 现在 tech_stack=Go,上一版本=Python
    r = client.post("/api/profile/rollback")
    assert r.status_code == 200
    assert r.json()["tech_stack"] == "Python"


def test_post_rollback_no_history_409(client):
    """无历史 → 409。"""
    r = client.post("/api/profile/rollback")
    assert r.status_code == 409


def test_put_profile_history_capped_at_5(client):
    """history 最近 5 条。"""
    for i in range(7):
        client.put("/api/profile", json={"field": "tech_stack", "content": str(i)})
    r = client.get("/api/profile/history")
    assert len(r.json()) == 5
