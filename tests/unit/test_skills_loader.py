from pathlib import Path

from taisang.skills.loader import load_skills
from taisang.skills.types import Skill


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_load_from_user_dir(tmp_path):
    user_dir = tmp_path / "user_skills"
    _write(
        user_dir / "commit" / "SKILL.md",
        "---\n"
        "description: 生成 commit\n"
        "when_to_use: 用户说提交时\n"
        "---\n"
        "调用 git commit……\n",
    )
    skills = load_skills(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert len(skills) == 1
    s = skills[0]
    assert s.name == "commit"
    assert s.description == "生成 commit"
    assert s.when_to_use == "用户说提交时"
    assert s.allowed_tools is None
    assert s.source == "user"
    assert "调用 git commit" in s.content


def test_project_overrides_user_same_name(tmp_path):
    user_dir = tmp_path / "user"
    proj_dir = tmp_path / "proj"
    for d in [user_dir, proj_dir]:
        _write(
            d / "commit" / "SKILL.md",
            f"---\ndescription: {d.name}版\n---\n{d.name}内容\n",
        )
    skills = load_skills(user_dirs=[user_dir], project_dirs=[proj_dir], system_dirs=[])
    assert len(skills) == 1
    assert skills[0].source == "project"
    assert skills[0].description == "proj版"


def test_missing_description_falls_back_to_first_paragraph(tmp_path):
    d = tmp_path / "user"
    _write(d / "x" / "SKILL.md", "---\n---\n第一段\n\n第二段\n")
    skills = load_skills(user_dirs=[d], project_dirs=[], system_dirs=[])
    assert skills[0].description == "第一段"


def test_broken_frontmatter_skipped(tmp_path):
    d = tmp_path / "user"
    _write(d / "bad" / "SKILL.md", "---\nname: [unclosed\n---\nbody\n")
    skills = load_skills(user_dirs=[d], project_dirs=[], system_dirs=[])
    assert len(skills) == 0


def test_allowed_tools_parsed(tmp_path):
    d = tmp_path / "user"
    _write(d / "r" / "SKILL.md", "---\nallowed_tools: [Bash, Read]\n---\nbody\n")
    skills = load_skills(user_dirs=[d], project_dirs=[], system_dirs=[])
    assert skills[0].allowed_tools == ["Bash", "Read"]


def test_no_frontmatter_uses_first_paragraph(tmp_path):
    d = tmp_path / "user"
    _write(d / "plain" / "SKILL.md", "纯正文首段\n\n次段")
    skills = load_skills(user_dirs=[d], project_dirs=[], system_dirs=[])
    assert skills[0].name == "plain"
    assert skills[0].description == "纯正文首段"


def test_load_from_project_dir(tmp_path):
    proj = tmp_path / "proj"
    _write(proj / "test" / "SKILL.md", "---\n---\nbody")
    skills = load_skills(user_dirs=[], project_dirs=[proj], system_dirs=[])
    assert len(skills) == 1
    assert skills[0].source == "project"


def test_builtin_system_skills_loaded_by_default():
    """不传 system_dirs 时,默认加载包内 builtin 目录,source=system。"""
    skills = load_skills(user_dirs=[], project_dirs=[])
    names = {s.name for s in skills}
    assert "commit" in names
    assert "review" in names
    assert all(s.source == "system" for s in skills)


def test_user_overrides_system_same_name(tmp_path):
    """同名时 user 覆盖 system。"""
    d = tmp_path / "skills"
    _write(d / "commit" / "SKILL.md", "---\nname: commit\ndescription: user version\n---\nuser body")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    commit = next(s for s in skills if s.name == "commit")
    assert commit.source == "user"
    assert commit.description == "user version"


def test_system_dirs_empty_disables_builtin():
    """显式传 system_dirs=[] 时不加载内置(测试隔离用)。"""
    skills = load_skills(user_dirs=[], project_dirs=[], system_dirs=[])
    assert skills == []


def test_skill_dataclass_has_plugin_name_default_none():
    """Skill dataclass 必须有 plugin_name 字段,默认 None。"""
    from pathlib import Path

    from taisang.skills.types import Skill

    s = Skill(
        name="x",
        description="d",
        when_to_use="",
        allowed_tools=None,
        dir_path=Path("/tmp"),
        content="",
        source="user",
    )
    assert s.plugin_name is None
