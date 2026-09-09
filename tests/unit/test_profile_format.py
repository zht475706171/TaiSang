from __future__ import annotations

from taisang.user_profile.format import format_profile_section
from taisang.user_profile.types import UserProfile


def test_format_empty_profile_returns_empty():
    """全空画像 → 空串(不注入段)。"""
    assert format_profile_section(UserProfile()) == ""


def test_format_partial_profile_skips_empty_fields():
    """部分栏空 → 跳过空栏。"""
    p = UserProfile(
        tech_stack="Python/Go", code_style="", communication="中文", environment="", taboos=""
    )
    out = format_profile_section(p)
    assert "### 技术栈" in out
    assert "Python/Go" in out
    assert "### 沟通" in out
    assert "中文" in out
    # 空栏不出现
    assert "### 代码风格" not in out
    assert "### 环境" not in out
    assert "### 禁忌" not in out


def test_format_full_profile_all_sections():
    """5 栏都有 → 全部出现,按顺序。"""
    p = UserProfile(
        tech_stack="Python",
        code_style="4 空格",
        communication="中文",
        environment="Windows",
        taboos="别动 main",
    )
    out = format_profile_section(p)
    # 顺序:技术栈 → 代码风格 → 沟通 → 环境 → 禁忌
    idx_tech = out.index("### 技术栈")
    idx_code = out.index("### 代码风格")
    idx_comm = out.index("### 沟通")
    idx_env = out.index("### 环境")
    idx_taboo = out.index("### 禁忌")
    assert idx_tech < idx_code < idx_comm < idx_env < idx_taboo


def test_format_truncates_over_500_chars():
    """总长 >500 → 截断到 500。"""
    # tech_stack 400 字 + code_style 400 字 = 800,超 500
    long_a = "A" * 400
    long_b = "B" * 400
    p = UserProfile(tech_stack=long_a, code_style=long_b)
    out = format_profile_section(p)
    assert len(out) <= 500
    # 前 400 个 A 应保留(在截断点之前)
    assert "A" * 100 in out


def test_format_truncation_keeps_partial_last_section():
    """截断点在栏中间 → 保留半截(不强行修)。"""
    p = UserProfile(tech_stack="X" * 300, code_style="Y" * 300)
    out = format_profile_section(p)
    # 总长应 ≤500,tech_stack 完整保留,code_style 被截断
    assert "X" * 100 in out
    # 不会出现完整的 code_style(300 个 Y 全在 500 外)
    assert "Y" * 300 not in out
