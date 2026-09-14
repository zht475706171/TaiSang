# Plugin 安装系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 Skill 管理页直接输入 github 地址安装 plugin（如 superpowers），自动批量导入 plugin 内所有 skills 到 user 源，统一在 UI 管理已装 plugin（查看、卸载、升级）。

**Architecture:** 后端新建 `installer.py` 负责 git clone + plugin 结构识别 + 批量复制 skills，`plugin_registry.py` 负责 installed_plugins.json 读写；修改 `loader.py` 扫描兼容 `*/*/SKILL.md` 二层结构并给 Skill 加 `plugin_name` 字段；修改 `skills_api.py` 加 3 个端点（install / uninstall / list plugins）；修改 `SkillManage.vue` 加安装按钮 + 已装 Plugin 面板 + Plugin 列 + 安装/卸载 dialog。

**Tech Stack:** Python 3.12 / FastAPI / pydantic / pytest / Vue 3.5 / TypeScript / TDesign / playwright（文本验证，禁止截图）

**Spec:** `docs/superpowers/specs/2026-09-11-plugin-install-design.md`

---

## File Structure

**Create:**
- `src/taisang/skills/installer.py` — plugin 安装核心：parse_github_source / install_plugin / uninstall_plugin / list_plugins / InstalledPlugin dataclass / PluginInstallError
- `src/taisang/skills/plugin_registry.py` — installed_plugins.json 读写：load_plugins / save_plugins / upsert_plugin / remove_plugin
- `tests/unit/test_skills_installer.py` — installer 单元测试
- `tests/unit/test_skills_plugin_registry.py` — plugin_registry 单元测试

**Modify:**
- `src/taisang/skills/types.py` — Skill dataclass 加 `plugin_name: str | None = None`
- `src/taisang/skills/loader.py` — load_skills 扫描兼容 `*/SKILL.md` + `*/*/SKILL.md`；_parse_skill_md 加 plugin_name 参数
- `src/taisang/web/skills_api.py` — 加 POST /api/skills/install-plugin、DELETE /api/skills/plugin/<name>、GET /api/skills/plugins；GET /api/skills 返回加 plugin_name
- `src/taisang/web/frontend/src/views/SkillManage.vue` — 加安装按钮 + 已装 Plugin 面板 + Plugin 列 + 安装/卸载 dialog
- `tests/unit/test_skills_loader.py` — 加二层扫描测试
- `tests/unit/test_skills_api.py` — 加 plugin 端点测试

---

### Task 1: Skill dataclass 加 plugin_name 字段

**Files:**
- Modify: `src/taisang/skills/types.py:7-16`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_skills_loader.py` (append at end of file):

```python
def test_skill_dataclass_has_plugin_name_default_none():
    """Skill dataclass 必须有 plugin_name 字段,默认 None。"""
    from taisang.skills.types import Skill
    from pathlib import Path
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_loader.py::test_skill_dataclass_has_plugin_name_default_none -v`
Expected: FAIL with `AttributeError: 'Skill' object has no attribute 'plugin_name'` or dataclass rejection.

- [ ] **Step 3: Write minimal implementation**

Modify `src/taisang/skills/types.py` to add the field:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str
    allowed_tools: list[str] | None
    dir_path: Path
    content: str
    source: str
    disabled: bool = False
    plugin_name: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_loader.py::test_skill_dataclass_has_plugin_name_default_none -v`
Expected: PASS

- [ ] **Step 5: Run full loader test suite to confirm no regression**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_loader.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/skills/types.py tests/unit/test_skills_loader.py
git commit -m "feat(skills): add plugin_name field to Skill dataclass"
```

---

### Task 2: plugin_registry.py — installed_plugins.json 读写

**Files:**
- Create: `src/taisang/skills/plugin_registry.py`
- Create: `tests/unit/test_skills_plugin_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_skills_plugin_registry.py`:

```python
import json
from pathlib import Path

import pytest

from taisang.skills.plugin_registry import (
    InstalledPlugin,
    load_plugins,
    save_plugins,
    upsert_plugin,
    remove_plugin,
)


def _make_plugin(name: str = "superpowers") -> InstalledPlugin:
    return InstalledPlugin(
        name=name,
        source="github:obra/superpowers",
        version="5.1.0",
        git_commit_sha="f2cbfbefebbf",
        installed_at="2026-09-11T10:00:00Z",
        skills=["brainstorming", "writing-plans"],
    )


def test_load_plugins_empty_file(tmp_path):
    f = tmp_path / "plugins.json"
    f.write_text("{}", encoding="utf-8")
    assert load_plugins(f) == {}


def test_load_plugins_missing_file(tmp_path):
    f = tmp_path / "plugins.json"
    assert load_plugins(f) == {}


def test_load_plugins_corrupted_returns_empty(tmp_path, caplog):
    f = tmp_path / "plugins.json"
    f.write_text("{not valid json", encoding="utf-8")
    result = load_plugins(f)
    assert result == {}


def test_save_and_load_roundtrip(tmp_path):
    f = tmp_path / "plugins.json"
    plugins = {"superpowers": _make_plugin()}
    save_plugins(f, plugins)
    loaded = load_plugins(f)
    assert "superpowers" in loaded
    assert loaded["superpowers"].version == "5.1.0"
    assert loaded["superpowers"].skills == ["brainstorming", "writing-plans"]


def test_save_plugins_writes_version_envelope(tmp_path):
    f = tmp_path / "plugins.json"
    save_plugins(f, {"superpowers": _make_plugin()})
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert "superpowers" in raw["plugins"]


def test_upsert_plugin_overwrites_same_name(tmp_path):
    f = tmp_path / "plugins.json"
    upsert_plugin(f, _make_plugin("superpowers"))
    # 同名不同版本
    p2 = _make_plugin("superpowers")
    p2.version = "5.2.0"
    upsert_plugin(f, p2)
    loaded = load_plugins(f)
    assert len(loaded) == 1
    assert loaded["superpowers"].version == "5.2.0"


def test_upsert_plugin_preserves_others(tmp_path):
    f = tmp_path / "plugins.json"
    upsert_plugin(f, _make_plugin("superpowers"))
    upsert_plugin(f, _make_plugin("other-plugin"))
    loaded = load_plugins(f)
    assert set(loaded.keys()) == {"superpowers", "other-plugin"}


def test_remove_plugin_removes_entry(tmp_path):
    f = tmp_path / "plugins.json"
    upsert_plugin(f, _make_plugin("superpowers"))
    remove_plugin(f, "superpowers")
    assert load_plugins(f) == {}


def test_remove_plugin_missing_is_noop(tmp_path):
    f = tmp_path / "plugins.json"
    # 不存在不报错
    remove_plugin(f, "nonexistent")
    assert load_plugins(f) == {}


def test_save_plugins_atomic_write(tmp_path):
    """原子写:中途 .tmp 文件存在,最终 .json 完整。"""
    f = tmp_path / "plugins.json"
    save_plugins(f, {"superpowers": _make_plugin()})
    # 最终文件存在且可解析
    assert f.exists()
    json.loads(f.read_text(encoding="utf-8"))
    # 不应残留 .tmp
    assert not f.with_suffix(".json.tmp").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_plugin_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'taisang.skills.plugin_registry'`

- [ ] **Step 3: Write minimal implementation**

Create `src/taisang/skills/plugin_registry.py`:

```python
"""installed_plugins.json 读写:记录用户已安装的 plugin 索引。

格式:
{
  "version": 1,
  "plugins": {
    "<plugin-name>": {
      "name": "<plugin-name>",
      "source": "github:owner/repo",
      "version": "x.y.z",
      "git_commit_sha": "12-char-short-sha",
      "installed_at": "ISO-8601 UTC",
      "skills": ["skill1", "skill2", ...]
    }
  }
}

原子写(tmp + os.replace);损坏文件当空 dict 处理并 log warning。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class InstalledPlugin:
    name: str
    source: str
    version: str
    git_commit_sha: str
    installed_at: str
    skills: list[str] = field(default_factory=list)


def load_plugins(plugins_file: Path) -> dict[str, InstalledPlugin]:
    """读 installed_plugins.json,返回 {name: InstalledPlugin}。

    文件不存在或损坏 → 返回 {} 并 log warning(损坏时)。
    """
    if not plugins_file.exists():
        return {}
    try:
        raw = json.loads(plugins_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("installed_plugins.json 损坏,当作空配置: %s", e)
        return {}
    plugins_raw = raw.get("plugins", {}) if isinstance(raw, dict) else {}
    result: dict[str, InstalledPlugin] = {}
    for name, p in plugins_raw.items():
        if not isinstance(p, dict):
            continue
        try:
            result[name] = InstalledPlugin(
                name=p.get("name", name),
                source=p.get("source", ""),
                version=p.get("version", ""),
                git_commit_sha=p.get("git_commit_sha", ""),
                installed_at=p.get("installed_at", ""),
                skills=list(p.get("skills", [])),
            )
        except (TypeError, ValueError):
            continue
    return result


def save_plugins(plugins_file: Path, plugins: dict[str, InstalledPlugin]) -> None:
    """原子写 installed_plugins.json。"""
    plugins_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "plugins": {name: asdict(p) for name, p in plugins.items()},
    }
    tmp = plugins_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, plugins_file)


def upsert_plugin(plugins_file: Path, plugin: InstalledPlugin) -> None:
    """覆盖式写入单个 plugin(同名覆盖,其他保留)。"""
    plugins = load_plugins(plugins_file)
    plugins[plugin.name] = plugin
    save_plugins(plugins_file, plugins)


def remove_plugin(plugins_file: Path, name: str) -> None:
    """删除单个 plugin 条目;不存在则 no-op。"""
    plugins = load_plugins(plugins_file)
    if name in plugins:
        del plugins[name]
        save_plugins(plugins_file, plugins)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_plugin_registry.py -v`
Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/skills/plugin_registry.py tests/unit/test_skills_plugin_registry.py
git commit -m "feat(skills): add plugin_registry for installed_plugins.json"
```

---

### Task 3: installer.py — parse_github_source + PluginInstallError

**Files:**
- Create: `src/taisang/skills/installer.py`
- Create: `tests/unit/test_skills_installer.py` (initial, only parse tests)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_skills_installer.py`:

```python
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
    "javascript:alert(1)",  # 注入尝试
])
def test_parse_github_source_invalid(bad):
    with pytest.raises(PluginInstallError):
        parse_github_source(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_installer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'taisang.skills.installer'`

- [ ] **Step 3: Write minimal implementation**

Create `src/taisang/skills/installer.py`:

```python
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

import re
from dataclasses import dataclass, field
from pathlib import Path


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
        from urllib.parse import urlparse
        parsed = urlparse(s)
        if parsed.netloc != "github.com":
            raise PluginInstallError(f"只支持 github.com 仓库,收到: {parsed.netloc}")
        path = parsed.path.strip("/")
        # 去掉 .git 后缀和末尾斜杠
        if path.endswith(".git"):
            path = path[:-4].rstrip("/")
        if not _OWNER_REPO_RE.match(path):
            raise PluginInstallError(f"github 路径格式错误,期望 owner/repo: {path}")
        return f"github:{path}"

    # 简写 owner/repo
    if not _OWNER_REPO_RE.match(s):
        raise PluginInstallError(
            f"地址格式错误,期望 owner/repo 或 https://github.com/owner/repo: {s}"
        )
    return f"github:{s}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_installer.py -v`
Expected: all 13 tests PASS (5 valid + 8 invalid)

- [ ] **Step 5: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/skills/installer.py tests/unit/test_skills_installer.py
git commit -m "feat(skills): add installer with parse_github_source"
```

---

### Task 4: installer.py — install_plugin 主流程（mock git clone）

**Files:**
- Modify: `src/taisang/skills/installer.py` (add install_plugin + helpers + InstalledPlugin)
- Modify: `tests/unit/test_skills_installer.py` (add install tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_skills_installer.py`:

```python
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from taisang.skills.installer import install_plugin, uninstall_plugin, InstalledPlugin


def _make_fake_clone(target_dir: Path, structure: str):
    """把 fixture 目录内容复制到 target_dir,模拟 git clone 结果。"""
    # structure 是 fixture 目录的绝对路径
    for item in structure.iterdir():
        dest = target_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
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


def test_install_plugin_superpowers_form(tmp_path, monkeypatch):
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


def test_install_plugin_git_not_installed(tmp_path, monkeypatch):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_installer.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'install_plugin'` (or similar).

- [ ] **Step 3: Write minimal implementation**

Append to `src/taisang/skills/installer.py` (after `parse_github_source`):

```python
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from .plugin_registry import InstalledPlugin, load_plugins, save_plugins, upsert_plugin, remove_plugin


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _plugin_name_from_source(canonical: str) -> str:
    """从 'github:owner/repo' 取 repo 名作为 plugin-name。"""
    return canonical.split("/", 1)[1]


def _read_version(clone_dir: Path) -> str:
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


def _copy_single_skill_form(clone_dir: Path, dest_plugin_dir: Path) -> list[str]:
    """单 skill 形态:把 clone_dir 根的 SKILL.md 落到 dest_plugin_dir/SKILL.md。

    注意:此形态下 dest_plugin_dir 既是 plugin 目录也是单 skill 目录,
    skills 列表里只放 repo 名(等于 plugin-name)。
    """
    dest_plugin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(clone_dir / "SKILL.md", dest_plugin_dir / "SKILL.md")
    # 单 skill 形态:skill name 取 repo 名(= plugin-name)
    return [dest_plugin_dir.name]


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
                ["git", "clone", "--depth", "1", clone_url, str(tmp_dir)],
                capture_output=True,
                timeout=120,
            )
        except FileNotFoundError as e:
            raise PluginInstallError("系统未安装 git,请先安装 git") from e
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
            raise PluginInstallError("未找到可导入的 skill(plugin 根无 SKILL.md 也无 skills/ 子目录)")

        # 3. 覆盖式升级:先删旧目录
        dest_plugin_dir = user_skills_dir / plugin_name
        if dest_plugin_dir.exists():
            shutil.rmtree(dest_plugin_dir)
        dest_plugin_dir.mkdir(parents=True, exist_ok=True)

        # 4. 复制 skills
        if form == "skills_dir":
            skills = _copy_skills_dir_form(tmp_dir, dest_plugin_dir)
        else:  # single_skill
            skills = _copy_single_skill_form(tmp_dir, dest_plugin_dir)

        if not skills:
            raise PluginInstallError("未找到可导入的 skill")

        # 5. 读 version + sha
        version = _read_version(tmp_dir) or _read_head_sha(tmp_dir)[:12]
        sha = _read_head_sha(tmp_dir)
        installed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 6. 更新 installed_plugins.json(覆盖式)
    plugin = InstalledPlugin(
        name=plugin_name,
        source=canonical,
        version=version,
        git_commit_sha=sha,
        installed_at=installed_at,
        skills=skills,
    )
    upsert_plugin(plugins_file, plugin)
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
        shutil.rmtree(dest)
    remove_plugin(plugins_file, name)
```

Also add `import logging` + `log = logging.getLogger(__name__)` at the top of the file (after the module docstring).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_installer.py -v`
Expected: all tests PASS (parse + install + uninstall)

- [ ] **Step 5: Run full unit suite to confirm no regression**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_installer.py tests/unit/test_skills_plugin_registry.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/skills/installer.py tests/unit/test_skills_installer.py
git commit -m "feat(skills): implement install_plugin + uninstall_plugin with 3-form detection"
```

---

### Task 5: loader.py — 二层扫描 + plugin_name 填充

**Files:**
- Modify: `src/taisang/skills/loader.py:15-88`
- Modify: `tests/unit/test_skills_loader.py` (append plugin-form tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_skills_loader.py`:

```python
def test_load_plugin_form_skills_subdir(tmp_path):
    """plugin 形态:user_dir/superpowers/<skill>/SKILL.md 二层结构。"""
    user_dir = tmp_path / "user"
    _write(
        user_dir / "superpowers" / "brainstorming" / "SKILL.md",
        "---\nname: brainstorming\ndescription: d\n---\nbody",
    )
    _write(
        user_dir / "superpowers" / "writing-plans" / "SKILL.md",
        "---\nname: writing-plans\ndescription: d2\n---\nbody2",
    )
    skills = load_skills(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    names = {s.name for s in skills}
    assert "brainstorming" in names
    assert "writing-plans" in names
    # plugin_name 字段填充
    bp = next(s for s in skills if s.name == "brainstorming")
    assert bp.plugin_name == "superpowers"
    wp = next(s for s in skills if s.name == "writing-plans")
    assert wp.plugin_name == "superpowers"


def test_load_plugin_form_and_single_form_coexist(tmp_path):
    """plugin 二层和旧单层结构在同一 user_dir 下共存。"""
    user_dir = tmp_path / "user"
    # 旧单层
    _write(user_dir / "legacy" / "SKILL.md", "---\nname: legacy\ndescription: d\n---\nbody")
    # plugin 二层
    _write(
        user_dir / "superpowers" / "brainstorming" / "SKILL.md",
        "---\nname: brainstorming\ndescription: d\n---\nbody",
    )
    skills = load_skills(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    by_name = {s.name: s for s in skills}
    assert "legacy" in by_name
    assert "brainstorming" in by_name
    assert by_name["legacy"].plugin_name is None
    assert by_name["brainstorming"].plugin_name == "superpowers"


def test_load_plugin_form_subdir_without_skill_md_skipped(tmp_path):
    """plugin 目录下没有 SKILL.md 的子目录跳过(不是 skill)。"""
    user_dir = tmp_path / "user"
    _write(
        user_dir / "superpowers" / "brainstorming" / "SKILL.md",
        "---\nname: brainstorming\ndescription: d\n---\nbody",
    )
    # 没装好的子目录,无 SKILL.md
    (user_dir / "superpowers" / "incomplete").mkdir(parents=True)
    skills = load_skills(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert {s.name for s in skills} == {"brainstorming"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_loader.py::test_load_plugin_form_skills_subdir -v`
Expected: FAIL — 当前 loader 只扫 `*/SKILL.md`,扫不到 `*/*/SKILL.md`,断言 `"brainstorming" in names` 失败。

- [ ] **Step 3: Write minimal implementation**

Modify `src/taisang/skills/loader.py`:

Change `_parse_skill_md` signature and body to accept optional `plugin_name`:

```python
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
```

Change the scan loop in `load_skills` to scan both layers:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_loader.py -v`
Expected: all tests PASS (including the 3 new ones and all existing ones)

- [ ] **Step 5: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/skills/loader.py tests/unit/test_skills_loader.py
git commit -m "feat(skills): loader scans */SKILL.md and */*/SKILL.md, fill plugin_name"
```

---

### Task 6: skills_api.py — 加 plugin 端点 + GET /api/skills 返回 plugin_name

**Files:**
- Modify: `src/taisang/web/skills_api.py`
- Modify: `tests/unit/test_skills_api.py` (append plugin API tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_skills_api.py`:

```python
import subprocess
from unittest.mock import patch


def _make_superpowers_fixture(tmp_path) -> Path:
    root = tmp_path / "fixture"
    (root / "skills" / "brainstorming").mkdir(parents=True)
    (root / "skills" / "brainstorming" / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: d\n---\nbody", encoding="utf-8"
    )
    (root / "skills" / "writing-plans").mkdir(parents=True)
    (root / "skills" / "writing-plans" / "SKILL.md").write_text(
        "---\nname: writing-plans\ndescription: d2\n---\nbody2", encoding="utf-8"
    )
    (root / "package.json").write_text('{"version": "5.1.0"}', encoding="utf-8")
    return root


def _fake_clone_factory(fixture_root: Path):
    def _fake(cmd, *a, **kw):
        target = Path(cmd[3])
        target.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(fixture_root, target, dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    return _fake


def _plugin_api_env(tmp_path, monkeypatch):
    """和 _skill_api_env 一样,但额外把 plugins_file 指到 tmp。"""
    user_dir = _skill_api_env(tmp_path, monkeypatch)
    plugins_file = tmp_path / "installed_plugins.json"
    monkeypatch.setattr("taisang.web.skills_api._PLUGINS_FILE", plugins_file)
    return user_dir, plugins_file


def test_install_plugin_api_success(tmp_path, monkeypatch):
    user_dir, plugins_file = _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123def456\n"):
            resp = client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["plugin"] == "superpowers"
    assert data["version"] == "5.1.0"
    assert "brainstorming" in data["skills"]
    # 落盘
    assert (user_dir / "superpowers" / "brainstorming" / "SKILL.md").exists()


def test_install_plugin_api_invalid_source_400(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/skills/install-plugin", json={"source": "not-a-url"})
    assert resp.status_code == 400
    assert "格式" in resp.json()["detail"] or "地址" in resp.json()["detail"]


def test_install_plugin_api_clone_failure_400(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    def _fail(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: not found")
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fail):
        resp = client.post("/api/skills/install-plugin", json={"source": "nobody/nope"})
    assert resp.status_code == 400
    assert "git clone" in resp.json()["detail"]


def test_list_plugins_api_empty(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.get("/api/skills/plugins")
    assert resp.status_code == 200
    assert resp.json() == {"plugins": []}


def test_list_plugins_api_after_install(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123\n"):
            client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    resp = client.get("/api/skills/plugins")
    data = resp.json()
    assert len(data["plugins"]) == 1
    p = data["plugins"][0]
    assert p["name"] == "superpowers"
    assert p["version"] == "5.1.0"
    assert "brainstorming" in p["skills"]


def test_uninstall_plugin_api_success(tmp_path, monkeypatch):
    user_dir, plugins_file = _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123\n"):
            client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    resp = client.delete("/api/skills/plugin/superpowers")
    assert resp.status_code == 200
    assert not (user_dir / "superpowers").exists()
    # 再 list 应空
    resp = client.get("/api/skills/plugins")
    assert resp.json() == {"plugins": []}


def test_uninstall_plugin_api_missing_404(tmp_path, monkeypatch):
    _plugin_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/plugin/nonexistent")
    assert resp.status_code == 404


def test_list_skills_returns_plugin_name(tmp_path, monkeypatch):
    user_dir, _ = _plugin_api_env(tmp_path, monkeypatch)
    fixture = _make_superpowers_fixture(tmp_path)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    with patch("taisang.skills.installer.subprocess.run", side_effect=_fake_clone_factory(fixture)):
        with patch("taisang.skills.installer.subprocess.check_output", return_value=b"abc123\n"):
            client.post("/api/skills/install-plugin", json={"source": "obra/superpowers"})
    resp = client.get("/api/skills")
    skills = resp.json()["skills"]
    bp = next(s for s in skills if s["name"] == "brainstorming")
    assert bp["plugin_name"] == "superpowers"
    # 非 plugin skill 的 plugin_name 为 None
    if any(s["name"] == "commit" for s in skills):
        commit = next(s for s in skills if s["name"] == "commit")
        assert commit["plugin_name"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_api.py -v -k "install_plugin or list_plugins or uninstall_plugin or list_skills_returns_plugin_name"`
Expected: FAIL — 路由不存在（404/405）或 `_PLUGINS_FILE` 不存在。

- [ ] **Step 3: Write minimal implementation**

Modify `src/taisang/web/skills_api.py`. Add imports at top (after existing imports):

```python
from ..skills.installer import (
    PluginInstallError,
    install_plugin,
    uninstall_plugin,
)
from ..skills.plugin_registry import load_plugins
```

Add `_PLUGINS_FILE` constant after `_STATE_FILE`:

```python
_PLUGINS_FILE = Path.home() / ".taisang" / "installed_plugins.json"
```

Add `plugin_name` to the `list_skills` response:

```python
    @app.get("/api/skills")
    async def list_skills() -> dict:
        """列出所有 skill(name/description/when_to_use/source/allowed_tools/disabled/plugin_name)。"""
        skills = load_skills_with_state(source_root)
        return {"skills": [
            {
                "name": s.name,
                "description": s.description,
                "when_to_use": s.when_to_use,
                "source": s.source,
                "allowed_tools": s.allowed_tools,
                "disabled": s.disabled,
                "plugin_name": s.plugin_name,
            }
            for s in skills
        ]}
```

Add three new routes (before `register_skills_routes` returns, inside the function):

```python
    @app.post("/api/skills/install-plugin")
    async def install_plugin_route(body: dict) -> dict:
        """安装 plugin:git clone + 批量导入 skills 到 user 源。"""
        source = (body or {}).get("source", "").strip()
        if not source:
            raise HTTPException(400, "source 不能为空")
        root = _import_root()
        try:
            plugin = install_plugin(source, root, _PLUGINS_FILE)
        except PluginInstallError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "plugin": plugin.name,
            "version": plugin.version,
            "sha": plugin.git_commit_sha,
            "source": plugin.source,
            "skills": plugin.skills,
        }

    @app.get("/api/skills/plugins")
    async def list_plugins_route() -> dict:
        """列出已安装的 plugin。"""
        plugins = load_plugins(_PLUGINS_FILE)
        return {"plugins": [
            {
                "name": p.name,
                "source": p.source,
                "version": p.version,
                "git_commit_sha": p.git_commit_sha,
                "installed_at": p.installed_at,
                "skills": p.skills,
            }
            for p in plugins.values()
        ]}

    @app.delete("/api/skills/plugin/{name}")
    async def uninstall_plugin_route(name: str) -> dict:
        """卸载 plugin:删 user 源下该 plugin 目录 + 删 installed_plugins.json 条目。"""
        root = _import_root()
        try:
            uninstall_plugin(name, root, _PLUGINS_FILE)
        except PluginInstallError as e:
            raise HTTPException(404, str(e)) from e
        return {"ok": True, "uninstalled": name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/test_skills_api.py -v`
Expected: all tests PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/web/skills_api.py tests/unit/test_skills_api.py
git commit -m "feat(api): add install-plugin/uninstall-plugin/list-plugins endpoints + plugin_name in GET /api/skills"
```

---

### Task 7: SkillManage.vue — 加安装按钮 + 已装 Plugin 面板 + Plugin 列 + 安装/卸载 Dialog

**Files:**
- Modify: `src/taisang/web/frontend/src/views/SkillManage.vue`

- [ ] **Step 1: Read current SkillManage.vue to confirm line numbers**

Run: `Read src/taisang/web/frontend/src/views/SkillManage.vue`
Confirm: template starts line 1, script line 66, style line 195.

- [ ] **Step 2: Replace the whole `<template>` section**

Replace lines 1-64 (the entire `<template>...</template>`) with:

```vue
<template>
  <div class="skill-manage">
    <div class="page-header">
      <h2 class="page-title">Skill 管理</h2>
      <div class="header-actions">
        <t-button theme="primary" aria-label="安装 plugin" @click="openInstallDialog">
          <template #icon>
            <t-icon name="cloud-download" />
          </template>
          安装 Plugin
        </t-button>
        <t-button variant="outline" aria-label="导入 skill" @click="fileInput?.click()">
          <template #icon>
            <t-icon name="upload" />
          </template>
          导入 Skill
        </t-button>
        <t-button variant="outline" aria-label="重载 skills" @click="reload">
          <template #icon>
            <t-icon name="refresh" />
          </template>
          重载
        </t-button>
      </div>
    </div>
    <input
      ref="fileInput"
      type="file"
      accept=".md,.zip"
      style="display: none"
      @change="onImportFile"
    />

    <!-- 已装 Plugin 面板 -->
    <t-collapse v-model="pluginPanelExpanded" class="plugin-panel">
      <t-collapse-panel value="plugins" header="已装 Plugin">
        <template #header>
          <span class="panel-title">已装 Plugin</span>
          <t-tag theme="primary" size="small" shape="round" class="panel-count">
            {{ plugins.length }}
          </t-tag>
        </template>
        <t-table
          v-if="plugins.length > 0"
          row-key="name"
          :data="plugins"
          :columns="pluginColumns"
          :pagination="false"
          size="small"
        >
          <template #source="{ row }">
            <code class="mono">{{ row.source }}</code>
          </template>
          <template #version="{ row }">
            <t-tag size="small" variant="light">v{{ row.version }}</t-tag>
          </template>
          <template #skillsCount="{ row }">
            <span class="skill-count">{{ row.skills.length }} 个</span>
          </template>
          <template #installedAt="{ row }">
            <span class="dim">{{ formatTime(row.installed_at) }}</span>
          </template>
          <template #op="{ row }">
            <t-button variant="text" size="small" @click="upgradePlugin(row)">
              升级
            </t-button>
            <t-button variant="text" theme="danger" size="small" @click="confirmUninstall(row)">
              卸载
            </t-button>
          </template>
        </t-table>
        <div v-else class="empty-tip">
          暂无已安装 plugin。点右上角"安装 Plugin"输入 github 地址(如 <code>obra/superpowers</code>)。
        </div>
      </t-collapse-panel>
    </t-collapse>

    <!-- Skill 表格 -->
    <t-table row-key="name" :data="skills" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag
          :theme="row.source === 'project' ? 'primary' : row.source === 'system' ? 'warning' : 'default'"
          size="small"
        >
          {{ row.source === 'project' ? '项目' : row.source === 'system' ? '内置' : '用户' }}
        </t-tag>
      </template>
      <template #pluginName="{ row }">
        <t-tag v-if="row.plugin_name" theme="primary" size="small" shape="round">
          {{ row.plugin_name }}
        </t-tag>
        <span v-else class="dim">—</span>
      </template>
      <template #allowed_tools="{ row }">
        <span v-if="row.allowed_tools">{{ row.allowed_tools.join(', ') }}</span>
        <span v-else class="dim">不限制</span>
      </template>
      <template #enabled="{ row }">
        <t-switch :value="!row.disabled" @change="() => toggle(row.name)" />
      </template>
      <template #op="{ row }">
        <t-button
          v-if="row.source !== 'system' && !row.plugin_name"
          variant="text"
          theme="danger"
          size="small"
          @click="confirmDelete(row.name)"
        >
          删除
        </t-button>
        <span v-else-if="row.plugin_name" class="dim" title="plugin 来源 skill 请到已装 Plugin 面板整包卸载">
          整包卸载
        </span>
        <span v-else class="dim">-</span>
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无自定义 skill。点右上角"导入 Skill"上传 .md 或 .zip,
          或用"安装 Plugin"从 github 拉取整包。
        </div>
      </template>
    </t-table>

    <!-- 安装 Plugin Dialog -->
    <t-dialog
      v-model:visible="installDialogVisible"
      header="安装 Plugin"
      :confirm-btn="installing ? null : '安装'"
      :cancel-btn="installing ? null : '取消'"
      :close-on-overlay-click="!installing"
      :close-on-esc-keydown="!installing"
      @confirm="doInstall"
    >
      <t-form>
        <t-form-item label="GitHub 地址" help="支持 owner/repo、https://github.com/owner/repo[.git]">
          <t-input
            v-model="installSource"
            placeholder="obra/superpowers"
            :disabled="installing"
            @enter="doInstall"
          />
        </t-form-item>
      </t-form>
      <t-alert
        v-if="installError"
        theme="error"
        :message="installError"
        class="install-error"
      />
      <div v-if="installing" class="install-progress">
        <t-loading />
        <span class="install-step">正在安装 {{ installSource }} ...</span>
        <div class="install-steps-text">
          git clone → 扫描 plugin 结构 → 批量导入 skills
        </div>
      </div>
      <t-alert
        v-else
        theme="warning"
        message="同名 plugin 重复安装会覆盖升级(先删后装),原有 skill 会被清空重拉。"
        class="install-warning"
      />
    </t-dialog>
  </div>
</template>
```

- [ ] **Step 3: Replace the whole `<script setup lang="ts">` section**

Replace lines 66-193 (the entire `<script setup>...</script>`) with:

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'

interface SkillRow {
  name: string
  description: string
  when_to_use: string
  source: 'user' | 'project' | 'system'
  allowed_tools: string[] | null
  disabled: boolean
  plugin_name: string | null
}

interface InstalledPlugin {
  name: string
  source: string
  version: string
  git_commit_sha: string
  installed_at: string
  skills: string[]
}

const skills = ref<SkillRow[]>([])
const plugins = ref<InstalledPlugin[]>([])
const loading = ref(false)
const fileInput = ref<HTMLInputElement>()

// 已装 Plugin 面板:默认展开
const pluginPanelExpanded = ref<string[]>(['plugins'])

// 安装 Dialog 状态
const installDialogVisible = ref(false)
const installSource = ref('')
const installing = ref(false)
const installError = ref('')

const columns = [
  { colKey: 'name', title: '名称', width: 160 },
  { colKey: 'description', title: '描述', ellipsis: true },
  { colKey: 'source', title: '来源', width: 80, cell: 'source' },
  { colKey: 'pluginName', title: 'Plugin', width: 120, cell: 'pluginName' },
  { colKey: 'allowed_tools', title: '工具限制', width: 130, cell: 'allowed_tools' },
  { colKey: 'enabled', title: '启用', width: 70, cell: 'enabled' },
  { colKey: 'op', title: '操作', width: 100, cell: 'op' },
]

const pluginColumns = [
  { colKey: 'name', title: '名称', width: 140 },
  { colKey: 'version', title: '版本', width: 80, cell: 'version' },
  { colKey: 'skillsCount', title: 'Skills', width: 80, cell: 'skillsCount' },
  { colKey: 'source', title: '来源', cell: 'source' },
  { colKey: 'installedAt', title: '安装时间', width: 140, cell: 'installedAt' },
  { colKey: 'op', title: '操作', width: 140, cell: 'op' },
]

function formatTime(iso: string): string {
  if (!iso) return ''
  // 取 YYYY-MM-DD HH:MM
  return iso.replace('T', ' ').slice(0, 16)
}

async function fetchSkills() {
  loading.value = true
  try {
    const r = await fetch('/api/skills')
    const data = await r.json()
    skills.value = data.skills ?? []
  } catch {
    MessagePlugin.error('加载 skills 失败')
  } finally {
    loading.value = false
  }
}

async function fetchPlugins() {
  try {
    const r = await fetch('/api/skills/plugins')
    const data = await r.json()
    plugins.value = data.plugins ?? []
  } catch {
    MessagePlugin.error('加载 plugins 失败')
  }
}

async function toggle(name: string) {
  try {
    await fetch(`/api/skills/${name}/toggle`, { method: 'POST' })
    await fetchSkills()
  } catch {
    MessagePlugin.error('切换失败')
  }
}

async function reload() {
  try {
    await fetch('/api/skills/reload', { method: 'POST' })
    await Promise.all([fetchSkills(), fetchPlugins()])
    MessagePlugin.success('已重载')
  } catch {
    MessagePlugin.error('重载失败')
  }
}

async function onImportFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const ok = await doImport(file, false)
  if (ok) {
    await fetchSkills()
    MessagePlugin.success(`已导入 ${file.name}`)
  }
  input.value = ''
}

async function doImport(file: File, overwrite: boolean): Promise<boolean> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`/api/skills/import?overwrite=${overwrite}`, {
    method: 'POST',
    body: fd,
  })
  if (r.status === 409) {
    const confirmed = await new Promise<boolean>((resolve) => {
      const dialog = DialogPlugin.confirm({
        header: 'Skill 已存在',
        body: '同名 skill 已存在,是否覆盖?',
        confirmBtn: '覆盖',
        cancelBtn: '取消',
        onConfirm: () => {
          dialog.destroy()
          resolve(true)
        },
        onClose: () => {
          dialog.destroy()
          resolve(false)
        },
      })
    })
    if (confirmed) return doImport(file, true)
    return false
  }
  if (!r.ok) {
    const data = (await r.json().catch(() => ({}))) as { detail?: string }
    MessagePlugin.error(data.detail ?? '导入失败')
    return false
  }
  return true
}

function confirmDelete(name: string) {
  const dialog = DialogPlugin.confirm({
    header: '删除 skill',
    body: `确定删除 "${name}"?该操作不可恢复。`,
    confirmBtn: '删除',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      const r = await fetch(`/api/skills/${name}`, { method: 'DELETE' })
      if (r.ok) {
        await fetchSkills()
        MessagePlugin.success('已删除')
      } else {
        const data = (await r.json().catch(() => ({}))) as { detail?: string }
        MessagePlugin.error(data.detail ?? '删除失败')
      }
    },
  })
}

// ===== Plugin 安装/卸载 =====

function openInstallDialog() {
  installSource.value = ''
  installError.value = ''
  installing.value = false
  installDialogVisible.value = true
}

async function doInstall() {
  if (!installSource.value.trim()) {
    installError.value = '请输入 github 地址'
    return
  }
  installing.value = true
  installError.value = ''
  try {
    const r = await fetch('/api/skills/install-plugin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: installSource.value.trim() }),
    })
    const data = (await r.json().catch(() => ({}))) as {
      plugin?: string
      version?: string
      skills?: string[]
      detail?: string
    }
    if (!r.ok) {
      installError.value = data.detail ?? '安装失败'
      installing.value = false
      return
    }
    installDialogVisible.value = false
    installing.value = false
    MessagePlugin.success(
      `已安装 ${data.plugin} v${data.version}（${(data.skills ?? []).length} 个 skill）`
    )
    await Promise.all([fetchSkills(), fetchPlugins()])
  } catch (e) {
    installError.value = `安装失败: ${e}`
    installing.value = false
  }
}

function upgradePlugin(row: InstalledPlugin) {
  // 升级 = 用同样 source 再装一次
  installSource.value = row.source.replace(/^github:/, '')
  installError.value = ''
  installing.value = false
  installDialogVisible.value = true
}

function confirmUninstall(row: InstalledPlugin) {
  const dialog = DialogPlugin.confirm({
    header: `确认卸载 ${row.name}?`,
    body: `将同时删除该 plugin 下的 ${row.skills.length} 个 skills。此操作不可撤销。`,
    confirmBtn: '确认卸载',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      const r = await fetch(`/api/skills/plugin/${row.name}`, { method: 'DELETE' })
      if (r.ok) {
        await Promise.all([fetchSkills(), fetchPlugins()])
        MessagePlugin.success(`已卸载 ${row.name}（移除 ${row.skills.length} 个 skill）`)
      } else {
        const data = (await r.json().catch(() => ({}))) as { detail?: string }
        MessagePlugin.error(data.detail ?? '卸载失败')
      }
    },
  })
}

onMounted(() => {
  fetchSkills()
  fetchPlugins()
})
</script>
```

- [ ] **Step 4: Replace the whole `<style scoped>` section**

Replace lines 195-230 (the entire `<style scoped>...</style>`) with:

```vue
<style scoped>
.skill-manage {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 1100px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.dim {
  color: var(--td-text-color-placeholder);
}
.empty-tip {
  padding: 24px 16px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.empty-tip code {
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
.plugin-panel {
  margin-bottom: 16px;
}
.panel-title {
  font-weight: 600;
}
.panel-count {
  margin-left: 8px;
}
.mono {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
.skill-count {
  color: var(--td-brand-color);
}
.install-error {
  margin-top: 12px;
}
.install-warning {
  margin-top: 12px;
}
.install-progress {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.install-step {
  font-weight: 500;
}
.install-steps-text {
  color: var(--td-text-color-placeholder);
  font-size: 12px;
}
</style>
```

- [ ] **Step 5: Build frontend to verify no TS errors**

Run: `cd D:\GoProject\TaiSang\src\taisang\web\frontend && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 6: Run full unit test suite to confirm backend still passes**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/ -x --ignore=tests/unit/test_agent_core.py -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
cd D:\GoProject\TaiSang
git add src/taisang/web/frontend/src/views/SkillManage.vue
git commit -m "feat(ui): SkillManage plugin install panel + dialog + Plugin column"
```

---

### Task 8: Playwright 端到端验证（使用 superpowers 真实安装）

**Files:**
- No code changes; verification only

**Prerequisite:** TaiSang web service running at http://localhost:8765. If not running, start it:

```bash
cd D:\GoProject\TaiSang
python -m taisang.web.app --port 8765
```

(set `run_in_background: true` on the Bash tool call so the service survives across turns.)

- [ ] **Step 1: Confirm service is up**

Run: `curl -s http://localhost:8765/api/skills/plugins`
Expected: `{"plugins":[]}` (or a list of already-installed plugins if any).

- [ ] **Step 2: Navigate to Skill Manage page**

Use `mcp__playwright__playwright_navigate` to `http://localhost:8765/skills`.
Then use `mcp__playwright__playwright_get_visible_text` to confirm the page loaded (should contain "Skill 管理" and "安装 Plugin" button text).

- [ ] **Step 3: Verify "安装 Plugin" button visible**

Use `mcp__playwright__playwright_get_visible_html` and grep for "安装 Plugin".
Expected: present.

- [ ] **Step 4: Verify "已装 Plugin" panel visible**

Use `mcp__playwright__playwright_get_visible_text` — should contain "已装 Plugin".

- [ ] **Step 5: Click "安装 Plugin" button to open dialog**

Use `mcp__playwright__playwright_click` with selector that matches the "安装 Plugin" button (use `playwright_get_visible_html` first to find the exact selector, likely `button` containing "安装 Plugin" text).
Then `playwright_get_visible_text` — should contain "GitHub 地址" and "支持 owner/repo".

- [ ] **Step 6: Fill input with `obra/superpowers`**

Use `mcp__playwright__playwright_fill` with the input selector and value `obra/superpowers`.

- [ ] **Step 7: Click "安装" button**

Use `mcp__playwright__playwright_click` on the confirm button.
This triggers a REAL git clone to github.com/obra/superpowers. Wait 30-60 seconds (the dialog shows loading).

- [ ] **Step 8: Wait for install to complete**

Use `mcp__playwright__playwright_wait_for` with `text: "已安装"` (toast) OR wait for the dialog to close and "已装 Plugin" panel to show "superpowers". Use a generous timeout (60s).

- [ ] **Step 9: Verify "已装 Plugin" panel shows superpowers**

Use `mcp__playwright__playwright_get_visible_text`.
Expected: panel shows `superpowers`, version (e.g. `v5.1.0` or commit SHA), skills count, `github:obra/superpowers`.

- [ ] **Step 10: Verify Skill table shows plugin skills with Plugin column**

Use `mcp__playwright__playwright_get_visible_text`.
Expected: skills like `brainstorming`, `writing-plans`, `using-superpowers` appear in the table, with `superpowers` shown in the Plugin column area.

- [ ] **Step 11: Verify Skill table Plugin column for non-plugin skills**

If any user-imported single-file skill exists, it should show `—` in Plugin column (or nothing).
If only plugin skills exist, verify system skills show `—`.

- [ ] **Step 12: Verify operation column for plugin skill**

For a plugin skill row, the operation column should show "整包卸载" gray text (not a red "删除" button).
Use `playwright_get_visible_html` and grep for "整包卸载".

- [ ] **Step 13: Test uninstall — click "卸载" on superpowers**

Use `playwright_click` on the "卸载" button in the plugin panel row.
A confirm dialog appears. Use `playwright_get_visible_text` — should contain "确认卸载" and "将同时删除".

- [ ] **Step 14: Confirm uninstall**

Click "确认卸载" button.
Wait for toast "已卸载 superpowers" (use `playwright_wait_for` with `text: "已卸载"`).

- [ ] **Step 15: Verify plugin and skills are gone**

`playwright_get_visible_text` — "已装 Plugin" panel should show empty state ("暂无已安装 plugin").
Skill table should no longer contain `brainstorming` etc.

- [ ] **Step 16: Re-install to leave user in clean installed state (optional)**

If the user wants superpowers to remain installed, repeat Steps 5-9 to reinstall.

- [ ] **Step 17: Final unit test sweep**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/ -x --ignore=tests/unit/test_agent_core.py -q`
Expected: all PASS

- [ ] **Step 18: No commit (verification only)**

This task is verification only — no code changes, no commit.

---

### Task 9: 收尾 — 跑全量测试 + 更新 memory + push

**Files:**
- Modify: `C:\Users\50892\.claude\projects\C--Users-50892\memory\MEMORY.md` (add index entry)
- Create: `C:\Users\50892\.claude\projects\C--Users-50892\memory\2026-09-11-taisang-plugin-install.md`

- [ ] **Step 1: Run full unit test suite**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/ -x --ignore=tests/unit/test_agent_core.py -q`
Expected: all PASS

- [ ] **Step 2: Confirm test count**

Run: `cd D:\GoProject\TaiSang && python -m pytest tests/unit/ --ignore=tests/unit/test_agent_core.py --co -q | tail -5`
Expected: should show more tests than the pre-feature baseline (617 + new tests ~25).

- [ ] **Step 3: Write memory file**

Create `C:\Users\50892\.claude\projects\C--Users-50892\memory\2026-09-11-taisang-plugin-install.md`:

```markdown
# 2026-09-11 TaiSang Plugin 安装系统

## 概要
D:/GoProject/TaiSang Skill 管理页加 plugin 安装功能,用户输入 github 地址(如 obra/superpowers)直接 git clone + 批量导入 plugin 内所有 skills 到 user 源,UI 统一管理已装 plugin(查看/卸载/升级)。

## 改动
1. **后端新建 installer.py**: parse_github_source 规范化 + install_plugin(3 形态识别:skills_dir/single_skill/marketplace) + uninstall_plugin(覆盖式升级)
2. **后端新建 plugin_registry.py**: installed_plugins.json 读写(原子写 + 损坏当空 dict)
3. **loader.py 二层扫描**: 兼容 */SKILL.md(旧单层)+ */*/SKILL.md(plugin 二层);Skill dataclass 加 plugin_name 字段
4. **skills_api.py 加 3 端点**: POST /api/skills/install-plugin、DELETE /api/skills/plugin/<name>、GET /api/skills/plugins;GET /api/skills 返回加 plugin_name
5. **SkillManage.vue UI**: 页头加"安装 Plugin"蓝按钮 + 已装 Plugin 折叠面板(默认展开)+ Skill 表格加 Plugin 列 + 安装 Dialog(输入/loading/error/warning)+ 卸载确认 Dialog;plugin skill 操作列显示"整包卸载"灰字禁止单删

## 关键设计
- plugin-name 从 repo 名取(不用 package.json name,可能不一致)
- 覆盖式升级:同名 plugin 先 rmtree 再写,旧 skill 清空重拉
- 安全:parse_github_source 只接受 github.com + owner/repo 格式,杜绝命令注入;git clone 用 subprocess 列表参数不经 shell
- 不执行 plugin 内任何脚本(hooks/agents/scripts 只复制不执行)
- 不做 slash 指令系统(YAGNI,UI 已覆盖)
- 不做 marketplace.json 解析(用户指定具体 plugin 仓库)
- 不做私有仓库 token 配置(依赖机器 git 配置)

## 落盘结构
~/.taisang/
├── installed_plugins.json          # 已装 plugin 索引
└── skills/<plugin-name>/<skill>/   # plugin 形态
└── skills/<single-skill>/          # 旧单层形态(向后兼容)

## 验证
- 单元测试: installer + plugin_registry + loader 二层 + api 端点
- Playwright: 真实安装 obra/superpowers,验证已装 Plugin 面板/Skill 表格 Plugin 列/卸载流程
```

- [ ] **Step 4: Update memory index**

Edit `C:\Users\50892\.claude\projects\C--Users-50892\memory\MEMORY.md` — add this entry at the top of the list:

```markdown
- [2026-09-11 TaiSang Plugin 安装系统](2026-09-11-taisang-plugin-install.md) — D:/GoProject/TaiSang Skill 管理页加 plugin 安装(github clone + 批量导入),installer.py + plugin_registry.py + loader 二层扫描 + 3 API 端点 + SkillManage.vue UI(安装按钮/已装面板/Plugin 列/Dialog),单元测试 + playwright 真实装 superpowers 验证
```

- [ ] **Step 5: Check git status and log**

Run: `cd D:\GoProject\TaiSang && git status && git log --oneline -10`
Expected: 7 new commits (Task 1-7), working tree clean (memory files are outside repo).

- [ ] **Step 6: Push to remote**

Run: `cd D:\GoProject\TaiSang && git push origin main`
Expected: push succeeds.

- [ ] **Step 7: Final verification — service still up and plugin page works**

`curl -s http://localhost:8765/api/skills/plugins`
Expected: `{"plugins":[...]}` — if superpowers was reinstalled in Task 8, shows it; otherwise empty.

- [ ] **Step 8: Done — report summary to user**

Report: number of commits, test count, verification result, memory file written, pushed.

---

## Self-Review Checklist (已自检)

**1. Spec coverage:**
- ✅ Skill 管理页"安装 Plugin"按钮 + 输入 dialog → Task 7
- ✅ 后端 git clone + 扫描 plugin 结构 + 批量导入 → Task 4
- ✅ installed_plugins.json 记录 → Task 2 + Task 4
- ✅ Skill 管理页"已装 Plugin"折叠面板 → Task 7
- ✅ skill 列表加"Plugin"列 → Task 7
- ✅ plugin 来源 skill 禁止单删 → Task 7 (op template v-if !row.plugin_name)
- ✅ Plugin 结构识别 3 形态 → Task 4 (_detect_plugin_form)
- ✅ plugin-name 从 repo 名取 → Task 4 (_plugin_name_from_source)
- ✅ load_skills 二层扫描兼容 → Task 5
- ✅ Skill dataclass 加 plugin_name → Task 1
- ✅ 3 个 API 端点 → Task 6
- ✅ 错误处理（git 未装/clone 失败/marketplace/无 skill/不存在卸载）→ Task 4 + Task 6
- ✅ 安全（parse 规范化 / subprocess 列表参数 / 不执行脚本）→ Task 3 + Task 4
- ✅ 原子写 installed_plugins.json → Task 2

**2. Placeholder scan:** 无 TBD/TODO/"add error handling"等占位符。

**3. Type consistency:**
- `InstalledPlugin` 字段: name/source/version/git_commit_sha/installed_at/skills — Task 2 定义，Task 4/6 使用一致
- `PluginInstallError` — Task 3 定义，Task 4/6 import 一致
- `parse_github_source` 返回 `github:owner/repo` — Task 3 定义，Task 4 使用
- `install_plugin(source, user_skills_dir, plugins_file) -> InstalledPlugin` — Task 4 定义，Task 6 使用
- `uninstall_plugin(name, user_skills_dir, plugins_file)` — Task 4 定义，Task 6 使用
- `load_plugins/save_plugins/upsert_plugin/remove_plugin` — Task 2 定义，Task 4 使用
- `_PLUGINS_FILE` — Task 6 定义并 monkeypatch
- `plugin_name` 字段 — Task 1 加到 Skill，Task 5 填充，Task 6 返回，Task 7 渲染
- 前端 `InstalledPlugin` interface — Task 7 定义，和后端 Task 6 返回字段一致（name/source/version/git_commit_sha/installed_at/skills）