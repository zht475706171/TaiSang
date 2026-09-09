"""Command 清单格式化:把 command 列表渲染成 system prompt 的清单段。

渐进披露:每条只含 name + description,正文在用户触发时才注入。
对齐 skill listing 的降级策略。
"""

from __future__ import annotations

from .types import Command

MAX_LISTING_DESC_CHARS = 250
MIN_DESC_LENGTH = 20


def _entry(cmd: Command) -> str:
    desc = cmd.description
    if cmd.argument_hint:
        desc = f"{cmd.description} (参数: {cmd.argument_hint})"
    if len(desc) > MAX_LISTING_DESC_CHARS:
        desc = desc[: MAX_LISTING_DESC_CHARS - 1] + "…"
    return f"- /{cmd.name}: {desc}"


def format_command_listing(commands: list[Command], char_budget: int = 2000) -> str:
    """格式化 command 清单为 system prompt 段落。空列表返回空字符串。

    渐进披露:每条只含 /name + description + argument_hint。
    超长降级:每条 ≤250 字符;超总预算则逐条截断;极端时只留名字。
    disabled 的 command 不列出。
    """
    if not commands:
        return ""
    enabled = [c for c in commands if not c.disabled]
    if not enabled:
        return ""
    full = "\n".join(_entry(c) for c in enabled)
    if len(full) <= char_budget:
        return full
    # 降级:逐条截断 description
    name_overhead = sum(len(c.name) + 5 for c in enabled) + (len(enabled) - 1)
    available = char_budget - name_overhead
    max_desc = available // len(enabled)
    if max_desc < MIN_DESC_LENGTH:
        # 极端降级:只留 /name
        return "\n".join(f"- /{c.name}" for c in enabled)
    lines = []
    for c in enabled:
        desc = c.description
        if c.argument_hint:
            desc = f"{c.description} (参数: {c.argument_hint})"
        if len(desc) > max_desc:
            desc = desc[: max_desc - 1] + "…"
        lines.append(f"- /{c.name}: {desc}")
    return "\n".join(lines)