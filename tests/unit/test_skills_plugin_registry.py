import json
import logging
from pathlib import Path

import pytest

from taisang.skills.plugin_registry import (
    InstalledPlugin,
    load_plugins,
    save_plugins,
    upsert_plugin,
    remove_plugin,
)


def _make_plugin(name: str = "superpowers") -> InstalledPlugin:
    return InstalledPlugin(
        name=name,
        source="github:obra/superpowers",
        version="5.1.0",
        git_commit_sha="f2cbfbefebbf",
        installed_at="2026-09-11T10:00:00Z",
        skills=["brainstorming", "writing-plans"],
    )


def test_load_plugins_empty_file(tmp_path):
    f = tmp_path / "plugins.json"
    f.write_text("{}", encoding="utf-8")
    assert load_plugins(f) == {}


def test_load_plugins_missing_file(tmp_path):
    f = tmp_path / "plugins.json"
    assert load_plugins(f) == {}


def test_load_plugins_corrupted_returns_empty(tmp_path, caplog):
    f = tmp_path / "plugins.json"
    f.write_text("{not valid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        result = load_plugins(f)
    assert result == {}
    assert "损坏" in caplog.text


def test_save_and_load_roundtrip(tmp_path):
    f = tmp_path / "plugins.json"
    plugins = {"superpowers": _make_plugin()}
    save_plugins(f, plugins)
    loaded = load_plugins(f)
    assert "superpowers" in loaded
    assert loaded["superpowers"].version == "5.1.0"
    assert loaded["superpowers"].skills == ["brainstorming", "writing-plans"]


def test_save_plugins_writes_version_envelope(tmp_path):
    f = tmp_path / "plugins.json"
    save_plugins(f, {"superpowers": _make_plugin()})
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert "superpowers" in raw["plugins"]


def test_upsert_plugin_overwrites_same_name(tmp_path):
    f = tmp_path / "plugins.json"
    upsert_plugin(f, _make_plugin("superpowers"))
    # 同名不同版本
    p2 = _make_plugin("superpowers")
    p2.version = "5.2.0"
    upsert_plugin(f, p2)
    loaded = load_plugins(f)
    assert len(loaded) == 1
    assert loaded["superpowers"].version == "5.2.0"


def test_upsert_plugin_preserves_others(tmp_path):
    f = tmp_path / "plugins.json"
    upsert_plugin(f, _make_plugin("superpowers"))
    upsert_plugin(f, _make_plugin("other-plugin"))
    loaded = load_plugins(f)
    assert set(loaded.keys()) == {"superpowers", "other-plugin"}


def test_remove_plugin_removes_entry(tmp_path):
    f = tmp_path / "plugins.json"
    upsert_plugin(f, _make_plugin("superpowers"))
    remove_plugin(f, "superpowers")
    assert load_plugins(f) == {}


def test_remove_plugin_missing_is_noop(tmp_path):
    f = tmp_path / "plugins.json"
    # 不存在不报错
    remove_plugin(f, "nonexistent")
    assert load_plugins(f) == {}


def test_save_plugins_atomic_write(tmp_path):
    """原子写:中途 .tmp 文件存在,最终 .json 完整。"""
    f = tmp_path / "plugins.json"
    save_plugins(f, {"superpowers": _make_plugin()})
    # 最终文件存在且可解析
    assert f.exists()
    json.loads(f.read_text(encoding="utf-8"))
    # 不应残留 .tmp
    assert not f.with_suffix(".json.tmp").exists()