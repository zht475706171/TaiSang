"""Command 加载器:三源扫描 *.md,parse frontmatter + 正文。

格式(对齐 Claude Code commands):
---
description: 简短描述
allowed-tools: Bash, read_file  # 可选,仅提示不硬拦
argument-hint: <file path>  # 可选,UI 提示
---
正文...$ARGUMENTS...  # $ARGUMENTS 被用户输入的 args 替换

平铺结构:一个 .md 文件 = 一个 command(name 从文件名或 frontmatter)。
不像 skill 用目录套 SKILL.md。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import Command

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n(.*)$", re.DOTALL)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

BUILTIN_COMMANDS_DIR = Path(__file__).parent / "builtin"


def _parse_command_md(path: Path, source: str) -> Command | None:
    """解析单个 .md 文件为 Command。格式不合法返回 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 无 frontmatter,整文当正文,name 从文件名
        content = text.strip()
        first_para = content.split("\n\n")[0].strip()[:200]
        name = path.stem
        if not _NAME_RE.match(name):
            return None
        return Command(
            name=name,
            description=first_para or "(no description)",
            argument_hint="",
            allowed_tools=None,
            content=content,
            file_path=path,
            source=source,
        )
    fm_text, content = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None
    name = str(fm.get("name") or path.stem)
    if not _NAME_RE.match(name):
        return None
    desc = str(
        fm.get("description")
        or content.split("\n\n")[0].strip()[:200]
        or "(no description)"
    )
    # argument-hint(连字符)或 argument_hint(下划线)都接受
    argument_hint = str(fm.get("argument-hint") or fm.get("argument_hint") or "")
    # allowed-tools(连字符)或 allowed_tools(下划线)都接受
    allowed = fm.get("allowed-tools") or fm.get("allowed_tools")
    if allowed is not None:
        if isinstance(allowed, str):
            # 逗号分隔字符串 → 列表
            allowed = [t.strip() for t in allowed.split(",") if t.strip()]
        elif isinstance(allowed, list):
            allowed = [str(t) for t in allowed]
        else:
            allowed = None
    return Command(
        name=name,
        description=desc,
        argument_hint=argument_hint,
        allowed_tools=allowed,
        content=content.strip(),
        file_path=path,
        source=source,
    )


def load_commands(
    user_dirs: list[Path],
    project_dirs: list[Path],
    system_dirs: list[Path] | None = None,
) -> list[Command]:
    """扫描三源 command 目录,返回去重后的 Command 列表。

    优先级(同名覆盖):project > user > system。
    system_dirs 默认取包内 builtin/ 目录(内置 command,不可删除)。
    """
    if system_dirs is None:
        system_dirs = [BUILTIN_COMMANDS_DIR]
    by_name: dict[str, Command] = {}
    # 顺序即优先级:后面的源覆盖前面的
    for source, dirs in [
        ("system", system_dirs),
        ("user", user_dirs),
        ("project", project_dirs),
    ]:
        for d in dirs:
            if not d.is_dir():
                continue
            for md in sorted(d.glob("*.md")):
                cmd = _parse_command_md(md, source)
                if cmd is None:
                    continue
                by_name[cmd.name] = cmd
    return list(by_name.values())