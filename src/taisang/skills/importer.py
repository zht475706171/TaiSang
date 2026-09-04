"""Skill 导入:前端上传 MD/zip,校验后落盘 skills_root/<name>/。

安全:
- frontmatter name 必须匹配安全字符集(字母数字开头,后跟字母数字_-),
  杜绝 name 携带路径分隔符造成的目录穿越
- zip-slip:成员路径拒绝绝对路径、.. 、反斜杠;全部成员必须在
  SKILL.md 所在目录前缀之下
- zip 原始字节 ≤ 10MB

注意:overwrite 时先 rmtree 再解压;所有校验(含 SKILL.md 解析取 name)
都在 rmtree 之前完成,旧版本只会在校验全通过后才被替换。
"""

from __future__ import annotations

import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path

import yaml

from .loader import _FRONTMATTER_RE

MAX_IMPORT_BYTES = 10 * 1024 * 1024

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


class SkillImportError(ValueError):
    """导入校验失败。message 面向用户,可直接展示。"""


class SkillExistsError(SkillImportError):
    """同名 skill 已存在,需用户确认覆盖后带 overwrite 重试。"""


def _extract_name(text: str) -> str:
    """从 SKILL.md 文本解析 frontmatter name 并校验合法性。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillImportError("SKILL.md 缺少 frontmatter(需要 --- name: xxx --- 段)")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillImportError(f"frontmatter YAML 解析失败: {e}") from e
    name = str(fm.get("name") or "").strip()
    if not name:
        raise SkillImportError("frontmatter 缺少 name 字段")
    if not _SAFE_NAME_RE.match(name):
        raise SkillImportError(f"name 不合法(只允许字母数字和 _ -,且字母数字开头): {name}")
    return name


def _prepare_target(name: str, skills_root: Path, overwrite: bool) -> Path:
    """返回目标目录;已存在时按 overwrite 决定拒绝或清空重建。"""
    skills_root.mkdir(parents=True, exist_ok=True)
    target = skills_root / name
    if target.exists():
        if not overwrite:
            raise SkillExistsError(f"skill 已存在: {name}")
        shutil.rmtree(target)
    return target


def import_skill_md(text: str, skills_root: Path, overwrite: bool = False) -> tuple[str, Path]:
    """导入单文件 SKILL.md:建 <name>/ 目录写入。返回 (name, 目录)。"""
    name = _extract_name(text)
    target = _prepare_target(name, skills_root, overwrite)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(text, encoding="utf-8")
    return name, target


def import_skill_zip(data: bytes, skills_root: Path, overwrite: bool = False) -> tuple[str, Path]:
    """导入 zip:SKILL.md 在 zip 根,或唯一一级目录下(压缩文件夹形态)。

    解压到 skills_root/<frontmatter name>/。返回 (name, 目录)。
    """
    if len(data) > MAX_IMPORT_BYTES:
        raise SkillImportError("文件超过 10MB 上限")
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as e:
        raise SkillImportError("不是合法的 zip 文件") from e
    with zf:
        names = [n for n in zf.namelist() if not _is_junk(n)]
        prefix = _locate_skill_root(names)
        for n in names:
            _check_member_safe(n, prefix)
        name = _extract_name(zf.read(prefix + "SKILL.md").decode("utf-8", errors="replace"))
        target = _prepare_target(name, skills_root, overwrite)
        target.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.endswith("/"):
                continue
            dest = target / n[len(prefix):]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(n))
    return name, target


def _is_junk(n: str) -> bool:
    """过滤目录条目和系统垃圾文件。"""
    return n.endswith("/") or "__MACOSX" in n or n.endswith(".DS_Store")


def _locate_skill_root(names: list[str]) -> str:
    """定位 SKILL.md 所在前缀:zip 根("")或唯一一级目录("dir/")。"""
    if "SKILL.md" in names:
        return ""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    if len(tops) == 1:
        prefix = next(iter(tops)) + "/"
        if prefix + "SKILL.md" in names:
            return prefix
    raise SkillImportError("zip 根目录(或唯一一级目录下)找不到 SKILL.md")


def _check_member_safe(n: str, prefix: str) -> None:
    """单个成员的 zip-slip + 前缀校验。"""
    p = Path(n)
    if p.is_absolute() or ".." in p.parts or "\\" in n:
        raise SkillImportError(f"zip 内路径不合法: {n}")
    if not n.startswith(prefix):
        raise SkillImportError(f"zip 内有 SKILL.md 所在目录之外的文件: {n}")