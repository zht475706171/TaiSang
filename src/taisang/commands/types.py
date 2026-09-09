from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Command:
    """一条 slash command 定义(从 .md 文件加载)。

    与 Skill 同构但更轻:平铺 .md 文件(不是目录套 SKILL.md)。
    用户输入 /name args 触发,正文替换 $ARGUMENTS 后作为 user 消息注入。
    """

    name: str
    description: str
    argument_hint: str  # 可空,UI 提示用户怎么传参
    allowed_tools: list[str] | None  # 可空,仅提示不硬拦(v1)
    content: str  # 正文($ARGUMENTS 占位)
    file_path: Path  # 源文件路径(导入/删除用)
    source: str  # project / user / system
    disabled: bool = False