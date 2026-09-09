from __future__ import annotations

from taisang.user_profile.format import format_profile_section
from taisang.user_profile.types import DEFAULT_PROFILE_TEMPLATE, UserProfile


def test_format_empty_content_returns_empty():
    """空 content → 空串(不注入段)。"""
    assert format_profile_section(UserProfile(content="")) == ""
    assert format_profile_section(UserProfile()) == ""


def test_format_whitespace_only_returns_empty():
    """只有空白 → 空串。"""
    assert format_profile_section(UserProfile(content="   \n\n  ")) == ""


def test_format_returns_content_as_is():
    """有内容 → 直接返回(stripped)。"""
    p = UserProfile(content="### 技术栈\nPython/Go\n\n### 沟通\n中文")
    out = format_profile_section(p)
    assert "### 技术栈" in out
    assert "Python/Go" in out
    assert "### 沟通" in out
    assert "中文" in out


def test_format_default_template_returns_template():
    """默认模板(5 空标题骨架) → 返回模板(标题都在,无内容)。"""
    p = UserProfile(content=DEFAULT_PROFILE_TEMPLATE)
    out = format_profile_section(p)
    assert "### 技术栈" in out
    assert "### 禁忌" in out


def test_format_truncates_over_500():
    """超 500 → 截断到 500。"""
    long_content = "### 技术栈\n" + "A" * 600
    p = UserProfile(content=long_content)
    out = format_profile_section(p)
    assert len(out) <= 500
    assert "### 技术栈" in out
    assert "A" * 100 in out  # 前部分保留
