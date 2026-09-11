import pytest

from taisang.skills.installer import parse_github_source, PluginInstallError


@pytest.mark.parametrize("raw,expected", [
    ("obra/superpowers", "github:obra/superpowers"),
    ("https://github.com/obra/superpowers", "github:obra/superpowers"),
    ("https://github.com/obra/superpowers.git", "github:obra/superpowers"),
    ("https://github.com/obra/superpowers/", "github:obra/superpowers"),
    ("  obra/superpowers  ", "github:obra/superpowers"),
])
def test_parse_github_source_valid(raw, expected):
    assert parse_github_source(raw) == expected


@pytest.mark.parametrize("bad", [
    "",
    "not-a-url",
    "https://gitlab.com/obra/superpowers",  # 非 github
    "https://github.com/onlyowner",  # 缺 repo
    "https://github.com//superpowers",  # 空 owner
    "ftp://github.com/obra/superpowers",  # 非 http(s)
    # 安全边界:以下三个测试真实威胁路径
    "https://evil.com@github.com/owner/repo",  # userinfo 伪装,netloc=evil.com@github.com 被 !=
    "https://github.com:8080/owner/repo",  # 端口绕过,netloc=github.com:8080 被 !=
    "https://github.com/owner/repo;rm -rf /",  # 分号注入,regex 拒绝
])
def test_parse_github_source_invalid(bad):
    with pytest.raises(PluginInstallError):
        parse_github_source(bad)


# ===== install_plugin / uninstall_plugin 测试 =====

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from taisang.skills.installer import install_plugin, uninstall_plugin, InstalledPlugin


def _make_fake_clone(target_dir: Path, structure: Path):
    """把 fixture 目录内容复制到 target_dir,模拟 git clone 结果。"""
    for item in structure.iterdir():
        dest = target_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


def _setup_fake_clone(fixture_root: Path):
    """返回一个函数,用作 mock subprocess.run 的 side_effect:
    把 fixture_root 的内容复制到命令行指定的目标目录。"""
    def _fake_run(cmd, *args, **kwargs):
        # cmd = ["git", "clone", url, tmpdir]
        target = Path(cmd[3])
        target.mkdir(parents=True, exist_ok=True)
        _make_fake_clone(target, fixture_root)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    return _fake_run


def _make_superpowers_fixture(tmp_path: Path) -> Path:
    """superpowers 形态:根有 skills/ 子目录,多个 skill 各带 SKILL.md。"""
    root = tmp_path / "fixture"
    (root / "skills" / "brainstorming").mkdir(parents=True)
    (root / "skills" / "brainstorming" / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: d1\n---\nbody1", encoding="utf-8"
    )
    (root / "skills" / "writing-plans").mkdir(parents=True)
    (root / "skills" / "writing-plans" / "SKILL.md").write_text(
        "---\nname: writing-plans\ndescription: d2\n---\nbody2", encoding="utf-8"
    )
    (root / "package.json").write_text('{"version": "5.1.0"}', encoding="utf-8")
    return root


def _make_single_skill_fixture(tmp_path: Path) -> Path:
    """单 skill 仓库形态:根直接是 SKILL.md。"""
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: solo\ndescription: solo skill\n---\nsolo body", encoding="utf-8"
    )
    (root / "package.json").write_text('{"version": "1.0.0"}', encoding="utf-8")
    return root


def _make_marketplace_fixture(tmp_path: Path) -> Path:
    """marketplace 形态:根有 .claude-plugin/marketplace.json。"""
    root = tmp_path / "fixture"
    root.mkdir()
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
    return root


def _make_empty_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    root.mkdir()
    return root


def test_install_plugin_superpowers_form(tmp_path):
    fixture = _make_superpowers_fixture(tmp_path)
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123def456\n"):
            result = install_plugin("obra/superpowers", user_dir, plugins_file)
    assert isinstance(result, InstalledPlugin)
    assert result.name == "superpowers"
    assert result.source == "github:obra/superpowers"
    assert result.version == "5.1.0"
    assert result.git_commit_sha == "abc123def456"
    # 落盘结构:user_dir/superpowers/<skill>/SKILL.md
    assert (user_dir / "superpowers" / "brainstorming" / "SKILL.md").exists()
    assert (user_dir / "superpowers" / "writing-plans" / "SKILL.md").exists()
    assert "brainstorming" in result.skills
    assert "writing-plans" in result.skills
    # plugins.json 写入
    raw = json.loads(plugins_file.read_text(encoding="utf-8"))
    assert "superpowers" in raw["plugins"]


def test_install_plugin_single_skill_form(tmp_path):
    fixture = _make_single_skill_fixture(tmp_path)
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"sha123\n"):
            result = install_plugin("solo/repo", user_dir, plugins_file)
    assert result.name == "repo"
    assert "solo" in result.skills
    # 单 skill 形态:落盘到 user_dir/<plugin>/SKILL.md(单层)
    assert (user_dir / "repo" / "SKILL.md").exists()


def test_install_plugin_marketplace_form_errors(tmp_path):
    fixture = _make_marketplace_fixture(tmp_path)
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with pytest.raises(PluginInstallError, match="marketplace"):
            install_plugin("foo/bar", user_dir, plugins_file)


def test_install_plugin_no_skills_errors(tmp_path):
    fixture = _make_empty_fixture(tmp_path)
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with pytest.raises(PluginInstallError, match="未找到可导入"):
            install_plugin("foo/bar", user_dir, plugins_file)


def test_install_plugin_overwrite_upgrades(tmp_path):
    """同名 plugin 重复安装:先删后装,版本更新。"""
    fixture = _make_superpowers_fixture(tmp_path)
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    # 第一次安装
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"aaa111222333\n"):
            install_plugin("obra/superpowers", user_dir, plugins_file)
    # 在旧 skill 目录里塞一个"垃圾"文件,验证升级时被清空
    junk = user_dir / "superpowers" / "brainstorming" / "junk.txt"
    junk.write_text("should be removed on upgrade", encoding="utf-8")
    # 第二次安装(升级) — fixture 改一下版本
    (fixture / "package.json").write_text('{"version": "5.2.0"}', encoding="utf-8")
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"bbb444555666\n"):
            result = install_plugin("obra/superpowers", user_dir, plugins_file)
    assert result.version == "5.2.0"
    assert result.git_commit_sha == "bbb444555666"
    # junk 应被清掉
    assert not junk.exists()
    # skills 仍然在
    assert (user_dir / "superpowers" / "brainstorming" / "SKILL.md").exists()


def test_install_plugin_clone_failure(tmp_path):
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    # git clone 失败
    def _fail(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: repository not found")
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fail):
        with pytest.raises(PluginInstallError, match="git clone 失败"):
            install_plugin("nobody/nope", user_dir, plugins_file)


def test_install_plugin_git_not_installed(tmp_path):
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    def _no_git(cmd, *a, **kw):
        raise FileNotFoundError("git not installed")
    with patch("taisang.skills.installer.subprocess.run", side_effect=_no_git):
        with pytest.raises(PluginInstallError, match="未安装 git"):
            install_plugin("obra/superpowers", user_dir, plugins_file)


def test_install_plugin_no_package_json_uses_sha_as_version(tmp_path):
    fixture = _make_superpowers_fixture(tmp_path)
    (fixture / "package.json").unlink()  # 删掉 package.json
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abcdef123456\n"):
            result = install_plugin("obra/superpowers", user_dir, plugins_file)
    # version 用 commit sha 前 12 位
    assert result.version == "abcdef123456"


def test_uninstall_plugin_removes_dir_and_entry(tmp_path):
    fixture = _make_superpowers_fixture(tmp_path)
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with patch("taisang.skills.installer.subprocess.run", side_effect=_setup_fake_clone(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"sha\n"):
            install_plugin("obra/superpowers", user_dir, plugins_file)
    assert (user_dir / "superpowers").exists()
    uninstall_plugin("superpowers", user_dir, plugins_file)
    assert not (user_dir / "superpowers").exists()
    raw = json.loads(plugins_file.read_text(encoding="utf-8"))
    assert "superpowers" not in raw["plugins"]


def test_uninstall_plugin_missing_errors(tmp_path):
    user_dir = tmp_path / "user_skills"
    plugins_file = tmp_path / "plugins.json"
    with pytest.raises(PluginInstallError, match="未安装"):
        uninstall_plugin("nonexistent", user_dir, plugins_file)
