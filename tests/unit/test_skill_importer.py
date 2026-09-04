"""importer 测试:MD/zip 校验、zip-slip、同名覆盖。

所有用例的 skills_root 都指向 tmp_path,不碰真实 ~/.taisang。
"""
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from taisang.skills.importer import (
    SkillExistsError,
    SkillImportError,
    import_skill_md,
    import_skill_zip,
)

_MD = "---\nname: alpha\ndescription: test skill\n---\nalpha body\n"


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


# ---------- MD ----------

def test_import_md_creates_dir(tmp_path):
    name, target = import_skill_md(_MD, tmp_path)
    assert name == "alpha"
    assert (target / "SKILL.md").read_text(encoding="utf-8") == _MD


def test_import_md_missing_name_rejected(tmp_path):
    with pytest.raises(SkillImportError, match="name"):
        import_skill_md("---\ndescription: no name\n---\nbody", tmp_path)


def test_import_md_no_frontmatter_rejected(tmp_path):
    with pytest.raises(SkillImportError, match="frontmatter"):
        import_skill_md("just plain text", tmp_path)


def test_import_md_unsafe_name_rejected(tmp_path):
    # name 里带路径分隔符 → 目录穿越,必须拒绝
    with pytest.raises(SkillImportError, match="name 不合法"):
        import_skill_md("---\nname: ../evil\n---\nbody", tmp_path)


def test_import_md_exists_raises(tmp_path):
    import_skill_md(_MD, tmp_path)
    with pytest.raises(SkillExistsError):
        import_skill_md(_MD, tmp_path)


def test_import_md_overwrite_replaces(tmp_path):
    import_skill_md(_MD, tmp_path)
    name, target = import_skill_md(
        "---\nname: alpha\ndescription: v2\n---\nv2 body", tmp_path, overwrite=True
    )
    assert "v2 body" in (target / "SKILL.md").read_text(encoding="utf-8")


# ---------- zip ----------

def test_import_zip_root_layout(tmp_path):
    data = _zip_bytes({"SKILL.md": _MD, "template.txt": "hello"})
    name, target = import_skill_zip(data, tmp_path)
    assert name == "alpha"
    assert (target / "SKILL.md").exists()
    assert (target / "template.txt").read_text(encoding="utf-8") == "hello"


def test_import_zip_single_top_dir_layout(tmp_path):
    # Windows "压缩文件夹" 常见形态:顶层一个目录包着 SKILL.md
    data = _zip_bytes({"myskill/SKILL.md": _MD, "myskill/assets/a.txt": "x"})
    name, target = import_skill_zip(data, tmp_path)
    assert name == "alpha"  # name 以 frontmatter 为准,不用目录名
    assert (target / "assets/a.txt").exists()


def test_import_zip_no_skill_md_rejected(tmp_path):
    data = _zip_bytes({"README.md": "hi"})
    with pytest.raises(SkillImportError, match="SKILL.md"):
        import_skill_zip(data, tmp_path)


def test_import_zip_slip_rejected(tmp_path):
    data = _zip_bytes({"SKILL.md": _MD, "../evil.txt": "pwn"})
    with pytest.raises(SkillImportError, match="路径不合法"):
        import_skill_zip(data, tmp_path)


def test_import_zip_absolute_path_rejected(tmp_path):
    data = _zip_bytes({"/abs/SKILL.md": _MD})
    with pytest.raises(SkillImportError):
        import_skill_zip(data, tmp_path)


def test_import_zip_two_top_dirs_rejected(tmp_path):
    # SKILL.md 不在根,且有多个顶层目录 → 找不到唯一 skill 根
    data = _zip_bytes({"a/SKILL.md": _MD, "b/other.txt": "x"})
    with pytest.raises(SkillImportError, match="SKILL.md"):
        import_skill_zip(data, tmp_path)


def test_import_zip_oversize_rejected(tmp_path):
    big = b"0" * (10 * 1024 * 1024 + 1)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("SKILL.md", _MD)
        zf.writestr("big.bin", big)
    with pytest.raises(SkillImportError, match="10MB"):
        import_skill_zip(buf.getvalue(), tmp_path)


def test_import_zip_bad_name_in_frontmatter_rejected(tmp_path):
    data = _zip_bytes({"SKILL.md": "---\nname: x/y\n---\nbody"})
    with pytest.raises(SkillImportError, match="name 不合法"):
        import_skill_zip(data, tmp_path)


def test_import_zip_not_a_zip_rejected(tmp_path):
    with pytest.raises(SkillImportError, match="zip"):
        import_skill_zip(b"not a zip at all", tmp_path)