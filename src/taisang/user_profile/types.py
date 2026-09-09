"""用户画像数据模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ProfileFieldKey = Literal["tech_stack", "code_style", "communication", "environment", "taboos"]

PROFILE_FIELD_LABELS: dict[ProfileFieldKey, str] = {
    "tech_stack": "技术栈",
    "code_style": "代码风格",
    "communication": "沟通",
    "environment": "环境",
    "taboos": "禁忌",
}


class UserProfile(BaseModel):
    """用户画像:5 栏,空串表示未填。"""

    model_config = {"extra": "ignore"}

    tech_stack: str = ""
    code_style: str = ""
    communication: str = ""
    environment: str = ""
    taboos: str = ""