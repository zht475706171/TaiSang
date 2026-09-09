"""画像段格式化:5 栏拼接成 system prompt 的 ## 用户画像 段。

总长超 500 按栏顺序截断尾部(空栏跳过)。全空返回空串。
"""

from __future__ import annotations

from .types import PROFILE_FIELD_LABELS, ProfileFieldKey, UserProfile

# 5 栏总和上限:注入 system prompt 时的 token 预算控制
_PROFILE_BUDGET = 500

# 栏顺序(按 ProfileFieldKey 枚举顺序)
_FIELD_ORDER: tuple[ProfileFieldKey, ...] = (
    "tech_stack",
    "code_style",
    "communication",
    "environment",
    "taboos",
)


def format_profile_section(profile: UserProfile) -> str:
    """格式化画像段(不含 ## 用户画像 头,头由 build_system_prompt 加)。

    5 栏按顺序拼接,空栏跳过。总长超 500 按栏顺序截断尾部。全空返回空串。
    """
    parts: list[str] = []
    for field in _FIELD_ORDER:
        content = getattr(profile, field)
        if content:
            parts.append(f"### {PROFILE_FIELD_LABELS[field]}\n{content}")

    if not parts:
        return ""

    full = "\n\n".join(parts)
    if len(full) <= _PROFILE_BUDGET:
        return full

    # 超预算:按栏顺序截断尾部
    return full[:_PROFILE_BUDGET]
