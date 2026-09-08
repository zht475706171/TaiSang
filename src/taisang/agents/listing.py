# src/taisang/agents/listing.py
"""Agent 清单格式化:把 agent 列表渲染成 system prompt 尾部的清单段。

跟 skill listing 同构:渐进披露 + 250 字符单条上限 + 2000 字符总预算 + 降级。
"""
from __future__ import annotations

from .types import AgentDefinition

MAX_LISTING_DESC_CHARS = 250
MIN_DESC_LENGTH = 20
DEFAULT_CHAR_BUDGET = 2000


def _tools_description(agent: AgentDefinition) -> str:
    """格式化工具集段:跟 claude-code formatAgentLine 对齐。"""
    has_allowlist = agent.tools is not None and len(agent.tools) > 0
    has_denylist = len(agent.disallowed_tools) > 0
    if has_allowlist and has_denylist:
        deny_set = set(agent.disallowed_tools)
        effective = [t for t in (agent.tools or []) if t not in deny_set]
        if not effective:
            return "None"
        return ", ".join(effective)
    if has_allowlist:
        return ", ".join(agent.tools or [])
    if has_denylist:
        return f"All tools except {', '.join(agent.disallowed_tools)}"
    return "All tools"


def _entry(agent: AgentDefinition) -> str:
    desc = agent.when_to_use
    if len(desc) > MAX_LISTING_DESC_CHARS:
        desc = desc[:MAX_LISTING_DESC_CHARS - 1] + "…"
    return f"- {agent.agent_type}: {desc} (Tools: {_tools_description(agent)})"


def format_agent_listing(
    agents: list[AgentDefinition],
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> str:
    """格式化 agent 清单为 system prompt 尾部段落。空列表返回空字符串。

    渐进披露:每条只含 type + whenToUse + tools,正文在调用时才注入。
    超长降级:每条 ≤250 字符;超总预算则逐条截断 description;极端时只留名字。
    disabled 的 agent 不列出。
    """
    if not agents:
        return ""
    enabled = [a for a in agents if not a.disabled]
    if not enabled:
        return ""
    full = "\n".join(_entry(a) for a in enabled)
    if len(full) <= char_budget:
        return full
    # 逐条降级:精确测量每条非 desc 开销(格式 "- {name}: {desc} (Tools: {tools})" + 换行)
    # 固定开销: "- " + name + ": " + " (Tools: " + tools_str + ")" = name + 14 + len(tools_str)
    # 加 (n-1) 个换行符
    name_overhead = sum(
        len(a.agent_type) + 14 + len(_tools_description(a))
        for a in enabled
    ) + max(0, len(enabled) - 1)
    available = char_budget - name_overhead
    max_desc = available // len(enabled) if enabled else 0
    if max_desc < MIN_DESC_LENGTH:
        # 极端降级:只留名字,但仍保证 ≤ budget
        lines = []
        total = 0
        for a in enabled:
            line = f"- {a.agent_type}"
            extra = len(line) + (1 if lines else 0)  # 换行符(首行无)
            if total + extra > char_budget:
                break
            lines.append(line)
            total += extra
        return "\n".join(lines)
    max_desc = min(max_desc, MAX_LISTING_DESC_CHARS)  # 250 字符硬上限
    lines = []
    for a in enabled:
        desc = a.when_to_use
        if len(desc) > max_desc:
            desc = desc[:max_desc - 1] + "…"
        lines.append(f"- {a.agent_type}: {desc} (Tools: {_tools_description(a)})")
    return "\n".join(lines)