# tests/unit/test_agents_loader.py
"""Agent loader 单测。"""
from __future__ import annotations

import textwrap
from pathlib import Path

from taisang.agents.loader import load_agents


def _write_agent_md(dir_path: Path, name: str, frontmatter: str, body: str) -> Path:
    """在 dir_path/<name>/AGENT.md 写一个 agent 定义。"""
    agent_dir = dir_path / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(
        f"---\n{frontmatter}\n---\n{body}", encoding="utf-8"
    )
    return agent_dir


def test_load_agents_basic(tmp_path: Path) -> None:
    """基本加载:扫 user 目录下的 AGENT.md,解析 frontmatter + body。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir,
        "explore",
        "name: explore\ndescription: 只读搜索专家\n",
        "You are a search specialist.\n",
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert len(agents) == 1
    a = agents[0]
    assert a.agent_type == "explore"
    assert a.when_to_use == "只读搜索专家"
    assert a.system_prompt.strip() == "You are a search specialist."
    assert a.source == "user"
    assert a.tools is None
    assert a.disallowed_tools == []


def test_load_agents_priority_project_over_user(tmp_path: Path) -> None:
    """同名 agent:project 覆盖 user。"""
    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    _write_agent_md(
        user_dir, "explore", "name: explore\ndescription: user 版\n", "user body"
    )
    _write_agent_md(
        project_dir, "explore", "name: explore\ndescription: project 版\n", "project body"
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[project_dir], system_dirs=[])
    assert len(agents) == 1
    assert agents[0].when_to_use == "project 版"
    assert agents[0].source == "project"


def test_load_agents_disallowed_tools(tmp_path: Path) -> None:
    """frontmatter disallowedTools 列表解析。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir,
        "explore",
        textwrap.dedent("""
            name: explore
            description: 只读
            disallowedTools:
              - Edit
              - Write
              - Agent
        """).strip(),
        "body",
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert agents[0].disallowed_tools == ["Edit", "Write", "Agent"]


def test_load_agents_max_turns_and_background(tmp_path: Path) -> None:
    """frontmatter maxTurns / background 字段解析。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir,
        "verification",
        textwrap.dedent("""
            name: verification
            description: 验证
            maxTurns: 100
            background: true
        """).strip(),
        "body",
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    a = agents[0]
    assert a.max_turns == 100
    assert a.background is True


def test_load_agents_corrupted_skipped(tmp_path: Path) -> None:
    """损坏的 frontmatter(无效 YAML)跳过,不抛错。"""
    user_dir = tmp_path / "user"
    agent_dir = user_dir / "broken"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(
        "---\nname: broken\n  description: : : invalid\n---\nbody",
        encoding="utf-8",
    )
    _write_agent_md(
        user_dir, "good", "name: good\ndescription: ok\n", "body"
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert {a.agent_type for a in agents} == {"good"}


def test_load_agents_missing_name_fallback_to_dirname(tmp_path: Path) -> None:
    """frontmatter 缺 name 字段:用目录名兜底。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir, "no-name", "description: 没 name\n", "body"
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert len(agents) == 1
    assert agents[0].agent_type == "no-name"


def test_load_agents_empty_dirs(tmp_path: Path) -> None:
    """空目录返回空列表。"""
    agents = load_agents(user_dirs=[tmp_path / "empty"], project_dirs=[], system_dirs=[])
    assert agents == []