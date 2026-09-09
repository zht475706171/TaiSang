"""用户画像包:5 栏结构化画像,存 settings.json,注入 system prompt。"""

from __future__ import annotations

from .types import PROFILE_FIELD_LABELS, ProfileFieldKey, UserProfile

__all__ = ["UserProfile", "ProfileFieldKey", "PROFILE_FIELD_LABELS"]
