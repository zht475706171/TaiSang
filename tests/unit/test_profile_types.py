from __future__ import annotations

from taisang.user_profile.types import (
    PROFILE_FIELD_LABELS,
    ProfileFieldKey,
    UserProfile,
)


def test_user_profile_defaults_all_empty():
    p = UserProfile()
    assert p.tech_stack == ""
    assert p.code_style == ""
    assert p.communication == ""
    assert p.environment == ""
    assert p.taboos == ""


def test_user_profile_accepts_all_fields():
    p = UserProfile(
        tech_stack="Python/Go",
        code_style="4 空格",
        communication="中文简洁",
        environment="Windows",
        taboos="别动 main",
    )
    assert p.tech_stack == "Python/Go"
    assert p.taboos == "别动 main"


def test_user_profile_ignores_extra_fields():
    p = UserProfile(tech_stack="Python", extra="ignored")  # type: ignore[call-arg]
    assert p.tech_stack == "Python"


def test_user_profile_tolerates_missing_fields():
    p = UserProfile(tech_stack="Python")  # type: ignore[call-arg]
    assert p.tech_stack == "Python"
    assert p.code_style == ""


def test_profile_field_labels_has_5_entries():
    assert len(PROFILE_FIELD_LABELS) == 5
    assert PROFILE_FIELD_LABELS["tech_stack"] == "技术栈"
    assert PROFILE_FIELD_LABELS["code_style"] == "代码风格"
    assert PROFILE_FIELD_LABELS["communication"] == "沟通"
    assert PROFILE_FIELD_LABELS["environment"] == "环境"
    assert PROFILE_FIELD_LABELS["taboos"] == "禁忌"