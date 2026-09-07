"""PromptsConfig 持久化层单测:load/save/reset,use_default 切换,损坏文件 fallback。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taisang.config import (
    PromptOverride,
    PromptsConfig,
    load_prompts,
    reset_prompt_override,
    save_prompt_override,
)


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """把 ~/.taisang/settings.json 重定向到 tmp_path。"""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home / ".taisang" / "settings.json"


def test_load_prompts_no_file_all_default(tmp_settings):
    """无 settings.json → 全 use_default=true。"""
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is True
    assert cfg.autocompact_prompt.use_default is True
    assert cfg.session_memory_template.use_default is True
    assert cfg.session_memory_update_prompt.use_default is True


def test_save_prompt_override_sets_use_default_false(tmp_settings):
    """save 后 use_default=false,value 写入。"""
    save_prompt_override("system_prompt", "你是自定义 agent。")
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is False
    assert cfg.system_prompt.value == "你是自定义 agent。"


def test_reset_prompt_override_sets_use_default_true(tmp_settings):
    """reset 后 use_default=true,value 清空。"""
    save_prompt_override("system_prompt", "自定义")
    reset_prompt_override("system_prompt")
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is True
    assert cfg.system_prompt.value == ""


def test_save_preserves_other_keys(tmp_settings):
    """保存 prompts 不丢 llm / skills 字段。"""
    # 先写一个含 llm 的 settings.json
    tmp_settings.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.write_text(
        json.dumps({"llm": {"model": "gpt-4o", "api_key": "k", "base_url": "u"}}),
        encoding="utf-8",
    )
    save_prompt_override("autocompact_prompt", "自定义摘要")
    raw = json.loads(tmp_settings.read_text(encoding="utf-8"))
    assert raw["llm"]["model"] == "gpt-4o"
    assert raw["prompts"]["autocompact_prompt"]["value"] == "自定义摘要"


def test_corrupted_settings_falls_back_to_default(tmp_settings):
    """损坏 settings.json → fallback 默认。"""
    tmp_settings.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.write_text("not json {{{", encoding="utf-8")
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is True


def test_save_empty_value_raises(tmp_settings):
    """空 value → ValueError。"""
    with pytest.raises(ValueError, match="不能为空"):
        save_prompt_override("system_prompt", "")


def test_save_too_long_value_raises(tmp_settings):
    """超 50KB → ValueError。"""
    with pytest.raises(ValueError, match="过长"):
        save_prompt_override("system_prompt", "x" * (50 * 1024 + 1))


def test_save_invalid_key_raises(tmp_settings):
    """非法 key → ValueError。"""
    with pytest.raises(ValueError, match="非法 key"):
        save_prompt_override("nonexistent_key", "xxx")


def test_reset_invalid_key_raises(tmp_settings):
    with pytest.raises(ValueError, match="非法 key"):
        reset_prompt_override("nonexistent_key")