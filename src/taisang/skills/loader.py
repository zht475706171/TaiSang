from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import Skill

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n(.*)$", re.DOTALL)

BUILTIN_SKILLS_DIR = Path(__file__).parent / "builtin"


def _parse_skill_md(path: Path, source: str, plugin_name: str | None = None) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        content = text.strip()
        first_para = content.split("\n\n")[0].strip()[:200]
        return Skill(
            name=path.parent.name,
            description=first_para or "(no description)",
            when_to_use="",
            allowed_tools=None,
            dir_path=path.parent,
            content=content,
            source=source,
            plugin_name=plugin_name,
        )
    fm_text, content = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None
    name = str(fm.get("name") or path.parent.name)
    desc = str(
        fm.get("description")
        or content.split("\n\n")[0].strip()[:200]
        or "(no description)"
    )
    when = str(fm.get("when_to_use") or "")
    allowed = fm.get("allowed_tools")
    if allowed is not None:
        if isinstance(allowed, str):
            allowed = [allowed]
        allowed = [str(t) for t in allowed]
    return Skill(
        name=name,
        description=desc,
        when_to_use=when,
        allowed_tools=allowed,
        dir_path=path.parent,
        content=content.strip(),
        source=source,
        plugin_name=plugin_name,
    )


def load_skills(
    user_dirs: list[Path],
    project_dirs: list[Path],
    system_dirs: list[Path] | None = None,
) -> list[Skill]:
    """扫描三源 skill 目录,返回去重后的 Skill 列表。

    优先级(同名覆盖):project > user > system。
    支持两种目录形态:
    - 旧单层:<dir>/<skill>/SKILL.md
    - plugin 二层:<dir>/<plugin>/<skill>/SKILL.md(plugin_name 取 <plugin>)

    system_dirs 默认取包内 builtin/ 目录(内置 skill,不可删除)。
    """
    if system_dirs is None:
        system_dirs = [BUILTIN_SKILLS_DIR]
    by_name: dict[str, Skill] = {}
    # 顺序即优先级:后面的源覆盖前面的
    for source, dirs in [
        ("system", system_dirs),
        ("user", user_dirs),
        ("project", project_dirs),
    ]:
        for d in dirs:
            if not d.is_dir():
                continue
            # 旧单层:<dir>/<skill>/SKILL.md
            for skill_md in sorted(d.glob("*/SKILL.md")):
                skill = _parse_skill_md(skill_md, source, plugin_name=None)
                if skill is None:
                    continue
                by_name[skill.name] = skill
            # plugin 二层:<dir>/<plugin>/<skill>/SKILL.md
            for skill_md in sorted(d.glob("*/*/SKILL.md")):
                plugin_name = skill_md.parent.parent.name
                skill = _parse_skill_md(skill_md, source, plugin_name=plugin_name)
                if skill is None:
                    continue
                by_name[skill.name] = skill
    return list(by_name.values())