# Skill 前端导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端 SkillManage 页支持导入 skill(单 MD 或 zip)与删除,loader 增加 system 来源并内置 2 个默认 skill。

**Architecture:** 后端新增 `skills/importer.py`(校验 + 落盘 `~/.taisang/skills/<name>/`),skills_api 加 `POST /api/skills/import`(409 冲突 → overwrite 确认覆盖)和 `DELETE /api/skills/{name}`(system 不可删);loader 加 `system_dirs`(包内 `builtin/` 目录,优先级 project > user > system);前端加导入按钮 + 覆盖确认 + 行内删除。

**Tech Stack:** Python 3.12 + FastAPI(UploadFile)+ zipfile/pathlib;Vue 3.5 + TDesign(DialogPlugin)+ Vite。

**泰哥已确认的决策:**
1. zip 解压到 `~/.taisang/skills/<name>/` 目录形式;单 MD 也统一建成目录
2. 同名冲突 → 409 → 前端确认 → overwrite=true 覆盖
3. 校验:SKILL.md 在 zip 根(或唯一一级目录下)、frontmatter 必须有合法 name、zip-slip 拦截、10MB 上限
4. source 只分 user/project/system;包内默认带 2 个内置 skill(commit、review)
5. 支持 delete(内置不可删,同时清 disabled 状态记录)
6. SkillManage 右上角"导入 Skill"按钮

**安全要点(实现时不可省):**
- frontmatter name 必须匹配 `^[A-Za-z0-9][A-Za-z0-9_-]*$`(防目录穿越)
- zip 成员路径:拒绝对路径、`..`、反斜杠;所有成员必须在 SKILL.md 所在目录前缀之下
- delete 只允许删 dir_path.parent 在已配置 user/project 目录内的 skill

---

### Task 1: loader 支持 system 来源 + 内置 skill

**Files:**
- Create: `src/taisang/skills/builtin/commit/SKILL.md`
- Create: `src/taisang/skills/builtin/review/SKILL.md`
- Modify: `src/taisang/skills/loader.py`
- Test: `tests/unit/test_skills_loader.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_skills_loader.py` 末尾追加:

```python
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
```

(若文件里没有 `_write` helper,在文件顶部补:

```python
def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
```

)

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/unit/test_skills_loader.py -v`
Expected: 3 个新测试 FAIL(load_skills 不接受 system_dirs 参数 / builtin 不存在)

- [ ] **Step 3: 实现**

`src/taisang/skills/loader.py` 的 `load_skills` 改为:

```python
# 包内内置 skill 目录,source=system,优先级最低
BUILTIN_SKILLS_DIR = Path(__file__).parent / "builtin"


def load_skills(
    user_dirs: list[Path],
    project_dirs: list[Path],
    system_dirs: list[Path] | None = None,
) -> list[Skill]:
    """扫描三源 skill 目录,返回去重后的 Skill 列表。

    优先级(同名覆盖):project > user > system。
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
            for skill_md in sorted(d.glob("*/SKILL.md")):
                skill = _parse_skill_md(skill_md, source)
                if skill is None:
                    continue
                by_name[skill.name] = skill
    return list(by_name.values())
```

- [ ] **Step 4: 创建内置 skill 文件**

`src/taisang/skills/builtin/commit/SKILL.md`:

```markdown
---
name: commit
description: 查看 git 改动并生成 commit message 提交
when_to_use: 用户要求提交代码、写 commit message 时
allowed_tools:
  - Bash
  - read_file
---

# 提交代码

按以下步骤执行:

1. `git status` + `git diff`(含 `--stat`)了解全部改动,不要只看单个文件
2. 判断改动意图,归纳成一个 commit;若改动包含多个不相关主题,向用户建议拆分
3. 写 commit message:
   - 格式:`type: 简述(中文)`;type 从 feat/fix/refactor/test/docs/chore 里选
   - 首行 ≤50 字符,正文(可省略)说明 why,不重复 diff 能看到的 what
4. 提交前把 message 给用户过目确认,再执行 `git add`(只加相关文件,不要无脑 `-A`)+ `git commit`
5. 不要 push,除非用户明确要求
```

`src/taisang/skills/builtin/review/SKILL.md`:

```markdown
---
name: review
description: 审查当前 git 改动或指定代码,输出问题清单
when_to_use: 用户要求 review 代码、审查改动时
---

# 代码审查

1. 确定审查范围:用户指定了文件/目录就只看那些;否则 `git diff`(有未提交改动)或 `git diff HEAD~1`(看最近一次提交)
2. 逐文件读上下文,不要只看 diff 片段就下结论
3. 按优先级输出问题:
   - **正确性**:逻辑错误、边界条件、异常路径
   - **安全**:注入、路径穿越、敏感信息泄露
   - **可读性/一致性**:命名、与代码库现有风格不符
4. 每条问题带 `file:line` 定位 + 一句修改建议;没有问题的维度不要硬凑
5. 结尾给整体结论:可合入 / 建议修改后再合入
```

- [ ] **Step 5: 跑测试确认绿**

Run: `python -m pytest tests/unit/test_skills_loader.py tests/unit/test_skills_api.py tests/unit/test_skill_e2e.py -v`
Expected: 全部 PASS(注意:test_skills_api / e2e 走 load_skills_with_state 默认参数,现在会带上 2 个内置 skill——若有测试断言 skill 总数,按新基线修正断言内容而不是改实现)

- [ ] **Step 6: Commit**

```bash
git add src/taisang/skills/loader.py src/taisang/skills/builtin/ tests/unit/test_skills_loader.py
git commit -m "feat(skill): loader 支持 system 来源 + 内置 commit/review 两个 skill"
```

---

### Task 2: importer 模块(MD/zip 校验 + 落盘)

**Files:**
- Create: `src/taisang/skills/importer.py`
- Test: `tests/unit/test_skill_importer.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_skill_importer.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/unit/test_skill_importer.py -v`
Expected: collection error(ModuleNotFoundError: taisang.skills.importer)

- [ ] **Step 3: 实现**

创建 `src/taisang/skills/importer.py`:

```python
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
```

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest tests/unit/test_skill_importer.py -v`
Expected: 17 PASS

- [ ] **Step 5: Commit**

```bash
git add src/taisang/skills/importer.py tests/unit/test_skill_importer.py
git commit -m "feat(skill): importer 模块(MD/zip 校验、zip-slip 防护、覆盖语义)"
```

---

### Task 3: API 路由(import + delete)

**Files:**
- Modify: `src/taisang/web/skills_api.py`
- Test: `tests/unit/test_skills_api.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_skills_api.py` 末尾追加(复用文件里已有的 monkeypatch 模式):

```python
def _skill_api_env(tmp_path, monkeypatch, state_json="{}"):
    """统一环境:settings 指 tmp、state 文件指 tmp、user_dirs 指 tmp/skills。"""
    user_dir = tmp_path / "skills"
    settings = tmp_path / "settings.json"
    settings.write_text(
        f'{{"skills": {{"user_dirs": ["{user_dir.as_posix()}"]}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("taisang.config._settings_path", lambda: settings)
    state_file = tmp_path / "skills_state.json"
    state_file.write_text(state_json, encoding="utf-8")
    monkeypatch.setattr("taisang.web.skills_api._STATE_FILE", state_file)
    return user_dir


def test_import_md_via_api(tmp_path, monkeypatch):
    user_dir = _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    md = b"---\nname: alpha\ndescription: d\n---\nbody"
    resp = client.post(
        "/api/skills/import", files={"file": ("alpha.md", md, "text/markdown")}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "alpha"
    assert (user_dir / "alpha" / "SKILL.md").exists()
    # list 里能看到
    resp = client.get("/api/skills")
    assert any(s["name"] == "alpha" for s in resp.json()["skills"])


def test_import_md_conflict_409_then_overwrite(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    md = b"---\nname: alpha\ndescription: v1\n---\nv1"
    assert client.post(
        "/api/skills/import", files={"file": ("alpha.md", md, "text/markdown")}
    ).status_code == 200
    # 同名再导 → 409
    resp = client.post(
        "/api/skills/import",
        files={"file": ("alpha.md", b"---\nname: alpha\ndescription: v2\n---\nv2", "text/markdown")},
    )
    assert resp.status_code == 409
    # overwrite=true → 覆盖成功
    resp = client.post(
        "/api/skills/import?overwrite=true",
        files={"file": ("alpha.md", b"---\nname: alpha\ndescription: v2\n---\nv2", "text/markdown")},
    )
    assert resp.status_code == 200


def test_import_bad_extension_400(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/skills/import", files={"file": ("x.exe", b"bin", "application/octet-stream")}
    )
    assert resp.status_code == 400


def test_import_md_missing_name_400(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/skills/import", files={"file": ("a.md", b"no frontmatter", "text/markdown")}
    )
    assert resp.status_code == 400
    assert "frontmatter" in resp.json()["detail"]


def test_delete_user_skill(tmp_path, monkeypatch):
    user_dir = _skill_api_env(tmp_path, monkeypatch, state_json='{"alpha": true}')
    (user_dir / "alpha").mkdir(parents=True)
    (user_dir / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: d\n---\nbody", encoding="utf-8"
    )
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/alpha")
    assert resp.status_code == 200
    assert not (user_dir / "alpha").exists()
    # disabled 状态记录一起清掉(重导入同名不会莫名 disabled)
    import json
    state = json.loads((tmp_path / "skills_state.json").read_text(encoding="utf-8"))
    assert "alpha" not in state


def test_delete_system_skill_400(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/commit")  # 内置
    assert resp.status_code == 400


def test_delete_unknown_404(tmp_path, monkeypatch):
    _skill_api_env(tmp_path, monkeypatch)
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.delete("/api/skills/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/unit/test_skills_api.py -v`
Expected: 7 个新测试 FAIL(404,路由不存在)

- [ ] **Step 3: 实现**

`src/taisang/web/skills_api.py` 修改:

顶部 import 增补:

```python
import shutil

from fastapi import File, HTTPException, UploadFile

from ..skills.importer import (
    SkillExistsError,
    SkillImportError,
    import_skill_md,
    import_skill_zip,
)
```

模块级加 helper(放在 `load_skills_with_state` 后面):

```python
def _import_root() -> Path:
    """导入目标目录:user_dirs 第一个(默认 ~/.taisang/skills)。"""
    cfg = load_skills_config()
    root = cfg.user_dirs[0] if cfg.user_dirs else Path.home() / ".taisang" / "skills"
    return root


def _deletable_roots(source_root: Path) -> set[Path]:
    """允许删除的 skill 目录的父目录集合(user/project 源)。"""
    cfg = load_skills_config()
    roots = list(cfg.user_dirs) + list(cfg.project_dirs) + [source_root / ".taisang" / "skills"]
    return {r.resolve() for r in roots}
```

`register_skills_routes` 内、toggle 路由之后追加两个路由:

```python
    @app.post("/api/skills/import")
    async def import_skill(file: UploadFile = File(...), overwrite: bool = False) -> dict:
        """导入 skill:.md 单文件或 zip(目录形式)。

        同名已存在 → 409;前端确认后带 ?overwrite=true 重试覆盖。
        """
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(400, "文件超过 10MB 上限")
        filename = (file.filename or "").lower()
        root = _import_root()
        try:
            if filename.endswith((".md", ".markdown")):
                name, _target = import_skill_md(
                    data.decode("utf-8", errors="replace"), root, overwrite
                )
            elif filename.endswith(".zip"):
                name, _target = import_skill_zip(data, root, overwrite)
            else:
                raise HTTPException(400, "只支持 .md 或 .zip 文件")
        except SkillExistsError as e:
            raise HTTPException(409, str(e)) from e
        except SkillImportError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "name": name}

    @app.delete("/api/skills/{name}")
    async def delete_skill(name: str) -> dict:
        """删除 skill。内置(system)不可删;连带清掉 disabled 状态记录。"""
        skills = load_skills_with_state(source_root)
        skill = next((s for s in skills if s.name == name), None)
        if skill is None:
            raise HTTPException(404, "skill not found")
        if skill.source == "system":
            raise HTTPException(400, "内置 skill 不能删除")
        if skill.dir_path.parent.resolve() not in _deletable_roots(source_root):
            raise HTTPException(400, "skill 目录不在可管理范围内,拒绝删除")
        shutil.rmtree(skill.dir_path)
        state = _load_disabled_state()
        if name in state:
            del state[name]
            _save_disabled_state(state)
        return {"ok": True, "deleted": name}
```

注意:DELETE 路由必须注册在 toggle 的 `POST /api/skills/{name}/toggle` 之后没有冲突(方法+路径不同,FastAPI 自动区分);但 `GET /api/skills` 与 `DELETE /api/skills/{name}` 路径前缀共存没问题。

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest tests/unit/test_skills_api.py tests/unit/test_skill_importer.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/skills_api.py tests/unit/test_skills_api.py
git commit -m "feat(skill): import/delete API(409 覆盖语义、内置不可删、状态清理)"
```

---

### Task 4: 前端 SkillManage(导入按钮 + 删除 + 来源标签)

**Files:**
- Modify: `src/taisang/web/frontend/src/views/SkillManage.vue`

- [ ] **Step 1: 重写 SkillManage.vue**

完整替换为:

```vue
<template>
  <div class="skill-manage">
    <div class="page-header">
      <h2 class="page-title">Skill 管理</h2>
      <div class="header-actions">
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

    <t-table row-key="name" :data="skills" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag
          :theme="row.source === 'project' ? 'primary' : row.source === 'system' ? 'warning' : 'default'"
          size="small"
        >
          {{ row.source === 'project' ? '项目' : row.source === 'system' ? '内置' : '用户' }}
        </t-tag>
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
          v-if="row.source !== 'system'"
          variant="text"
          theme="danger"
          size="small"
          @click="confirmDelete(row.name)"
        >
          删除
        </t-button>
        <span v-else class="dim">-</span>
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无自定义 skill。点右上角"导入 Skill"上传 .md 或 .zip,
          或手动放置到 <code>~/.taisang/skills/&lt;name&gt;/SKILL.md</code>。
        </div>
      </template>
    </t-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'

interface SkillRow {
  name: string
  description: string
  when_to_use: string
  source: 'user' | 'project' | 'system'
  allowed_tools: string[] | null
  disabled: boolean
}

const skills = ref<SkillRow[]>([])
const loading = ref(false)
const fileInput = ref<HTMLInputElement>()

const columns = [
  { colKey: 'name', title: '名称', width: 140 },
  { colKey: 'description', title: '描述', ellipsis: true },
  { colKey: 'source', title: '来源', width: 80, cell: 'source' },
  { colKey: 'allowed_tools', title: '工具限制', width: 130, cell: 'allowed_tools' },
  { colKey: 'enabled', title: '启用', width: 70, cell: 'enabled' },
  { colKey: 'op', title: '操作', width: 70, cell: 'op' },
]

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
    await fetchSkills()
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

onMounted(fetchSkills)
</script>

<style scoped>
.skill-manage {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 960px;
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
  padding: 32px 16px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.empty-tip code {
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
```

- [ ] **Step 2: type-check + build**

```bash
cd src/taisang/web/frontend && npm run type-check && npm run build
```

Expected: 0 error,build 成功。

- [ ] **Step 3: 清理 stale hash chunk**

```bash
cd /d/GoProject/TaiSang && git status src/taisang/web/static
```

对照 `index.html` 引用的 js/css + 动态 import(SkillManage chunk 是懒加载,grep 新 build 产物里 `SkillManage` 确认新 chunk 名),把不再被引用的旧 chunk `git rm`。

- [ ] **Step 4: 重启后端 + 浏览器验证(Playwright DOM 断言,禁截图)**

```bash
# 重启 8765(带新代码),然后 Playwright:
```

验证清单:
1. `/skills` 表格渲染出内置 commit、review,来源标签"内置"(warning 色),操作列显示 `-`,无删除按钮
2. 造一个临时 skill md(如 `%TEMP%/test-import.md`,frontmatter name: test-import),`playwright_upload_file` 到 `input[type=file]`,断言表格出现 test-import 行(来源"用户")
3. 再次上传同名 → 出现"Skill 已存在"确认弹窗 → 点覆盖 → 仍为一行
4. 点 test-import 行"删除" → 确认弹窗 → 行消失;`GET /api/skills` 确认不在
5. 内置 commit 行无删除按钮(断言 op 单元格无 button)
6. `/chat/:id` 深链刷新不回归

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/frontend/src/views/SkillManage.vue src/taisang/web/static
git commit -m "feat(skill): SkillManage 导入按钮(MD/zip、覆盖确认)+ 删除 + 内置标签"
```

---

### Task 5: 全量回归 + e2e 补测

**Files:**
- Test: `tests/unit/test_skill_e2e.py`(或仅回归)

- [ ] **Step 1: 全量测试**

Run: `python -m pytest`
Expected: 全部 PASS(基线 223 + Task1~3 新增;若有旧断言因内置 skill 计数变化而挂,修断言)

- [ ] **Step 2: 端到端冒烟(可选,若 Task 4 Step 4 已全过则跳过)**

重启后端后走一遍:导入 → 新建会话确认 system prompt 清单含内置 skill → 删除。

- [ ] **Step 3: Commit(如有补改)**

```bash
git add -A && git commit -m "test(skill): 导入功能回归补测"
```

---

## Self-Review 记录

- 决策覆盖:1(zip→目录/MD 也建目录)→ Task 2;2(409+确认覆盖)→ Task 2/3/4;3(四项校验)→ Task 2;4(system 源 + 内置 2 skill)→ Task 1;5(delete + 状态清理 + 内置保护)→ Task 3/4;6(右上角按钮)→ Task 4 ✅
- 类型一致性:`import_skill_md/zip(text|bytes, skills_root, overwrite) -> (name, Path)`,Task 3 调用一致;`SkillExistsError` 是 `SkillImportError` 子类,路由 except 顺序先 Exists 后 Import ✅
- 已知取舍:overwrite 在校验全过后 rmtree,解压中途失败(磁盘满/CRC)会丢旧版本——概率低,接受;要做原子替换(临时目录+rename)留 v2
- MockLLM/e2e 不受影响:skill 注入链路零改动,仅来源多一类
