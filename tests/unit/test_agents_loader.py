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


def test_load_builtin_agents() -> None:
    """默认 system_dirs 加载 4 个内置 agent。"""
    from taisang.agents.loader import load_agents, BUILTIN_AGENTS_DIR
    agents = load_agents(user_dirs=[], project_dirs=[], system_dirs=[BUILTIN_AGENTS_DIR])
    names = {a.agent_type for a in agents}
    assert names == {"general-purpose", "explore", "plan", "verification"}
    # verification 是 background
    verif = next(a for a in agents if a.agent_type == "verification")
    assert verif.background is True
    assert verif.max_turns == 100
    # explore / plan / verification 黑名单含 Edit/Write/Agent
    for name in ("explore", "plan", "verification"):
        a = next(a for a in agents if a.agent_type == name)
        assert "Edit" in a.disallowed_tools
        assert "Write" in a.disallowed_tools
        assert "Agent" in a.disallowed_tools
    # general-purpose 全工具
    gp = next(a for a in agents if a.agent_type == "general-purpose")
    assert gp.tools is not None
    assert set(gp.tools) == {"Read", "Grep", "Glob", "Edit", "Write", "Bash"}


def test_builtin_agents_packaged_in_wheel() -> None:
    """wheel 包含 builtin AGENT.md(setuptools package-data 生效)。"""
    # 这个测试只验证文件存在于源码目录,wheel 打包靠 pyproject.toml 配置
    from taisang.agents.loader import BUILTIN_AGENTS_DIR
    for name in ("general-purpose", "explore", "plan", "verification"):
        assert (BUILTIN_AGENTS_DIR / name / "AGENT.md").is_file()


def test_load_agents_with_state_applies_disabled(tmp_path: Path, monkeypatch) -> None:
    """load_agents_with_state 读 agents_state.json,把 disabled=True 的 agent 标记禁用。"""
    from taisang.agents.loader import load_agents_with_state
    user_dir = tmp_path / "user"
    _write_agent_md(user_dir, "explore", "name: explore\ndescription: ok\n", "body")
    _write_agent_md(user_dir, "plan", "name: plan\ndescription: ok\n", "body")
    # state 文件:explore 禁用,plan 不禁
    state_file = tmp_path / "agents_state.json"
    state_file.write_text('{"explore": true}', encoding="utf-8")
    # monkeypatch state 文件路径
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", state_file)
    agents = load_agents_with_state(source_root=tmp_path, user_dirs=[user_dir], project_dirs=[])
    by_type = {a.agent_type: a for a in agents}
    assert by_type["explore"].disabled is True
    assert by_type["plan"].disabled is False


def test_load_agents_with_state_missing_file_no_error(tmp_path: Path, monkeypatch) -> None:
    """state 文件不存在时,所有 agent disabled=False,不报错。"""
    from taisang.agents.loader import load_agents_with_state
    user_dir = tmp_path / "user"
    _write_agent_md(user_dir, "explore", "name: explore\ndescription: ok\n", "body")
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "nonexistent.json")
    agents = load_agents_with_state(source_root=tmp_path, user_dirs=[user_dir], project_dirs=[])
    assert all(not a.disabled for a in agents)