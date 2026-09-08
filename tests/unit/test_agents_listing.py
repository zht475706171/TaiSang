# tests/unit/test_agents_listing.py
"""Agent 清单格式化单测。"""
from __future__ import annotations

from pathlib import Path

from taisang.agents.listing import format_agent_listing
from taisang.agents.types import AgentDefinition


def _make_agent(name: str, when: str = "desc", tools=None, disallowed=None) -> AgentDefinition:
    return AgentDefinition(
        agent_type=name,
        when_to_use=when,
        tools=tools,
        disallowed_tools=disallowed or [],
        base_dir=Path("/tmp"),
        system_prompt="body",
    )


def test_format_empty() -> None:
    """空列表返回空字符串。"""
    assert format_agent_listing([]) == ""


def test_format_disabled_filtered() -> None:
    """disabled 的 agent 不列出。"""
    a1 = _make_agent("explore", "搜索")
    a2 = _make_agent("plan", "规划")
    a2.disabled = True
    out = format_agent_listing([a1, a2])
    assert "explore" in out
    assert "plan" not in out


def test_format_basic_line() -> None:
    """每行格式:- type: whenToUse (Tools: ...)。"""
    a = _make_agent("explore", "只读搜索", tools=["Read", "Grep"])
    out = format_agent_listing([a])
    assert out == "- explore: 只读搜索 (Tools: Read, Grep)"


def test_format_all_tools() -> None:
    """tools=None 显示 All tools。"""
    a = _make_agent("general-purpose", "通用", tools=None)
    out = format_agent_listing([a])
    assert "All tools" in out


def test_format_disallowed_only() -> None:
    """只有 disallowed_tools 显示 'All tools except X, Y'。"""
    a = _make_agent("explore", "搜索", tools=None, disallowed=["Edit", "Write", "Agent"])
    out = format_agent_listing([a])
    assert "All tools except Edit, Write, Agent" in out


def test_format_long_desc_truncated() -> None:
    """超长 description 截断到 250 字符 + …(… 在 desc 截断处,Tools 段跟在后面)。"""
    long_desc = "x" * 300
    a = _make_agent("explore", long_desc)
    out = format_agent_listing([a])
    line = out.split("\n")[0]
    assert len(line) <= 280  # 250 desc + 前缀(11) + Tools 段(19)
    # … 在 desc 截断处,后面跟 (Tools: ...)
    assert "… (Tools:" in line


def test_format_budget_degradation() -> None:
    """超总预算时降级:逐条截断 description,总长度受控。"""
    # 30 agents, when=100, budget=1500 → per-entry 路径(max_desc ≈ 25, > MIN_DESC_LENGTH)
    agents = [_make_agent(f"a{i}", "y" * 100) for i in range(30)]
    out = format_agent_listing(agents, char_budget=1500)
    # 仍能列出所有 agent name
    for i in range(30):
        assert f"a{i}" in out
    # 总长度受控(精确 name_overhead 后应 ≤ budget)
    assert len(out) <= 1500
    # 至少有一行被截断(含 …)
    assert "…" in out


def test_format_extreme_degradation_names_only() -> None:
    """极端降级:预算极小时只留名字,且总长度受控。"""
    agents = [_make_agent(f"a{i}", "y" * 100) for i in range(20)]
    out = format_agent_listing(agents, char_budget=100)
    lines = [l for l in out.split("\n") if l]
    # 每行只剩 - aN,无 y
    for line in lines:
        assert line.startswith("- a") and "y" not in line
    # 总长度受控
    assert len(out) <= 100
    # 至少列出部分 agent(可能不全,因 budget 限制)
    assert len(lines) >= 1


def test_format_all_disabled_returns_empty() -> None:
    """所有 agent 都 disabled 时返回空字符串。"""
    a1 = _make_agent("explore", "搜索")
    a2 = _make_agent("plan", "规划")
    a1.disabled = True
    a2.disabled = True
    assert format_agent_listing([a1, a2]) == ""