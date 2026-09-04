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
    skills = load_skills(user_dirs=[user_dir], project_dirs=[])
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
    skills = load_skills(user_dirs=[user_dir], project_dirs=[proj_dir])
    assert len(skills) == 1
    assert skills[0].source == "project"
    assert skills[0].description == "proj版"


def test_missing_description_falls_back_to_first_paragraph(tmp_path):
    d = tmp_path / "user"
    _write(d / "x" / "SKILL.md", "---\n---\n第一段\n\n第二段\n")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert skills[0].description == "第一段"


def test_broken_frontmatter_skipped(tmp_path):
    d = tmp_path / "user"
    _write(d / "bad" / "SKILL.md", "---\nname: [unclosed\n---\nbody\n")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert len(skills) == 0


def test_allowed_tools_parsed(tmp_path):
    d = tmp_path / "user"
    _write(d / "r" / "SKILL.md", "---\nallowed_tools: [Bash, Read]\n---\nbody\n")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert skills[0].allowed_tools == ["Bash", "Read"]


def test_no_frontmatter_uses_first_paragraph(tmp_path):
    d = tmp_path / "user"
    _write(d / "plain" / "SKILL.md", "纯正文首段\n\n次段")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert skills[0].name == "plain"
    assert skills[0].description == "纯正文首段"