# 本地 Repo 支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `taisang` 从"只支持远程 git clone"改造成"只支持本地 repo",索引产物落 `<repo>/.taisang/`。

**Architecture:** `Fetcher` 退化成只有 `current_commit(path)` 静态方法的薄壳(砍 git clone);`PathManager` 砍 `cache_dir`/`indices_dir`/`_repo_hash` 等远程相关方法,新增 `index_dir(source_root)` 等 classmethod 落 `<repo>/.taisang/`;`IndexerService.build/update` 参数从 `repo_url: str` 改成 `source_root: Path`;`RepoIndex.repo_url` 字段改名 `source_root`;CLI 加 `_normalize_path` helper + 路径校验。破坏性改动,不写迁移。

**Tech Stack:** Python 3.11+ / pydantic 2 / click / sqlite3 / subprocess(git)

**Spec:** `docs/superpowers/specs/2026-08-21-local-repo-support-design.md`

---

## File Structure

**修改的源文件**:
- `src/taisang/types.py` — `RepoIndex.repo_url` 改名 `source_root`
- `src/taisang/indexer/fetcher.py` — 砍 `fetch` + `_url_hash`,`_current_commit` 改 `current_commit` 静态方法 + OSError 兜底
- `src/taisang/storage/paths.py` — 砍 `cache_dir`/`indices_dir`/`_repo_hash`/`index_db_path(repo_url)`/`repo_map_path(repo_url)`/`chroma_path(repo_url)`/`index_errors_path(repo_url)`,新增 `index_dir(source_root)` 等 classmethod
- `src/taisang/indexer/service.py` — `build(repo_url)` → `build(source_root)`,`update(repo_url)` → `update(source_root)`,扫源码排除 `.taisang/`
- `src/taisang/cli/main.py` — 加 `_normalize_path`,`cmd_index`/`cmd_ask` 改路径参数 + 路径校验 + `.gitignore` 提示

**修改的测试文件**:
- `tests/unit/test_fetcher.py` — 重写 3 个测试(clone 改 current_commit)
- `tests/unit/test_paths.py` — 重写 4 个测试(cache/indices 改 index_dir)
- `tests/unit/test_types.py` — 改 `repo_url` → `source_root` 断言
- `tests/unit/test_cli.py` — 改参数 + 新增 2 个路径校验测试 + 改断言
- `tests/integration/test_indexer_service.py` — 改 `idx.repo_url` → `idx.source_root` + 新增排除 `.taisang/` 测试
- `tests/integration/test_end_to_end.py` — 改 `service.build(str(repo))` → `service.build(repo)`,断言路径落 `<repo>/.taisang/`

---

## Task 1: 改 `RepoIndex.repo_url` → `source_root`

**Files:**
- Modify: `src/taisang/types.py:37-44`
- Test: `tests/unit/test_types.py`

- [ ] **Step 1: 看 `test_types.py` 现有断言**

Run: `python -m pytest tests/unit/test_types.py -v`
Expected: PASS(当前全绿)

- [ ] **Step 2: 改 `types.py` 的 `RepoIndex` 字段名**

把 `src/taisang/types.py:40` 的 `repo_url: str` 改成 `source_root: str`:

```python
class RepoIndex(BaseModel):
    """一次索引的产物:AST 解析 + 跨文件调用图。"""

    source_root: str
    commit_hash: str
    symbols: list[Symbol]
    files: list[str]
    index_errors: list[dict[str, str]] = Field(default_factory=list)
```

- [ ] **Step 3: 检查 `test_types.py` 是否硬编码 `repo_url`**

Run: `grep -n "repo_url" tests/unit/test_types.py`
Expected: 如果有匹配,改成 `source_root`;如果无匹配,跳到 Step 4

- [ ] **Step 4: 跑全量测试看哪些挂**

Run: `python -m pytest -q 2>&1 | tail -20`
Expected: FAIL(预期 `IndexerService` / `CLI` / 集成测试硬编码 `repo_url` 处都挂),记录失败的测试列表供后续 task 用

- [ ] **Step 5: 不提交,继续 Task 2**

本轮破坏性改动跨多个文件,单 task 不绿不提交,等 Task 6 全绿后一起提交。

---

## Task 2: 重写 `PathManager` 落 `<repo>/.taisang/`

**Files:**
- Modify: `src/taisang/storage/paths.py` (整体重写)
- Test: `tests/unit/test_paths.py` (整体重写)

- [ ] **Step 1: 重写 `test_paths.py`(先写新测试)**

整个文件替换为:

```python
"""测试路径管理。

本地 repo 索引产物落 <source_root>/.taisang/。
~/.taisang/ 只剩 settings.json。
"""

from pathlib import Path

from taisang.storage.paths import PathManager


def _isolate_home(tmp_path, monkeypatch):
    """跨平台隔离 HOME / USERPROFILE 到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def test_root_default(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.root == tmp_path / ".taisang"


def test_settings_path(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    pm = PathManager()
    assert pm.settings_path == pm.root / "settings.json"


def test_index_dir_creates_taisang_subdir(tmp_path):
    """index_dir 返回 <source_root>/.taisang/ 并自动创建。"""
    d = PathManager.index_dir(tmp_path)
    assert d == tmp_path / ".taisang"
    assert d.exists() and d.is_dir()


def test_index_db_path_under_taisang(tmp_path):
    p = PathManager.index_db_path(tmp_path)
    assert p == tmp_path / ".taisang" / "ast.db"


def test_repo_map_path_under_taisang(tmp_path):
    p = PathManager.repo_map_path(tmp_path)
    assert p == tmp_path / ".taisang" / "repo_map.json"


def test_chroma_and_errors_paths(tmp_path):
    assert PathManager.chroma_path(tmp_path) == tmp_path / ".taisang" / "chroma"
    assert PathManager.index_errors_path(tmp_path) == tmp_path / ".taisang" / "index_errors.json"
```

- [ ] **Step 2: 跑新测试看它失败**

Run: `python -m pytest tests/unit/test_paths.py -v 2>&1 | tail -20`
Expected: FAIL(`PathManager` 还有 `cache_dir`/`indices_dir`,新测试调的 `index_dir`/`index_db_path(source_root)` 等方法不存在)

- [ ] **Step 3: 重写 `paths.py`**

整个文件替换为:

```python
"""路径管理。本地 repo 索引产物落 <repo>/.taisang/。

~/.taisang/ 只保留 settings.json(LLM 配置)。
本地 repo 的索引产物(ast.db / repo_map.json 等)落到 <source_root>/.taisang/。
"""

from __future__ import annotations

from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    本地 repo 索引产物落 <source_root>/.taisang/。
    ~/.taisang/ 只保留 settings.json。
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path.home() / ".taisang"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def settings_path(self) -> Path:
        """LLM 配置文件路径。"""
        return self.root / "settings.json"

    @staticmethod
    def index_dir(source_root: Path) -> Path:
        """单个 repo 的索引产物目录:<source_root>/.taisang/"""
        d = source_root / ".taisang"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def index_db_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "ast.db"

    @classmethod
    def repo_map_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "repo_map.json"

    @classmethod
    def chroma_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "chroma"

    @classmethod
    def index_errors_path(cls, source_root: Path) -> Path:
        return cls.index_dir(source_root) / "index_errors.json"
```

- [ ] **Step 4: 跑新测试看它通过**

Run: `python -m pytest tests/unit/test_paths.py -v 2>&1 | tail -20`
Expected: PASS(7 个测试全绿)

- [ ] **Step 5: 不提交,继续 Task 3**

`IndexerService` 还没改,全量测试还会挂。等 Task 6 一起提交。

---

## Task 3: 重写 `Fetcher` 砍 git clone

**Files:**
- Modify: `src/taisang/indexer/fetcher.py` (整体重写)
- Test: `tests/unit/test_fetcher.py` (整体重写)

- [ ] **Step 1: 重写 `test_fetcher.py`**

整个文件替换为:

```python
"""测试 Fetcher(本地 repo 探针,取 commit hash)。"""

import os
import subprocess
from pathlib import Path

from taisang.indexer.fetcher import Fetcher


def _make_local_git_repo(tmp_path: Path) -> Path:
    """在 tmp_path 下造一个本地 git repo,含 1 个 .py 文件。"""
    repo = tmp_path / "local-repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    return repo


def test_current_commit_returns_hash_for_git_repo(tmp_path):
    """有 .git 的本地 repo,返回 40 位 commit hash。"""
    repo = _make_local_git_repo(tmp_path)
    commit = Fetcher.current_commit(repo)
    assert len(commit) == 40  # sha1 hex


def test_current_commit_returns_unknown_for_non_git_dir(tmp_path):
    """无 .git 的目录,返回 'unknown'。"""
    repo = tmp_path / "no-git"
    repo.mkdir()
    (repo / "a.py").write_text("x", encoding="utf-8")
    assert Fetcher.current_commit(repo) == "unknown"


def test_current_commit_returns_unknown_when_git_not_installed(tmp_path):
    """git 未装 / subprocess 抛 FileNotFoundError,返回 'unknown' 不崩。"""
    repo = tmp_path / "fake"
    repo.mkdir()
    (repo / "a.py").write_text("x", encoding="utf-8")

    original_run = subprocess.run

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    # monkeypatch subprocess.run 在 fetcher 模块里的引用
    import taisang.indexer.fetcher as fetcher_mod

    saved = fetcher_mod.subprocess.run
    fetcher_mod.subprocess.run = fake_run
    try:
        assert Fetcher.current_commit(repo) == "unknown"
    finally:
        fetcher_mod.subprocess.run = saved
```

- [ ] **Step 2: 跑新测试看它失败**

Run: `python -m pytest tests/unit/test_fetcher.py -v 2>&1 | tail -20`
Expected: FAIL(`Fetcher.fetch` 还在,`Fetcher()` 还需要 `cache_dir` 参数,新测试调的 `Fetcher.current_commit` 静态方法不存在)

- [ ] **Step 3: 重写 `fetcher.py`**

整个文件替换为:

```python
"""本地 repo 探针:取 commit hash。

v1 不做远程 git clone。用户先 `git clone` 到本地,再 `taisang index <path>`。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class Fetcher:
    """本地 repo 探针。v1 不做远程 clone,只取 commit hash。"""

    def __init__(self) -> None:
        pass  # 不再需要 cache_dir

    @staticmethod
    def current_commit(path: Path) -> str:
        """取本地 repo 的 HEAD commit hash。

        无 .git / git 未装 / git 命令失败,统一返回 'unknown',不抛异常。
        """
        try:
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=path,
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
            log.warning("git rev-parse failed for %s: %s", path, e)
            return "unknown"
        if r.returncode != 0:
            return "unknown"
        return r.stdout.decode().strip()
```

- [ ] **Step 4: 跑新测试看它通过**

Run: `python -m pytest tests/unit/test_fetcher.py -v 2>&1 | tail -20`
Expected: PASS(3 个测试全绿)

- [ ] **Step 5: 不提交,继续 Task 4**

`IndexerService` 还调 `fetcher.fetch`,全量测试还挂。

---

## Task 4: 改 `IndexerService.build/update` 接 `source_root`

**Files:**
- Modify: `src/taisang/indexer/service.py:21-140`

- [ ] **Step 1: 改 `IndexerService.__init__`**

把 `src/taisang/indexer/service.py:24-26` 的:

```python
def __init__(self, pm: PathManager) -> None:
    self.pm = pm
    self.fetcher = Fetcher(pm.cache_dir)
```

改成:

```python
def __init__(self, pm: PathManager) -> None:
    self.pm = pm
    self.fetcher = Fetcher()
```

- [ ] **Step 2: 改 `build` 方法签名和实现**

把 `src/taisang/indexer/service.py:28-73` 的整个 `build` 方法替换为:

```python
def build(self, source_root: Path) -> RepoIndex:
    """全量索引:扫 source_root 下所有 .py → parse → linker → 入库。

    索引产物落 <source_root>/.taisang/ast.db。
    """
    commit = self.fetcher.current_commit(source_root)
    storage = IndexStorage(self.pm.index_db_path(source_root))

    py_files = sorted(source_root.rglob("*.py"))
    # 排除 .git 和 .taisang 目录(防止把索引产物当源码解析)
    py_files = [
        f for f in py_files
        if ".git" not in f.parts and ".taisang" not in f.parts
    ]

    symbols: list[Symbol] = []
    errors: list[dict] = []
    fingerprints: dict[str, str] = {}
    for f in py_files:
        rel = str(f.relative_to(source_root)).replace("\\", "/")
        try:
            fp = file_hash(f)
            fingerprints[rel] = fp
            file_syms = parse_file(f, rel)
            if not file_syms and f.stat().st_size > 0:
                logger.warning("no symbols extracted from %s (possible syntax error)", rel)
                errors.append(
                    {
                        "file": rel,
                        "stage": "parse",
                        "error": "no symbols extracted (possible syntax error)",
                    }
                )
            else:
                symbols.extend(file_syms)
        except Exception as e:
            logger.warning("parse failed for %s: %s", rel, e)
            errors.append({"file": rel, "stage": "parse", "error": str(e)})

    storage.save_symbols(str(source_root), symbols, commit_hash=commit)
    storage.save_fingerprints(str(source_root), fingerprints)
    storage.save_index_errors(str(source_root), errors)

    return RepoIndex(
        source_root=str(source_root),
        commit_hash=commit,
        symbols=symbols,
        files=list(fingerprints.keys()),
        index_errors=errors,
    )
```

**注意**:`storage.save_*` 第一个参数原来是 `repo_hash`(url 的 sha1),现在改成 `str(source_root)` 作为 repo_hash 传给 SQLite。这样不同 repo 路径自然隔离(原来不同 url 也隔离,语义一致)。

- [ ] **Step 3: 改 `update` 方法签名和实现**

把 `src/taisang/indexer/service.py:75-136` 的整个 `update` 方法替换为:

```python
def update(self, source_root: Path) -> RepoIndex:
    """增量索引:基于已有 fingerprints,只重解析变动文件。

    v1 简化:如果第一次没 build 过,自动走 build()。
    """
    db = self.pm.index_db_path(source_root)
    if not db.exists():
        return self.build(source_root)
    commit = self.fetcher.current_commit(source_root)
    storage = IndexStorage(db)
    old_fps = storage.load_fingerprints(str(source_root))

    py_files = sorted(source_root.rglob("*.py"))
    py_files = [
        f for f in py_files
        if ".git" not in f.parts and ".taisang" not in f.parts
    ]
    new_fps: dict[str, str] = {}
    for f in py_files:
        rel = str(f.relative_to(source_root)).replace("\\", "/")
        new_fps[rel] = file_hash(f)

    added, modified, deleted, unchanged = diff_files(old_fps, new_fps)

    old_symbols = storage.load_symbols(str(source_root))
    to_drop = deleted | modified
    kept = [s for s in old_symbols if s.file not in to_drop]
    new_symbols: list[Symbol] = []
    errors: list[dict] = []
    for f in py_files:
        rel = str(f.relative_to(source_root)).replace("\\", "/")
        if rel in added or rel in modified:
            try:
                file_syms = parse_file(f, rel)
                if not file_syms and f.stat().st_size > 0:
                    logger.warning("no symbols extracted from %s (possible syntax error)", rel)
                    errors.append(
                        {
                            "file": rel,
                            "stage": "parse",
                            "error": "no symbols extracted (possible syntax error)",
                        }
                    )
                else:
                    new_symbols.extend(file_syms)
            except Exception as e:
                logger.warning("parse failed for %s: %s", rel, e)
                errors.append({"file": rel, "stage": "parse", "error": str(e)})
    all_symbols = kept + new_symbols
    storage.save_symbols(str(source_root), all_symbols, commit_hash=commit)
    storage.save_fingerprints(str(source_root), new_fps)
    old_errors = storage.load_index_errors(str(source_root))
    storage.save_index_errors(str(source_root), old_errors + errors)
    return RepoIndex(
        source_root=str(source_root),
        commit_hash=commit,
        symbols=all_symbols,
        files=list(new_fps.keys()),
        index_errors=old_errors + errors,
    )
```

- [ ] **Step 4: 不跑单独测试,继续 Task 5**

`IndexerService` 改完,但 `test_indexer_service.py` 还用 `service.build(str(remote))` 传字符串,会挂。等 Task 5 改完测试再一起跑。

---

## Task 5: 改 `test_indexer_service.py` + 新增排除 `.taisang/` 测试

**Files:**
- Modify: `tests/integration/test_indexer_service.py`

- [ ] **Step 1: 改 4 个现有测试的 `idx.repo_url` → `idx.source_root`**

Run: `grep -n "repo_url\|build(str\|update(str" tests/integration/test_indexer_service.py`
Expected: 看到 4 处 `service.build(str(remote))` 和 1 处 `idx.repo_url`

把所有 `service.build(str(remote))` 改成 `service.build(remote)`(`remote` 已经是 `Path`)。
把所有 `service.build(str(repo))` 改成 `service.build(repo)`。
把 `idx.repo_url == str(remote)` 改成 `idx.source_root == str(remote)`。

具体改动(按行号):

`test_index_builds_repoindex`(原 45-56 行):
```python
def test_index_builds_repoindex(tmp_path, monkeypatch):
    _isolate_home(tmp_path, monkeypatch)
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(remote)
    assert idx.source_root == str(remote)
    assert len(idx.commit_hash) > 0
    names = {s.name for s in idx.symbols}
    assert {"foo", "bar", "baz"}.issubset(names)
    assert "a.py" in idx.files and "b.py" in idx.files
```

`test_index_builds_call_graph`(原 59-69 行):把 `service.build(str(remote))` 改 `service.build(remote)`,其余不变。

`test_index_persists_to_storage`(原 72-80 行):把两处 `service.build(str(remote))` 改 `service.build(remote)`,其余不变。

`test_index_records_errors_for_bad_files`(原 83-111 行):把 `service.build(str(repo))` 改 `service.build(repo)`,其余不变。

- [ ] **Step 2: 新增"排除 `.taisang/`"测试**

在文件末尾追加:

```python
def test_index_excludes_taisang_dir(tmp_path, monkeypatch):
    """索引时应排除 .taisang/ 目录,不解析里面的文件。"""
    _isolate_home(tmp_path, monkeypatch)
    repo = tmp_path / "with-cr"
    repo.mkdir()
    (repo / "real.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    # 模拟索引产物已存在:在 .taisang/ 里放个 .py 文件
    cr_dir = repo / ".taisang"
    cr_dir.mkdir()
    (cr_dir / "fake.py").write_text("def fake():\n    pass\n", encoding="utf-8")

    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(repo)
    # real.py 应被解析
    assert "real.py" in idx.files
    # .taisang/fake.py 不应被解析
    assert ".taisang/fake.py" not in idx.files
    assert all(not f.startswith(".taisang/") for f in idx.files)
```

- [ ] **Step 3: 跑 indexer service 测试**

Run: `python -m pytest tests/integration/test_indexer_service.py -v 2>&1 | tail -20`
Expected: PASS(5 个测试全绿:4 个改参数 + 1 个新增排除 .taisang)

- [ ] **Step 4: 跑全量测试看剩余挂的**

Run: `python -m pytest -q 2>&1 | tail -15`
Expected: `test_cli.py` 和 `test_end_to_end.py` 还挂(CLI 还没改),`test_paths.py` / `test_fetcher.py` / `test_types.py` 已绿。记录剩余失败。

- [ ] **Step 5: 不提交,继续 Task 6**

---

## Task 6: 改 CLI 接本地路径 + 路径校验

**Files:**
- Modify: `src/taisang/cli/main.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_end_to_end.py`

- [ ] **Step 1: 重写 `src/taisang/cli/main.py`**

整个文件替换为:

```python
"""Code Reader Agent CLI 入口。

命令:
- taisang index <repo_path>  建索引(本地路径)
- taisang ask "<question>" --repo <path>  问问题
- taisang --help  帮助

环境变量:
- CODE_READER_MOCK_LLM=1  使用 MockLLM(测试用,返回固定回答)
- CODE_READER_LLM_*  LLM 配置
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from ..agent_core.service import AgentService
from ..config import load_config
from ..indexer.service import IndexerService
from ..llm_client import LLMClient, LLMResponse, MockLLM
from ..storage.paths import PathManager
from ..summarizer.service import SummarizerService
from ..types import RepoMap


def _normalize_path(path: str) -> Path:
    """规范化路径:展开 ~ + resolve。"""
    return Path(os.path.expanduser(path)).resolve()


def _make_llm():
    """根据环境决定用真 LLM 还是 MockLLM。"""
    if os.environ.get("CODE_READER_MOCK_LLM") == "1":
        return MockLLM(
            [
                LLMResponse(text="(mock) 这个 repo 定义了 main 函数 [a.py:1]", tool_calls=[]),
            ]
            * 10
        )
    cfg = load_config()
    if not cfg.api_key:
        click.echo(
            "错误:未配置 LLM API key。请设置 CODE_READER_LLM_API_KEY 环境变量,"
            "或写 ~/.taisang/settings.json。测试可用 CODE_READER_MOCK_LLM=1。",
            err=True,
        )
        sys.exit(2)
    return LLMClient(cfg)


@click.group()
def cli() -> None:
    """Code Reader Agent - 3 分钟让陌生代码库变成可问答。"""


@cli.command("index")
@click.argument("repo_path")
def cmd_index(repo_path: str) -> None:
    """建索引:扫本地 repo → 解析 AST → 三层摘要 → 入库。

    索引产物落到 <repo_path>/.taisang/。
    """
    source_root = _normalize_path(repo_path)
    if not source_root.is_dir():
        click.echo(
            f"错误:路径不存在或不是目录: {source_root}。"
            f"v1 不再支持远程 git clone,请先 `git clone` 到本地再 index。",
            err=True,
        )
        sys.exit(1)

    pm = PathManager()
    click.echo(f"开始索引: {source_root}")
    indexer = IndexerService(pm)
    idx = indexer.build(source_root)
    click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")
    if idx.index_errors:
        click.echo(f"  失败文件 {len(idx.index_errors)} 个(已跳过)")

    llm = _make_llm()
    summarizer = SummarizerService(llm=llm)
    click.echo("生成三层摘要...")
    repo_map = summarizer.summarize(idx, source_root=source_root)
    pm.repo_map_path(source_root).write_text(repo_map.model_dump_json(indent=2), encoding="utf-8")
    n_files = len(repo_map.file_summaries)
    n_modules = len(repo_map.module_summaries)
    click.echo(f"摘要完成: {n_files} 文件, {n_modules} 模块")
    if summarizer.errors:
        click.echo(f"  摘要失败 {len(summarizer.errors)} 个(已跳过)")
    click.echo("✓ 索引完成")
    click.echo(f"提示:索引产物已落到 {source_root}/.taisang/。建议把 .taisang/ 加到 .gitignore")


@cli.command("ask")
@click.argument("question")
@click.option("--repo", required=True, help="本地 repo 路径(必须先 index 过)")
def cmd_ask(question: str, repo: str) -> None:
    """问问题,Agent 跨文件追踪调用链回答。"""
    source_root = _normalize_path(repo)
    if not source_root.is_dir():
        click.echo(
            f"错误:路径不存在或不是目录: {source_root}",
            err=True,
        )
        sys.exit(1)

    pm = PathManager()
    repo_map_path = pm.repo_map_path(source_root)
    if not repo_map_path.exists():
        click.echo(f"错误:repo 未索引过,请先 `taisang index {source_root}`", err=True)
        sys.exit(1)

    repo_map = RepoMap.model_validate_json(repo_map_path.read_text(encoding="utf-8"))

    indexer = IndexerService(pm)
    idx = indexer.update(source_root)
    call_graph = indexer.build_call_graph(idx)

    llm = _make_llm()
    agent = AgentService(
        llm=llm,
        source_root=source_root,
        call_graph=call_graph,
        repo_map=repo_map,
    )
    answer = agent.run(question)
    click.echo(answer.text)
    if answer.citations:
        click.echo("\n引用:")
        for c in answer.citations:
            click.echo(f"  - {c.file}:{c.line_range[0]}-{c.line_range[1]}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: 改 `test_cli.py`**

整个文件替换为:

```python
"""测试 CLI 入口:用 click 的 CliRunner 跑子命令。"""

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from taisang.cli.main import cli


def _isolate_home(tmp_path, monkeypatch):
    """Windows: Path.home() 读 USERPROFILE;Linux/Mac 读 HOME。同时 patch。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def main():\n    print('hello')\n\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    git_env["PATH"] = os.environ.get("PATH", "")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=git_env,
    )
    return repo


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "index" in result.output
    assert "ask" in result.output


def test_cli_index_command(tmp_path, monkeypatch):
    """index 命令应建索引并落盘到 <repo>/.taisang/。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["index", str(repo)])
    assert result.exit_code == 0, result.output
    # 索引产物应落到 <repo>/.taisang/
    assert (repo / ".taisang").exists()
    assert (repo / ".taisang" / "ast.db").exists()
    assert (repo / ".taisang" / "repo_map.json").exists()


def test_cli_ask_command_with_mock_llm(tmp_path, monkeypatch):
    """ask 命令用 MockLLM 应能跑通,返回字符串。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(repo)])
    result = runner.invoke(cli, ["ask", "main 函数干啥的", "--repo", str(repo)])
    assert result.exit_code == 0, result.output
    assert "main" in result.output or "mock" in result.output.lower()


def test_cli_index_rejects_nonexistent_path(tmp_path, monkeypatch):
    """路径不存在,index exit 1 + 错误提示。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    runner = CliRunner()
    result = runner.invoke(cli, ["index", str(tmp_path / "nonexistent")])
    assert result.exit_code == 1
    assert "路径不存在" in result.output or "not a directory" in result.output


def test_cli_ask_without_index_exits_1(tmp_path, monkeypatch):
    """未索引过的路径,ask exit 1 + 提示先 index。"""
    _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["ask", "q", "--repo", str(repo)])
    assert result.exit_code == 1
    assert "未索引过" in result.output
```

- [ ] **Step 3: 改 `test_end_to_end.py`**

把 `test_end_to_end.py` 里所有 `service.build(str(repo))` / `service.update(str(repo))` 改成 `service.build(repo)` / `service.update(repo)`。

具体:
- `test_end_to_end_call_graph_built` 第 88 行:`idx = service.update(str(repo))` → `idx = service.update(repo)`
- `test_end_to_end_trace_call_chain_three_hops` 第 111 行:`idx = service.update(str(repo))` → `idx = service.update(repo)`

`test_end_to_end_index_then_ask` 不用改(它走 CLI,CliRunner 传 `str(repo)` 给 `index`/`ask` 命令,CLI 内部 `_normalize_path` 处理)。

- [ ] **Step 4: 跑 CLI 测试**

Run: `python -m pytest tests/unit/test_cli.py -v 2>&1 | tail -20`
Expected: PASS(5 个测试全绿:3 个原 + 2 个新)

- [ ] **Step 5: 跑 E2E 测试**

Run: `python -m pytest tests/integration/test_end_to_end.py -v 2>&1 | tail -20`
Expected: PASS(3 个测试全绿)

- [ ] **Step 6: 跑全量回归**

Run: `python -m pytest -q 2>&1 | tail -15`
Expected: PASS(预期 105 个测试全绿)

- [ ] **Step 7: lint + black**

Run: `ruff check src tests && black --check src tests 2>&1 | tail -5`
Expected: All checks passed / All done

如果 ruff/black 报错,用 `ruff check --fix <file>` 和 `black <file>` 自动修复,再跑一次确认。

- [ ] **Step 8: 提交**

```bash
git add src/taisang/types.py src/taisang/indexer/fetcher.py src/taisang/storage/paths.py src/taisang/indexer/service.py src/taisang/cli/main.py tests/unit/test_fetcher.py tests/unit/test_paths.py tests/unit/test_types.py tests/unit/test_cli.py tests/integration/test_indexer_service.py tests/integration/test_end_to_end.py
git commit -m "$(cat <<'EOF'
refactor: drop remote clone, support local repo only + land index under <repo>/.taisang/

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 更新 lessons-learned + README

**Files:**
- Modify: `memory/lessons-learned.md`
- Modify: `README.md`

- [ ] **Step 1: 在 `memory/lessons-learned.md` 末尾追加新章节**

```markdown
### Task 2/3/9 遗留 — ✅ 已修(2026-08-21,本地 repo 改造)

1. **Fetcher `git clone` 过度设计** ✅ 已修
   - 解法:砍 `fetch` + `_url_hash`,退化成 `current_commit(path)` 静态方法薄壳。用户先 `git clone` 到本地再 `taisang index <path>`
2. **PathManager 集中落盘不可读** ✅ 已修
   - 解法:砍 `cache_dir`/`indices_dir`/`_repo_hash`,新增 `index_dir(source_root)` 等 classmethod,落 `<repo>/.taisang/`。删 repo 时索引自动清,team 共享连 repo 一起 copy
3. **`Fetcher._current_commit` 未捕获 OSError** ✅ 已修
   - 解法:`current_commit` 加 `try/except (TimeoutExpired, OSError, FileNotFoundError)`,Windows git 未装时返回 "unknown" 不崩
4. **IndexerService 扫源码未排除 `.taisang/`** ✅ 已修
   - 解法:`py_files` 过滤条件加 `".taisang" not in f.parts`,防止索引产物被当源码解析
5. **`RepoIndex.repo_url` 字段名误导** ✅ 已修
   - 解法:改名 `source_root: str`,语义清晰
```

- [ ] **Step 2: 改 `README.md` 的 Quick Start**

把 `README.md` 的 Quick Start 部分(9-23 行)替换为:

```markdown
## Quick Start

```bash
# 安装(开发模式)
pip install -e ".[dev]"

# 配置 LLM(支持任意 OpenAI 兼容 endpoint)
export CODE_READER_LLM_BASE_URL=https://api.deepseek.com
export CODE_READER_LLM_API_KEY=sk-xxx
export CODE_READER_LLM_MODEL=deepseek-chat

# 先 clone 到本地(v1 不支持远程 clone)
git clone https://github.com/tiangolo/fastapi ~/repos/fastapi

# 建索引(产物落 ~/repos/fastapi/.taisang/)
taisang index ~/repos/fastapi

# 问问题
taisang ask "FastAPI 的路由是怎么注册的" --repo ~/repos/fastapi
```
```

- [ ] **Step 3: 提交**

```bash
git add memory/lessons-learned.md README.md
git commit -m "$(cat <<'EOF'
docs: update README Quick Start + lessons-learned for local repo refactor

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## 验证清单(全部 task 完成后)

```bash
cd D:/GoProject/Repo-Onboarding-Agent

# 1. 全量测试(预期 105 passed)
python -m pytest -q

# 2. lint + black
ruff check src tests
black --check src tests

# 3. E2E
python -m pytest tests/integration -v

# 4. 真实闭环(可选,需要 LLM key)
# 先 clone 一个小 repo 到本地
git clone https://github.com/pallets/click ~/repos/click
taisang index ~/repos/click
taisang ask "CliRunner 是干啥的" --repo ~/repos/click
# 检查索引产物
ls ~/repos/click/.taisang/
```