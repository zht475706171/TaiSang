from __future__ import annotations

import json
import threading

from taisang.user_profile.store import (
    clear_profile,
    load_profile,
    reset_profile_to_default,
    save_profile_content,
)
from taisang.user_profile.types import DEFAULT_PROFILE_TEMPLATE


def test_load_profile_missing_file(tmp_path):
    """settings.json 不存在 → 空 content。"""
    p = load_profile(settings_path=tmp_path / "nope.json")
    assert p.content == ""


def test_load_profile_no_user_profile_section(tmp_path):
    """settings.json 有文件但无 user_profile 段 → 空。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"llm": {"model": "x"}}), encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.content == ""


def test_load_profile_corrupt_json(tmp_path):
    """损坏 JSON → 空。"""
    sp = tmp_path / "settings.json"
    sp.write_text("{not valid json", encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.content == ""


def test_load_profile_wrong_section_type(tmp_path):
    """user_profile 段非 dict → 空。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"user_profile": "not a dict"}), encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.content == ""


def test_load_profile_new_format_content_field(tmp_path):
    """新版格式:{"content": "..."} 直接取。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"user_profile": {"content": "### 技术栈\nPython"}}),
        encoding="utf-8",
    )
    p = load_profile(settings_path=sp)
    assert p.content == "### 技术栈\nPython"


def test_load_profile_legacy_5_fields_migration(tmp_path):
    """旧版 5 字段格式 → 拼成 ### 标题段(向后兼容)。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"user_profile": {"tech_stack": "Python", "code_style": "4 空格"}}),
        encoding="utf-8",
    )
    p = load_profile(settings_path=sp)
    assert "### 技术栈" in p.content
    assert "Python" in p.content
    assert "### 代码风格" in p.content
    assert "4 空格" in p.content


def test_load_profile_legacy_empty_fields_skipped(tmp_path):
    """旧版 5 字段中空字段不拼(避免空标题段)。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"user_profile": {"tech_stack": "Python", "code_style": ""}}),
        encoding="utf-8",
    )
    p = load_profile(settings_path=sp)
    assert "### 技术栈" in p.content
    assert "Python" in p.content
    assert "### 代码风格" not in p.content  # 空字段跳过


def test_save_profile_content_overwrites(tmp_path):
    """save 整篇覆盖。"""
    sp = tmp_path / "settings.json"
    save_profile_content("### 技术栈\nPython", source="user", session_id=None, settings_path=sp)
    save_profile_content("### 技术栈\nGo", source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.content == "### 技术栈\nGo"


def test_save_profile_content_preserves_other_sections(tmp_path):
    """save 画像时保留 llm/skills 等其它段。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"llm": {"model": "x"}, "user_profile": {"content": "old"}}),
        encoding="utf-8",
    )
    save_profile_content("new", source="user", session_id=None, settings_path=sp)
    data = json.loads(sp.read_text(encoding="utf-8"))
    assert data["llm"]["model"] == "x"
    assert data["user_profile"]["content"] == "new"


def test_save_profile_content_creates_file_if_missing(tmp_path):
    """settings.json 不存在时 save 能创建。"""
    sp = tmp_path / "settings.json"
    save_profile_content("x", source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.content == "x"


def test_save_profile_content_returns_old(tmp_path):
    """save 返回 old content(供 history 用)。"""
    sp = tmp_path / "settings.json"
    save_profile_content("old", source="user", session_id=None, settings_path=sp)
    old, snapshot_before = save_profile_content(
        "new", source="user", session_id=None, settings_path=sp
    )
    assert old == "old"
    assert snapshot_before["content"] == "old"


def test_reset_profile_to_default(tmp_path):
    """reset 到默认模板。"""
    sp = tmp_path / "settings.json"
    save_profile_content("custom", source="user", session_id=None, settings_path=sp)
    reset_profile_to_default(source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.content == DEFAULT_PROFILE_TEMPLATE


def test_clear_profile(tmp_path):
    """clear 整篇置空。"""
    sp = tmp_path / "settings.json"
    save_profile_content("custom", source="user", session_id=None, settings_path=sp)
    clear_profile(source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.content == ""


def test_save_profile_content_concurrent_safe(tmp_path):
    """两线程并发写,后写的胜(threading.Lock,不损坏文件)。"""
    sp = tmp_path / "settings.json"
    save_profile_content("init", source="user", session_id=None, settings_path=sp)

    def worker(value: str):
        save_profile_content(value, source="user", session_id=None, settings_path=sp)

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    p = load_profile(settings_path=sp)
    # 不损坏,值是 A 或 B 之一(不是混合 garbage)
    assert p.content in ("A", "B")
