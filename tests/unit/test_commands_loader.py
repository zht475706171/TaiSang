"""测试 commands loader:parse /md + 三源加载 + 优先级。"""

from pathlib import Path

from taisang.commands.loader import _parse_command_md, load_commands
from taisang.commands.types import Command


def test_parse_command_md_with_frontmatter(tmp_path: Path) -> None:
    """带 frontmatter 的 .md:解析 name/description/argument-hint/allowed-tools。"""
    md = tmp_path / "commit.md"
    md.write_text(
        "---\n"
        "description: 提交代码\n"
        "argument-hint: <msg>\n"
        "allowed-tools: Bash, read_file\n"
        "---\n"
        "# 提交\n"
        "git status\n$ARGUMENTS\n",
        encoding="utf-8",
    )
    cmd = _parse_command_md(md, source="user")
    assert cmd is not None
    assert cmd.name == "commit"  # 从文件名
    assert cmd.description == "提交代码"
    assert cmd.argument_hint == "<msg>"
    assert cmd.allowed_tools == ["Bash", "read_file"]
    assert "$ARGUMENTS" in cmd.content
    assert cmd.source == "user"
    assert cmd.file_path == md


def test_parse_command_md_no_frontmatter(tmp_path: Path) -> None:
    """无 frontmatter:整文当正文,name 从文件名,description 取首段。"""
    md = tmp_path / "simple.md"
    md.write_text("做一件事\n\n详细说明\n", encoding="utf-8")
    cmd = _parse_command_md(md, source="project")
    assert cmd is not None
    assert cmd.name == "simple"
    assert cmd.description == "做一件事"
    assert cmd.argument_hint == ""
    assert cmd.allowed_tools is None
    assert "详细说明" in cmd.content


def test_parse_command_md_frontmatter_name_override(tmp_path: Path) -> None:
    """frontmatter name 字段覆盖文件名。"""
    md = tmp_path / "file.md"
    md.write_text(
        "---\nname: custom-name\ndescription: x\n---\nbody\n",
        encoding="utf-8",
    )
    cmd = _parse_command_md(md, source="system")
    assert cmd is not None
    assert cmd.name == "custom-name"


def test_parse_command_md_invalid_name_rejected(tmp_path: Path) -> None:
    """name 含非法字符(目录穿越尝试)→ 拒绝。"""
    md = tmp_path / "bad.md"
    md.write_text(
        "---\nname: ../etc/passwd\ndescription: x\n---\nbody\n",
        encoding="utf-8",
    )
    cmd = _parse_command_md(md, source="user")
    assert cmd is None


def test_parse_command_md_malformed_yaml_returns_none(tmp_path: Path) -> None:
    """frontmatter yaml 损坏 → 返回 None。"""
    md = tmp_path / "bad.md"
    md.write_text("---\nname: [unclosed\n---\nbody\n", encoding="utf-8")
    cmd = _parse_command_md(md, source="user")
    assert cmd is None


def test_parse_command_md_allowed_tools_list_form(tmp_path: Path) -> None:
    """allowed-tools 支持 list 形式(对齐 skill)。"""
    md = tmp_path / "cmd.md"
    md.write_text(
        "---\n"
        "allowed-tools:\n  - Bash\n  - read_file\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    cmd = _parse_command_md(md, source="user")
    assert cmd is not None
    assert cmd.allowed_tools == ["Bash", "read_file"]


def test_load_commands_three_sources_priority(tmp_path: Path) -> None:
    """三源加载:project > user > system(同名覆盖)。"""
    system_dir = tmp_path / "system"
    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    system_dir.mkdir()
    user_dir.mkdir()
    project_dir.mkdir()

    (system_dir / "commit.md").write_text(
        "---\ndescription: system 版\n---\nsystem body\n", encoding="utf-8"
    )
    (user_dir / "commit.md").write_text(
        "---\ndescription: user 版\n---\nuser body\n", encoding="utf-8"
    )
    (project_dir / "commit.md").write_text(
        "---\ndescription: project 版\n---\nproject body\n", encoding="utf-8"
    )
    # 各源独有
    (system_dir / "sysonly.md").write_text(
        "---\ndescription: sys only\n---\nbody\n", encoding="utf-8"
    )
    (user_dir / "usronly.md").write_text(
        "---\ndescription: user only\n---\nbody\n", encoding="utf-8"
    )

    commands = load_commands(
        user_dirs=[user_dir],
        project_dirs=[project_dir],
        system_dirs=[system_dir],
    )
    by_name = {c.name: c for c in commands}
    # project 覆盖 user 覆盖 system
    assert by_name["commit"].source == "project"
    assert by_name["commit"].description == "project 版"
    # 各源独有的都保留
    assert by_name["sysonly"].source == "system"
    assert by_name["usronly"].source == "user"


def test_load_commands_empty_dirs_returns_empty(tmp_path: Path) -> None:
    """空目录 → 空列表。"""
    commands = load_commands(
        user_dirs=[tmp_path / "noexist"],
        project_dirs=[],
        system_dirs=[tmp_path / "also_noexist"],
    )
    assert commands == []


def test_load_commands_builtin_loaded_by_default(tmp_path: Path) -> None:
    """system_dirs 默认取包内 builtin/,含 commit/review 内置。"""
    commands = load_commands(user_dirs=[], project_dirs=[])
    names = {c.name for c in commands}
    assert "commit" in names
    assert "review" in names
    # 内置 source = system
    commit = next(c for c in commands if c.name == "commit")
    assert commit.source == "system"
    assert commit.allowed_tools is not None
    assert "Bash" in commit.allowed_tools