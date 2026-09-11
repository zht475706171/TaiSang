"""Plugin 安装核心:git clone + 结构识别 + 批量导入 skills 到 user 源。

source 规范化:
- "owner/repo"           → "github:owner/repo"
- "https://github.com/owner/repo[.git|/]" → "github:owner/repo"

安全:
- parse_github_source 只接受 github.com + owner/repo 格式,杜绝命令注入
- git clone 用 subprocess.run 列表参数(不经 shell)
- 临时目录用 tempfile.TemporaryDirectory 自动清理
- 不执行 plugin 内任何脚本(hooks/agents/scripts 只复制不执行)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .plugin_registry import (
    InstalledPlugin,
    load_plugins,
    remove_plugin,
    upsert_plugin,
)
from .loader import _FRONTMATTER_RE

import yaml

log = logging.getLogger(__name__)


class PluginInstallError(ValueError):
    """plugin 安装失败。message 面向用户,可直接展示。"""


# owner/repo:owner 和 repo 都只能是 [A-Za-z0-9._-]+,字母数字开头
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_github_source(source: str) -> str:
    """把用户输入规范化成 'github:owner/repo'。

    接受:
      owner/repo
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      https://github.com/owner/repo/

    其他一律抛 PluginInstallError(非 github 域名、缺 owner/repo、协议错误)。
    """
    s = source.strip()
    if not s:
        raise PluginInstallError("github 地址不能为空")

    if s.startswith(("http://", "https://")):
        # 必须是 https://github.com/owner/repo 形式
        parsed = urlparse(s)
        if parsed.netloc != "github.com":
            raise PluginInstallError(f"只支持 github.com 仓库,收到: {parsed.netloc}")
        path = parsed.path.strip("/")
        # 去掉 .git 后缀和末尾斜杠
        if path.endswith(".git"):
            path = path[:-4]
        if not _OWNER_REPO_RE.match(path):
            raise PluginInstallError(f"github 路径格式错误,期望 owner/repo: {path}")
        return f"github:{path}"

    # 简写 owner/repo
    if not _OWNER_REPO_RE.match(s):
        raise PluginInstallError(
            f"地址格式错误,期望 owner/repo 或 https://github.com/owner/repo: {s}"
        )
    return f"github:{s}"


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _plugin_name_from_source(canonical: str) -> str:
    """从 'github:owner/repo' 取 repo 名作为 plugin-name。"""
    return canonical.split("/", 1)[1]


def _read_version(clone_dir: Path) -> str | None:
    """从 plugin 根 package.json 读 version;没有则返回 None。"""
    pkg = clone_dir / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    v = data.get("version")
    return str(v) if v else None


def _read_head_sha(clone_dir: Path) -> str:
    """git rev-parse HEAD 取前 12 位;失败返回 'unknown'。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(clone_dir), stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8", errors="replace").strip()[:12]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _detect_plugin_form(clone_dir: Path) -> str:
    """识别 plugin 形态,返回 'skills_dir' | 'single_skill' | 'marketplace' | 'empty'。"""
    if (clone_dir / ".claude-plugin" / "marketplace.json").is_file():
        return "marketplace"
    if (clone_dir / "skills").is_dir() and any((clone_dir / "skills").glob("*/SKILL.md")):
        return "skills_dir"
    if (clone_dir / "SKILL.md").is_file():
        return "single_skill"
    return "empty"


def _copy_skills_dir_form(clone_dir: Path, dest_plugin_dir: Path) -> list[str]:
    """superpowers 形态:复制 skills/<skill>/ 整目录到 dest_plugin_dir/<skill>/。"""
    skills: list[str] = []
    for skill_md in sorted((clone_dir / "skills").glob("*/SKILL.md")):
        skill_name = skill_md.parent.name
        if not _SAFE_NAME_RE.match(skill_name):
            log.warning("跳过不合法的 skill 目录名: %s", skill_name)
            continue
        dest = dest_plugin_dir / skill_name
        dest.mkdir(parents=True, exist_ok=True)
        for item in skill_md.parent.iterdir():
            if item.is_dir():
                shutil.copytree(item, dest / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest / item.name)
        skills.append(skill_name)
    return skills


def _parse_skill_name_from_frontmatter(skill_md: Path) -> str | None:
    """从 SKILL.md frontmatter 解析 name 字段;无 frontmatter 或解析失败返回 None。

    复用 loader._FRONTMATTER_RE + yaml.safe_load,和 loader/importer 行为一致。
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    name = fm.get("name")
    return str(name).strip() if name else None


def _copy_single_skill_form(clone_dir: Path, dest_plugin_dir: Path) -> list[str]:
    """单 skill 形态:把 clone_dir 根的 SKILL.md 落到 dest_plugin_dir/SKILL.md。

    skill name 优先取 SKILL.md frontmatter 的 name 字段;失败回落到 repo 名。
    """
    dest_plugin_dir.mkdir(parents=True, exist_ok=True)
    src_skill_md = clone_dir / "SKILL.md"
    shutil.copy2(src_skill_md, dest_plugin_dir / "SKILL.md")
    skill_name = _parse_skill_name_from_frontmatter(src_skill_md) or dest_plugin_dir.name
    return [skill_name]


def install_plugin(
    source: str,
    user_skills_dir: Path,
    plugins_file: Path,
) -> InstalledPlugin:
    """主流程:解析 source → git clone → 识别结构 → 复制 skills → 更新 plugins.json。

    覆盖式升级:同名 plugin 先 rmtree 再写。
    """
    canonical = parse_github_source(source)  # 'github:owner/repo'
    plugin_name = _plugin_name_from_source(canonical)
    clone_url = f"https://github.com/{canonical.split(':', 1)[1]}.git"

    # 1. git clone 到临时目录
    with tempfile.TemporaryDirectory(prefix="taisang-plugin-") as tmp:
        tmp_dir = Path(tmp)
        try:
            result = subprocess.run(
                ["git", "clone", clone_url, str(tmp_dir)],
                capture_output=True,
                timeout=120,
            )
        except FileNotFoundError as e:
            raise PluginInstallError("系统未安装 git,请先安装 git") from e
        except subprocess.TimeoutExpired as e:
            raise PluginInstallError(f"git clone 超时(120s),仓库过大或网络慢: {clone_url}") from e
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise PluginInstallError(f"git clone 失败: {stderr or '未知错误'}")

        # 2. 识别 plugin 形态
        form = _detect_plugin_form(tmp_dir)
        if form == "marketplace":
            raise PluginInstallError(
                "这是 marketplace 不是 plugin,请指定具体 plugin 仓库地址"
            )
        if form == "empty":
            raise PluginInstallError(
                "未找到可导入的 skill(plugin 根无 SKILL.md 也无 skills/ 子目录)"
            )

        # 3. 覆盖式升级:先删旧目录
        dest_plugin_dir = user_skills_dir / plugin_name
        if dest_plugin_dir.exists():
            try:
                shutil.rmtree(dest_plugin_dir)
            except OSError as e:
                raise PluginInstallError(
                    f"删除旧 plugin 目录失败,可能被占用: {dest_plugin_dir}"
                ) from e
        dest_plugin_dir.mkdir(parents=True, exist_ok=True)

        # 4. 复制 skills
        if form == "skills_dir":
            skills = _copy_skills_dir_form(tmp_dir, dest_plugin_dir)
        else:  # single_skill
            skills = _copy_single_skill_form(tmp_dir, dest_plugin_dir)

        if not skills:
            raise PluginInstallError("未找到可导入的 skill")

        # 5. 读 version + sha
        sha = _read_head_sha(tmp_dir)
        version = _read_version(tmp_dir) or sha
        installed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 6. 更新 installed_plugins.json(覆盖式) — 失败时回滚已复制的目录
    plugin = InstalledPlugin(
        name=plugin_name,
        source=canonical,
        version=version,
        git_commit_sha=sha,
        installed_at=installed_at,
        skills=skills,
    )
    try:
        upsert_plugin(plugins_file, plugin)
    except OSError as e:
        shutil.rmtree(dest_plugin_dir, ignore_errors=True)
        raise PluginInstallError(f"写入 plugin 注册表失败: {e}") from e
    return plugin


def uninstall_plugin(
    name: str,
    user_skills_dir: Path,
    plugins_file: Path,
) -> None:
    """卸载:删 user_skills_dir/<name>/ + 删 plugins.json 条目。"""
    dest = user_skills_dir / name
    if not dest.exists() and name not in load_plugins(plugins_file):
        raise PluginInstallError(f"未安装: {name}")
    if dest.exists():
        try:
            shutil.rmtree(dest)
        except OSError as e:
            raise PluginInstallError(
                f"删除 plugin 目录失败,可能被占用: {dest}"
            ) from e
    remove_plugin(plugins_file, name)
