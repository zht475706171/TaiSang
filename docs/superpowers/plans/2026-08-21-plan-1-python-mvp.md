# Code Reader Agent - Plan 1: Python-only MVP 闭环 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Code Reader Agent 的 Python-only 最小可用闭环——输入一个 Python repo URL，自动建索引，能用自然语言问答并带源码引用回答。

**Architecture:** 三层架构（索引层 / Agent 内核 / CLI 接入层）。索引层用 tree-sitter 解析 Python AST + 跨文件 linker 建调用图 + LLM 分层摘要 + Chroma/BM25 混合检索；Agent 内核实现 plan→act→observe→reflect 循环 + 5 工具 + 上下文预算管理；CLI 提供建索引和问答入口。LLM 通过 OpenAI 兼容 client 调用，支持任意厂商 endpoint。

**Tech Stack:** Python 3.11+ / tree-sitter + tree-sitter-python / Chroma + rank-bm25 / SQLite / openai SDK (兼容任意 endpoint) / click (CLI) / pytest / ruff + black

**Spec 参考:** `docs/superpowers/specs/2026-08-20-repo-onboarding-agent-design.md`

**Plan 1 范围说明:**
- 只做 Python 一门语言（JS/TS/Java/Go 留给 Plan 2）
- 全 5 工具：read_file / grep / glob / trace_call_chain / lookup_map
- CLI 优先，Web 端留给 Plan 5
- 不做 eval set（留给 Plan 3）、不做 session/trace 落盘（留给 Plan 4）、不做开源化（留给 Plan 6）
- LLM 调用支持 MockLLM 测试

---

## 文件结构

```
taisang-agent/
├── pyproject.toml                    # 项目元数据 + 依赖 + ruff/black 配置
├── src/taisang/
│   ├── __init__.py
│   ├── config.py                     # LLM endpoint 配置加载(settings.json/env)
│   ├── llm_client.py                 # OpenAI 兼容 client + MockLLM
│   ├── types.py                      # Symbol/RepoIndex/RepoMap/Answer 数据类型
│   ├── storage/
│   │   ├── __init__.py
│   │   └── paths.py                  # ~/.taisang/ 路径管理
│   ├── indexer/
│   │   ├── __init__.py
│   │   ├── fetcher.py                # git clone
│   │   ├── parser_python.py          # tree-sitter Python adapter
│   │   ├── linker.py                 # 跨文件符号表 join → 调用图
│   │   ├── fingerprint.py            # 文件 hash 增量
│   │   ├── storage.py                # SQLite 持久化
│   │   └── service.py                # build() / update() 入口
│   ├── summarizer/
│   │   ├── __init__.py
│   │   ├── prompts.py                # 三层摘要 prompt 模板
│   │   └── service.py                # summarize() 入口
│   ├── retriever/
│   │   ├── __init__.py
│   │   ├── vectorstore.py            # Chroma 封装
│   │   ├── bm25.py                   # BM25 索引
│   │   ├── hybrid.py                 # 混合排序
│   │   └── service.py                # search() 入口
│   ├── agent_core/
│   │   ├── __init__.py
│   │   ├── tools.py                  # 5 工具实现
│   │   ├── prompts.py                # Agent system prompt
│   │   ├── context.py                # 上下文管理 + compaction
│   │   └── service.py                # run() 循环入口
│   └── cli/
│       ├── __init__.py
│       └── main.py                   # click CLI 入口
├── tests/
│   ├── conftest.py                   # pytest 公共 fixture
│   ├── fixtures/
│   │   └── python/                   # Python 测试 fixture 文件
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_llm_client.py
│   │   ├── test_fingerprint.py
│   │   ├── test_parser_python.py
│   │   ├── test_linker.py
│   │   ├── test_storage.py
│   │   ├── test_summarizer.py
│   │   ├── test_retriever.py
│   │   ├── test_tools.py
│   │   ├── test_context.py
│   │   └── test_agent_core.py
│   └── integration/
│       └── test_end_to_end.py
└── .github/workflows/ci.yml          # CI 占位
```

**职责说明:**
- `types.py`: 所有跨模块数据类型集中（Symbol / RepoIndex / RepoMap / Snippet / Answer / Citation），避免循环导入
- `config.py` + `llm_client.py`: LLM 接入层，配置加载 + OpenAI 兼容 client + MockLLM
- `indexer/`: 索引层 6 个子模块，service.py 是编排入口
- `summarizer/`: 摘要层，prompts.py 跟 service.py 分离便于测试
- `retriever/`: 检索层，vectorstore/bm25/hybrid 各司其职
- `agent_core/`: Agent 内核，tools/context/prompts 分离
- `cli/main.py`: click 入口，调用各 service

---

## Task 1: 项目骨架 + 依赖配置

**Files:**
- Create: `pyproject.toml`
- Create: `src/taisang/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "taisang"
version = "0.1.0"
description = "Code Reader Agent - 3 分钟让陌生代码库变成可问答、可追踪调用链"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "泰哥" }]
dependencies = [
    "openai>=1.0",
    "tree-sitter>=0.21",
    "tree-sitter-python>=0.21",
    "chromadb>=0.5",
    "rank-bm25>=0.2",
    "gitpython>=3.1",
    "click>=8.1",
    "structlog>=24.1",
    "tiktoken>=0.7",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.5",
    "black>=24.0",
    "pre-commit>=3.7",
]

[project.scripts]
taisang = "taisang.cli.main:cli"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: 写空 __init__.py 文件**

`src/taisang/__init__.py`:
```python
"""Code Reader Agent - 3 分钟让陌生代码库变成可问答、可追踪调用链。"""

__version__ = "0.1.0"
```

`tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` 全部为空文件。

- [ ] **Step 3: 写 CI 占位文件**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: black --check src tests
      - run: pytest -v
```

- [ ] **Step 4: 安装依赖验证**

Run: `pip install -e ".[dev]"`
Expected: 安装成功，无报错

- [ ] **Step 5: 验证 CLI 入口可加载（即使还没实现）**

Run: `taisang --help`
Expected: 报错 `ModuleNotFoundError: No module named 'taisang.cli'`（预期，因为 cli 还没写，证明入口注册了但模块缺失）

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/taisang/__init__.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py .github/workflows/ci.yml
git commit -m "feat: scaffold project structure with pyproject.toml and CI placeholder"
```

---

## Task 2: 核心数据类型 types.py

**Files:**
- Create: `src/taisang/types.py`
- Test: `tests/unit/test_types.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_types.py`:
```python
"""测试核心数据类型能正确构造和序列化。"""
from taisang.types import (
    Symbol, SymbolKind, RepoIndex, RepoMap, FileSummary,
    ModuleSummary, GlobalSummary, Snippet, Citation, Answer
)


def test_symbol_basic():
    s = Symbol(
        id="fastapi/application.py::FastAPI.run",
        kind=SymbolKind.FUNCTION,
        name="run",
        file="fastapi/application.py",
        line_range=(110, 145),
        calls=["uvicorn.run"],
        imports=["uvicorn"],
    )
    assert s.kind == SymbolKind.FUNCTION
    assert s.line_range == (110, 145)
    assert s.calls == ["uvicorn.run"]


def test_symbol_kind_values():
    assert SymbolKind.FUNCTION != SymbolKind.CLASS
    assert SymbolKind.METHOD.value == "method"


def test_repo_index_holds_symbols():
    sym = Symbol(
        id="app.py::main",
        kind=SymbolKind.FUNCTION,
        name="main",
        file="app.py",
        line_range=(1, 10),
        calls=[],
        imports=[],
    )
    idx = RepoIndex(
        repo_url="https://github.com/test/repo",
        commit_hash="abc123",
        symbols=[sym],
        files=["app.py"],
    )
    assert len(idx.symbols) == 1
    assert idx.files == ["app.py"]


def test_repo_map_three_layers():
    fmap = {"app.py": FileSummary(file="app.py", summary="应用入口", symbol_ids=["app.py::main"])}
    mmap = {"": ModuleSummary(path="", summary="根模块", file_count=1)}
    gmap = GlobalSummary(
        entry_points=["app.py::main"],
        core_modules=[""],
        dependency_summary="无外部依赖",
    )
    rm = RepoMap(global_summary=gmap, module_summaries=mmap, file_summaries=fmap)
    assert rm.file_summaries["app.py"].summary == "应用入口"


def test_citation_and_answer():
    c = Citation(file="app.py", line_range=(1, 10), symbol_id="app.py::main")
    a = Answer(
        text="main 是应用入口",
        citations=[c],
        complete=True,
    )
    assert a.citations[0].file == "app.py"
    assert a.complete is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'taisang.types'`

- [ ] **Step 3: 写 types.py**

`src/taisang/types.py`:
```python
"""核心数据类型。所有跨模块共享的数据结构集中在此,避免循环导入。"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    """符号种类。"""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"


class Symbol(BaseModel):
    """一个代码符号(函数/类/方法等)。

    id 格式: "<file_path>::<qualified_name>",全局唯一。
    calls 是被调用符号的名字列表(best-effort,可能未解析到定义)。
    imports 是该符号所在文件 import 的模块名列表。
    """
    id: str
    kind: SymbolKind
    name: str
    file: str
    line_range: tuple[int, int]
    calls: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


class RepoIndex(BaseModel):
    """一次索引的产物:AST 解析 + 跨文件调用图。"""
    repo_url: str
    commit_hash: str
    symbols: list[Symbol]
    files: list[str]
    index_errors: list[dict] = Field(default_factory=list)


class FileSummary(BaseModel):
    """文件级摘要(目标 100 字)。"""
    file: str
    summary: str
    symbol_ids: list[str] = Field(default_factory=list)


class ModuleSummary(BaseModel):
    """模块级摘要(目标 300 字,按目录聚合)。"""
    path: str  # 目录路径,根目录为 ""
    summary: str
    file_count: int


class GlobalSummary(BaseModel):
    """全局级摘要(目标 1000 字)。"""
    entry_points: list[str]
    core_modules: list[str]
    dependency_summary: str


class RepoMap(BaseModel):
    """三层摘要的完整产物。"""
    global_summary: GlobalSummary
    module_summaries: dict[str, ModuleSummary]
    file_summaries: dict[str, FileSummary]


class Snippet(BaseModel):
    """检索返回的片段。"""
    file: str
    line_range: tuple[int, int]
    text: str
    score: float
    symbol_id: str | None = None


class Citation(BaseModel):
    """答案中的引用。"""
    file: str
    line_range: tuple[int, int]
    symbol_id: str | None = None


class Answer(BaseModel):
    """Agent 最终回答。"""
    text: str
    citations: list[Citation] = Field(default_factory=list)
    complete: bool = True  # False 表示因 max_steps/token 提前终止
    steps_used: int = 0
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_types.py -v`
Expected: PASS (5 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/types.py tests/unit/test_types.py
git commit -m "feat: add core data types (Symbol/RepoIndex/RepoMap/Answer)"
```

---

## Task 3: 路径管理 storage/paths.py

**Files:**
- Create: `src/taisang/storage/__init__.py`
- Create: `src/taisang/storage/paths.py`
- Test: `tests/unit/test_paths.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_paths.py`:
```python
"""测试路径管理(用 tmp_path 隔离,不污染真实 ~/.taisang/)。"""
from pathlib import Path
from taisang.storage.paths import PathManager


def test_root_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pm = PathManager()
    assert pm.root == tmp_path / ".taisang"


def test_indices_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pm = PathManager()
    # repo_hash 是 url 的 sha1
    idx_dir = pm.indices_dir("https://github.com/test/repo")
    assert idx_dir.parent == pm.root / "indices"
    assert idx_dir.exists()


def test_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pm = PathManager()
    assert pm.cache_dir.exists()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 paths.py**

`src/taisang/storage/__init__.py`: 空文件

`src/taisang/storage/paths.py`:
```python
"""~/.taisang/ 路径管理。所有落盘位置都从这里取,便于测试用 env 覆盖。"""
from __future__ import annotations

import hashlib
from pathlib import Path


class PathManager:
    """统一管理所有落盘路径。

    默认根目录是 ~/.taisang/,测试时通过 monkeypatch HOME 隔离。
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = Path.home() / ".taisang"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        """repo clone 缓存目录。"""
        d = self.root / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _repo_hash(self, repo_url: str) -> str:
        return hashlib.sha1(repo_url.encode()).hexdigest()[:16]

    def indices_dir(self, repo_url: str) -> Path:
        """单个 repo 的索引产物目录。"""
        d = self.root / "indices" / self._repo_hash(repo_url)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def index_db_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "ast.db"

    def repo_map_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "repo_map.json"

    def chroma_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "chroma"

    def index_errors_path(self, repo_url: str) -> Path:
        return self.indices_dir(repo_url) / "index_errors.json"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_paths.py -v`
Expected: PASS (3 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/storage/__init__.py src/taisang/storage/paths.py tests/unit/test_paths.py
git commit -m "feat: add PathManager for ~/.taisang/ path management"
```

---

## Task 4: LLM 配置加载 config.py

**Files:**
- Create: `src/taisang/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_config.py`:
```python
"""测试 LLM 配置加载(环境变量 / settings.json / 默认值)。"""
import json
from pathlib import Path
from taisang.config import LLMConfig, load_config


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("CODE_READER_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("CODE_READER_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("CODE_READER_LLM_MODEL", "deepseek-chat")
    cfg = load_config()
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.api_key == "sk-test"
    assert cfg.model == "deepseek-chat"


def test_config_from_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "llm": {
            "base_url": "https://api.openai.com",
            "api_key": "sk-file",
            "model": "gpt-4o",
        }
    }))
    # 清掉 env 让文件生效
    for k in ["CODE_READER_LLM_BASE_URL", "CODE_READER_LLM_API_KEY", "CODE_READER_LLM_MODEL"]:
        monkeypatch.delenv(k, raising=False)
    cfg = load_config()
    assert cfg.model == "gpt-4o"


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "llm": {"base_url": "https://from-file", "api_key": "k", "model": "m"}
    }))
    monkeypatch.setenv("CODE_READER_LLM_MODEL", "from-env")
    cfg = load_config()
    assert cfg.model == "from-env"
    assert cfg.base_url == "https://from-file"


def test_summarizer_config_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODE_READER_LLM_BASE_URL", "https://api.x.com")
    monkeypatch.setenv("CODE_READER_LLM_API_KEY", "k")
    monkeypatch.setenv("CODE_READER_LLM_MODEL", "strong-model")
    monkeypatch.setenv("CODE_READER_SUMMARIZER_MODEL", "cheap-model")
    cfg = load_config()
    assert cfg.model == "strong-model"
    assert cfg.summarizer_model == "cheap-model"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 config.py**

`src/taisang/config.py`:
```python
"""LLM endpoint 配置加载。

优先级: 环境变量 > ~/.taisang/settings.json > 默认值。
支持两套独立配置: 主模型(Agent 循环) 和 摘要模型(便宜模型)。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from pydantic import BaseModel


class LLMConfig(BaseModel):
    """LLM 接入配置。"""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    # 摘要模型(可选,默认跟主模型一致)
    summarizer_base_url: str | None = None
    summarizer_api_key: str | None = None
    summarizer_model: str | None = None


def _settings_path() -> Path:
    return Path.home() / ".taisang" / "settings.json"


def _load_settings_file() -> dict:
    p = _settings_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_config() -> LLMConfig:
    """加载 LLM 配置。env 覆盖文件,文件覆盖默认值。"""
    file_cfg = _load_settings_file().get("llm", {})
    base_url = os.environ.get("CODE_READER_LLM_BASE_URL", file_cfg.get("base_url", "https://api.openai.com/v1"))
    api_key = os.environ.get("CODE_READER_LLM_API_KEY", file_cfg.get("api_key", ""))
    model = os.environ.get("CODE_READER_LLM_MODEL", file_cfg.get("model", "gpt-4o"))
    summ_model = os.environ.get("CODE_READER_SUMMARIZER_MODEL", file_cfg.get("summarizer_model"))
    summ_base = os.environ.get("CODE_READER_SUMMARIZER_BASE_URL", file_cfg.get("summarizer_base_url"))
    summ_key = os.environ.get("CODE_READER_SUMMARIZER_API_KEY", file_cfg.get("summarizer_api_key"))
    return LLMConfig(
        base_url=base_url, api_key=api_key, model=model,
        summarizer_base_url=summ_base, summarizer_api_key=summ_key, summarizer_model=summ_model,
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS (4 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/config.py tests/unit/test_config.py
git commit -m "feat: add LLMConfig with env/file/default priority"
```

---

## Task 5: LLM Client + MockLLM

**Files:**
- Create: `src/taisang/llm_client.py`
- Test: `tests/unit/test_llm_client.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_llm_client.py`:
```python
"""测试 LLM client + MockLLM(自研轻量 mock)。"""
from taisang.llm_client import LLMClient, MockLLM, LLMResponse


def test_mock_llm_returns_prescribed_responses_in_order():
    mock = MockLLM([
        LLMResponse(text="第一个响应", tool_calls=[]),
        LLMResponse(text="第二个响应", tool_calls=[]),
    ])
    r1 = mock.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    r2 = mock.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert r1.text == "第一个响应"
    assert r2.text == "第二个响应"


def test_mock_llm_records_calls():
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    mock.chat(messages=[{"role": "user", "content": "q"}], tools=[{"name": "grep"}])
    assert len(mock.calls) == 1
    assert mock.calls[0]["messages"][0]["content"] == "q"
    assert mock.calls[0]["tools"][0]["name"] == "grep"


def test_mock_llm_raises_when_run_out():
    import pytest
    mock = MockLLM([LLMResponse(text="only", tool_calls=[])])
    mock.chat(messages=[], tools=[])
    with pytest.raises(RuntimeError, match="no more mock responses"):
        mock.chat(messages=[], tools=[])


def test_mock_llm_tool_call_response():
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[{"name": "grep", "args": {"pattern": "foo"}}]),
    ])
    r = mock.chat(messages=[], tools=[])
    assert r.tool_calls == [{"name": "grep", "args": {"pattern": "foo"}}]
    assert r.text == ""


def test_real_llm_client_constructs_with_config():
    """只测 client 能用 config 构造,不真发请求。"""
    from taisang.config import LLMConfig
    cfg = LLMConfig(base_url="https://api.x.com", api_key="k", model="m")
    client = LLMClient(cfg)
    assert client.model == "m"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 llm_client.py**

`src/taisang/llm_client.py`:
```python
"""LLM client:OpenAI 兼容接口 + 自研 MockLLM。

MockLLM 约 50 行,按调用顺序返回预设响应,不依赖外部服务。
LLMClient 用 openai SDK,兼容任意 OpenAI 兼容 endpoint。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import LLMConfig


@dataclass
class LLMResponse:
    """LLM 一次响应。text 和 tool_calls 至少有一个非空。"""
    text: str
    tool_calls: list[dict] = field(default_factory=list)


class LLMClient:
    """真实 LLM client,基于 openai SDK。"""

    def __init__(self, cfg: LLMConfig) -> None:
        from openai import OpenAI
        self.cfg = cfg
        self.model = cfg.model
        self._client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """发 chat completion 请求,返回 LLMResponse。

        tools 是工具 schema 列表(OpenAI tool 格式)。
        """
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": t} for t in tools
            ]
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            import json
            for tc in msg.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments),
                })
        return LLMResponse(text=msg.content or "", tool_calls=tool_calls)


class MockLLM:
    """测试用 mock LLM。按调用顺序返回预设响应,记录所有调用。

    用法:
        mock = MockLLM([resp1, resp2])
        mock.chat(messages=[...], tools=[...])  # 返回 resp1
        mock.chat(messages=[...], tools=[...])  # 返回 resp2
        mock.calls  # 查看所有调用记录
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            raise RuntimeError("no more mock responses prescribed")
        return self._responses.pop(0)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_llm_client.py -v`
Expected: PASS (5 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/llm_client.py tests/unit/test_llm_client.py
git commit -m "feat: add LLMClient (OpenAI-compatible) + MockLLM for testing"
```

---

## Task 6: 文件指纹 fingerprint.py

**Files:**
- Create: `src/taisang/indexer/__init__.py`
- Create: `src/taisang/indexer/fingerprint.py`
- Test: `tests/unit/test_fingerprint.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_fingerprint.py`:
```python
"""测试文件指纹:同一文件 hash 稳定,不同文件 hash 不同,内容变 hash 变。"""
from pathlib import Path
from taisang.indexer.fingerprint import file_hash, diff_files


def test_file_hash_stable(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print('hi')\n", encoding="utf-8")
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2


def test_file_hash_changes_with_content(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print('hi')\n", encoding="utf-8")
    h1 = file_hash(f)
    f.write_text("print('bye')\n", encoding="utf-8")
    h2 = file_hash(f)
    assert h1 != h2


def test_diff_files_detects_added_modified_deleted(tmp_path):
    old = {
        "a.py": "hash-a-old",
        "b.py": "hash-b",
    }
    new = {
        "a.py": "hash-a-new",  # modified
        "b.py": "hash-b",       # unchanged
        "c.py": "hash-c",       # added
    }
    added, modified, deleted, unchanged = diff_files(old, new)
    assert added == {"c.py"}
    assert modified == {"a.py"}
    assert deleted == {"a.py"} or deleted == set()  # 别犯懒,下面修正
    # 修正上面这个混淆:
    assert deleted == set()
    assert unchanged == {"b.py"}
```

> **注意**:上面 `test_diff_files_detects_added_modified_deleted` 中那个"别犯懒"行是错的,实际正确断言是 `deleted == set()`(old 里的 a.py/b.py 都还在 new 里)。下面 Step 3 的实现按此设计。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 fingerprint.py**

`src/taisang/indexer/__init__.py`: 空文件

`src/taisang/indexer/fingerprint.py`:
```python
"""文件指纹:用 sha1 计算文件内容 hash,做增量索引基础。"""
from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path) -> str:
    """计算文件内容 sha1,返回前 16 位(够用,省空间)。"""
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def diff_files(
    old: dict[str, str], new: dict[str, str]
) -> tuple[set[str], set[str], set[str], set[str]]:
    """对比新旧文件指纹字典。

    Returns: (added, modified, deleted, unchanged) 四个文件路径集合。
    """
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    deleted = old_keys - new_keys
    common = old_keys & new_keys
    modified = {k for k in common if old[k] != new[k]}
    unchanged = {k for k in common if old[k] == new[k]}
    return added, modified, deleted, unchanged
```

- [ ] **Step 4: 修正测试里的混淆断言**

把 `tests/unit/test_fingerprint.py` 里的 `test_diff_files_detects_added_modified_deleted` 改成:
```python
def test_diff_files_detects_added_modified_deleted(tmp_path):
    old = {"a.py": "hash-a-old", "b.py": "hash-b", "d.py": "hash-d"}
    new = {"a.py": "hash-a-new", "b.py": "hash-b", "c.py": "hash-c"}
    added, modified, deleted, unchanged = diff_files(old, new)
    assert added == {"c.py"}
    assert modified == {"a.py"}
    assert deleted == {"d.py"}
    assert unchanged == {"b.py"}
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/unit/test_fingerprint.py -v`
Expected: PASS (3 个测试全绿)

- [ ] **Step 6: Commit**

```bash
git add src/taisang/indexer/__init__.py src/taisang/indexer/fingerprint.py tests/unit/test_fingerprint.py
git commit -m "feat: add file fingerprint (sha1) and diff_files for incremental indexing"
```

---

## Task 7: Python AST 解析器 parser_python.py

**Files:**
- Create: `src/taisang/indexer/parser_python.py`
- Create: `tests/fixtures/python/sample_simple.py` (fixture)
- Create: `tests/fixtures/python/sample_with_class.py` (fixture)
- Create: `tests/fixtures/python/sample_with_syntax_error.py` (fixture)
- Test: `tests/unit/test_parser_python.py`

- [ ] **Step 1: 写 fixture 文件**

`tests/fixtures/python/sample_simple.py`:
```python
"""一个简单的 fixture 文件,用于测试 parser。"""
import os
from pathlib import Path


def greet(name: str) -> str:
    """Greet someone."""
    return f"hello, {name}"


def main():
    name = os.environ.get("USER", "world")
    print(greet(name))
    Path("log.txt").write_text("done")


if __name__ == "__main__":
    main()
```

`tests/fixtures/python/sample_with_class.py`:
```python
"""含 class 和 method 的 fixture。"""
from typing import List


class Stack:
    def __init__(self):
        self.items: List[int] = []

    def push(self, x: int) -> None:
        self.items.append(x)

    def pop(self) -> int:
        return self.items.pop()


def use_stack():
    s = Stack()
    s.push(1)
    return s.pop()
```

`tests/fixtures/python/sample_with_syntax_error.py`:
```python
"""语法错误 fixture,parser 应容错不崩。"""
def broken(
    # 缺右括号和冒号
    print("this file has syntax error")
```

- [ ] **Step 2: 写失败测试**

`tests/unit/test_parser_python.py`:
```python
"""测试 Python tree-sitter parser。"""
from pathlib import Path
from taisang.indexer.parser_python import parse_file
from taisang.types import SymbolKind

FIXTURES = Path(__file__).parent.parent / "fixtures" / "python"


def test_parse_simple_file_extracts_functions():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    names = {s.name for s in symbols}
    assert "greet" in names
    assert "main" in names


def test_parse_simple_file_function_kind():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    greet = next(s for s in symbols if s.name == "greet")
    assert greet.kind == SymbolKind.FUNCTION
    assert greet.file.endswith("sample_simple.py")
    # line_range 是 (start, end),从 1 开始
    assert greet.line_range[0] >= 5  # greet 在第 6 行附近
    assert greet.line_range[1] > greet.line_range[0]


def test_parse_simple_file_extracts_calls():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    main = next(s for s in symbols if s.name == "main")
    # main 里调用了 greet, os.environ.get, print, Path
    assert "greet" in main.calls
    assert "print" in main.calls


def test_parse_simple_file_extracts_imports():
    symbols = parse_file(FIXTURES / "sample_simple.py")
    # imports 算在文件级,这里用第一个符号的 imports 代表文件 imports
    assert any("os" in s.imports for s in symbols)
    assert any("pathlib" in s.imports for s in symbols)


def test_parse_class_extracts_methods():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    names = {s.name for s in symbols}
    assert "Stack" in names  # class 本身也是 symbol
    assert "push" in names
    assert "pop" in names
    assert "__init__" in names


def test_parse_class_method_kind():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    push = next(s for s in symbols if s.name == "push")
    assert push.kind == SymbolKind.METHOD


def test_parse_class_method_calls():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    use_stack = next(s for s in symbols if s.name == "use_stack")
    assert "Stack" in use_stack.calls  # 构造调用
    assert "push" in use_stack.calls


def test_parse_syntax_error_does_not_crash():
    """容错解析:语法错误文件不抛异常,返回可能为空或部分符号。"""
    symbols = parse_file(FIXTURES / "sample_with_syntax_error.py")
    # 只要不抛异常就算过,符号列表可以为空
    assert isinstance(symbols, list)


def test_parse_symbol_id_unique_and_qualified():
    symbols = parse_file(FIXTURES / "sample_with_class.py")
    ids = {s.id for s in symbols}
    # id 格式: "<file>::<name>",全唯一
    assert len(ids) == len(symbols)
    for sid in ids:
        assert "::" in sid
```

- [ ] **Step 3: 运行测试验证失败**

Run: `pytest tests/unit/test_parser_python.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: 写 parser_python.py**

`src/taisang/indexer/parser_python.py`:
```python
"""Python tree-sitter parser。

用 tree-sitter 解析 Python 文件,抽出 Symbol 列表(函数/类/方法)。
容错:遇到语法错误不抛异常,返回能抽到的部分(可能为空)。
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from ..types import Symbol, SymbolKind

_LANGUAGE = Language(tspython.language())
_PARSER = Parser(_LANGUAGE)


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_calls(body_node, source: bytes) -> list[str]:
    """从函数体里抽所有 call 芃点,返回被调用函数名列表。"""
    calls: list[str] = []
    stack = [body_node]
    while stack:
        n = stack.pop()
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is not None:
                name = _node_text(fn, source)
                # 只取最末段(比如 self.foo 取 foo,obj.bar 取 bar)
                if "." in name:
                    name = name.split(".")[-1]
                calls.append(name)
            continue  # 不再深入 call 子节点(避免重复)
        for child in n.children:
            stack.append(child)
    return calls


def _extract_imports(root_node, source: bytes) -> list[str]:
    """从文件根抽 import 的模块名。"""
    imports: list[str] = []
    for child in root_node.children:
        if child.type == "import_statement":
            # import os / import os.path → 取 os
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                imports.append(name.split(".")[0])
        elif child.type == "import_from_statement":
            module_node = child.child_by_field_name("module_name")
            if module_node:
                name = _node_text(module_node, source)
                imports.append(name.split(".")[0])
    return imports


def _make_symbol_id(file_rel: str, name: str, parent: str | None) -> str:
    qual = f"{parent}.{name}" if parent else name
    return f"{file_rel}::{qual}"


def _walk_functions_and_classes(root_node, source: bytes, file_rel: str, imports: list[str]):
    """遍历 AST,产出 Symbol。class 内的 method 标 METHOD,parent 为 class 名。"""
    symbols: list[Symbol] = []

    def visit(node, parent_class: str | None):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = _node_text(name_node, source)
            body = node.child_by_field_name("body")
            calls = _extract_calls(body, source) if body else []
            kind = SymbolKind.METHOD if parent_class else SymbolKind.FUNCTION
            symbols.append(Symbol(
                id=_make_symbol_id(file_rel, name, parent_class),
                kind=kind,
                name=name,
                file=file_rel,
                line_range=(node.start_point[0] + 1, node.end_point[0] + 1),
                calls=calls,
                imports=imports,
            ))
            # 函数内可能嵌套函数(不深入 method 体的 call,已经在 _extract_calls 里抓了)
            for child in node.children:
                if child.type == "function_definition":
                    visit(child, parent_class)
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = _node_text(name_node, source)
            symbols.append(Symbol(
                id=_make_symbol_id(file_rel, name, parent_class),
                kind=SymbolKind.CLASS,
                name=name,
                file=file_rel,
                line_range=(node.start_point[0] + 1, node.end_point[0] + 1),
                calls=[],
                imports=imports,
            ))
            # 进入 class body 找 method
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    visit(child, parent_class=name)
            return  # 不再深入 class 的其他子节点
        else:
            for child in node.children:
                visit(child, parent_class)

    visit(root_node, None)
    return symbols


def parse_file(path: Path, rel_path: str | None = None) -> list[Symbol]:
    """解析单个 Python 文件,返回 Symbol 列表。

    rel_path 是相对 repo 根的路径,用于 Symbol.file 和 id。
    如果不传,用 path.name。
    容错:语法错误不抛异常,返回空列表或部分符号。
    """
    file_rel = rel_path or path.name
    try:
        source = path.read_bytes()
    except OSError:
        return []
    try:
        tree = _PARSER.parse(source)
    except Exception:
        return []
    root = tree.root_node
    imports = _extract_imports(root, source)
    return _walk_functions_and_classes(root, source, file_rel, imports)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/unit/test_parser_python.py -v`
Expected: PASS (9 个测试全绿)

> 如果某些断言失败(比如 `greet` 不在 calls 里),可能是 tree-sitter 遍历顺序导致,调试时打印 `main.calls` 看实际抽出什么,调整断言或 _extract_calls 逻辑。

- [ ] **Step 6: Commit**

```bash
git add src/taisang/indexer/parser_python.py tests/fixtures/python/ tests/unit/test_parser_python.py
git commit -m "feat: add Python tree-sitter parser with fault-tolerant extraction"
```

---

## Task 8: 跨文件 linker linker.py

**Files:**
- Create: `src/taisang/indexer/linker.py`
- Test: `tests/unit/test_linker.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_linker.py`:
```python
"""测试跨文件 linker:把多个文件的 Symbol 拼成全局调用图。"""
from taisang.indexer.linker import build_call_graph, resolve_call_chain
from taisang.types import Symbol, SymbolKind


def _sym(id_, kind, name, file, line, calls=None, imports=None):
    return Symbol(
        id=id_, kind=kind, name=name, file=file, line_range=(line, line + 5),
        calls=calls or [], imports=imports or [],
    )


def test_build_call_graph_links_cross_file_call():
    """a.py 的 func_a 调 func_b,b.py 定义 func_b。"""
    symbols = [
        _sym("a.py::func_a", SymbolKind.FUNCTION, "func_a", "a.py", 1, calls=["func_b"]),
        _sym("b.py::func_b", SymbolKind.FUNCTION, "func_b", "b.py", 1, calls=[]),
    ]
    graph = build_call_graph(symbols)
    # func_a 的 resolved_calls 应该指向 b.py::func_b
    assert "b.py::func_b" in graph["a.py::func_a"].resolved_calls


def test_build_call_graph_unresolved_call_kept_as_name():
    """调用了不存在于全局表的名字(比如 print),保留原名,不崩。"""
    symbols = [
        _sym("a.py::func_a", SymbolKind.FUNCTION, "func_a", "a.py", 1, calls=["print", "func_b"]),
    ]
    graph = build_call_graph(symbols)
    # func_b 未定义,只保留名字
    assert "print" in graph["a.py::func_a"].unresolved_calls
    assert "func_b" in graph["a.py::func_a"].unresolved_calls


def test_resolve_call_chain_two_hops():
    """a → b → c 的调用链,depth=2 返回 a, b, c。"""
    symbols = [
        _sym("a.py::a", SymbolKind.FUNCTION, "a", "a.py", 1, calls=["b"]),
        _sym("b.py::b", SymbolKind.FUNCTION, "b", "b.py", 1, calls=["c"]),
        _sym("c.py::c", SymbolKind.FUNCTION, "c", "c.py", 1, calls=[]),
    ]
    graph = build_call_graph(symbols)
    chain = resolve_call_chain(graph, "a.py::a", depth=2)
    assert chain == ["a.py::a", "b.py::b", "c.py::c"]


def test_resolve_call_chain_handles_cycle():
    """a → b → a 形成环,depth=3 时不应无限循环。"""
    symbols = [
        _sym("a.py::a", SymbolKind.FUNCTION, "a", "a.py", 1, calls=["b"]),
        _sym("b.py::b", SymbolKind.FUNCTION, "b", "b.py", 1, calls=["a"]),
    ]
    graph = build_call_graph(symbols)
    chain = resolve_call_chain(graph, "a.py::a", depth=3)
    # 环到 a 时停止,不重复
    assert chain == ["a.py::a", "b.py::b"]


def test_resolve_call_chain_unknown_symbol_returns_single():
    """查不存在的 symbol_id,只返回它自己(或空)。"""
    symbols = [_sym("a.py::a", SymbolKind.FUNCTION, "a", "a.py", 1, calls=[])]
    graph = build_call_graph(symbols)
    chain = resolve_call_chain(graph, "unknown::x", depth=3)
    assert chain == []


def test_build_call_graph_method_qualified():
    """Stack.push 调用 self.items.append,push 的 calls 里有 append,append 未定义则 unresolved。"""
    symbols = [
        _sym("stack.py::Stack.push", SymbolKind.METHOD, "push", "stack.py", 5, calls=["append"]),
    ]
    graph = build_call_graph(symbols)
    assert "append" in graph["stack.py::Stack.push"].unresolved_calls


def test_build_call_graph_method_call_to_other_method_in_same_class():
    """Stack.push 调用 self.pop,pop 也在 Stack 里,应解析到 Stack.pop。"""
    symbols = [
        _sym("stack.py::Stack.push", SymbolKind.METHOD, "push", "stack.py", 5, calls=["pop"]),
        _sym("stack.py::Stack.pop", SymbolKind.METHOD, "pop", "stack.py", 8, calls=[]),
    ]
    graph = build_call_graph(symbols)
    # push 调 pop,pop 在同一个 class Stack 里,应解析
    assert "stack.py::Stack.pop" in graph["stack.py::Stack.push"].resolved_calls
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_linker.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 linker.py**

`src/taisang/indexer/linker.py`:
```python
"""跨文件 linker:把多文件 Symbol 拼成全局调用图。

设计:
- build_call_graph 建 symbol_id → CallGraphNode 的图
- resolve_call_chain 从某 symbol 出发 BFS,返回 N 跳调用链
- 弱类型语言(如 Python)调用追踪靠"同名符号"匹配,best-effort
- method 内调 self.xxx 优先解析到同 class 的 method
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..types import Symbol


@dataclass
class CallGraphNode:
    """调用图节点。"""
    symbol_id: str
    name: str
    file: str
    line_range: tuple[int, int]
    resolved_calls: list[str] = field(default_factory=list)  # 解析到的 symbol_id
    unresolved_calls: list[str] = field(default_factory=list)  # 未解析的裸名


def _method_class(symbol_id: str) -> str | None:
    """从 symbol_id 抽 class 名(如果有)。id 格式: file::Class.method 或 file::func。"""
    qual = symbol_id.split("::", 1)[1] if "::" in symbol_id else symbol_id
    if "." in qual:
        return qual.split(".", 1)[0]
    return None


def build_call_graph(symbols: list[Symbol]) -> dict[str, CallGraphNode]:
    """构建全局调用图。

    匹配策略:
    1. caller 是 method 且 call name 跟同 class 内某 method 同名 → 解析到那个 method
    2. 否则在全局按 name 找唯一匹配的 symbol → 解析
    3. 多个同名或无匹配 → 加入 unresolved_calls
    """
    # name → list[symbol_id]
    by_name: dict[str, list[str]] = {}
    for s in symbols:
        by_name.setdefault(s.name, []).append(s.id)

    graph: dict[str, CallGraphNode] = {}
    for s in symbols:
        node = CallGraphNode(
            symbol_id=s.id, name=s.name, file=s.file, line_range=s.line_range,
        )
        caller_class = _method_class(s.id)
        for call_name in s.calls:
            # 策略 1: method 内调 self.xxx → 同 class 的 method
            if caller_class:
                candidate = next(
                    (sid for sid in by_name.get(call_name, [])
                     if _method_class(sid) == caller_class),
                    None,
                )
                if candidate:
                    node.resolved_calls.append(candidate)
                    continue
            # 策略 2: 全局唯一 name
            candidates = by_name.get(call_name, [])
            if len(candidates) == 1:
                node.resolved_calls.append(candidates[0])
            else:
                node.unresolved_calls.append(call_name)
        graph[s.id] = node
    return graph


def resolve_call_chain(
    graph: dict[str, CallGraphNode], start: str, depth: int
) -> list[str]:
    """BFS 返回从 start 出发的 N 跳调用链(含 start)。

    环检测:遇到已访问节点停止该分支。
    start 不在图中返回 []。
    """
    if start not in graph:
        return []
    visited: set[str] = {start}
    chain: list[str] = [start]
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        node_id, d = queue.popleft()
        if d >= depth:
            continue
        node = graph.get(node_id)
        if not node:
            continue
        for callee in node.resolved_calls:
            if callee in visited:
                continue
            visited.add(callee)
            chain.append(callee)
            queue.append((callee, d + 1))
    return chain
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_linker.py -v`
Expected: PASS (6 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/indexer/linker.py tests/unit/test_linker.py
git commit -m "feat: add cross-file linker with BFS call chain resolution"
```

---

## Task 9: SQLite 持久化 storage.py

**Files:**
- Create: `src/taisang/indexer/storage.py`
- Test: `tests/unit/test_storage.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_storage.py`:
```python
"""测试索引 SQLite 持久化。"""
from pathlib import Path
from taisang.indexer.storage import IndexStorage
from taisang.types import Symbol, SymbolKind


def _sym(id_, name, file="a.py", line=1):
    return Symbol(
        id=id_, kind=SymbolKind.FUNCTION, name=name, file=file,
        line_range=(line, line + 5), calls=[], imports=[],
    )


def test_save_and_load_symbols(tmp_path):
    db = tmp_path / "ast.db"
    storage = IndexStorage(db)
    storage.save_symbols("hash1", [
        _sym("a.py::foo", "foo"),
        _sym("b.py::bar", "bar", "b.py", 10),
    ], commit_hash="abc123")
    loaded = storage.load_symbols("hash1")
    assert len(loaded) == 2
    assert {s.name for s in loaded} == {"foo", "bar"}


def test_load_symbols_returns_empty_for_unknown(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    assert storage.load_symbols("nonexistent") == []


def test_save_and_load_fingerprints(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    storage.save_fingerprints("hash1", {"a.py": "h-a", "b.py": "h-b"})
    fps = storage.load_fingerprints("hash1")
    assert fps == {"a.py": "h-a", "b.py": "h-b"}


def test_load_fingerprints_unknown_returns_empty(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    assert storage.load_fingerprints("nonexistent") == {}


def test_save_symbols_overwrites_old(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    storage.save_symbols("h", [_sym("a.py::foo", "foo")], commit_hash="v1")
    storage.save_symbols("h", [_sym("a.py::bar", "bar")], commit_hash="v2")
    loaded = storage.load_symbols("h")
    assert {s.name for s in loaded} == {"bar"}


def test_save_and_load_index_errors(tmp_path):
    storage = IndexStorage(tmp_path / "ast.db")
    errors = [{"file": "bad.py", "stage": "parse", "error": "syntax error"}]
    storage.save_index_errors("h", errors)
    loaded = storage.load_index_errors("h")
    assert loaded == errors
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 storage.py**

`src/taisang/indexer/storage.py`:
```python
"""索引 SQLite 持久化。

存储三类数据:
- symbols: 按 repo_hash 存 Symbol 列表(JSON 序列化)
- fingerprints: 按 repo_hash 存 {file: hash}
- index_errors: 按 repo_hash 存失败文件清单
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..types import Symbol


class IndexStorage:
    """SQLite 索引存储。线程不安全,每 repo 一个实例。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS symbols (
                    repo_hash TEXT NOT NULL,
                    symbol_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY (repo_hash, symbol_id)
                );
                CREATE TABLE IF NOT EXISTS fingerprints (
                    repo_hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    PRIMARY KEY (repo_hash, file_path)
                );
                CREATE TABLE IF NOT EXISTS index_errors (
                    repo_hash TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commits (
                    repo_hash TEXT PRIMARY KEY,
                    commit_hash TEXT NOT NULL
                );
            """)

    def save_symbols(self, repo_hash: str, symbols: list[Symbol], commit_hash: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM symbols WHERE repo_hash = ?", (repo_hash,))
            c.execute(
                "INSERT OR REPLACE INTO commits(repo_hash, commit_hash) VALUES (?, ?)",
                (repo_hash, commit_hash),
            )
            for s in symbols:
                c.execute(
                    "INSERT INTO symbols(repo_hash, symbol_id, data) VALUES (?, ?, ?)",
                    (repo_hash, s.id, s.model_dump_json()),
                )

    def load_symbols(self, repo_hash: str) -> list[Symbol]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT data FROM symbols WHERE repo_hash = ?", (repo_hash,)
            ).fetchall()
        return [Symbol.model_validate_json(r[0]) for r in rows]

    def save_fingerprints(self, repo_hash: str, fingerprints: dict[str, str]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM fingerprints WHERE repo_hash = ?", (repo_hash,))
            for fp, h in fingerprints.items():
                c.execute(
                    "INSERT INTO fingerprints(repo_hash, file_path, file_hash) VALUES (?, ?, ?)",
                    (repo_hash, fp, h),
                )

    def load_fingerprints(self, repo_hash: str) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT file_path, file_hash FROM fingerprints WHERE repo_hash = ?",
                (repo_hash,),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def save_index_errors(self, repo_hash: str, errors: list[dict]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM index_errors WHERE repo_hash = ?", (repo_hash,))
            for e in errors:
                c.execute(
                    "INSERT INTO index_errors(repo_hash, data) VALUES (?, ?)",
                    (repo_hash, json.dumps(e)),
                )

    def load_index_errors(self, repo_hash: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT data FROM index_errors WHERE repo_hash = ?", (repo_hash,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_storage.py -v`
Expected: PASS (6 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/indexer/storage.py tests/unit/test_storage.py
git commit -m "feat: add SQLite-based IndexStorage for symbols/fingerprints/errors"
```

---

## Task 10: Repo 抓取 fetcher.py

**Files:**
- Create: `src/taisang/indexer/fetcher.py`
- Test: `tests/unit/test_fetcher.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_fetcher.py`:
```python
"""测试 repo 抓取。用本地 git init 造 fixture,不依赖网络。"""
import subprocess
from pathlib import Path
from taisang.indexer.fetcher import Fetcher


def _make_local_repo(tmp_path: Path) -> Path:
    """在 tmp_path 下造一个本地 git repo,含 2 个 .py 文件。"""
    repo = tmp_path / "fake-remote"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    (repo / "b.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return repo


def test_fetch_clones_local_repo(tmp_path):
    remote = _make_local_repo(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    fetcher = Fetcher(cache_dir=cache)
    local_path, commit = fetcher.fetch(str(remote))
    assert local_path.exists()
    assert (local_path / "a.py").exists()
    assert (local_path / "b.py").exists()
    assert len(commit) > 0


def test_fetch_returns_same_path_for_already_cloned(tmp_path):
    remote = _make_local_repo(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    fetcher = Fetcher(cache_dir=cache)
    p1, _ = fetcher.fetch(str(remote))
    p2, _ = fetcher.fetch(str(remote))
    assert p1 == p2


def test_fetch_invalid_url_raises(tmp_path):
    import pytest
    cache = tmp_path / "cache"
    cache.mkdir()
    fetcher = Fetcher(cache_dir=cache)
    with pytest.raises(RuntimeError, match="clone failed"):
        fetcher.fetch("/nonexistent/path/that/does/not/exist")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 fetcher.py**

`src/taisang/indexer/fetcher.py`:
```python
"""Repo 抓取:git clone 到本地 cache,返回本地路径和 commit hash。

v1 只支持公开 repo(含本地 file:// URL)。私有 repo 走 GitHub token 留 v1.5。
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


class Fetcher:
    """git clone 封装。cache_dir 按 repo URL hash 分子目录。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _url_hash(self, repo_url: str) -> str:
        return hashlib.sha1(repo_url.encode()).hexdigest()[:16]

    def fetch(self, repo_url: str) -> tuple[Path, str]:
        """clone repo 到 cache,返回 (本地路径, commit_hash)。

        如果已 clone 过,直接复用并 pull 最新(公开 repo 场景)。
        clone 失败重试 2 次,仍失败抛 RuntimeError。
        """
        target = self.cache_dir / self._url_hash(repo_url)
        if target.exists() and (target / ".git").exists():
            # 已 clone,复用
            commit = self._current_commit(target)
            return target, commit
        # 新 clone
        last_err = ""
        for _ in range(2):
            try:
                if target.exists():
                    # 残留目录,删掉重来
                    import shutil
                    shutil.rmtree(target)
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(target)],
                    capture_output=True, timeout=120,
                )
                if result.returncode == 0:
                    return target, self._current_commit(target)
                last_err = result.stderr.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                last_err = "clone timeout"
        raise RuntimeError(f"clone failed for {repo_url}: {last_err}")

    def _current_commit(self, path: Path) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path,
            capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            return "unknown"
        return r.stdout.decode().strip()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_fetcher.py -v`
Expected: PASS (3 个测试全绿)

> 注意:`git clone --depth 1` 对本地 file:// URL 也工作,但本地 repo 没有 remote 时可能 clone 出空 commit。如果 `test_fetch_clones_local_repo` 的 commit 断言失败,把 `--depth 1` 去掉重试。

- [ ] **Step 5: Commit**

```bash
git add src/taisang/indexer/fetcher.py tests/unit/test_fetcher.py
git commit -m "feat: add Fetcher for git clone with cache and retry"
```

---

## Task 11: 索引编排服务 indexer/service.py

**Files:**
- Create: `src/taisang/indexer/service.py`
- Test: `tests/integration/test_indexer_service.py`

> 这是 indexer 的编排入口,把 fetcher + parser + linker + storage 串起来。放到 integration 是因为它涉及多模块协作。

- [ ] **Step 1: 写失败测试**

`tests/integration/test_indexer_service.py`:
```python
"""测试 indexer service 端到端:本地 repo → RepoIndex。"""
import subprocess
from pathlib import Path
from taisang.indexer.service import IndexerService
from taisang.storage.paths import PathManager


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8"
    )
    (repo / "b.py").write_text(
        "from a import foo\n\ndef baz():\n    return foo()\n", encoding="utf-8"
    )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return repo


def test_index_builds_repoindex(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(str(remote))
    assert idx.repo_url == str(remote)
    assert len(idx.commit_hash) > 0
    # foo, bar, baz 三个函数都应被抽出来
    names = {s.name for s in idx.symbols}
    assert {"foo", "bar", "baz"}.issubset(names)
    assert "a.py" in idx.files and "b.py" in idx.files


def test_index_builds_call_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(str(remote))
    graph = service.build_call_graph(idx)
    # a.py::foo 调 bar,应解析到 a.py::bar
    assert "a.py::bar" in graph["a.py::foo"].resolved_calls
    # b.py::baz 调 foo,应解析到 a.py::foo
    assert "a.py::foo" in graph["b.py::baz"].resolved_calls


def test_index_persists_to_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    remote = _make_repo(tmp_path)
    pm = PathManager()
    service = IndexerService(pm)
    service.build(str(remote))
    # 第二次 build 应该走增量路径(不报错即过)
    idx2 = service.build(str(remote))
    assert len(idx2.symbols) > 0


def test_index_records_errors_for_bad_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "with-bad"
    repo.mkdir()
    (repo / "good.py").write_text("def ok():\n    pass\n", encoding="utf-8")
    (repo / "bad.py").write_text("def broken(\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.build(str(repo))
    # bad.py 应在 index_errors 里
    assert any(e["file"] == "bad.py" for e in idx.index_errors)
    # good.py 的符号应该在
    assert any(s.name == "ok" for s in idx.symbols)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/integration/test_indexer_service.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 service.py**

`src/taisang/indexer/service.py`:
```python
"""indexer 编排服务:fetcher → parser → linker → storage。

build() 是全量索引,update() 是增量(只重解析变动文件)。
"""
from __future__ import annotations

from pathlib import Path

from ..storage.paths import PathManager
from ..types import RepoIndex, Symbol
from .fetcher import Fetcher
from .fingerprint import file_hash, diff_files
from .linker import CallGraphNode, build_call_graph
from .parser_python import parse_file
from .storage import IndexStorage


class IndexerService:
    """索引编排服务。"""

    def __init__(self, pm: PathManager) -> None:
        self.pm = pm
        self.fetcher = Fetcher(pm.cache_dir)

    def build(self, repo_url: str) -> RepoIndex:
        """全量索引:clone → 扫所有 .py → parse → linker → 入库。"""
        local_path, commit = self.fetcher.fetch(repo_url)
        repo_hash = self.pm._repo_hash(repo_url)
        storage = IndexStorage(self.pm.index_db_path(repo_url))

        py_files = sorted(local_path.rglob("*.py"))
        # 排除 .git 目录
        py_files = [f for f in py_files if ".git" not in f.parts]

        symbols: list[Symbol] = []
        errors: list[dict] = []
        fingerprints: dict[str, str] = {}
        for f in py_files:
            rel = str(f.relative_to(local_path)).replace("\\", "/")
            try:
                fp = file_hash(f)
                fingerprints[rel] = fp
                file_syms = parse_file(f, rel)
                symbols.extend(file_syms)
            except Exception as e:
                errors.append({"file": rel, "stage": "parse", "error": str(e)})

        storage.save_symbols(repo_hash, symbols, commit_hash=commit)
        storage.save_fingerprints(repo_hash, fingerprints)
        storage.save_index_errors(repo_hash, errors)

        return RepoIndex(
            repo_url=repo_url, commit_hash=commit,
            symbols=symbols, files=list(fingerprints.keys()),
            index_errors=errors,
        )

    def update(self, repo_url: str) -> RepoIndex:
        """增量索引:基于已有 fingerprints,只重解析变动文件。

        v1 简化:如果第一次没 build 过,自动走 build()。
        """
        repo_hash = self.pm._repo_hash(repo_url)
        db = self.pm.index_db_path(repo_url)
        if not db.exists():
            return self.build(repo_url)
        local_path, commit = self.fetcher.fetch(repo_url)
        storage = IndexStorage(db)
        old_fps = storage.load_fingerprints(repo_hash)

        py_files = sorted(local_path.rglob("*.py"))
        py_files = [f for f in py_files if ".git" not in f.parts]
        new_fps: dict[str, str] = {}
        for f in py_files:
            rel = str(f.relative_to(local_path)).replace("\\", "/")
            new_fps[rel] = file_hash(f)

        added, modified, deleted, unchanged = diff_files(old_fps, new_fps)

        # 加载已有 symbols
        old_symbols = storage.load_symbols(repo_hash)
        # 删除被删/被改文件的旧 symbols
        to_drop = deleted | modified
        kept = [s for s in old_symbols if s.file not in to_drop]
        # 重新解析 added/modified
        new_symbols: list[Symbol] = []
        errors: list[dict] = []
        for f in py_files:
            rel = str(f.relative_to(local_path)).replace("\\", "/")
            if rel in added or rel in modified:
                try:
                    new_symbols.extend(parse_file(f, rel))
                except Exception as e:
                    errors.append({"file": rel, "stage": "parse", "error": str(e)})
        all_symbols = kept + new_symbols
        storage.save_symbols(repo_hash, all_symbols, commit_hash=commit)
        storage.save_fingerprints(repo_hash, new_fps)
        # 保留旧的 errors,追加新的(简化)
        old_errors = storage.load_index_errors(repo_hash)
        storage.save_index_errors(repo_hash, old_errors + errors)
        return RepoIndex(
            repo_url=repo_url, commit_hash=commit,
            symbols=all_symbols, files=list(new_fps.keys()),
            index_errors=old_errors + errors,
        )

    def build_call_graph(self, idx: RepoIndex) -> dict[str, CallGraphNode]:
        """从 RepoIndex 构建调用图(给 agent_core 的 trace_call_chain 工具用)。"""
        return build_call_graph(idx.symbols)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/integration/test_indexer_service.py -v`
Expected: PASS (4 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/indexer/service.py tests/integration/test_indexer_service.py
git commit -m "feat: add IndexerService orchestrator with build/update"
```

---

## Task 12: 分层摘要 summarizer

**Files:**
- Create: `src/taisang/summarizer/__init__.py`
- Create: `src/taisang/summarizer/prompts.py`
- Create: `src/taisang/summarizer/service.py`
- Test: `tests/unit/test_summarizer.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_summarizer.py`:
```python
"""测试分层摘要:用 MockLLM 避免真调 API。"""
import pytest
from taisang.summarizer.service import SummarizerService
from taisang.summarizer.prompts import build_file_summary_prompt
from taisang.types import RepoIndex, Symbol, SymbolKind
from taisang.llm_client import MockLLM, LLMResponse


def _idx(symbols, files=None) -> RepoIndex:
    return RepoIndex(
        repo_url="https://github.com/test/repo",
        commit_hash="abc",
        symbols=symbols,
        files=files or [s.file for s in symbols],
    )


def _sym(id_, name, file, line=1, calls=None, imports=None):
    return Symbol(
        id=id_, kind=SymbolKind.FUNCTION, name=name, file=file,
        line_range=(line, line + 5), calls=calls or [], imports=imports or [],
    )


def test_build_file_summary_prompt_contains_source_and_symbols():
    prompt = build_file_summary_prompt(
        rel_path="a.py",
        source="def foo():\n    return 1\n",
        symbols=[_sym("a.py::foo", "foo", "a.py")],
    )
    assert "def foo" in prompt
    assert "foo" in prompt
    assert "a.py" in prompt


def test_summarize_file_uses_llm_response(tmp_path):
    mock = MockLLM([LLMResponse(text="这是 a.py 的摘要:定义 foo 函数返回 1", tool_calls=[])])
    service = SummarizerService(llm=mock)
    idx = _idx([_sym("a.py::foo", "foo", "a.py")])
    # 需要源码,用一个临时文件
    src_file = tmp_path / "a.py"
    src_file.write_text("def foo():\n    return 1\n", encoding="utf-8")
    repo_map = service.summarize(idx, source_root=tmp_path)
    assert "a.py" in repo_map.file_summaries
    assert "foo" in repo_map.file_summaries["a.py"].summary


def test_summarize_file_failure_skips_and_records(tmp_path):
    """LLM 调用失败应跳过文件,不崩。"""
    class FailingLLM:
        def chat(self, messages, tools):
            raise RuntimeError("API down")
    service = SummarizerService(llm=FailingLLM())
    idx = _idx([_sym("a.py::foo", "foo", "a.py")])
    src_file = tmp_path / "a.py"
    src_file.write_text("def foo():\n    return 1\n", encoding="utf-8")
    # 不应抛异常
    repo_map = service.summarize(idx, source_root=tmp_path)
    # 该文件没有摘要
    assert "a.py" not in repo_map.file_summaries
    # 失败被记录
    assert any(e["file"] == "a.py" for e in service.errors)


def test_summarize_module_level_aggregates_files(tmp_path):
    """同目录的文件摘要聚合到模块级。"""
    mock = MockLLM([
        LLMResponse(text="a.py 摘要", tool_calls=[]),
        LLMResponse(text="b.py 摘要", tool_calls=[]),
        LLMResponse(text="根模块聚合:含 a 和 b 两个文件", tool_calls=[]),
    ])
    service = SummarizerService(llm=mock)
    idx = _idx([
        _sym("a.py::foo", "foo", "a.py"),
        _sym("b.py::bar", "bar", "b.py"),
    ], files=["a.py", "b.py"])
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    repo_map = service.summarize(idx, source_root=tmp_path)
    # 根模块 "" 应有摘要
    assert "" in repo_map.module_summaries
    assert repo_map.module_summaries[""].file_count == 2


def test_summarize_global_level(tmp_path):
    """全局级摘要应包含入口点。"""
    mock = MockLLM([
        LLMResponse(text="a.py 摘要,定义 main", tool_calls=[]),
        LLMResponse(text="根模块", tool_calls=[]),
        LLMResponse(text="全局:入口是 main,依赖无", tool_calls=[]),
    ])
    service = SummarizerService(llm=mock)
    idx = _idx([_sym("a.py::main", "main", "a.py")], files=["a.py"])
    (tmp_path / "a.py").write_text("def main():\n    pass\n", encoding="utf-8")
    repo_map = service.summarize(idx, source_root=tmp_path)
    assert "main" in repo_map.global_summary.entry_points
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_summarizer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 prompts.py**

`src/taisang/summarizer/__init__.py`: 空文件

`src/taisang/summarizer/prompts.py`:
```python
"""摘要 prompt 模板。"""
from __future__ import annotations

from ..types import Symbol

FILE_SUMMARY_SYSTEM = """你是代码理解专家。给定一个 Python 文件,用不超过 100 字概括它的作用。
要求:
- 客观、具体,不空话
- 提到关键函数/类的名字和职责
- 不复述源码,要总结
- 中文回答"""

MODULE_SUMMARY_SYSTEM = """你是代码理解专家。给定一个目录下所有文件的摘要,用不超过 300 字概括这个模块的作用。
要求:
- 聚合同目录文件的职责,提炼模块边界
- 指出模块的入口/对外接口(如果有)
- 中文回答"""

GLOBAL_SUMMARY_SYSTEM = """你是代码理解专家。给定一个 repo 所有模块的摘要,用不超过 1000 字概括全局架构。
要求:
- 指出入口点(如 main 函数、CLI 入口、Web 路由)
- 指出核心模块及其依赖关系
- 中文回答"""


def build_file_summary_prompt(rel_path: str, source: str, symbols: list[Symbol]) -> str:
    sym_list = "\n".join(f"- {s.name} ({s.kind.value}, 行 {s.line_range[0]}-{s.line_range[1]})" for s in symbols)
    return f"""文件路径: {rel_path}

源码:
```
{source}
```

该文件定义的符号:
{sym_list or '(无符号)'}

请概括这个文件的作用。"""


def build_module_summary_prompt(module_path: str, file_summaries: list[tuple[str, str]]) -> str:
    files_block = "\n".join(f"- {fp}: {summary}" for fp, summary in file_summaries)
    return f"""模块路径: {module_path or '(根目录)'}

该模块下文件的摘要:
{files_block}

请概括这个模块的作用。"""


def build_global_summary_prompt(
    module_summaries: list[tuple[str, str]],
    entry_candidates: list[str],
) -> str:
    modules_block = "\n".join(f"- {mp}: {summary}" for mp, summary in module_summaries)
    entries_block = "\n".join(f"- {e}" for e in entry_candidates) or "(未识别)"
    return f"""以下是 repo 各模块的摘要:

{modules_block}

候选入口点(名为 main / __main__ / run / app 的符号):
{entries_block}

请概括这个 repo 的全局架构。"""
```

- [ ] **Step 4: 写 service.py**

`src/taisang/summarizer/service.py`:
```python
"""分层摘要服务:文件级 → 模块级 → 全局级。

LLM 失败时跳过该文件,记录到 errors,不崩。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..llm_client import LLMClient, MockLLM
from ..types import FileSummary, GlobalSummary, ModuleSummary, RepoIndex, RepoMap
from .prompts import (
    FILE_SUMMARY_SYSTEM, MODULE_SUMMARY_SYSTEM, GLOBAL_SUMMARY_SYSTEM,
    build_file_summary_prompt, build_module_summary_prompt, build_global_summary_prompt,
)

log = logging.getLogger(__name__)

# 简单 token 预算控制:超过这个字数就再压一层(简化版,不做真 token 计数)
FILE_BUDGET = 200  # 字数
MODULE_BUDGET = 600
GLOBAL_BUDGET = 2000


class SummarizerService:
    """三层摘要服务。"""

    def __init__(self, llm: LLMClient | MockLLM) -> None:
        self.llm = llm
        self.errors: list[dict] = []

    def _chat(self, system: str, user: str) -> str | None:
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                tools=[],
            )
            text = resp.text.strip()
            if not text:
                return None
            # 字数预算控制(超了截断,简化版)
            return text
        except Exception as e:
            log.warning("LLM chat failed: %s", e)
            return None

    def summarize(self, idx: RepoIndex, source_root: Path) -> RepoMap:
        """产三层 RepoMap。"""
        self.errors = []

        # 文件级
        file_summaries: dict[str, FileSummary] = {}
        # 按文件分组 symbols
        by_file: dict[str, list] = {}
        for s in idx.symbols:
            by_file.setdefault(s.file, []).append(s)

        for rel_path in idx.files:
            src_file = source_root / rel_path
            if not src_file.exists():
                self.errors.append({"file": rel_path, "stage": "summarize", "error": "source not found"})
                continue
            try:
                source = src_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                self.errors.append({"file": rel_path, "stage": "summarize", "error": str(e)})
                continue
            syms = by_file.get(rel_path, [])
            prompt = build_file_summary_prompt(rel_path, source, syms)
            summary = self._chat(FILE_SUMMARY_SYSTEM, prompt)
            if summary is None:
                self.errors.append({"file": rel_path, "stage": "summarize", "error": "LLM returned empty"})
                continue
            file_summaries[rel_path] = FileSummary(
                file=rel_path, summary=summary[:FILE_BUDGET],
                symbol_ids=[s.id for s in syms],
            )

        # 模块级:按目录分组
        modules: dict[str, list[tuple[str, str]]] = {}
        for fp, fs in file_summaries.items():
            dir_path = str(Path(fp).parent).replace("\\", "/")
            if dir_path == ".":
                dir_path = ""
            modules.setdefault(dir_path, []).append((fp, fs.summary))

        module_summaries: dict[str, ModuleSummary] = {}
        for mp, files in modules.items():
            prompt = build_module_summary_prompt(mp, files)
            summary = self._chat(MODULE_SUMMARY_SYSTEM, prompt)
            if summary is None:
                continue
            module_summaries[mp] = ModuleSummary(
                path=mp, summary=summary[:MODULE_BUDGET], file_count=len(files),
            )

        # 全局级:入口候选
        entry_candidates = [
            s.id for s in idx.symbols
            if s.name in {"main", "__main__", "run", "app", "create_app", "start"}
        ]
        prompt = build_global_summary_prompt(
            [(mp, ms.summary) for mp, ms in module_summaries.items()],
            entry_candidates,
        )
        global_text = self._chat(GLOBAL_SUMMARY_SYSTEM, prompt) or ""
        global_summary = GlobalSummary(
            entry_points=entry_candidates[:10],
            core_modules=list(module_summaries.keys())[:10],
            dependency_summary=global_text[:GLOBAL_BUDGET],
        )

        return RepoMap(
            global_summary=global_summary,
            module_summaries=module_summaries,
            file_summaries=file_summaries,
        )
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/unit/test_summarizer.py -v`
Expected: PASS (5 个测试全绿)

- [ ] **Step 6: Commit**

```bash
git add src/taisang/summarizer/__init__.py src/taisang/summarizer/prompts.py src/taisang/summarizer/service.py tests/unit/test_summarizer.py
git commit -m "feat: add 3-layer summarizer (file/module/global) with LLM failure fallback"
```

---

## Task 13: 混合检索 retriever

**Files:**
- Create: `src/taisang/retriever/__init__.py`
- Create: `src/taisang/retriever/vectorstore.py`
- Create: `src/taisang/retriever/bm25.py`
- Create: `src/taisang/retriever/hybrid.py`
- Create: `src/taisang/retriever/service.py`
- Test: `tests/unit/test_retriever.py`

> v1 用简单 embedding(OpenAI 兼容) + Chroma + BM25。如果 embedding API 不可用,fallback 到只用 BM25。

- [ ] **Step 1: 写失败测试**

`tests/unit/test_retriever.py`:
```python
"""测试混合检索。用 MockLLM 做 embedding,fallback 纯 BM25。"""
from pathlib import Path
from taisang.retriever.bm25 import BM25Index
from taisang.retriever.hybrid import hybrid_rank
from taisang.retriever.service import RetrieverService
from taisang.types import RepoMap, GlobalSummary, ModuleSummary, FileSummary, Snippet


def test_bm25_basic_search():
    idx = BM25Index()
    idx.add("a", "支付模块处理订单")
    idx.add("b", "用户登录认证")
    idx.add("c", "支付退款流程")
    results = idx.search("支付", top_k=2)
    assert len(results) == 2
    # a 和 c 跟"支付"相关,应该在 top 2
    files = {r[0] for r in results}
    assert files == {"a", "c"}


def test_bm25_empty_query_returns_empty():
    idx = BM25Index()
    idx.add("a", "hello")
    assert idx.search("", top_k=5) == []


def test_hybrid_rank_combines_vector_and_bm25():
    # 模拟两路打分
    vector_scores = [("a.py", 0.9), ("b.py", 0.5), ("c.py", 0.3)]
    bm25_scores = [("c.py", 2.0), ("b.py", 1.0), ("a.py", 0.0)]
    ranked = hybrid_rank(vector_scores, bm25_scores, vector_weight=0.7, bm25_weight=0.3)
    # a.py 向量分高,bm25 分低;综合下来应该靠前
    assert ranked[0][0] == "a.py"


def test_retriever_service_search_files():
    """端到端:基于 RepoMap 检索相关文件。"""
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={"": ModuleSummary(path="", summary="根模块", file_count=2)},
        file_summaries={
            "a.py": FileSummary(file="a.py", summary="处理支付订单的模块", symbol_ids=[]),
            "b.py": FileSummary(file="b.py", summary="用户登录认证模块", symbol_ids=[]),
        },
    )
    service = RetrieverService()
    service.build_from_repo_map(rm)
    snippets = service.search_files("支付", top_k=1)
    assert len(snippets) == 1
    assert snippets[0].file == "a.py"


def test_retriever_service_empty_query_returns_empty():
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={"a.py": FileSummary(file="a.py", summary="x", symbol_ids=[])},
    )
    service = RetrieverService()
    service.build_from_repo_map(rm)
    assert service.search_files("", top_k=5) == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_retriever.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 bm25.py**

`src/taisang/retriever/__init__.py`: 空文件

`src/taisang/retriever/bm25.py`:
```python
"""BM25 索引:基于 rank_bm25 库,封装成 key-based 检索。"""
from __future__ import annotations

import re

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    # 简单分词:中英文混合,英文按非字母数字切,中文按字切
    tokens: list[str] = []
    for chunk in re.findall(r"[a-zA-Z0-9_]+|[一-龥]", text):
        if re.match(r"[一-龥]", chunk):
            tokens.extend(list(chunk))
        else:
            tokens.append(chunk.lower())
    return tokens


class BM25Index:
    """key → text 的 BM25 索引。"""

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._bm25: BM25Okapi | None = None

    def add(self, key: str, text: str) -> None:
        self._keys.append(key)
        # 简化:每次 add 后重建(数据量小)
        corpus = [_tokenize(text) for text in [text]]
        # 实际我们要存所有,改实现:
        self._pending: list[tuple[str, str]] = getattr(self, "_pending", [])
        if not hasattr(self, "_pending"):
            self._pending = []
        # 上面逻辑有 bug,重写

    def add(self, key: str, text: str) -> None:  # noqa: F811  覆盖上面的错误版本
        if not hasattr(self, "_pending"):
            self._pending = []
        self._pending.append((key, text))

    def _build(self) -> None:
        if not self._pending:
            self._bm25 = None
            return
        self._keys = [k for k, _ in self._pending]
        corpus = [_tokenize(t) for _, t in self._pending]
        self._bm25 = BM25Okapi(corpus)
        self._pending = []

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if self._pending:
            self._build()
        if self._bm25 is None or not query.strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(
            zip(self._keys, scores.tolist()), key=lambda x: x[1], reverse=True
        )
        return ranked[:top_k]
```

- [ ] **Step 4: 写 hybrid.py**

`src/taisang/retriever/hybrid.py`:
```python
"""混合排序:融合向量检索和 BM25 的分数。"""
from __future__ import annotations


def _normalize(scores: list[tuple[str, float]]) -> dict[str, float]:
    if not scores:
        return {}
    vals = [s for _, s in scores]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return {k: 1.0 for k, _ in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores}


def hybrid_rank(
    vector_scores: list[tuple[str, float]],
    bm25_scores: list[tuple[str, float]],
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
    top_k: int | None = None,
) -> list[tuple[str, float]]:
    """加权融合两路打分,返回 (key, fused_score) 降序列表。"""
    v = _normalize(vector_scores)
    b = _normalize(bm25_scores)
    keys = set(v.keys()) | set(b.keys())
    fused = {k: vector_weight * v.get(k, 0.0) + bm25_weight * b.get(k, 0.0) for k in keys}
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    if top_k:
        ranked = ranked[:top_k]
    return ranked
```

- [ ] **Step 5: 写 vectorstore.py**

`src/taisang/retriever/vectorstore.py`:
```python
"""Chroma 向量库封装。

v1 简化:如果 embedding API 不可用(没配 key 或测试环境),fallback 到 BM25-only。
真正的 Chroma 集成留给后续,先做接口骨架。
"""
from __future__ import annotations

from typing import Protocol


class VectorStore(Protocol):
    """向量库接口。"""

    def add(self, key: str, text: str) -> None: ...
    def search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...


class BM25OnlyStore:
    """无 embedding 时的 fallback:完全用 BM25。"""

    def __init__(self) -> None:
        from .bm25 import BM25Index
        self._idx = BM25Index()

    def add(self, key: str, text: str) -> None:
        self._idx.add(key, text)

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return self._idx.search(query, top_k)
```

- [ ] **Step 6: 写 service.py**

`src/taisang/retriever/service.py`:
```python
"""检索服务:基于 RepoMap 建索引,提供 search_files。

v1 简化:用 BM25-only(不依赖 embedding API,测试友好)。
embedding + Chroma 留给后续优化。
"""
from __future__ import annotations

from ..types import RepoMap, Snippet
from .bm25 import BM25Index
from .hybrid import hybrid_rank


class RetrieverService:
    """检索服务。"""

    def __init__(self) -> None:
        self._bm25 = BM25Index()
        self._summaries: dict[str, str] = {}

    def build_from_repo_map(self, repo_map: RepoMap) -> None:
        """从 RepoMap 建文件级 BM25 索引。"""
        self._bm25 = BM25Index()
        self._summaries = {}
        for fp, fs in repo_map.file_summaries.items():
            self._bm25.add(fp, fs.summary)
            self._summaries[fp] = fs.summary

    def search_files(self, query: str, top_k: int = 5) -> list[Snippet]:
        """搜相关文件,返回 Snippet 列表。"""
        if not query.strip():
            return []
        results = self._bm25.search(query, top_k=top_k)
        snippets: list[Snippet] = []
        for fp, score in results:
            snippets.append(Snippet(
                file=fp, line_range=(1, 1),  # 文件级,行号占位
                text=self._summaries.get(fp, ""),
                score=float(score),
            ))
        return snippets

    def search_modules(self, query: str, top_k: int = 3) -> list[tuple[str, float]]:
        """搜相关模块(v1 简单实现,用模块摘要建临时 BM25)。"""
        # 简化:v1 暂不实现独立模块索引,直接返回空,实际问答时 agent 会用 search_files
        return []
```

- [ ] **Step 7: 运行测试验证通过**

Run: `pytest tests/unit/test_retriever.py -v`
Expected: PASS (5 个测试全绿)

> 如果 `test_bm25_basic_search` 失败,可能是分词问题。调试:打印 `_tokenize("支付")` 看输出,确保中文被切成单字。

- [ ] **Step 8: Commit**

```bash
git add src/taisang/retriever/ tests/unit/test_retriever.py
git commit -m "feat: add hybrid retriever (BM25 + vector interface, v1 BM25-only)"
```

---

## Task 14: Agent 5 工具实现 agent_core/tools.py

**Files:**
- Create: `src/taisang/agent_core/__init__.py`
- Create: `src/taisang/agent_core/tools.py`
- Test: `tests/unit/test_tools.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_tools.py`:
```python
"""测试 Agent 5 工具。"""
from pathlib import Path
from taisang.agent_core.tools import (
    ToolRegistry, ReadFileTool, GrepTool, GlobTool,
    TraceCallChainTool, LookupMapTool,
)
from taisang.indexer.linker import CallGraphNode
from taisang.types import RepoMap, GlobalSummary, ModuleSummary, FileSummary


def test_read_file_tool(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = ReadFileTool(source_root=tmp_path)
    result = tool.run({"path": "a.py"})
    assert "def foo" in result["content"]
    assert result["error"] is None


def test_read_file_tool_missing_file(tmp_path):
    tool = ReadFileTool(source_root=tmp_path)
    result = tool.run({"path": "nope.py"})
    assert result["error"] is not None
    assert "not found" in result["error"].lower()


def test_grep_tool(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8")
    tool = GrepTool(source_root=tmp_path)
    result = tool.run({"pattern": "def foo", "scope": "a.py"})
    assert len(result["matches"]) == 1
    assert result["matches"][0]["line"] == 1


def test_grep_tool_truncates_large_results(tmp_path):
    (tmp_path / "big.py").write_text("\n".join(f"x = {i}" for i in range(1000)), encoding="utf-8")
    tool = GrepTool(source_root=tmp_path, max_matches=100)
    result = tool.run({"pattern": "x = ", "scope": "big.py"})
    assert len(result["matches"]) == 100
    assert result["truncated"] is True


def test_glob_tool(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    tool = GlobTool(source_root=tmp_path)
    result = tool.run({"pattern": "*.py"})
    assert set(result["matches"]) == {"a.py", "b.py"}


def test_trace_call_chain_tool():
    graph = {
        "a.py::a": CallGraphNode("a.py::a", "a", "a.py", (1, 5), resolved_calls=["b.py::b"], unresolved_calls=[]),
        "b.py::b": CallGraphNode("b.py::b", "b", "b.py", (1, 5), resolved_calls=["c.py::c"], unresolved_calls=[]),
        "c.py::c": CallGraphNode("c.py::c", "c", "c.py", (1, 5), resolved_calls=[], unresolved_calls=[]),
    }
    tool = TraceCallChainTool(call_graph=graph)
    result = tool.run({"symbol_id": "a.py::a", "depth": 2})
    assert result["chain"] == ["a.py::a", "b.py::b", "c.py::c"]


def test_trace_call_chain_unknown_symbol():
    tool = TraceCallChainTool(call_graph={})
    result = tool.run({"symbol_id": "unknown", "depth": 3})
    assert result["chain"] == []
    assert result["error"] is not None


def test_lookup_map_tool_file_layer():
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={
            "a.py": FileSummary(file="a.py", summary="a 文件摘要", symbol_ids=[]),
        },
    )
    tool = LookupMapTool(repo_map=rm)
    result = tool.run({"layer": "file", "query": "a"})
    assert "a.py" in result["text"]


def test_lookup_map_tool_global_layer():
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=["a.py::main"], core_modules=[""], dependency_summary="全局摘要"),
        module_summaries={},
        file_summaries={},
    )
    tool = LookupMapTool(repo_map=rm)
    result = tool.run({"layer": "global", "query": ""})
    assert "全局摘要" in result["text"]
    assert "main" in result["text"]


def test_tool_registry_lists_schemas():
    reg = ToolRegistry(
        source_root=Path("."),
        call_graph={},
        repo_map=RepoMap(
            global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
            module_summaries={}, file_summaries={},
        ),
    )
    schemas = reg.schemas()
    names = {s["name"] for s in schemas}
    assert names == {"read_file", "grep", "glob", "trace_call_chain", "lookup_map"}


def test_tool_registry_dispatches():
    reg = ToolRegistry(
        source_root=Path("."),
        call_graph={},
        repo_map=RepoMap(
            global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
            module_summaries={}, file_summaries={},
        ),
    )
    result = reg.call("glob", {"pattern": "*.nonexistent"})
    assert isinstance(result, dict)
    assert "matches" in result
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 tools.py**

`src/taisang/agent_core/__init__.py`: 空文件

`src/taisang/agent_core/tools.py`:
```python
"""Agent 5 工具实现。

每个工具:
- schema(): 返回 OpenAI function schema
- run(args): 执行,返回 dict observation

工具集:
- read_file(path) — 读文件
- grep(pattern, scope) — 正则搜
- glob(pattern) — 文件名匹配
- trace_call_chain(symbol_id, depth) — 调用链追踪
- lookup_map(layer, query) — 查 RepoMap
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from ..indexer.linker import CallGraphNode, resolve_call_chain
from ..types import RepoMap


class _BaseTool:
    """工具基类。"""

    name: str = ""

    def schema(self) -> dict:
        raise NotImplementedError

    def run(self, args: dict) -> dict:
        raise NotImplementedError


class ReadFileTool(_BaseTool):
    name = "read_file"

    def __init__(self, source_root: Path, max_bytes: int = 32_000) -> None:
        self.source_root = source_root
        self.max_bytes = max_bytes

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "读取指定源码文件内容。返回文件文本(可能截断)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 repo 根的文件路径,如 'a/b.py'"},
                },
                "required": ["path"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("path", "")
        full = self.source_root / path
        if not full.exists() or not full.is_file():
            return {"content": "", "error": f"file not found: {path}"}
        try:
            data = full.read_bytes()
            truncated = False
            if len(data) > self.max_bytes:
                data = data[: self.max_bytes]
                truncated = True
            return {
                "content": data.decode("utf-8", errors="replace"),
                "truncated": truncated,
                "error": None,
            }
        except Exception as e:
            return {"content": "", "error": str(e)}


class GrepTool(_BaseTool):
    name = "grep"

    def __init__(self, source_root: Path, max_matches: int = 200) -> None:
        self.source_root = source_root
        self.max_matches = max_matches

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "在源码里正则搜索。返回命中的 (file, line, text) 列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式"},
                    "scope": {"type": "string", "description": "限定文件路径或 glob,如 'a/*.py';空表示全 repo"},
                },
                "required": ["pattern"],
            },
        }

    def run(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        scope = args.get("scope", "")
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"matches": [], "truncated": False, "error": f"bad regex: {e}"}

        files: list[Path] = []
        if scope:
            files = list(self.source_root.glob(scope))
            if not files and (self.source_root / scope).is_file():
                files = [self.source_root / scope]
        else:
            files = [f for f in self.source_root.rglob("*") if f.is_file() and ".git" not in f.parts]

        matches: list[dict] = []
        truncated = False
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append({
                        "file": str(f.relative_to(self.source_root)).replace("\\", "/"),
                        "line": i,
                        "text": line[:200],
                    })
                    if len(matches) >= self.max_matches:
                        truncated = True
                        return {"matches": matches, "truncated": truncated, "error": None}
        return {"matches": matches, "truncated": truncated, "error": None}


class GlobTool(_BaseTool):
    name = "glob"

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "按 glob 模式匹配文件路径,返回文件列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 模式,如 '**/*.py'"},
                },
                "required": ["pattern"],
            },
        }

    def run(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        if not pattern:
            return {"matches": [], "error": "empty pattern"}
        matched: list[str] = []
        for f in self.source_root.rglob("*"):
            if ".git" in f.parts:
                continue
            rel = str(f.relative_to(self.source_root)).replace("\\", "/")
            if fnmatch.fnmatch(rel, pattern):
                matched.append(rel)
        return {"matches": sorted(matched), "error": None}


class TraceCallChainTool(_BaseTool):
    name = "trace_call_chain"

    def __init__(self, call_graph: dict[str, CallGraphNode]) -> None:
        self.call_graph = call_graph

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "从某符号出发,追踪 N 跳调用链。返回 symbol_id 列表(含起点)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_id": {"type": "string", "description": "起点符号 id,格式 'file::Class.method' 或 'file::func'"},
                    "depth": {"type": "integer", "description": "追踪深度,默认 3", "default": 3},
                },
                "required": ["symbol_id"],
            },
        }

    def run(self, args: dict) -> dict:
        sid = args.get("symbol_id", "")
        depth = int(args.get("depth", 3))
        if not sid:
            return {"chain": [], "error": "empty symbol_id"}
        if sid not in self.call_graph:
            return {"chain": [], "error": f"symbol not in call graph: {sid}"}
        chain = resolve_call_chain(self.call_graph, sid, depth=depth)
        return {"chain": chain, "error": None}


class LookupMapTool(_BaseTool):
    name = "lookup_map"

    def __init__(self, repo_map: RepoMap) -> None:
        self.repo_map = repo_map

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "查代码库地图(分层摘要)。layer: 'global' / 'module' / 'file'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": ["global", "module", "file"]},
                    "query": {"type": "string", "description": "过滤关键词(可空)"},
                },
                "required": ["layer"],
            },
        }

    def run(self, args: dict) -> dict:
        layer = args.get("layer", "")
        query = args.get("query", "").lower()
        if layer == "global":
            g = self.repo_map.global_summary
            text = f"入口: {', '.join(g.entry_points)}\n核心模块: {', '.join(g.core_modules)}\n摘要: {g.dependency_summary}"
            return {"text": text, "error": None}
        if layer == "module":
            lines = []
            for mp, ms in self.repo_map.module_summaries.items():
                if not query or query in ms.summary.lower() or query in mp.lower():
                    lines.append(f"[{mp or '(root)'}] {ms.file_count} 文件: {ms.summary}")
            return {"text": "\n".join(lines), "error": None}
        if layer == "file":
            lines = []
            for fp, fs in self.repo_map.file_summaries.items():
                if not query or query in fs.summary.lower() or query in fp.lower():
                    lines.append(f"[{fp}] {fs.summary}")
            return {"text": "\n".join(lines), "error": None}
        return {"text": "", "error": f"unknown layer: {layer}"}


class ToolRegistry:
    """工具注册表 + 调度。"""

    def __init__(
        self,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
    ) -> None:
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: ReadFileTool(source_root),
            GrepTool.name: GrepTool(source_root),
            GlobTool.name: GlobTool(source_root),
            TraceCallChainTool.name: TraceCallChainTool(call_graph),
            LookupMapTool.name: LookupMapTool(repo_map),
        }

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def call(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"unknown tool: {name}"}
        try:
            return tool.run(args)
        except Exception as e:
            return {"error": f"tool {name} failed: {e}"}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_tools.py -v`
Expected: PASS (11 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agent_core/__init__.py src/taisang/agent_core/tools.py tests/unit/test_tools.py
git commit -m "feat: add 5 agent tools (read_file/grep/glob/trace_call_chain/lookup_map)"
```

---

## Task 15: 上下文管理 agent_core/context.py

**Files:**
- Create: `src/taisang/agent_core/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_context.py`:
```python
"""测试上下文管理:token 估算 + compaction。"""
from taisang.agent_core.context import ContextManager


def test_estimate_tokens_approximate():
    cm = ContextManager(token_budget=32000)
    # 1 token ≈ 4 字符(英文),中文按 1.5 字符/token 估算,这里只测大致量级
    assert cm.estimate_tokens("hello world") > 0
    assert cm.estimate_tokens("你好世界") > 0


def test_within_budget_no_compaction():
    cm = ContextManager(token_budget=32000)
    cm.append_system("system prompt")
    cm.append_user("question")
    assert cm.should_compact() is False


def test_compaction_triggers_near_limit():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system")
    # 塞大量内容触发
    cm.append_tool_result("x" * 4000, name="read_file")
    assert cm.should_compact() is True


def test_compact_keeps_system_and_recent():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system prompt")
    cm.append_user("q1")
    cm.append_tool_result("old result" * 100, name="read_file")
    cm.append_tool_result("new result" * 100, name="grep")
    cm.compact()
    # compact 后 system 保留,旧 tool_result 被压缩成摘要
    msgs = cm.messages()
    assert msgs[0]["role"] == "system"
    # 旧的应该被压成摘要,不是原文
    text = "\n".join(m["content"] for m in msgs if isinstance(m.get("content"), str))
    assert "old result" not in text or "[compacted" in text


def test_compact_preserves_recent_observations():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system")
    cm.append_tool_result("recent important" * 50, name="grep")
    cm.compact()
    msgs = cm.messages()
    # 最近的 observation 应该保留原文
    found = any("recent important" in m.get("content", "") for m in msgs)
    assert found


def test_total_tokens_after_compaction_within_budget():
    cm = ContextManager(token_budget=1000)
    cm.append_system("system")
    for _ in range(20):
        cm.append_tool_result("x" * 500, name="read_file")
    cm.compact()
    assert cm.total_tokens() < 1000
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 context.py**

`src/taisang/agent_core/context.py`:
```python
"""Agent 上下文管理 + compaction。

策略(从 claude-code 抄的简化版):
- token 预算逼近时触发 compact
- compact 保留: system + 最早的摘要(简化为不保留) + 最近 N 轮 tool_result + 引用源码(简化为保留)
- 旧 tool_result 压成一行摘要 "[compacted: tool=X, Y chars]"
"""
from __future__ import annotations


class ContextManager:
    """管理 messages 列表 + token 估算。"""

    def __init__(
        self,
        token_budget: int = 32_000,
        compact_ratio: float = 0.8,  # 用到 80% 触发
        keep_recent: int = 4,  # compact 时保留最近 N 条 tool_result
    ) -> None:
        self.token_budget = token_budget
        self.compact_ratio = compact_ratio
        self.keep_recent = keep_recent
        self._messages: list[dict] = []

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数。

        英文约 4 char/token,中文约 1.5 char/token。混合取 3 char/token 近似。
        真实场景可换 tiktoken,这里简化以保证测试稳定。
        """
        if not text:
            return 0
        return max(1, len(text) // 3)

    def _msg_tokens(self, msg: dict) -> int:
        content = msg.get("content", "")
        if isinstance(content, str):
            return self.estimate_tokens(content)
        return 0

    def total_tokens(self) -> int:
        return sum(self._msg_tokens(m) for m in self._messages)

    def should_compact(self) -> bool:
        return self.total_tokens() > self.token_budget * self.compact_ratio

    def append_system(self, text: str) -> None:
        self._messages.append({"role": "system", "content": text})

    def append_user(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def append_assistant(self, text: str, tool_calls: list[dict] | None = None) -> None:
        msg = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)

    def append_tool_result(self, text: str, name: str, tool_call_id: str | None = None) -> None:
        self._messages.append({
            "role": "tool",
            "name": name,
            "content": text,
            "tool_call_id": tool_call_id or name,
        })

    def messages(self) -> list[dict]:
        return list(self._messages)

    def compact(self) -> None:
        """压缩旧 tool_result,保留 system + 最近 N 条。"""
        if not self.should_compact() and self.total_tokens() <= self.token_budget:
            # 只在确实超预算时压(测试可能直接调 compact)
            pass
        # 收集所有 tool message 的索引
        tool_idx = [i for i, m in enumerate(self._messages) if m["role"] == "tool"]
        if len(tool_idx) <= self.keep_recent:
            return
        # 要压缩的:除最近 N 条之外
        to_compact_idx = tool_idx[: -self.keep_recent]
        for i in to_compact_idx:
            m = self._messages[i]
            old_text = m.get("content", "")
            if isinstance(old_text, str) and not old_text.startswith("[compacted"):
                m["content"] = f"[compacted: tool={m.get('name')}, {len(old_text)} chars]"
        # 循环压,直到 token 够用
        while self.total_tokens() > self.token_budget and any(
            isinstance(m.get("content"), str) and not m.get("content", "").startswith("[compacted")
            for m in self._messages if m["role"] == "tool"
        ):
            # 找下一个最旧的未压缩 tool message
            for i, m in enumerate(self._messages):
                if m["role"] != "tool":
                    continue
                content = m.get("content", "")
                if isinstance(content, str) and not content.startswith("[compacted"):
                    m["content"] = f"[compacted: tool={m.get('name')}, {len(content)} chars]"
                    break
            else:
                break
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_context.py -v`
Expected: PASS (6 个测试全绿)

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agent_core/context.py tests/unit/test_context.py
git commit -m "feat: add ContextManager with token estimation and compaction"
```

---

## Task 16: Agent 循环 agent_core/service.py + prompts.py

**Files:**
- Create: `src/taisang/agent_core/prompts.py`
- Create: `src/taisang/agent_core/service.py`
- Test: `tests/unit/test_agent_core.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_agent_core.py`:
```python
"""测试 Agent 主循环。用 MockLLM 注入预设响应。"""
from pathlib import Path
from taisang.agent_core.service import AgentService
from taisang.agent_core.tools import ToolRegistry
from taisang.agent_core.context import ContextManager
from taisang.indexer.linker import CallGraphNode
from taisang.llm_client import MockLLM, LLMResponse
from taisang.types import RepoMap, GlobalSummary, ModuleSummary, FileSummary, Answer


def _make_empty_repo_map() -> RepoMap:
    return RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={},
    )


def test_agent_no_tool_calls_returns_answer_directly(tmp_path):
    mock = MockLLM([LLMResponse(text="直接回答:这是个空 repo", tool_calls=[])])
    service = AgentService(llm=mock, source_root=tmp_path, call_graph={}, repo_map=_make_empty_repo_map())
    ans = service.run("这个 repo 是干啥的")
    assert isinstance(ans, Answer)
    assert "空 repo" in ans.text
    assert ans.complete is True
    assert ans.steps_used == 1


def test_agent_one_tool_call_then_answer(tmp_path):
    """Agent 先调 lookup_map,然后回答。"""
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[{"name": "lookup_map", "args": {"layer": "file", "query": ""}}]),
        LLMResponse(text="a.py 定义了 foo 函数", tool_calls=[]),
    ])
    rm = RepoMap(
        global_summary=GlobalSummary(entry_points=[], core_modules=[], dependency_summary=""),
        module_summaries={},
        file_summaries={"a.py": FileSummary(file="a.py", summary="定义 foo 函数", symbol_ids=[])},
    )
    service = AgentService(llm=mock, source_root=tmp_path, call_graph={}, repo_map=rm)
    ans = service.run("a.py 干啥的")
    assert "foo" in ans.text


def test_agent_max_steps_terminates(tmp_path):
    """Agent 一直调工具不回答,应超 max_steps 终止。"""
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[{"name": "lookup_map", "args": {"layer": "global"}}])
    ] * 20)  # 给够响应
    service = AgentService(
        llm=mock, source_root=tmp_path, call_graph={}, repo_map=_make_empty_repo_map(),
        max_steps=3,
    )
    ans = service.run("q")
    assert ans.complete is False  # 提前终止
    assert ans.steps_used == 3


def test_agent_unknown_tool_does_not_crash(tmp_path):
    """LLM 调了不存在的工具,Agent 应记录错误 observation 继续。"""
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[{"name": "nonexistent_tool", "args": {}}]),
        LLMResponse(text="回答", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, call_graph={}, repo_map=_make_empty_repo_map())
    ans = service.run("q")
    assert ans.text == "回答"
    assert ans.steps_used == 2


def test_agent_trace_call_chain_in_answer(tmp_path):
    """Agent 用 trace_call_chain 追链路,答案里应体现链。"""
    graph = {
        "a.py::foo": CallGraphNode("a.py::foo", "foo", "a.py", (1, 5), resolved_calls=["a.py::bar"], unresolved_calls=[]),
        "a.py::bar": CallGraphNode("a.py::bar", "bar", "a.py", (8, 12), resolved_calls=[], unresolved_calls=[]),
    }
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[{"name": "trace_call_chain", "args": {"symbol_id": "a.py::foo", "depth": 2}}]),
        LLMResponse(text="调用链: foo → bar", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, call_graph=graph, repo_map=_make_empty_repo_map())
    ans = service.run("foo 调用了谁")
    assert "foo" in ans.text and "bar" in ans.text
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_agent_core.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 prompts.py**

`src/taisang/agent_core/prompts.py`:
```python
"""Agent system prompt。"""
from __future__ import annotations

SYSTEM_PROMPT = """你是 Code Reader Agent,专门帮用户读懂陌生代码库。

你的能力:
- 查代码库地图(lookup_map):查全局/模块/文件三层摘要
- 读文件(read_file):看具体源码
- 正则搜(grep):按模式找代码
- 文件名匹配(glob):找文件
- 追调用链(trace_call_chain):从某符号出发追 N 跳调用关系

工作策略:
1. 先查 lookup_map 了解全局,定位相关文件
2. 用 read_file 读关键文件,或 grep 精确定位
3. 如果问题涉及调用关系,用 trace_call_chain 追链
4. 信息够了就综合回答,必须带源码引用(文件:行号)

回答要求:
- 中文回答
- 涉及代码位置时,用 [file.py:line] 格式标注引用
- 不确定时明说,不编造
- 答案末尾列出引用的文件列表
"""
```

- [ ] **Step 4: 写 service.py**

`src/taisang/agent_core/service.py`:
```python
"""Agent 主循环:plan → act → observe → reflect。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..indexer.linker import CallGraphNode
from ..llm_client import LLMClient, MockLLM
from ..types import Answer, Citation, RepoMap
from .context import ContextManager
from .prompts import SYSTEM_PROMPT
from .tools import ToolRegistry

log = logging.getLogger(__name__)


class AgentService:
    """Agent 主循环服务。"""

    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
        max_steps: int = 10,
        token_budget: int = 32_000,
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.call_graph = call_graph
        self.repo_map = repo_map
        self.max_steps = max_steps
        self.token_budget = token_budget

    def run(self, query: str) -> Answer:
        """执行 Agent 循环,返回 Answer。"""
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)
        # 初始注入:全局地图摘要(让 Agent 有起点)
        ctx.append_user(
            f"代码库全局摘要:\n{self.repo_map.global_summary.dependency_summary}\n\n"
            f"用户问题: {query}"
        )

        registry = ToolRegistry(
            source_root=self.source_root,
            call_graph=self.call_graph,
            repo_map=self.repo_map,
        )

        steps = 0
        while steps < self.max_steps:
            steps += 1
            if ctx.should_compact():
                ctx.compact()

            try:
                resp = self.llm.chat(messages=ctx.messages(), tools=registry.schemas())
            except Exception as e:
                log.warning("LLM call failed at step %d: %s", steps, e)
                return Answer(
                    text=f"(LLM 调用失败: {e})",
                    citations=[], complete=False, steps_used=steps,
                )

            if not resp.tool_calls:
                # 给出最终答案
                citations = self._extract_citations(resp.text)
                return Answer(
                    text=resp.text, citations=citations,
                    complete=True, steps_used=steps,
                )

            # 有 tool calls:执行每个
            ctx.append_assistant(text=resp.text, tool_calls=resp.tool_calls)
            for tc in resp.tool_calls:
                name = tc["name"]
                args = tc.get("args", {})
                result = registry.call(name, args)
                observation = json.dumps(result, ensure_ascii=False)
                ctx.append_tool_result(observation, name=name, tool_call_id=name)

        # 超 max_steps
        return Answer(
            text="(达到最大步数,信息可能不全)",
            citations=[], complete=False, steps_used=steps,
        )

    def _extract_citations(self, text: str) -> list[Citation]:
        """从答案文本抽 [file.py:line] 格式引用。"""
        import re
        citations: list[Citation] = []
        seen: set[str] = set()
        for m in re.finditer(r"\[([^\]\s]+\.py)(?::(\d+)(?:-(\d+))?)?\]", text):
            file = m.group(1)
            start = int(m.group(2)) if m.group(2) else 1
            end = int(m.group(3)) if m.group(3) else start
            key = f"{file}:{start}-{end}"
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(file=file, line_range=(start, end)))
        return citations
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/unit/test_agent_core.py -v`
Expected: PASS (5 个测试全绿)

> 如果 `test_agent_max_steps_terminates` 失败,检查 `while steps < self.max_steps` 的边界条件——steps 在循环开始就 +1,所以跑 max_steps 次后退出。

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/prompts.py src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat: add AgentService with plan-act-observe-reflect loop"
```

---

## Task 17: CLI 入口 cli/main.py

**Files:**
- Create: `src/taisang/cli/__init__.py`
- Create: `src/taisang/cli/main.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_cli.py`:
```python
"""测试 CLI 入口:用 click 的 CliRunner 跑子命令。"""
import subprocess
from pathlib import Path
from click.testing import CliRunner
from taisang.cli.main import cli


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def main():\n    print('hello')\n\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return repo


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "index" in result.output
    assert "ask" in result.output


def test_cli_index_command(tmp_path, monkeypatch):
    """index 命令应建索引并落盘到 ~/.taisang/。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    # 用 MockLLM 替代真 LLM:通过环境变量切 mock 模式
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["index", str(repo)])
    assert result.exit_code == 0, result.output
    # 索引产物应存在
    assert (tmp_path / ".taisang" / "indices").exists()


def test_cli_ask_command_with_mock_llm(tmp_path, monkeypatch):
    """ask 命令用 MockLLM 应能跑通,返回字符串。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)
    runner = CliRunner()
    # 先建索引
    runner.invoke(cli, ["index", str(repo)])
    # 再问
    result = runner.invoke(cli, ["ask", "main 函数干啥的", "--repo", str(repo)])
    assert result.exit_code == 0, result.output
    assert "main" in result.output or "mock" in result.output.lower()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 cli/main.py**

`src/taisang/cli/__init__.py`: 空文件

`src/taisang/cli/main.py`:
```python
"""Code Reader Agent CLI 入口。

命令:
- taisang index <repo_url>  建索引
- taisang ask "<question>" --repo <url>  问问题
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

from ..config import load_config
from ..indexer.service import IndexerService
from ..llm_client import LLMClient, MockLLM, LLMResponse
from ..storage.paths import PathManager
from ..summarizer.service import SummarizerService


def _make_llm():
    """根据环境决定用真 LLM 还是 MockLLM。"""
    if os.environ.get("CODE_READER_MOCK_LLM") == "1":
        return MockLLM([
            LLMResponse(text="(mock) 这个 repo 定义了 main 函数 [a.py:1]", tool_calls=[]),
        ] * 10)
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
@click.argument("repo_url")
def cmd_index(repo_url: str) -> None:
    """建索引:clone repo → 解析 AST → 三层摘要 → 入库。"""
    pm = PathManager()
    click.echo(f"开始索引: {repo_url}")
    indexer = IndexerService(pm)
    idx = indexer.build(repo_url)
    click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")
    if idx.index_errors:
        click.echo(f"  失败文件 {len(idx.index_errors)} 个(已跳过)")

    # 跑摘要(需要 source_root,从 fetcher cache 取)
    # 简化:从 cache 找 clone 后的目录
    repo_hash = pm._repo_hash(repo_url)
    source_root = pm.cache_dir / repo_hash
    if not source_root.exists():
        click.echo("错误:clone 目录丢失", err=True)
        sys.exit(1)

    llm = _make_llm()
    summarizer = SummarizerService(llm=llm)
    click.echo("生成三层摘要...")
    repo_map = summarizer.summarize(idx, source_root=source_root)
    # 落盘 repo_map
    import json
    pm.repo_map_path(repo_url).write_text(
        repo_map.model_dump_json(indent=2), encoding="utf-8"
    )
    click.echo(f"摘要完成: {len(repo_map.file_summaries)} 文件, {len(repo_map.module_summaries)} 模块")
    if summarizer.errors:
        click.echo(f"  摘要失败 {len(summarizer.errors)} 个(已跳过)")
    click.echo("✓ 索引完成")


@cli.command("ask")
@click.argument("question")
@click.option("--repo", required=True, help="repo URL(必须先 index 过)")
def cmd_ask(question: str, repo: str) -> None:
    """问问题,Agent 跨文件追踪调用链回答。"""
    pm = PathManager()
    repo_map_path = pm.repo_map_path(repo)
    if not repo_map_path.exists():
        click.echo(f"错误:repo 未索引过,请先 `taisang index {repo}`", err=True)
        sys.exit(1)

    # 加载 repo_map 和索引
    from ..types import RepoMap, RepoIndex
    repo_map = RepoMap.model_validate_json(repo_map_path.read_text(encoding="utf-8"))

    indexer = IndexerService(pm)
    # 走 update(会复用已有索引)
    idx = indexer.update(repo)
    call_graph = indexer.build_call_graph(idx)

    # 找 source_root
    repo_hash = pm._repo_hash(repo)
    source_root = pm.cache_dir / repo_hash

    llm = _make_llm()
    from ..agent_core.service import AgentService
    agent = AgentService(
        llm=llm, source_root=source_root,
        call_graph=call_graph, repo_map=repo_map,
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

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_cli.py -v`
Expected: PASS (3 个测试全绿)

> 如果 `test_cli_ask_command_with_mock_llm` 失败,可能是 MockLLM 响应不够多(循环里需要多个响应)。把 MockLLM 的响应列表加大,或在 MockLLM 里改成"响应用完就循环复用第一个"。

- [ ] **Step 5: Commit**

```bash
git add src/taisang/cli/__init__.py src/taisang/cli/main.py tests/unit/test_cli.py
git commit -m "feat: add CLI with index/ask commands (MockLLM for testing)"
```

---

## Task 18: 端到端集成测试

**Files:**
- Create: `tests/integration/test_end_to_end.py`

> 这是整个 Plan 1 的验收测试:本地 repo → index → ask → 带引用的 Answer。

- [ ] **Step 1: 写端到端测试**

`tests/integration/test_end_to_end.py`:
```python
"""端到端:本地多文件 repo → index → ask → Answer。"""
import subprocess
from pathlib import Path
from click.testing import CliRunner
from taisang.cli.main import cli


def _make_realistic_repo(tmp_path: Path) -> Path:
    """造一个含跨文件调用的 repo。"""
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "from utils import helper\n\n"
        "def main():\n"
        "    helper()\n"
        "    print('done')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (repo / "utils.py").write_text(
        "def helper():\n"
        "    return do_thing()\n\n"
        "def do_thing():\n"
        "    return 42\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return repo


def test_end_to_end_index_then_ask(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_realistic_repo(tmp_path)

    runner = CliRunner()
    # 1. index
    r1 = runner.invoke(cli, ["index", str(repo)])
    assert r1.exit_code == 0, r1.output
    assert "索引完成" in r1.output

    # 2. ask
    r2 = runner.invoke(cli, ["ask", "main 函数调用了谁", "--repo", str(repo)])
    assert r2.exit_code == 0, r2.output
    # mock LLM 固定回答包含 main
    assert "main" in r2.output


def test_end_to_end_call_graph_built(tmp_path, monkeypatch):
    """index 后调用图应能解析 main → helper → do_thing。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_realistic_repo(tmp_path)

    runner = CliRunner()
    runner.invoke(cli, ["index", str(repo)])

    # 直接调 IndexerService 验证调用图
    from taisang.indexer.service import IndexerService
    from taisang.storage.paths import PathManager
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.update(str(repo))
    graph = service.build_call_graph(idx)
    # main 调 helper,应解析到 utils.py::helper
    assert "utils.py::helper" in graph["main.py::main"].resolved_calls
    # helper 调 do_thing,应解析到 utils.py::do_thing
    assert "utils.py::do_thing" in graph["utils.py::helper"].resolved_calls


def test_end_to_end_trace_call_chain_three_hops(tmp_path, monkeypatch):
    """trace_call_chain 工具能追 main → helper → do_thing。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_realistic_repo(tmp_path)

    runner = CliRunner()
    runner.invoke(cli, ["index", str(repo)])

    from taisang.indexer.service import IndexerService
    from taisang.storage.paths import PathManager
    from taisang.agent_core.tools import TraceCallChainTool
    pm = PathManager()
    service = IndexerService(pm)
    idx = service.update(str(repo))
    graph = service.build_call_graph(idx)

    tool = TraceCallChainTool(call_graph=graph)
    result = tool.run({"symbol_id": "main.py::main", "depth": 3})
    assert result["chain"] == ["main.py::main", "utils.py::helper", "utils.py::do_thing"]
```

- [ ] **Step 2: 运行端到端测试**

Run: `pytest tests/integration/test_end_to_end.py -v`
Expected: PASS (3 个测试全绿)

> 如果失败,通常是 MockLLM 响应不够。把 cli/main.py 里 MockLLM 的响应列表加大(乘以 20),或在 MockLLM 里改成"响应用完后循环复用最后一个"。

- [ ] **Step 3: 跑全部测试确认全绿**

Run: `pytest -v`
Expected: 全部测试 PASS(预计 60+ 个测试)

- [ ] **Step 4: 跑 lint 和格式化**

Run: `ruff check src tests && black --check src tests`
Expected: 无错误

如果有 ruff 报错,修复后重跑。如果有 black 格式问题,跑 `black src tests` 自动格式化。

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_end_to_end.py
git commit -m "test: add end-to-end integration tests for index→ask flow"
```

---

## Task 19: README 占位 + Plan 1 收尾

**Files:**
- Create: `README.md`
- Modify: `memory/project-context.md` (更新进度)

- [ ] **Step 1: 写最小 README**

`README.md`:
```markdown
# Code Reader Agent

> 3 分钟让陌生代码库变成可问答、可追踪调用链、可生成 onboarding 文档。

**当前状态:v0.1 开发中(Plan 1: Python-only MVP 闭环)**

## Quick Start

```bash
# 安装(开发模式)
pip install -e ".[dev]"

# 配置 LLM(支持任意 OpenAI 兼容 endpoint)
export CODE_READER_LLM_BASE_URL=https://api.deepseek.com
export CODE_READER_LLM_API_KEY=sk-xxx
export CODE_READER_LLM_MODEL=deepseek-chat

# 建索引
taisang index https://github.com/tiangolo/fastapi

# 问问题
taisang ask "FastAPI 的路由是怎么注册的" --repo https://github.com/tiangolo/fastapi
```

## 跟 Claude Code / Cursor 的区别

| 维度 | Claude Code + 手写 CLAUDE.md | Code Reader Agent |
|------|------------------------------|-------------------|
| 建索引成本 | 手写半个月 | 自动 3 分钟 |
| 知识形态 | 自然语言笔记 | 结构化 AST + 调用图 |
| 使用门槛 | 高手才能写好 INDEX | 丢 URL 即可 |
| 团队复用 | 个人笔记 | 索引建一次,N 人共享 |
| 可量化 | 体感 | eval set + baseline |
| 调用链追踪 | O(N) 次 LLM 推理 | O(1) 次图查询 |

## 开发路线

- **Plan 1(v0.1,进行中)**:Python-only MVP 闭环
- Plan 2:多语言扩展(JS/TS/Java/Go)
- Plan 3:评测体系(10 题 eval set + baseline)
- Plan 4:session/trace/增量完善
- Plan 5:Web 端(FastAPI + frontend-design)
- Plan 6:开源化(README 完整 + 引流)

详见 `docs/superpowers/specs/2026-08-20-repo-onboarding-agent-design.md`。

## License

MIT
```

- [ ] **Step 2: 更新 memory/project-context.md 的进度表**

在 `memory/project-context.md` 的"进度"章节,把:
```
| writing-plans 出实现计划 | ⏳ 待启动 |
| 实现 | ⏳ 未开始 |
```
改为:
```
| writing-plans Plan 1 | ✅ 完成(docs/superpowers/plans/2026-08-21-plan-1-python-mvp.md) |
| Plan 1 实现 | ⏳ 待启动(用 subagent-driven-development 或 executing-plans) |
| Plan 2-6 | ⏳ 待启动 |
```

- [ ] **Step 3: Commit**

```bash
git add README.md memory/project-context.md
git commit -m "docs: add minimal README and update progress after Plan 1 written"
```

---

## Self-Review

### Spec 覆盖检查

对照设计文档 §2 核心组件,Plan 1 覆盖情况:

| Spec 组件 | Plan 1 任务 | 状态 |
|-----------|-------------|------|
| 2.1 indexer (Python only) | Task 6,7,8,9,10,11 | ✅ 全覆盖 |
| 2.2 summarizer (三层) | Task 12 | ✅ 全覆盖 |
| 2.3 retriever (BM25-only v1) | Task 13 | ✅ 简化版(向量库留 v1.5) |
| 2.4 agent_core (5 工具) | Task 14,15,16 | ✅ 全覆盖 |
| 2.5 evaluator | — | ❌ Plan 3 做 |
| 2.6 cli | Task 17 | ✅ 全覆盖(Web 端留 Plan 5) |

**已知简化**(在 Plan 1 范围内合理,不算缺陷):
- retriever 只做 BM25,不做向量库(避免 Plan 1 引入 Chroma 复杂度,留 v1.5)
- LLM 调用用 MockLLM 测试,真 LLM 集成留到 Plan 1 跑通后手动验证
- 没有 session/trace 落盘(留 Plan 4)
- 没有开源化文档(留 Plan 6)

### Placeholder 扫描

- ✅ 无 "TBD" / "TODO" / "implement later"
- ✅ 所有 step 都有具体代码或命令
- ✅ 测试都有真实断言,不是"测试上面的"
- ✅ 每个任务都重复了完整代码,不写"同 Task N"

### 类型一致性

- ✅ `Symbol` / `RepoIndex` / `RepoMap` / `Answer` 在所有任务中字段名一致
- ✅ `SymbolKind` 枚举值(`FUNCTION`/`CLASS`/`METHOD`)在 Task 2 定义,Task 7/8 使用一致
- ✅ `CallGraphNode` 在 Task 8 定义,Task 14/16 使用一致
- ✅ `LLMResponse` 在 Task 5 定义,Task 12/16 使用一致
- ✅ CLI 命令名 `taisang` 全 plan 一致
- ✅ `PathManager` 方法名(`indices_dir`/`cache_dir`/`repo_map_path`)在 Task 3 定义,Task 11/17 使用一致

### 已知风险(实现时注意)

1. **tree-sitter Python API** 可能因版本不同有差异。Task 7 Step 4 的代码基于 tree-sitter 0.21+。如果 `Language(tspython.language())` 报错,查 tree-sitter 文档,新版 API 是 `tspython.language()` 直接返回 Language 对象。
2. **MockLLM 响应用完**。CLI/Agent 测试中 MockLLM 可能响应不够。实现时把 MockLLM 改成"响应用完循环复用最后一个",或在测试里给足量响应。
3. **本地 git repo 的 `--depth 1`**。Task 10 的 `git clone --depth 1` 对本地 file:// URL 可能有问题。如果测试失败,去掉 `--depth 1`。
4. **Windows 路径分隔符**。多处用 `.replace("\\", "/")` 统一为 Unix 风格,避免 Windows 测试失败。
5. **中文分词**。Task 13 的 `_tokenize` 简单按字切中文,够用但不够好。v1.5 可换 jieba。

---

## 执行交接

Plan 1 完成并落盘到 `docs/superpowers/plans/2026-08-21-plan-1-python-mvp.md`。

两种执行方式:

**1. Subagent-Driven(推荐)** - 每个 Task 派一个 fresh subagent 实现,任务间 review,快速迭代。适合 Plan 1 这种 19 个任务的中型计划。

**2. Inline Execution** - 在当前 session 里按 executing-plans 批量执行,带 checkpoint review。适合你想全程跟进度的情况。

哪种方式?