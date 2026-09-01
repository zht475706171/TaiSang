# 本地 Repo 支持 — 设计文档

> 日期:2026-08-21
> 状态:已用户审阅通过,待写实施 plan
> 范围:Plan 1 完成后的增量改造,独立小 spec

## 一、背景与动机

Plan 1 完成后,`taisang` 只支持 `taisang index <repo_url>` 走 `git clone` 远程仓库。问题:

1. **用户场景错位**:真实用户想看一个项目,通常是先 `git clone` 到本地再看。强制 `taisang` 自己 clone 反人类——用户磁盘里会莫名其妙多一堆 `~/.taisang/cache/<hash>/` 目录。
2. **落盘位置不合理**:索引产物集中落 `~/.taisang/indices/<hash>/`,hash 不可读,用户想看"我索引过哪些 repo""某 repo 的摘要是啥"只能人肉翻文件 / 翻 SQLite。
3. **`Fetcher` 过度设计**:`git clone` + retry + stale target 清理 + cache_dir hash 分子目录——这套逻辑用户根本不需要。

## 二、目标

**核心改动**:`taisang` 改成只支持本地 repo,索引产物落 `<repo>/.taisang/`。

**不做的事**(明确排除):
- 不做"查看命令"(`list` / `show` / `dump`),留下一轮
- 不做 session/trace 落盘(Plan 4 的事)
- 不做向后兼容迁移(用户量 = 0,早期阶段)
- 不做远程 clone 保留(整个砍掉)

## 三、架构改动

### 3.1 改动前后对比

```
改动前:
  CLI index <url> → IndexerService.build(url)
    → Fetcher.fetch(url) → git clone 到 ~/.taisang/cache/<hash>/
    → parser → linker → Storage(~/.taisang/indices/<hash>/ast.db)
    → Summarizer → ~/.taisang/indices/<hash>/repo_map.json

改动后:
  CLI index <path> → IndexerService.build(path)
    → Fetcher.current_commit(path) → 直接用 path,不 clone
    → parser → linker → Storage(<path>/.taisang/ast.db)
    → Summarizer → <path>/.taisang/repo_map.json
```

### 3.2 `~/.taisang/` 改动后只剩 `settings.json`(LLM 配置),`cache/` 和 `indices/` 目录不再创建。

### 3.3 三个组件职责变化

| 组件 | 改动前 | 改动后 |
|------|--------|--------|
| `Fetcher` | git clone + 取 commit | 只取 commit(本地 repo 探针),`fetch` 方法删 |
| `PathManager` | 管理 `~/.taisang/cache` + `indices/<hash>` | 管理 `<repo>/.taisang/`,删 cache/indices 相关 |
| `IndexerService` | 调 `fetcher.fetch` 拿 local_path | 接收 `source_root` 直接用,commit 从 `Fetcher.current_commit` 取 |

## 四、组件改动细节

### 4.1 `Fetcher`(`src/taisang/indexer/fetcher.py`)

**砍掉**:`fetch` 方法 + `_url_hash` 方法 + 整个 git clone 逻辑
**保留**:`_current_commit` 改名 `current_commit`(公开,改静态方法),接收任意本地 path
**新增**:OSError 兜底(`FileNotFoundError` 在 Windows git 未装时会抛)

```python
"""本地 repo 探针:取 commit hash。"""
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
        """取本地 repo 的 HEAD commit hash。无 .git 返回 'unknown'。"""
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

### 4.2 `PathManager`(`src/taisang/storage/paths.py`)

**砍掉**:`cache_dir` property、`_repo_hash` 方法、`indices_dir(repo_url)`、`index_db_path(repo_url)`、`repo_map_path(repo_url)`、`chroma_path(repo_url)`、`index_errors_path(repo_url)`

**保留+改造**:`__init__` 不再创建 `cache` 和 `indices` 子目录(只读 `settings.json` 用)

**新增**:基于 `source_root`(本地 repo 根路径)的路径方法,全部 `classmethod`

```python
"""路径管理。本地 repo 索引产物落 <repo>/.taisang/。"""
from __future__ import annotations

from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    本地 repo 索引产物落 <source_root>/.taisang/。
    ~/.taisang/ 只保留 settings.json(LLM 配置)。
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path.home() / ".taisang"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def settings_path(self) -> Path:
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

### 4.3 `IndexerService`(`src/taisang/indexer/service.py`)

**`__init__`**:`self.fetcher = Fetcher()`(不再传 cache_dir)

**`build(source_root: Path)` 替代 `build(repo_url: str)`**:
- 参数从 `repo_url: str` 改成 `source_root: Path`
- 不再调 `self.fetcher.fetch(repo_url)`,直接用 `source_root`
- `commit = self.fetcher.current_commit(source_root)`
- `repo_hash` 砍掉(不再用 hash 作索引键)
- `storage = IndexStorage(self.pm.index_db_path(source_root))`
- `RepoIndex` 构造改 `source_root=str(source_root)`

**`update(source_root: Path)` 替代 `update(repo_url: str)`**:同上,`db = self.pm.index_db_path(source_root)`

**扫源码新增排除 `.taisang/`**(防止把索引产物当源码解析):
```python
py_files = [
    f for f in py_files
    if ".git" not in f.parts and ".taisang" not in f.parts
]
```

**`build_call_graph(idx)`**:不变(只依赖 `idx.symbols`)

### 4.4 `RepoIndex`(`src/taisang/types.py`)

```python
class RepoIndex(BaseModel):
    source_root: str          # 改名,原 repo_url: str
    commit_hash: str
    symbols: list[Symbol]
    files: list[str]
    index_errors: list[dict]
```

### 4.5 CLI(`src/taisang/cli/main.py`)

**新增 `_normalize_path` helper**:
```python
import os

def _normalize_path(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()
```

**`cmd_index(repo_path: str)`**(原 `cmd_index(repo_url: str)`):
```python
source_root = _normalize_path(repo_path)
if not source_root.is_dir():
    click.echo(f"错误:路径不存在或不是目录: {source_root}", err=True)
    sys.exit(1)

click.echo(f"开始索引: {source_root}")
indexer = IndexerService(pm)
idx = indexer.build(source_root)
click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")
# ... 跑摘要
summarizer = SummarizerService(llm=llm)
repo_map = summarizer.summarize(idx, source_root=source_root)
pm.repo_map_path(source_root).write_text(repo_map.model_dump_json(indent=2), encoding="utf-8")
# 提示用户加 .gitignore
click.echo(f"提示:索引产物已落到 {source_root}/.taisang/。建议把 .taisang/ 加到 .gitignore")
```

**`cmd_ask(question, repo)`**:
```python
source_root = _normalize_path(repo)
repo_map_path = pm.repo_map_path(source_root)
if not repo_map_path.exists():
    click.echo(f"错误:repo 未索引过,请先 `taisang index {source_root}`", err=True)
    sys.exit(1)

repo_map = RepoMap.model_validate_json(repo_map_path.read_text(encoding="utf-8"))
indexer = IndexerService(pm)
idx = indexer.update(source_root)
call_graph = indexer.build_call_graph(idx)

agent = AgentService(
    llm=llm,
    source_root=source_root,
    call_graph=call_graph,
    repo_map=repo_map,
)
```

### 4.6 不强制改用户 `.gitignore`

只在 `taisang index` 末态打印一行提示:`建议把 .taisang/ 加到 .gitignore`。不主动改用户的 `.gitignore` 文件。

## 五、数据流 + 错误处理

### 5.1 端到端数据流(改动后)

```
用户: taisang index D:/GoProject/wwBuy
  │
  ├─ CLI _normalize_path → source_root: Path
  ├─ 校验 source_root.is_dir() → 否则 exit 1
  ├─ IndexerService.build(source_root):
  │    ├─ Fetcher.current_commit(source_root) → commit 或 "unknown"
  │    ├─ IndexStorage(PathManager.index_db_path(source_root))
  │    │    → <source_root>/.taisang/ast.db
  │    ├─ 扫所有 *.py(排除 .git + .taisang)
  │    ├─ 每个文件 parse_file → Symbol,失败记 index_errors
  │    └─ storage.save_symbols / save_fingerprints / save_index_errors
  │    → RepoIndex(source_root=str, commit_hash, symbols, files, index_errors)
  │
  ├─ SummarizerService.summarize(idx, source_root=source_root) → 调 LLM
  ├─ PathManager.repo_map_path(source_root).write_text(repo_map.model_dump_json())
  │    → <source_root>/.taisang/repo_map.json
  └─ click.echo 提示:建议把 .taisang/ 加到 .gitignore

用户: taisang ask "main 调了谁" --repo D:/GoProject/wwBuy
  │
  ├─ CLI _normalize_path → source_root
  ├─ repo_map_path = PathManager.repo_map_path(source_root),不存在 → exit 1
  ├─ RepoMap.model_validate_json(repo_map_path.read_text())
  ├─ IndexerService.update(source_root):
  │    ├─ db = PathManager.index_db_path(source_root),不存在 → 走 build()
  │    ├─ Fetcher.current_commit(source_root)
  │    ├─ 扫 *.py(排除 .git + .taisang)
  │    ├─ diff_files(old_fps, new_fps) → added/modified/deleted/unchanged
  │    ├─ 只重解析 added + modified
  │    └─ storage.save_symbols(全量 kept + new)
  ├─ call_graph = indexer.build_call_graph(idx)
  ├─ AgentService.run(question):
  │    └─ read_file/grep 工具的 source_root = 命令行传的 source_root
  └─ 打印 Answer + citations
```

### 5.2 错误处理矩阵

| 场景 | 当前行为 | 改动后行为 |
|------|----------|-----------|
| 路径不存在 | clone 失败抛 RuntimeError | `is_dir()` 校验失败,exit 1 + 提示 |
| 路径存在但非目录 | 同上 | 同上 |
| 路径无读权限 | clone 失败 | parse_file 抛 OSError,记 index_errors(原逻辑) |
| 路径无 `.git` | clone 后 `_current_commit` 返回 "unknown" | `current_commit` subprocess 失败,返回 "unknown" |
| `git rev-parse` 超时 | 10 秒超时返回 "unknown" | 同上 |
| `git rev-parse` 抛 OSError(git 未装) | **崩**(原代码未捕获) | try/except 包,返回 "unknown" + log warning |
| `.taisang/ast.db` 损坏 | 不存在此场景 | SQLite 打开失败抛 `DatabaseError`,CLI 层捕获提示删 `.taisang/` 重建 |

### 5.3 向后兼容性

**不向后兼容**:本次改造是破坏性改动。
- `RepoIndex.repo_url` 字段改名 `source_root` — 旧 `repo_map.json` 反序列化会失败
- CLI 参数语义变了 — 旧脚本 `taisang index <url>` 会当 url 是本地路径,`is_dir()` 失败

**处理**:不写迁移脚本。旧 `~/.taisang/cache/` + `indices/` 目录留垃圾,不主动清(用户可手动删)。

## 六、测试改动

### 6.1 受影响测试清单

| 测试文件 | 测试数 | 改动程度 |
|---------|-------|---------|
| `tests/unit/test_fetcher.py` | 3 | **重写**(clone 逻辑砍了) |
| `tests/unit/test_paths.py` | 5 | **重写**(cache/indices 方法砍了) |
| `tests/integration/test_indexer_service.py` | 4 | **改参数**(`repo_url` → `source_root`) |
| `tests/unit/test_cli.py` | 3 | **改参数** + 新增路径校验测试 |
| `tests/integration/test_end_to_end.py` | 3 | **改参数** |
| `tests/unit/test_summarizer.py` | 间接 | 检查是否硬编码 `repo_url` |
| `tests/unit/test_types.py` | 间接 | 检查是否断言 `repo_url` 字段 |

### 6.2 `test_fetcher.py` 重写(3 个新测试)

- `test_current_commit_returns_hash_for_git_repo` — 有 .git 的本地 repo 返回 40 位 sha1
- `test_current_commit_returns_unknown_for_non_git_dir` — 无 .git 目录返回 "unknown"
- `test_current_commit_returns_unknown_when_git_not_installed` — monkeypatch `subprocess.run` 抛 FileNotFoundError,断言返回 "unknown" 不崩

### 6.3 `test_paths.py` 重写(4 个新测试)

- `test_index_dir_creates_taisang_subdir` — `index_dir(tmp_path)` 返回 `tmp_path/.taisang` 且自动创建
- `test_index_db_path_under_taisang` — 路径是 `tmp_path/.taisang/ast.db`
- `test_repo_map_path_under_taisang` — 路径是 `tmp_path/.taisang/repo_map.json`
- `test_chroma_and_errors_paths` — chroma + index_errors 路径正确

### 6.4 `test_indexer_service.py` 改参数(4 个测试)

把所有 `indexer.build("https://github.com/foo/bar")` 改成在 `tmp_path` 建几个 .py 文件,然后 `indexer.build(tmp_path)`。断言 `idx.source_root == str(tmp_path)`。Fetcher 不用 mock(直接传 path)。

### 6.5 `test_cli.py` 改参数 + 新增(原 3 + 新 2 = 5)

原 3 个改 `repo_url` → `repo_path`。新增:
- `test_cli_index_rejects_nonexistent_path` — 路径不存在,exit 1
- `test_cli_ask_without_index_exits_1` — 未索引过的路径,ask exit 1

### 6.6 `test_end_to_end.py` 改参数(3 个测试)

原来用 `https://github.com/...` URL,改成在 `tmp_path` 下建几个 .py 文件,然后 `taisang index <tmp_path>` / `ask --repo <tmp_path>`。

### 6.7 新增:扫源码排除 `.taisang/` 测试

- `test_indexer_excludes_taisang_dir` — 在 `tmp_path/.taisang/fake.py` 放个 Python 文件,断言它不被解析进 `idx.files`

### 6.8 预期测试总量

- 原有 103 个
- 删:`test_fetcher.py` 3 + `test_paths.py` 5 = 8 个
- 改:约 10 个(改参数,逻辑不变)
- 新增:`test_fetcher.py` 3 + `test_paths.py` 4 + `test_cli.py` 2 + `test_indexer_excludes_taisang_dir` 1 = 10 个

**预期改动后**:103 - 8 + 10 = **105 个测试全绿**

### 6.9 测试顺序(同步改,不严格 TDD)

本次是破坏性重命名,测试和实现必须同步改,无法严格 TDD。采用分步策略:

1. 先改 `types.py`(`RepoIndex.repo_url` → `source_root`)→ 跑测试看哪些挂
2. 改 `PathManager` + 测试 → 跑
3. 改 `Fetcher` + 测试 → 跑
4. 改 `IndexerService` + 测试 → 跑
5. 改 CLI + 测试 → 跑
6. 全量回归 + ruff/black + E2E

## 七、提交策略

单个 commit,消息:`refactor: drop remote clone, support local repo only + land index under <repo>/.taisang/`

破坏性改动,但属于同一主题(本地化 + 落盘改造),合在一个 commit 便于回溯。

## 八、风险

1. **Windows 上 `Path.resolve()` 行为**:对符号链接 / UNC 路径会展开。MVP 本地 repo 无符号链接,风险低。
2. **`os.path.expanduser` 在 Windows 展开 `~`**:Windows 上 `~` 展开成 `C:\Users\<user>`,符合预期。
3. **用户误把 `taisang index <url>` 当旧用法**:URL 不存在本地,`is_dir()` 失败,exit 1 + 提示"路径不存在"。错误信息可加一句"v1 不再支持远程 clone,请先 `git clone` 到本地再 index"。
4. **`<repo>/.taisang/` 已被用户占用**:理论上不会,但若用户正好有同名目录,`PathManager.index_dir` 会 `mkdir(exist_ok=True)` 不报错,`IndexStorage` 会建 `ast.db`。可接受。
5. **`git rev-parse` 在大 repo 上慢**:`--depth 1` clone 的浅克隆 commit hash 取得很快,本地 repo 完整克隆也只需 `rev-parse HEAD`,毫秒级。无风险。