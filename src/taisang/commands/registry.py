"""CommandRegistry:按 name 查找 + 渲染正文($ARGUMENTS 替换)。

CLI 和 Web send_message 路由共用:用户输入 /name args → render(name, args)
返回渲染后正文 → 作为 user 消息走 agent.run()。
"""

from __future__ import annotations

from .types import Command


class CommandRegistry:
    """按 name 查找 command + 渲染正文。

    disabled 的 command 查不到(get/render 返回 None),等效于不存在。
    """

    def __init__(self, commands: list[Command]) -> None:
        self.commands: dict[str, Command] = {c.name: c for c in commands}

    def get(self, name: str) -> Command | None:
        """按 name 查找。disabled 或不存在返回 None。"""
        c = self.commands.get(name)
        if c is None or c.disabled:
            return None
        return c

    def render(self, name: str, args: str) -> str | None:
        """渲染 command 正文:替换 $ARGUMENTS + 拼装 header。

        找不到/disabled 返回 None。调用方据此判断是否命中 command。
        """
        c = self.get(name)
        if c is None:
            return None
        content = c.content
        # $ARGUMENTS 替换(对齐 Claude Code 约定)
        content = content.replace("$ARGUMENTS", args or "")
        # allowed_tools 提示段(对齐 skill,仅提示不硬拦)
        header = ""
        if c.allowed_tools is not None:
            tools_list = ", ".join(c.allowed_tools)
            header = f"> 执行本 command 期间,只允许使用以下工具: {tools_list}\n\n"
        return f"{header}# Command: {c.name}\n\n{content}"

    def list_enabled(self) -> list[Command]:
        """列出所有启用的 command(供 system prompt 清单用)。"""
        return [c for c in self.commands.values() if not c.disabled]

    def list_all(self) -> list[Command]:
        """列出所有 command(含 disabled,供管理 UI 用)。"""
        return list(self.commands.values())