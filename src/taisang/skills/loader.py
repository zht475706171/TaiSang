from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import Skill

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n(.*)$", re.DOTALL)


def _parse_skill_md(path: Path, source: str) -> Skill | None:
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
    )


def load_skills(user_dirs: list[Path], project_dirs: list[Path]) -> list[Skill]:
    by_name: dict[str, Skill] = {}
    for source, dirs in [("user", user_dirs), ("project", project_dirs)]:
        for d in dirs:
            if not d.is_dir():
                continue
            for skill_md in sorted(d.glob("*/SKILL.md")):
                skill = _parse_skill_md(skill_md, source)
                if skill is None:
                    continue
                by_name[skill.name] = skill
    return list(by_name.values())