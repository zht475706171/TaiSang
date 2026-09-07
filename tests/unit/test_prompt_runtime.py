"""prompt 运行时读取单测:get_system_prompt / get_autocompact_prompt / get_template / get_update_prompt。"""

from __future__ import annotations

from pathlib import Path

import pytest

from taisang.config import reset_prompt_override, save_prompt_override
from taisang.agent_core.prompts import SYSTEM_PROMPT, build_system_prompt, get_system_prompt
from taisang.compaction.prompts import (
    BASE_COMPACT_PROMPT,
    DEFAULT_AUTOCOMPACT_PROMPT,
    NO_TOOLS_PREAMBLE,
    NO_TOOLS_TRAILER,
    get_autocompact_prompt,
)
from taisang.session_memory.template import DEFAULT_TEMPLATE, DEFAULT_UPDATE_PROMPT, get_template, get_update_prompt


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    yield
    # 每个测试后清理:把所有 key 重置回默认(防测试间污染)
    for key in ["system_prompt", "autocompact_prompt", "session_memory_template", "session_memory_update_prompt"]:
        try:
            reset_prompt_override(key)
        except Exception:
            pass


def test_get_system_prompt_default_returns_constant(tmp_settings):
    """use_default 时返回代码常量 SYSTEM_PROMPT。"""
    assert get_system_prompt() == SYSTEM_PROMPT


def test_get_system_prompt_custom_returns_value(tmp_settings):
    """自定义时返回 value。"""
    save_prompt_override("system_prompt", "你是自定义 agent。")
    assert get_system_prompt() == "你是自定义 agent。"


def test_build_system_prompt_uses_custom_system(tmp_settings):
    """build_system_prompt 用自定义 system prompt + 拼 skills 段。"""
    save_prompt_override("system_prompt", "自定义基座。")
    result = build_system_prompt(skills_section="## Skills\n- skill1", mcp_section="")
    assert result.startswith("自定义基座。")
    assert "## Skills\n- skill1" in result


def test_build_system_prompt_default(tmp_settings):
    """默认时 build_system_prompt 用 SYSTEM_PROMPT + 拼段。"""
    result = build_system_prompt(skills_section="X", mcp_section="Y")
    assert result.startswith(SYSTEM_PROMPT)
    assert "X" in result and "Y" in result


def test_get_autocompact_prompt_default(tmp_settings):
    """默认时返回三段 + {conversation} 替换后的文本。"""
    result = get_autocompact_prompt("你好世界")
    assert NO_TOOLS_PREAMBLE in result
    assert BASE_COMPACT_PROMPT in result
    assert NO_TOOLS_TRAILER in result
    assert "你好世界" in result
    # 确认默认值里 {conversation} 被替换
    assert "{conversation}" not in result


def test_get_autocompact_prompt_custom(tmp_settings):
    """自定义时用 value,替换 {conversation}。"""
    save_prompt_override("autocompact_prompt", "前缀\n{conversation}\n后缀")
    result = get_autocompact_prompt("对话内容")
    assert result == "前缀\n对话内容\n后缀"


def test_get_template_default(tmp_settings):
    assert get_template() == DEFAULT_TEMPLATE


def test_get_template_custom(tmp_settings):
    save_prompt_override("session_memory_template", "自定义模板")
    assert get_template() == "自定义模板"


def test_get_update_prompt_default(tmp_settings):
    result = get_update_prompt(current_notes="现有笔记", memory_path="/tmp/notes.md")
    assert "{current_notes}" not in result
    assert "现有笔记" in result
    assert "/tmp/notes.md" in result


def test_get_update_prompt_custom(tmp_settings):
    save_prompt_override(
        "session_memory_update_prompt",
        "更新笔记 {memory_path}\n当前:\n{current_notes}",
    )
    result = get_update_prompt(current_notes="N", memory_path="/p.md")
    assert result == "更新笔记 /p.md\n当前:\nN"