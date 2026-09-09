"""Slash command 系统:用户输入 /name args 触发预定义 prompt 模板。

对标 Claude Code commands。与 Skill 系统同构(markdown + frontmatter),
但触发路径不同:Skill 是 LLM 主动调工具,Command 是用户主动输入 slash。

三源加载(project > user > system),disabled 状态持久化到
~/.taisang/commands_state.json。
"""

from .types import Command
from .loader import load_commands, BUILTIN_COMMANDS_DIR
from .registry import CommandRegistry

__all__ = [
    "Command",
    "load_commands",
    "BUILTIN_COMMANDS_DIR",
    "CommandRegistry",
]