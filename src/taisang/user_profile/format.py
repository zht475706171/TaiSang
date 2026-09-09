"""画像段格式化:直接返回 content,超 500 截断。

content 是用户/agent 用 ### 标题分段的自由 markdown。
全空(空串或只有空白)返回空串(不注入段)。
"""

from __future__ import annotations

from .types import UserProfile

# content 上限:注入 system prompt 时的 token 预算控制
_PROFILE_BUDGET = 500


def format_profile_section(profile: UserProfile) -> str:
    """格式化画像段(不含 ## 用户画像 头,头由 build_system_prompt 加)。

    直接返回 content。全空(空串或只有空白)返回空串。
    超 500 截断到 500。
    """
    content = (profile.content or "").strip()
    if not content:
        return ""
    if len(content) <= _PROFILE_BUDGET:
        return content
    return content[:_PROFILE_BUDGET]
