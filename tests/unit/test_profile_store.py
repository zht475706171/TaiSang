from __future__ import annotations

import json
import threading

from taisang.user_profile.store import (
    load_profile,
    reset_profile_field,
    save_profile_field,
)


def test_load_profile_missing_file(tmp_path):
    """settings.json 不存在 → 空 UserProfile。"""
    p = load_profile(settings_path=tmp_path / "nope.json")
    assert p.tech_stack == ""


def test_load_profile_no_user_profile_section(tmp_path):
    """settings.json 有文件但无 user_profile 段 → 空。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"llm": {"model": "x"}}), encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.tech_stack == ""


def test_load_profile_corrupt_json(tmp_path):
    """损坏 JSON → 空(复用 _load_settings_file 容错)。"""
    sp = tmp_path / "settings.json"
    sp.write_text("{not valid json", encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.tech_stack == ""


def test_load_profile_wrong_section_type(tmp_path):
    """user_profile 段非 dict → 空。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"user_profile": "not a dict"}), encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.tech_stack == ""


def test_load_profile_partial_fields(tmp_path):
    """部分字段缺失 → 缺失字段填默认空。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"user_profile": {"tech_stack": "Python"}}), encoding="utf-8")
    p = load_profile(settings_path=sp)
    assert p.tech_stack == "Python"
    assert p.code_style == ""


def test_save_profile_field_updates_one_field(tmp_path):
    """save 单栏,别栏不动。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"user_profile": {"tech_stack": "Python", "code_style": "4 空格"}}),
        encoding="utf-8",
    )
    save_profile_field("tech_stack", "Go", source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.tech_stack == "Go"
    assert p.code_style == "4 空格"  # 别栏保留


def test_save_profile_field_preserves_other_sections(tmp_path):
    """save 画像时保留 llm/skills 等其它段。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"llm": {"model": "x"}, "user_profile": {"tech_stack": "Python"}}),
        encoding="utf-8",
    )
    save_profile_field("tech_stack", "Go", source="user", session_id=None, settings_path=sp)
    data = json.loads(sp.read_text(encoding="utf-8"))
    assert data["llm"]["model"] == "x"
    assert data["user_profile"]["tech_stack"] == "Go"


def test_save_profile_field_creates_file_if_missing(tmp_path):
    """settings.json 不存在时 save 能创建。"""
    sp = tmp_path / "settings.json"
    save_profile_field("tech_stack", "Go", source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.tech_stack == "Go"


def test_reset_profile_field_clears_one_field(tmp_path):
    """reset 清空单栏,别栏不动。"""
    sp = tmp_path / "settings.json"
    sp.write_text(
        json.dumps({"user_profile": {"tech_stack": "Python", "code_style": "4 空格"}}),
        encoding="utf-8",
    )
    reset_profile_field("tech_stack", source="user", session_id=None, settings_path=sp)
    p = load_profile(settings_path=sp)
    assert p.tech_stack == ""
    assert p.code_style == "4 空格"


def test_save_profile_field_concurrent_safe(tmp_path):
    """两线程并发各改一栏,结果都保留(threading.Lock)。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"user_profile": {}}), encoding="utf-8")

    def worker(field: str, value: str):
        save_profile_field(field, value, source="user", session_id=None, settings_path=sp)

    t1 = threading.Thread(target=worker, args=("tech_stack", "Python"))
    t2 = threading.Thread(target=worker, args=("code_style", "4 空格"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    p = load_profile(settings_path=sp)
    assert p.tech_stack == "Python"
    assert p.code_style == "4 空格"


def test_save_profile_field_returns_old_value(tmp_path):
    """save 返回 old 值(供 history 用)。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"user_profile": {"tech_stack": "Python"}}), encoding="utf-8")
    old, snapshot_before = save_profile_field(
        "tech_stack", "Go", source="user", session_id=None, settings_path=sp
    )
    assert old == "Python"
    assert snapshot_before["tech_stack"] == "Python"
