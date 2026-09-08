# src/taisang/agents/loader.py
"""Agent 定义文件加载。

复用 skill loader 的套路:三源扫描 + 优先级合并(project > user > system) +
PyYAML frontmatter 解析 + 损坏文件跳过。

AGENT.md 目录约定:每个 agent 一个目录,目录名 = agent name,里面一个 AGENT.md。
跟 skill 的 SKILL.md 同构。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import AgentDefinition

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n(.*)$", re.DOTALL)

BUILTIN_AGENTS_DIR = Path(__file__).parent / "builtin"


def _parse_agent_md(path: Path, source: str) -> AgentDefinition | None:
    """解析单个 AGENT.md,失败返回 None(由 caller 跳过)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 无 frontmatter,用目录名 + 全文当 system_prompt
        content = text.strip()
        first_para = content.split("\n\n")[0].strip()[:200]
        return AgentDefinition(
            agent_type=path.parent.name,
            when_to_use=first_para or "(no description)",
            system_prompt=content,
            source=source,
            base_dir=path.parent,
        )
    fm_text, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None
    name = str(fm.get("name") or path.parent.name)
    desc = str(fm.get("description") or "")
    if not desc:
        desc = body.strip().split("\n\n")[0].strip()[:200] or "(no description)"
    tools = fm.get("tools")
    if tools is not None:
        if isinstance(tools, str):
            tools = [tools]
        tools = [str(t) for t in tools]
    disallowed = fm.get("disallowedTools") or []
    if isinstance(disallowed, str):
        disallowed = [disallowed]
    disallowed = [str(t) for t in disallowed]
    max_turns_raw = fm.get("maxTurns")
    max_turns = int(max_turns_raw) if isinstance(max_turns_raw, (int, float)) else None
    background = bool(fm.get("background", False))
    model_raw = fm.get("model")
    model = "inherit" if isinstance(model_raw, str) and model_raw.strip().lower() == "inherit" else None
    return AgentDefinition(
        agent_type=name,
        when_to_use=desc,
        tools=tools,
        disallowed_tools=disallowed,
        max_turns=max_turns,
        background=background,
        model=model,
        source=source,
        base_dir=path.parent,
        system_prompt=body.strip(),
    )


def load_agents(
    user_dirs: list[Path],
    project_dirs: list[Path],
    system_dirs: list[Path] | None = None,
) -> list[AgentDefinition]:
    """扫描三源 agent 目录,返回去重后的 AgentDefinition 列表。

    优先级(同名覆盖):project > user > system。
    system_dirs 默认取包内 builtin/ 目录(内置 agent,不可删除)。
    """
    if system_dirs is None:
        system_dirs = [BUILTIN_AGENTS_DIR]
    by_name: dict[str, AgentDefinition] = {}
    for source, dirs in [
        ("system", system_dirs),
        ("user", user_dirs),
        ("project", project_dirs),
    ]:
        for d in dirs:
            if not d.is_dir():
                continue
            for agent_md in sorted(d.glob("*/AGENT.md")):
                agent = _parse_agent_md(agent_md, source)
                if agent is None:
                    continue
                by_name[agent.agent_type] = agent
    return list(by_name.values())