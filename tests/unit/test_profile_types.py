from __future__ import annotations

from taisang.user_profile.types import DEFAULT_PROFILE_TEMPLATE, UserProfile


def test_user_profile_defaults_empty_content():
    p = UserProfile()
    assert p.content == ""


def test_user_profile_accepts_content():
    p = UserProfile(content="### 技术栈\nPython/Go")
    assert p.content == "### 技术栈\nPython/Go"


def test_user_profile_ignores_extra_fields():
    p = UserProfile(content="x", extra="ignored")  # type: ignore[call-arg]
    assert p.content == "x"


def test_default_profile_template_has_5_headings():
    """默认模板含 5 个 ### 标题骨架。"""
    assert "### 技术栈" in DEFAULT_PROFILE_TEMPLATE
    assert "### 代码风格" in DEFAULT_PROFILE_TEMPLATE
    assert "### 沟通" in DEFAULT_PROFILE_TEMPLATE
    assert "### 环境" in DEFAULT_PROFILE_TEMPLATE
    assert "### 禁忌" in DEFAULT_PROFILE_TEMPLATE
