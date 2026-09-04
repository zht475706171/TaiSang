"""Skill 清单格式化:把 skill 列表渲染成 system prompt 尾部的清单段。"""

from __future__ import annotations
from .types import Skill

MAX_LISTING_DESC_CHARS = 250
MIN_DESC_LENGTH = 20

def _entry(skill: Skill) -> str:
    desc = skill.description
    if skill.when_to_use:
        desc = f"{skill.description} - {skill.when_to_use}"
    if len(desc) > MAX_LISTING_DESC_CHARS:
        desc = desc[:MAX_LISTING_DESC_CHARS - 1] + "…"
    return f"- {skill.name}: {desc}"

def format_skill_listing(skills: list[Skill], char_budget: int = 2000) -> str:
    """格式化 skill 清单为 system prompt 尾部段落。空列表返回空字符串。

    渐进披露:每条只含 name + description + when_to_use,正文在调用时才注入。
    超长降级:每条 ≤250 字符;超总预算则逐条截断 description;极端时只留名字。
    disabled 的 skill 不列出。
    """
    if not skills:
        return ""
    enabled = [s for s in skills if not s.disabled]
    if not enabled:
        return ""
    full = "\n".join(_entry(s) for s in enabled)
    if len(full) <= char_budget:
        return full
    # 降级:逐条截断 description
    name_overhead = sum(len(s.name) + 4 for s in enabled) + (len(enabled) - 1)
    available = char_budget - name_overhead
    max_desc = available // len(enabled)
    if max_desc < MIN_DESC_LENGTH:
        # 极端降级:只留名字
        return "\n".join(f"- {s.name}" for s in enabled)
    lines = []
    for s in enabled:
        desc = s.description
        if s.when_to_use:
            desc = f"{s.description} - {s.when_to_use}"
        if len(desc) > max_desc:
            desc = desc[:max_desc - 1] + "…"
        lines.append(f"- {s.name}: {desc}")
    return "\n".join(lines)