"""用户画像数据模型。"""

from __future__ import annotations

from pydantic import BaseModel

# 默认画像模板:5 个空标题骨架。用户点「恢复默认模板」时画像变成这个。
# 用户/agent 在各标题下用自由文本填写偏好。空标题段 format 时会被跳过。
DEFAULT_PROFILE_TEMPLATE = """### 技术栈

### 代码风格

### 沟通

### 环境

### 禁忌"""


class UserProfile(BaseModel):
    """用户画像:单字段自由 markdown,用 ### 标题分段。

    空串表示未填(不注入 system prompt)。
    默认模板是 5 个空标题骨架(有标题无内容)。
    """

    model_config = {"extra": "ignore"}

    content: str = ""
