"""用户画像包:单字段自由 markdown,存 settings.json,注入 system prompt。"""

from __future__ import annotations

from .types import DEFAULT_PROFILE_TEMPLATE, UserProfile

__all__ = ["UserProfile", "DEFAULT_PROFILE_TEMPLATE"]
