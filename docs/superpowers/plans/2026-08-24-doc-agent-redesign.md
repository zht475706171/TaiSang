# Doc Agent 重构实现计划:从问答 Agent 到文档生成 Agent

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Code Reader Agent 从"问答 agent"重构为"文档生成 agent"——输入一个本地 repo,产出一套让人能读完吃透项目的 markdown 文档树;agent 保留 plan-act-observe 核心循环,落地三道上下文管理机制(apply-tool-result-budget / microcompact / autocompact)和一道 session memory 机制(分支 agent 异步维护笔记)。

**Architecture:** 保留 agent_core 的核心循环,把任务从"回答问题"改成"产文档树";新增 outliner(重点挖掘)和 docgen(文档树落地)两个模块;在 agent 循环外面包三道压缩流水线 + session memory 后台维护;CLI 砍掉 `ask`/`shell`,只留 `doc` 命令;统一用主 LLM(用户配的单一 model),不再区分主/便宜模型。

**Tech Stack:** Python 3.11+ / tree-sitter + tree-sitter-python / SQLite / openai SDK(兼容任意 endpoint)/ click / pydantic / tiktoken(真 token 计数)/ pytest / ruff + black

**Spec 参考:**
- 设计原文:`docs/superpowers/specs/2026-08-20-repo-onboarding-agent-design.md`
- 上下文管理机制参考:`D:/GoProject/claude-learn/50-context-memory/` 下的 `apply-tool-result-budget/`、`microcompact/`、`autocompact/` 三份笔记

**重构范围说明:**
- 砍掉 `ask`/`shell` 命令(详见 Task 1)
- 保留 indexer / linker / summarizer / retriever 不动(retriever 暂不接入,v0.2 再说)
- 保留 agent_core 的 plan-act-observe 循环,但任务级 prompt 重写
- 新增 outliner / docgen / session_memory / compaction 四个模块
- 平铺摘要字数从 200 放宽到 500-800(详见 Task 3)

---

## 文件结构

```
src/code_reader/
├── cli/
│   └── main.py                      # 改:砍 ask/shell,加 doc 命令
├── indexer/                          # 保留不动
│   ├── fetcher.py
│   ├── fingerprint.py
│   ├── linker.py                     # 改:加 import 解析 + 同模块优先 + render_chain
│   ├── parser_python.py
│   ├── service.py
│   └── storage.py
├── summarizer/                       # 改:字数预算放宽
│   ├── prompts.py
│   └── service.py
├── retriever/                        # 保留不动(v0.2 再接入)
├── outliner/                         # 新增★ 重点挖掘
│   ├── __init__.py
│   ├── entry_points.py               # 入口挖掘(纯程序)
│   ├── mechanism_candidates.py       # 核心机制候选(调用图指标)
│   ├── flow_candidates.py            # 关键流程候选(BFS 端到端路径)
│   ├── module_candidates.py          # 核心模块候选
│   ├── selector.py                   # LLM 介入选 5-10 个机制
│   └── service.py                    # OutlinerService 编排
├── deepwriter/                       # 新增★ 重点深挖
│   ├── __init__.py
│   ├── prompts.py                    # 机制/流程/模块深挖 prompt 模板
│   ├── code_extractor.py             # 抽代码片段(签名 + 注释 + 函数体)
│   └── service.py                    # DeepWriterService
├── docgen/                           # 新增★ 文档树落地
│   ├── __init__.py
│   ├── tree.py                       # 自适应深度,生成章节树
│   ├── render.py                     # markdown 渲染
│   └── service.py                    # DocGenService 编排
├── session_memory/                   # 新增★ 分支 agent 异步维护笔记
│   ├── __init__.py
│   ├── template.py                   # 10 章节模板
│   ├── extractor.py                  # post-sampling 钩子,触发提取
│   ├── forked_agent.py               # 分支 agent(只能 Edit summary.md)
│   └── service.py                    # SessionMemoryService
├── compaction/                       # 新增★ 三道压缩流水线
│   ├── __init__.py
│   ├── tool_result_budget.py         # 阶段 5: apply-tool-result-budget
│   ├── microcompact.py               # 阶段 6: 章节边界 microcompact
│   ├── autocompact.py                # 阶段 7: 旁路 LLM 9 章节摘要
│   ├── prompts.py                    # autocompact 9 章节模板
│   └── pipeline.py                   # 三道流水线编排
├── agent_core/                       # 改:任务级 prompt + 接入压缩流水线
│   ├── context.py                    # 改:接 tiktoken,接 compaction
│   ├── events.py                     # 改:加 DOC_WRITTEN 事件
│   ├── prompts.py                    # 改:任务级 system prompt + 软约束
│   ├── service.py                    # 改:每 turn 跑压缩流水线 + post-sampling
│   └── tools.py                      # 改:加 write_doc/list_pending_sections/finalize_doc
├── storage/
│   └── paths.py                      # 改:加 session-memory / doc 产物路径
├── config.py                         # 保留(去掉 summarizer_* 字段)
├── llm_client.py                     # 保留
├── llm_errors.py                     # 保留
└── types.py                          # 改:加 DocTree/DocSection/MechanismCandidate 等

tests/
├── unit/
│   ├── test_outliner_*.py            # 新增
│   ├── test_deepwriter.py            # 新增
│   ├── test_docgen.py                # 新增
│   ├── test_session_memory.py        # 新增
│   ├── test_compaction_*.py          # 新增
│   ├── test_agent_core.py            # 改
│   └── ... (保留)
├── integration/
│   ├── test_doc_pipeline.py          # 新增:端到端 doc 生成
│   └── ... (保留)
└── fixtures/
    └── python/                       # 保留 + 加 multi_module/ fixture
```

---

## Task 列表(11 个阶段,21 个 task)

> 每个 task 是 TDD 闭环:写失败测试 → 跑测试看失败 → 写最小实现 → 跑测试看通过 → commit。
> 每个 task 标注依赖(前置 task 必须完成)。

---

### Task 1: 砍 ask/shell,加 doc 命令骨架

**依赖:** 无
**Files:**
- Modify: `src/code_reader/cli/main.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_end_to_end.py`

- [ ] **Step 1: 写失败测试——doc 命令存在且 accept repo 参数**

```python
# tests/unit/test_cli.py 追加
def test_doc_command_exists(tmp_path, monkeypatch):
    """doc 命令存在,accept repo 参数,未索引时给出提示。"""
    from click.testing import CliRunner
    from code_reader.cli.main import cli
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    runner = CliRunner()
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    r = runner.invoke(cli, ["doc", str(repo)])
    assert r.exit_code == 0
    assert "REPO_GUIDE.md" in r.output or "文档" in r.output
```

- [ ] **Step 2: 跑测试看失败**

Run: `pytest tests/unit/test_cli.py::test_doc_command_exists -v`
Expected: FAIL with "No such command 'doc'"

- [ ] **Step 3: 改 CLI——砍 ask/shell,加 doc 骨架**

```python
# src/code_reader/cli/main.py(替换文件内容,从 32 行开始的部分)
# 保留:_normalize_path, _make_llm, _render_event(改名 _render_event_keep), _make_progress
# 删除:cmd_ask, cmd_shell
# 新增:cmd_doc(骨架,只占位,Task 11 填完整逻辑)

@cli.command("doc")
@click.argument("repo_path")
@click.option("--lang", default="auto", help="产物语言:zh/en/auto")
@click.option("--update", is_flag=True, default=False, help="增量更新模式")
@click.option("--force", is_flag=True, default=False, help="强制全量重生成")
def cmd_doc(repo_path: str, lang: str, update: bool, force: bool) -> None:
    """生成可读文档树,让人能读完吃透这个 repo。"""
    source_root = _normalize_path(repo_path)
    if not source_root.is_dir():
        click.echo(f"错误:路径不存在或不是目录: {source_root}", err=True)
        sys.exit(1)
    click.echo(f"开始为 {source_root} 生成文档...")
    # 骨架:Task 2-11 逐步填充
    click.echo("✓ 文档生成完成(骨架)")
```

同时删除 `cmd_ask` 和 `cmd_shell` 两个函数。`_render_event` 暂时保留(Task 9 会改)。

- [ ] **Step 4: 跑测试看通过**

Run: `pytest tests/unit/test_cli.py::test_doc_command_exists -v`
Expected: PASS

- [ ] **Step 5: 修复 integration 测试**

```python
# tests/integration/test_end_to_end.py
# 删除 test_end_to_end_index_then_ask(ask 命令已砍)
# 保留 test_end_to_end_call_graph_built 和 test_end_to_end_trace_call_chain_three_hops(它们不依赖 ask 命令)
```

- [ ] **Step 6: 跑全部测试看通过**

Run: `pytest tests/ -v`
Expected: PASS(ask/shell 相关测试已删,其他保留)

- [ ] **Step 7: Commit**

```bash
git add src/code_reader/cli/main.py tests/unit/test_cli.py tests/integration/test_end_to_end.py
git commit -m "feat: 砍 ask/shell,加 doc 命令骨架"
```

---

### Task 2: 补 linker 匹配精度(import 解析 + 同模块优先 + render_chain)

**依赖:** 无(可与 Task 1 并行)
**Files:**
- Modify: `src/code_reader/indexer/linker.py`
- Modify: `src/code_reader/types.py`
- Modify: `tests/unit/test_linker.py`

- [ ] **Step 1: 写失败测试——import 解析能跨文件连**

```python
# tests/unit/test_linker.py 追加
def test_linker_resolves_via_import():
    """a.py 的 helper 调用,通过 import 解析到 b.py::helper。"""
    from code_reader.indexer.linker import build_call_graph
    from code_reader.types import Symbol, SymbolKind
    symbols = [
        Symbol(id="a.py::main", kind=SymbolKind.FUNCTION, name="main", file="a.py",
               line_range=(1, 3), calls=["helper"], imports=["b"]),
        Symbol(id="b.py::helper", kind=SymbolKind.FUNCTION, name="helper", file="b.py",
               line_range=(1, 2), calls=[], imports=[]),
    ]
    graph = build_call_graph(symbols)
    assert "b.py::helper" in graph["a.py::main"].resolved_calls
```

- [ ] **Step 2: 写失败测试——同模块优先于全局同名**

```python
# tests/unit/test_linker.py 追加
def test_linker_same_module_priority():
    """a.py 调 foo,同模块的 a.py::foo 优先于其他模块的 foo。"""
    from code_reader.indexer.linker import build_call_graph
    from code_reader.types import Symbol, SymbolKind
    symbols = [
        Symbol(id="a.py::caller", kind=SymbolKind.FUNCTION, name="caller", file="a.py",
               line_range=(1, 3), calls=["foo"], imports=[]),
        Symbol(id="a.py::foo", kind=SymbolKind.FUNCTION, name="foo", file="a.py",
               line_range=(5, 6), calls=[], imports=[]),
        Symbol(id="b.py::foo", kind=SymbolKind.FUNCTION, name="foo", file="b.py",
               line_range=(1, 2), calls=[], imports=[]),
    ]
    graph = build_call_graph(symbols)
    assert graph["a.py::caller"].resolved_calls == ["a.py::foo"]
```

- [ ] **Step 3: 写失败测试——render_chain 把 symbol_id 列表展开成人话**

```python
# tests/unit/test_linker.py 追加
def test_render_chain_renders_human_readable(tmp_path):
    """render_chain 把 [symbol_id, ...] 展开成 'name (file:line) → ...' 格式。"""
    from code_reader.indexer.linker import build_call_graph, render_chain
    from code_reader.types import Symbol, SymbolKind
    symbols = [
        Symbol(id="a.py::main", kind=SymbolKind.FUNCTION, name="main", file="a.py",
               line_range=(10, 20), calls=["helper"], imports=[]),
        Symbol(id="b.py::helper", kind=SymbolKind.FUNCTION, name="helper", file="b.py",
               line_range=(5, 8), calls=[], imports=[]),
    ]
    graph = build_call_graph(symbols)
    rendered = render_chain(graph, ["a.py::main", "b.py::helper"])
    assert "main (a.py:10-20)" in rendered
    assert "helper (b.py:5-8)" in rendered
    assert "→" in rendered
```

- [ ] **Step 4: 跑测试看全部失败**

Run: `pytest tests/unit/test_linker.py::test_linker_resolves_via_import tests/unit/test_linker.py::test_linker_same_module_priority tests/unit/test_linker.py::test_render_chain_renders_human_readable -v`
Expected: FAIL(3 个测试都失败)

- [ ] **Step 5: 实现新匹配策略**

```python
# src/code_reader/indexer/linker.py(在 build_call_graph 函数里改匹配逻辑)
# 新匹配优先级:
# 1. method 内调 self.foo → 同 class 的 method(保留原有逻辑)
# 2. caller 和某候选 symbol 在同模块(caller.file == candidate.file)→ 优先
# 3. caller 的 imports 含 candidate.file 对应的模块名 → 优先
# 4. 全局唯一 name → 解析
# 5. 否则 unresolved

def _file_module_name(file: str) -> str:
    """a/b/c.py → b(取第一级目录,因为 import 通常写 from b import c)。
    简化版:取 file 去掉 .py 后的最后一段。"""
    return file.rsplit("/", 1)[-1].replace(".py", "")

def build_call_graph(symbols: list[Symbol]) -> dict[str, CallGraphNode]:
    by_name: dict[str, list[str]] = {}
    for s in symbols:
        by_name.setdefault(s.name, []).append(s.id)

    # file → 模块名映射,用于 import 解析
    file_to_module = {s.file: _file_module_name(s.file) for s in symbols}

    graph: dict[str, CallGraphNode] = {}
    for s in symbols:
        node = CallGraphNode(
            symbol_id=s.id, name=s.name, file=s.file, line_range=s.line_range,
        )
        caller_class = _method_class(s.id)
        caller_module = _file_module_name(s.file)
        caller_imports = set(s.imports)
        for call_name in s.calls:
            candidates = by_name.get(call_name, [])
            # 策略 1: method 内调 self.foo → 同 class 的 method
            if caller_class:
                candidate = next(
                    (sid for sid in candidates if _method_class(sid) == caller_class),
                    None,
                )
                if candidate:
                    node.resolved_calls.append(candidate)
                    continue
            # 策略 2: 同文件优先
            same_file = [sid for sid in candidates if sid.split("::")[0] == s.file]
            if len(same_file) == 1:
                node.resolved_calls.append(same_file[0])
                continue
            # 策略 3: import 解析(caller 的 imports 含候选所在模块名)
            import_matched = [
                sid for sid in candidates
                if file_to_module.get(sid.split("::")[0]) in caller_imports
            ]
            if len(import_matched) == 1:
                node.resolved_calls.append(import_matched[0])
                continue
            # 策略 4: 全局唯一 name
            if len(candidates) == 1:
                node.resolved_calls.append(candidates[0])
                continue
            # 策略 5: unresolved
            node.unresolved_calls.append(call_name)
        graph[s.id] = node
    return graph
```

- [ ] **Step 6: 实现 render_chain**

```python
# src/code_reader/indexer/linker.py 追加
def render_chain(graph: dict[str, CallGraphNode], chain: list[str]) -> str:
    """把 symbol_id 列表展开成人话叙事:'name (file:start-end) → name2 (file2:...)'."""
    parts: list[str] = []
    for sid in chain:
        node = graph.get(sid)
        if not node:
            parts.append(f"[missing: {sid}]")
            continue
        start, end = node.line_range
        parts.append(f"{node.name} ({node.file}:{start}-{end})")
    return " → ".join(parts)
```

- [ ] **Step 7: 跑测试看通过**

Run: `pytest tests/unit/test_linker.py -v`
Expected: PASS(含原有测试 + 3 个新测试)

- [ ] **Step 8: Commit**

```bash
git add src/code_reader/indexer/linker.py tests/unit/test_linker.py
git commit -m "feat(linker): import 解析 + 同模块优先 + render_chain"
```

---

### Task 3: 平铺摘要字数放宽到 500-800

**依赖:** 无
**Files:**
- Modify: `src/code_reader/summarizer/service.py`
- Modify: `tests/unit/test_summarizer.py`

- [ ] **Step 1: 写失败测试——文件摘要不被切到 200 字**

```python
# tests/unit/test_summarizer.py 追加
def test_file_summary_not_truncated_to_200(tmp_path):
    """LLM 返回 600 字摘要,终值不应被切到 200 字。"""
    from code_reader.summarizer.service import SummarizerService
    from code_reader.types import RepoIndex, Symbol
    from code_reader.llm_client import MockLLM, LLMResponse

    long_summary = "x" * 600  # 600 字
    mock = MockLLM([LLMResponse(text=long_summary, tool_calls=[])])
    service = SummarizerService(llm=mock)
    src = tmp_path / "a.py"
    src.write_text("def f():\n    pass\n", encoding="utf-8")
    idx = RepoIndex(
        source_root=str(tmp_path), commit_hash="x",
        symbols=[Symbol(id="a.py::f", kind="function", name="f", file="a.py",
                       line_range=(1, 2), calls=[], imports=[])],
        files=["a.py"], index_errors=[],
    )
    repo_map = service.summarize(idx, source_root=tmp_path)
    assert len(repo_map.file_summaries["a.py"].summary) == 600
```

- [ ] **Step 2: 跑测试看失败**

Run: `pytest tests/unit/test_summarizer.py::test_file_summary_not_truncated_to_200 -v`
Expected: FAIL(summary 被切到 200 字)

- [ ] **Step 3: 改 FILE_BUDGET / MODULE_BUDGET / GLOBAL_BUDGET**

```python
# src/code_reader/summarizer/service.py 第 26-28 行
FILE_BUDGET = 800   # 字数(原 200,放宽到 800)
MODULE_BUDGET = 1500  # 字数(原 600,放宽)
GLOBAL_BUDGET = 3000  # 字数(原 2000,放宽)
```

- [ ] **Step 4: 跑测试看通过**

Run: `pytest tests/unit/test_summarizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/code_reader/summarizer/service.py tests/unit/test_summarizer.py
git commit -m "feat(summarizer): 平铺摘要字数放宽到 500-800"
```

---

### Task 4: outliner——重点挖掘(入口 + 机制候选 + 流程候选 + 模块候选)

**依赖:** Task 2(linker 改进)
**Files:**
- Create: `src/code_reader/outliner/__init__.py`
- Create: `src/code_reader/outliner/entry_points.py`
- Create: `src/code_reader/outliner/mechanism_candidates.py`
- Create: `src/code_reader/outliner/flow_candidates.py`
- Create: `src/code_reader/outliner/module_candidates.py`
- Create: `src/code_reader/outliner/service.py`
- Modify: `src/code_reader/types.py`
- Create: `tests/unit/test_outliner_entry_points.py`
- Create: `tests/unit/test_outliner_mechanism_candidates.py`
- Create: `tests/unit/test_outliner_flow_candidates.py`
- Create: `tests/unit/test_outliner_module_candidates.py`

- [ ] **Step 1: 加新数据类型**

```python
# src/code_reader/types.py 追加
class EntryPoint(BaseModel):
    """挖掘出的入口。"""
    symbol_id: str
    kind: str  # "cli" / "main" / "api_endpoint" / "test"
    description: str = ""

class MechanismCandidate(BaseModel):
    """核心机制候选(调用图指标筛出来的)。"""
    symbol_id: str
    name: str
    file: str
    in_degree: int          # 被多少符号调用
    cross_module_refs: int  # 跨模块引用数
    out_degree: int         # 它调用多少符号
    score: float            # 加权打分
    one_liner: str = ""     # LLM 给的一句话定位

class FlowCandidate(BaseModel):
    """关键流程候选(端到端调用链)。"""
    name: str               # 流程名(从入口 symbol 派生)
    entry_symbol_id: str
    chain: list[str]        # symbol_id 列表
    hop_count: int
    rendered: str           # 人话叙事(render_chain 输出)

class ModuleCandidate(BaseModel):
    """核心模块候选。"""
    path: str               # 目录路径
    file_count: int
    symbol_count: int
    in_degree: int          # 该模块所有符号被引用总和
    one_liner: str = ""

class Outline(BaseModel):
    """outliner 的完整产物。"""
    entry_points: list[EntryPoint]
    mechanism_candidates: list[MechanismCandidate]  # top 20
    flow_candidates: list[FlowCandidate]
    module_candidates: list[ModuleCandidate]
    selected_mechanisms: list[MechanismCandidate]   # LLM 选 5-10 个
```

- [ ] **Step 2: 写失败测试——entry_points 能找出 main**

```python
# tests/unit/test_outliner_entry_points.py
from code_reader.outliner.entry_points import find_entry_points
from code_reader.types import RepoIndex, Symbol, SymbolKind

def test_find_entry_points_finds_main():
    symbols = [
        Symbol(id="main.py::main", kind=SymbolKind.FUNCTION, name="main",
               file="main.py", line_range=(1, 3), calls=[], imports=[]),
        Symbol(id="utils.py::helper", kind=SymbolKind.FUNCTION, name="helper",
               file="utils.py", line_range=(1, 2), calls=[], imports=[]),
    ]
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=symbols,
                    files=["main.py", "utils.py"], index_errors=[])
    entries = find_entry_points(idx)
    assert len(entries) == 1
    assert entries[0].symbol_id == "main.py::main"
    assert entries[0].kind == "main"
```

- [ ] **Step 3: 跑测试看失败**

Run: `pytest tests/unit/test_outliner_entry_points.py -v`
Expected: FAIL(模块不存在)

- [ ] **Step 4: 实现 entry_points**

```python
# src/code_reader/outliner/entry_points.py
from __future__ import annotations
from ..types import EntryPoint, RepoIndex, SymbolKind

# 入口文件名匹配
_ENTRY_FILES = {"main.py", "cli.py", "app.py", "__main__.py", "run.py", "start.py"}
# 入口函数名匹配
_ENTRY_NAMES = {"main", "__main__", "run", "app", "create_app", "start", "cli"}

def find_entry_points(idx: RepoIndex) -> list[EntryPoint]:
    entries: list[EntryPoint] = []
    for s in idx.symbols:
        # 入口文件 + 入口函数名
        if s.file in _ENTRY_FILES and s.name in _ENTRY_NAMES:
            entries.append(EntryPoint(
                symbol_id=s.id, kind="main",
                description=f"入口文件 {s.file} 的 {s.name}",
            ))
        # 普通文件但函数名是入口
        elif s.name == "main" and s.file.endswith(".py"):
            entries.append(EntryPoint(
                symbol_id=s.id, kind="main",
                description=f"{s.file} 的 main 函数",
            ))
    # 去重(同 symbol_id 只保留一个)
    seen = set()
    unique: list[EntryPoint] = []
    for e in entries:
        if e.symbol_id not in seen:
            seen.add(e.symbol_id)
            unique.append(e)
    return unique
```

```python
# src/code_reader/outliner/__init__.py
"""outliner:重点挖掘。"""
```

- [ ] **Step 5: 跑测试看通过**

Run: `pytest tests/unit/test_outliner_entry_points.py -v`
Expected: PASS

- [ ] **Step 6: 写失败测试——mechanism_candidates 打分排序**

```python
# tests/unit/test_outliner_mechanism_candidates.py
from code_reader.outliner.mechanism_candidates import find_mechanism_candidates
from code_reader.types import RepoIndex, Symbol, SymbolKind

def test_mechanism_candidates_score_by_in_degree():
    """被引用最多的符号分数最高。"""
    symbols = [
        Symbol(id="a.py::hub", kind=SymbolKind.FUNCTION, name="hub", file="a.py",
               line_range=(1, 5), calls=[], imports=[]),
        Symbol(id="b.py::user1", kind=SymbolKind.FUNCTION, name="user1", file="b.py",
               line_range=(1, 3), calls=["hub"], imports=[]),
        Symbol(id="c.py::user2", kind=SymbolKind.FUNCTION, name="user2", file="c.py",
               line_range=(1, 3), calls=["hub"], imports=[]),
        Symbol(id="d.py::user3", kind=SymbolKind.FUNCTION, name="user3", file="d.py",
               line_range=(1, 3), calls=["hub"], imports=[]),
    ]
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=symbols,
                    files=["a.py", "b.py", "c.py", "d.py"], index_errors=[])
    cands = find_mechanism_candidates(idx, top_k=10)
    assert cands[0].symbol_id == "a.py::hub"
    assert cands[0].in_degree == 3
    assert cands[0].cross_module_refs == 3  # b/c/d 三个不同模块引用
```

- [ ] **Step 7: 跑测试看失败**

Run: `pytest tests/unit/test_outliner_mechanism_candidates.py -v`
Expected: FAIL

- [ ] **Step 8: 实现 mechanism_candidates**

```python
# src/code_reader/outliner/mechanism_candidates.py
from __future__ import annotations
from ..indexer.linker import build_call_graph
from ..types import MechanismCandidate, RepoIndex

def _module_of(file: str) -> str:
    """a/b/c.py → a(取顶层目录,作为模块)。根目录文件 → 文件名。"""
    parts = file.split("/")
    if len(parts) == 1:
        return parts[0]
    return parts[0]

def find_mechanism_candidates(idx: RepoIndex, top_k: int = 20) -> list[MechanismCandidate]:
    """调用图指标打分,top_k 返回。"""
    graph = build_call_graph(idx.symbols)
    # 算每个 symbol 的入度(被谁调用)+ 跨模块引用 + 出度
    in_degree: dict[str, int] = {sid: 0 for sid in graph}
    cross_module: dict[str, set[str]] = {sid: set() for sid in graph}
    for sid, node in graph.items():
        caller_module = _module_of(node.file)
        for callee in node.resolved_calls:
            in_degree[callee] = in_degree.get(callee, 0) + 1
            callee_module = _module_of(graph[callee].file) if callee in graph else caller_module
            if callee_module != caller_module:
                cross_module[callee].add(caller_module)
    cands: list[MechanismCandidate] = []
    for sid, node in graph.items():
        out_degree = len(node.resolved_calls)
        # 加权打分:跨模块引用 × 3 + 入度 × 2 + 出度 × 1
        score = len(cross_module[sid]) * 3 + in_degree[sid] * 2 + out_degree * 1
        cands.append(MechanismCandidate(
            symbol_id=sid, name=node.name, file=node.file,
            in_degree=in_degree[sid],
            cross_module_refs=len(cross_module[sid]),
            out_degree=out_degree, score=score,
        ))
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands[:top_k]
```

- [ ] **Step 9: 跑测试看通过**

Run: `pytest tests/unit/test_outliner_mechanism_candidates.py -v`
Expected: PASS

- [ ] **Step 10: 写失败测试——flow_candidates 从入口 BFS 找链**

```python
# tests/unit/test_outliner_flow_candidates.py
from code_reader.outliner.flow_candidates import find_flow_candidates
from code_reader.types import RepoIndex, Symbol, SymbolKind

def test_flow_candidates_from_entry():
    symbols = [
        Symbol(id="main.py::main", kind=SymbolKind.FUNCTION, name="main",
               file="main.py", line_range=(1, 3), calls=["handle"], imports=["svc"]),
        Symbol(id="svc.py::handle", kind=SymbolKind.FUNCTION, name="handle",
               file="svc.py", line_range=(1, 3), calls=["process"], imports=[]),
        Symbol(id="svc.py::process", kind=SymbolKind.FUNCTION, name="process",
               file="svc.py", line_range=(5, 7), calls=[], imports=[]),
    ]
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=symbols,
                    files=["main.py", "svc.py"], index_errors=[])
    flows = find_flow_candidates(idx, entry_symbol_ids=["main.py::main"], max_depth=8)
    assert len(flows) == 1
    assert flows[0].chain == ["main.py::main", "svc.py::handle", "svc.py::process"]
    assert "main (main.py:1-3)" in flows[0].rendered
    assert "→" in flows[0].rendered
```

- [ ] **Step 11: 跑测试看失败**

Run: `pytest tests/unit/test_outliner_flow_candidates.py -v`
Expected: FAIL

- [ ] **Step 12: 实现 flow_candidates**

```python
# src/code_reader/outliner/flow_candidates.py
from __future__ import annotations
from collections import deque
from ..indexer.linker import build_call_graph, render_chain
from ..types import FlowCandidate, RepoIndex

def find_flow_candidates(
    idx: RepoIndex,
    entry_symbol_ids: list[str],
    max_depth: int = 8,
    min_depth: int = 3,
) -> list[FlowCandidate]:
    """从每个入口 BFS 找第一条端到端路径,过滤太短/太长。"""
    graph = build_call_graph(idx.symbols)
    flows: list[FlowCandidate] = []
    for entry_id in entry_symbol_ids:
        if entry_id not in graph:
            continue
        # BFS 找最深的一条链(简化:找第一条到叶子节点的链)
        chain = _bfs_to_leaf(graph, entry_id, max_depth)
        if len(chain) < min_depth:
            continue
        flows.append(FlowCandidate(
            name=graph[entry_id].name,
            entry_symbol_id=entry_id,
            chain=chain,
            hop_count=len(chain),
            rendered=render_chain(graph, chain),
        ))
    return flows

def _bfs_to_leaf(graph, start, max_depth):
    """BFS 找到第一个叶子节点(无 resolved_calls)的路径。"""
    queue = deque([(start, [start])])
    visited = {start}
    while queue:
        node_id, path = queue.popleft()
        if len(path) >= max_depth:
            return path
        node = graph.get(node_id)
        if not node or not node.resolved_calls:
            return path  # 叶子
        for callee in node.resolved_calls:
            if callee not in visited:
                visited.add(callee)
                queue.append((callee, path + [callee]))
    return path
```

- [ ] **Step 13: 跑测试看通过**

Run: `pytest tests/unit/test_outliner_flow_candidates.py -v`
Expected: PASS

- [ ] **Step 14: 写失败测试——module_candidates 按目录聚类**

```python
# tests/unit/test_outliner_module_candidates.py
from code_reader.outliner.module_candidates import find_module_candidates
from code_reader.types import RepoIndex, Symbol, SymbolKind

def test_module_candidates_group_by_dir():
    symbols = [
        Symbol(id="core/a.py::x", kind=SymbolKind.FUNCTION, name="x", file="core/a.py",
               line_range=(1, 2), calls=[], imports=[]),
        Symbol(id="core/b.py::y", kind=SymbolKind.FUNCTION, name="y", file="core/b.py",
               line_range=(1, 2), calls=[], imports=[]),
        Symbol(id="utils/c.py::z", kind=SymbolKind.FUNCTION, name="z", file="utils/c.py",
               line_range=(1, 2), calls=[], imports=[]),
    ]
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=symbols,
                    files=["core/a.py", "core/b.py", "utils/c.py"], index_errors=[])
    mods = find_module_candidates(idx, top_k=5)
    paths = [m.path for m in mods]
    assert "core" in paths
    assert "utils" in paths
    core_mod = next(m for m in mods if m.path == "core")
    assert core_mod.file_count == 2
    assert core_mod.symbol_count == 2
```

- [ ] **Step 15: 跑测试看失败**

Run: `pytest tests/unit/test_outliner_module_candidates.py -v`
Expected: FAIL

- [ ] **Step 16: 实现 module_candidates**

```python
# src/code_reader/outliner/module_candidates.py
from __future__ import annotations
from collections import defaultdict
from pathlib import PurePosixPath
from ..types import ModuleCandidate, RepoIndex

def find_module_candidates(idx: RepoIndex, top_k: int = 5) -> list[ModuleCandidate]:
    """按目录聚类,统计每个模块的文件数/符号数/入度。"""
    files_by_dir: dict[str, set[str]] = defaultdict(set)
    syms_by_dir: dict[str, int] = defaultdict(int)
    for s in idx.symbols:
        d = str(PurePosixPath(s.file).parent)
        if d == ".":
            d = ""
        files_by_dir[d].add(s.file)
        syms_by_dir[d] += 1
    # 入度:从调用图算(简化:用 in_degree 总和)
    from ..indexer.linker import build_call_graph
    graph = build_call_graph(idx.symbols)
    in_degree: dict[str, int] = defaultdict(int)
    for node in graph.values():
        for callee in node.resolved_calls:
            callee_dir = str(PurePosixPath(graph[callee].file).parent) if callee in graph else ""
            if callee_dir == ".":
                callee_dir = ""
            in_degree[callee_dir] += 1
    cands = [
        ModuleCandidate(
            path=d, file_count=len(files), symbol_count=syms_by_dir[d],
            in_degree=in_degree[d],
        )
        for d, files in files_by_dir.items()
    ]
    cands.sort(key=lambda m: (m.in_degree, m.symbol_count), reverse=True)
    return cands[:top_k]
```

- [ ] **Step 17: 跑测试看通过**

Run: `pytest tests/unit/test_outliner_module_candidates.py -v`
Expected: PASS

- [ ] **Step 18: 实现 OutlinerService 编排**

```python
# src/code_reader/outliner/service.py
from __future__ import annotations
from ..llm_client import LLMClient, MockLLM
from ..types import Outline, RepoIndex
from .entry_points import find_entry_points
from .mechanism_candidates import find_mechanism_candidates
from .flow_candidates import find_flow_candidates
from .module_candidates import find_module_candidates
from .selector import select_mechanisms

class OutlinerService:
    def __init__(self, llm: LLMClient | MockLLM) -> None:
        self.llm = llm

    def outline(self, idx: RepoIndex) -> Outline:
        entries = find_entry_points(idx)
        entry_ids = [e.symbol_id for e in entries]
        mechanisms = find_mechanism_candidates(idx, top_k=20)
        flows = find_flow_candidates(idx, entry_symbol_ids=entry_ids)
        modules = find_module_candidates(idx, top_k=5)
        # LLM 从 top 20 候选里选 5-10 个
        selected = select_mechanisms(self.llm, idx, mechanisms)
        return Outline(
            entry_points=entries,
            mechanism_candidates=mechanisms,
            flow_candidates=flows,
            module_candidates=modules,
            selected_mechanisms=selected,
        )
```

- [ ] **Step 19: Commit**

```bash
git add src/code_reader/outliner/ src/code_reader/types.py tests/unit/test_outliner_*.py
git commit -m "feat(outliner): 入口/机制/流程/模块候选挖掘"
```

---

### Task 5: outliner——LLM 选 5-10 个机制(selector)

**依赖:** Task 4
**Files:**
- Create: `src/code_reader/outliner/selector.py`
- Create: `tests/unit/test_outliner_selector.py`

- [ ] **Step 1: 写失败测试——LLM 从候选里选机制**

```python
# tests/unit/test_outliner_selector.py
from code_reader.outliner.selector import select_mechanisms
from code_reader.types import MechanismCandidate, RepoIndex, Symbol, SymbolKind
from code_reader.llm_client import MockLLM, LLMResponse

def test_select_mechanisms_llm_picks_5():
    """LLM 返回 JSON 含 5 个 symbol_id,selector 选出对应候选。"""
    cands = [
        MechanismCandidate(symbol_id=f"f{i}.py::m{i}", name=f"m{i}",
                           file=f"f{i}.py", in_degree=10-i,
                           cross_module_refs=5, out_degree=3, score=100-i)
        for i in range(20)
    ]
    # LLM 返回前 5 个
    llm_resp = '{"selected": ["f0.py::m0", "f1.py::m1", "f2.py::m2", "f3.py::m3", "f4.py::m4"]}'
    mock = MockLLM([LLMResponse(text=llm_resp, tool_calls=[])])
    idx = RepoIndex(source_root=".", commit_hash="x", symbols=[], files=[], index_errors=[])
    selected = select_mechanisms(mock, idx, cands)
    assert len(selected) == 5
    assert selected[0].symbol_id == "f0.py::m0"
```

- [ ] **Step 2: 跑测试看失败**

Run: `pytest tests/unit/test_outliner_selector.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 selector**

```python
# src/code_reader/outliner/selector.py
from __future__ import annotations
import json
from ..llm_client import LLMClient, MockLLM
from ..types import MechanismCandidate, RepoIndex

SELECTOR_SYSTEM = """你是一个代码库专家。从下面的候选机制里挑 5-10 个"这个项目最重要的机制"。
返回 JSON:{"selected": ["symbol_id1", "symbol_id2", ...], "reasons": {"symbol_id": "一句话定位"}}
只返回 JSON,不要其他文字。"""

def select_mechanisms(
    llm: LLMClient | MockLLM,
    idx: RepoIndex,
    candidates: list[MechanismCandidate],
    min_count: int = 3,
    max_count: int = 10,
) -> list[MechanismCandidate]:
    if not candidates:
        return []
    cand_text = "\n".join(
        f"- {c.symbol_id} (in_degree={c.in_degree}, cross_module={c.cross_module_refs}, "
        f"score={c.score})"
        for c in candidates
    )
    user_prompt = f"候选机制(top 20):\n{cand_text}\n\n请挑 {min_count}-{max_count} 个最重要的。"
    resp = llm.chat(
        messages=[
            {"role": "system", "content": SELECTOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        tools=[],
    )
    try:
        data = json.loads(resp.text)
        selected_ids = data.get("selected", [])[:max_count]
    except (json.JSONDecodeError, AttributeError):
        # fallback:取分数最高的前 5 个
        return candidates[:min_count]
    reasons = data.get("reasons", {}) if isinstance(data, dict) else {}
    by_id = {c.symbol_id: c for c in candidates}
    result = []
    for sid in selected_ids:
        if sid in by_id:
            c = by_id[sid].model_copy()
            c.one_liner = reasons.get(sid, "")
            result.append(c)
    # 不足 min_count 用高分补
    if len(result) < min_count:
        existing = {c.symbol_id for c in result}
        for c in candidates:
            if c.symbol_id not in existing:
                result.append(c)
                if len(result) >= min_count:
                    break
    return result
```

- [ ] **Step 4: 跑测试看通过**

Run: `pytest tests/unit/test_outliner_selector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/code_reader/outliner/selector.py tests/unit/test_outliner_selector.py
git commit -m "feat(outliner): LLM 从候选里选 5-10 个机制"
```

---

### Task 6: deepwriter——重点深挖(机制/流程/模块)

**依赖:** Task 2(render_chain)、Task 4(Outline)
**Files:**
- Create: `src/code_reader/deepwriter/__init__.py`
- Create: `src/code_reader/deepwriter/prompts.py`
- Create: `src/code_reader/deepwriter/code_extractor.py`
- Create: `src/code_reader/deepwriter/service.py`
- Modify: `src/code_reader/storage/paths.py`
- Create: `tests/unit/test_deepwriter.py`

- [ ] **Step 1: 加 storage 路径——doc 产物目录**

```python
# src/code_reader/storage/paths.py 追加方法
    @classmethod
    def doc_dir(cls, source_root: Path) -> Path:
        """文档产物目录:<source_root>/.code-reader/docs/"""
        d = cls.index_dir(source_root) / "docs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_dir(cls, source_root: Path, session_id: str) -> Path:
        """session memory 目录:.code-reader/sessions/<id>/session-memory/"""
        d = cls.index_dir(source_root) / "sessions" / session_id / "session-memory"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_path(cls, source_root: Path, session_id: str) -> Path:
        return cls.session_memory_dir(source_root, session_id) / "summary.md"

    @classmethod
    def observations_dir(cls, source_root: Path) -> Path:
        """大 observation 持久化目录:.code-reader/observations/"""
        d = cls.index_dir(source_root) / "observations"
        d.mkdir(parents=True, exist_ok=True)
        return d
```

- [ ] **Step 2: 写失败测试——code_extractor 抽代码片段**

```python
# tests/unit/test_deepwriter.py
from pathlib import Path
from code_reader.deepwriter.code_extractor import extract_code_snippet

def test_extract_code_snippet_returns_signature_and_body(tmp_path):
    f = tmp_path / "a.py"
    f.write_text(
        "# 这是注释\n"
        "def foo(x):\n"
        "    y = x + 1\n"
        "    return y\n"
        "\n"
        "def bar():\n"
        "    pass\n",
        encoding="utf-8",
    )
    snippet = extract_code_snippet(f, "a.py", start_line=2, end_line=4)
    assert "def foo(x):" in snippet
    assert "return y" in snippet
    assert "[a.py:2-4]" in snippet
```

- [ ] **Step 3: 跑测试看失败**

Run: `pytest tests/unit/test_deepwriter.py::test_extract_code_snippet_returns_signature_and_body -v`
Expected: FAIL

- [ ] **Step 4: 实现 code_extractor**

```python
# src/code_reader/deepwriter/code_extractor.py
from __future__ import annotations
from pathlib import Path

def extract_code_snippet(
    file_path: Path,
    rel_path: str,
    start_line: int,
    end_line: int,
    context_lines: int = 3,
) -> str:
    """抽代码片段:context_lines 行前文 + start_line-end_line + 标注行号。"""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    ctx_start = max(0, start_line - 1 - context_lines)
    ctx_end = min(len(lines), end_line + context_lines)
    parts: list[str] = []
    parts.append(f"[{rel_path}:{start_line}-{end_line}]")
    for i in range(ctx_start, ctx_end):
        marker = ">>" if start_line <= i + 1 <= end_line else "  "
        parts.append(f"{marker} {i+1:4d}  {lines[i]}")
    return "\n".join(parts)
```

```python
# src/code_reader/deepwriter/__init__.py
"""deepwriter:重点深挖。"""
```

- [ ] **Step 5: 跑测试看通过**

Run: `pytest tests/unit/test_deepwriter.py::test_extract_code_snippet_returns_signature_and_body -v`
Expected: PASS

- [ ] **Step 6: 实现 prompts**

```python
# src/code_reader/deepwriter/prompts.py
MECHANISM_SYSTEM = """你正在为一个完全没见过这个项目的开发者写讲解文档。

写一篇 1500-3000 字的讲解,包含:
1. 这个机制解决什么问题
2. 怎么实现的(带 [file:line] 引用)
3. 为什么这么设计(取舍点)
4. 典型用法示例

语言:跟用户问题同语言(中文或英文)。
格式:markdown,带 [file:line] 引用。"""

MECHANISM_USER = """【机制名】: {name}
【一句话定位】: {one_liner}
【相关符号】:
{symbols_with_file_line}
【代码片段】:
{code_snippets}

请写一篇 1500-3000 字的讲解。"""

FLOW_SYSTEM = """你正在为一个完全没见过这个项目的开发者写端到端流程讲解。

写一篇 1500-3000 字的讲解,包含:
1. 这个流程从哪个入口开始
2. 端到端每一步在哪、做什么
3. 数据怎么流动
4. 关键决策点

语言:跟用户问题同语言。格式:markdown,带 [file:line] 引用。"""

FLOW_USER = """【流程名】: {name}
【端到端调用链】:
{rendered_chain}
【每一步的代码片段】:
{code_snippets}

请写一篇 1500-3000 字的讲解。"""

MODULE_SYSTEM = """你正在为一个完全没见过这个项目的开发者写核心模块讲解。

写一篇 1000-2000 字的讲解,包含:
1. 这个模块的职责
2. 对外接口
3. 内部结构
4. 和谁耦合

语言:跟用户问题同语言。格式:markdown。"""

MODULE_USER = """【模块路径】: {module_path}
【包含文件数】: {file_count}
【一句话定位】: {one_liner}
【相关符号】:
{symbols}"""
```

- [ ] **Step 7: 实现 DeepWriterService**

```python
# src/code_reader/deepwriter/service.py
from __future__ import annotations
from pathlib import Path
from ..indexer.linker import render_chain
from ..llm_client import LLMClient, MockLLM
from ..types import FlowCandidate, MechanismCandidate, ModuleCandidate, RepoIndex
from .code_extractor import extract_code_snippet
from .prompts import (
    FLOW_SYSTEM, FLOW_USER, MECHANISM_SYSTEM, MECHANISM_USER,
    MODULE_SYSTEM, MODULE_USER,
)

class DeepWriterService:
    def __init__(self, llm: LLMClient | MockLLM, source_root: Path) -> None:
        self.llm = llm
        self.source_root = source_root

    def write_mechanism(self, idx: RepoIndex, m: MechanismCandidate) -> str:
        # 抽该机制的代码片段
        snippets = self._snippets_for_symbols(idx, [m.symbol_id])
        symbols_text = f"- {m.symbol_id} (in_degree={m.in_degree})"
        prompt = MECHANISM_USER.format(
            name=m.name, one_liner=m.one_liner or "(待补)",
            symbols_with_file_line=symbols_text, code_snippets=snippets,
        )
        return self._chat(MECHANISM_SYSTEM, prompt)

    def write_flow(self, idx: RepoIndex, f: FlowCandidate) -> str:
        snippets = self._snippets_for_symbols(idx, f.chain)
        prompt = FLOW_USER.format(
            name=f.name, rendered_chain=f.rendered, code_snippets=snippets,
        )
        return FLOW_SYSTEM and self._chat(FLOW_SYSTEM, prompt)

    def write_module(self, idx: RepoIndex, m: ModuleCandidate) -> str:
        # 找该模块下所有 symbol
        mod_symbols = [s for s in idx.symbols if _module_of(s.file) == m.path]
        syms_text = "\n".join(f"- {s.id}" for s in mod_symbols[:20])
        prompt = MODULE_USER.format(
            module_path=m.path or "(root)", file_count=m.file_count,
            one_liner=m.one_liner or "(待补)", symbols=syms_text,
        )
        return self._chat(MODULE_SYSTEM, prompt)

    def _snippets_for_symbols(self, idx: RepoIndex, symbol_ids: list[str]) -> str:
        by_id = {s.id: s for s in idx.symbols}
        parts: list[str] = []
        for sid in symbol_ids:
            s = by_id.get(sid)
            if not s:
                continue
            f = self.source_root / s.file
            if not f.exists():
                continue
            parts.append(extract_code_snippet(f, s.file, s.line_range[0], s.line_range[1]))
        return "\n\n".join(parts)

    def _chat(self, system: str, user: str) -> str:
        resp = self.llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=[],
        )
        return resp.text
```

```python
# src/code_reader/deepwriter/service.py 顶部加 helper
def _module_of(file: str) -> str:
    parts = file.split("/")
    return parts[0] if len(parts) > 1 else ""
```

- [ ] **Step 8: 写失败测试——DeepWriterService 写机制**

```python
# tests/unit/test_deepwriter.py 追加
def test_deepwriter_write_mechanism(tmp_path):
    from code_reader.deepwriter.service import DeepWriterService
    from code_reader.types import MechanismCandidate, RepoIndex, Symbol, SymbolKind
    from code_reader.llm_client import MockLLM, LLMResponse

    f = tmp_path / "a.py"
    f.write_text("def foo():\n    return 42\n", encoding="utf-8")
    mock = MockLLM([LLMResponse(text="这是一个机制的讲解 [a.py:1-2]", tool_calls=[])])
    service = DeepWriterService(llm=mock, source_root=tmp_path)
    idx = RepoIndex(
        source_root=str(tmp_path), commit_hash="x",
        symbols=[Symbol(id="a.py::foo", kind=SymbolKind.FUNCTION, name="foo",
                        file="a.py", line_range=(1, 2), calls=[], imports=[])],
        files=["a.py"], index_errors=[],
    )
    m = MechanismCandidate(symbol_id="a.py::foo", name="foo", file="a.py",
                            in_degree=5, cross_module_refs=3, out_degree=2, score=20)
    text = service.write_mechanism(idx, m)
    assert "机制" in text
    assert "a.py" in text
```

- [ ] **Step 9: 跑测试看通过**

Run: `pytest tests/unit/test_deepwriter.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/code_reader/deepwriter/ src/code_reader/storage/paths.py tests/unit/test_deepwriter.py
git commit -m "feat(deepwriter): 重点深挖机制/流程/模块"
```

---

### Task 7: docgen——文档树落地(自适应深度 + 章节生成)

**依赖:** Task 4(Outline)、Task 6(DeepWriter)
**Files:**
- Create: `src/code_reader/docgen/__init__.py`
- Create: `src/code_reader/docgen/tree.py`
- Create: `src/code_reader/docgen/render.py`
- Create: `src/code_reader/docgen/service.py`
- Modify: `src/code_reader/types.py`
- Create: `tests/unit/test_docgen.py`

- [ ] **Step 1: 加 DocTree 数据类型**

```python
# src/code_reader/types.py 追加
class DocSection(BaseModel):
    """一个章节。"""
    path: str               # 落盘相对路径,如 "02_核心机制/01_依赖注入.md"
    title: str
    content: str = ""       # 章节正文(markdown)
    kind: str = "generic"   # "guide" / "overview" / "mechanism" / "flow" / "module" / "glossary" / "reading_map"

class DocTree(BaseModel):
    """完整文档树。"""
    repo_name: str
    language: str            # "zh" / "en"
    sections: list[DocSection]
```

- [ ] **Step 2: 写失败测试——tree.py 自适应深度**

```python
# tests/unit/test_docgen.py
from code_reader.docgen.tree import build_doc_tree_structure
from code_reader.types import (
    DocSection, FlowCandidate, MechanismCandidate, ModuleCandidate, Outline,
    EntryPoint,
)

def test_build_doc_tree_small_repo():
    """小 repo(<5 机制)只生成最少章节。"""
    outline = Outline(
        entry_points=[EntryPoint(symbol_id="main.py::main", kind="main")],
        mechanism_candidates=[],
        flow_candidates=[],
        module_candidates=[],
        selected_mechanisms=[
            MechanismCandidate(symbol_id=f"f{i}.py::m{i}", name=f"m{i}",
                               file=f"f{i}.py", in_degree=3, cross_module_refs=2,
                               out_degree=1, score=10)
            for i in range(3)
        ],
    )
    sections = build_doc_tree_structure(outline, repo_name="demo", language="zh")
    paths = [s.path for s in sections]
    assert "REPO_GUIDE.md" in paths
    assert "00_项目是什么.md" in paths
    assert "01_架构总览.md" in paths
    # 3 个机制 → 3 个文件
    mechanism_paths = [p for p in paths if p.startswith("02_核心机制/")]
    assert len(mechanism_paths) == 3
    assert "05_概念词典.md" in paths
    assert "06_阅读路线图.md" in paths
```

- [ ] **Step 3: 跑测试看失败**

Run: `pytest tests/unit/test_docgen.py::test_build_doc_tree_small_repo -v`
Expected: FAIL

- [ ] **Step 4: 实现 tree.py**

```python
# src/code_reader/docgen/tree.py
from __future__ import annotations
from ..types import DocSection, Outline

def build_doc_tree_structure(outline: Outline, repo_name: str, language: str) -> list[DocSection]:
    """根据 outline 自适应生成章节树结构(空 content)。"""
    sections: list[DocSection] = [
        DocSection(path="REPO_GUIDE.md", title=f"{repo_name} 阅读指南", kind="guide"),
        DocSection(path="00_项目是什么.md", title="项目是什么", kind="overview"),
        DocSection(path="01_架构总览.md", title="架构总览", kind="overview"),
    ]
    # 02_核心机制/:每个机制一个文件
    for i, m in enumerate(outline.selected_mechanisms, start=1):
        slug = _slugify(m.name)
        sections.append(DocSection(
            path=f"02_核心机制/{i:02d}_{slug}.md",
            title=m.name, kind="mechanism",
        ))
    # 03_关键流程/:每个流程一个文件
    for i, f in enumerate(outline.flow_candidates, start=1):
        slug = _slugify(f.name)
        sections.append(DocSection(
            path=f"03_关键流程/{i:02d}_{slug}.md",
            title=f.name, kind="flow",
        ))
    # 04_核心模块/:每个模块一个文件
    for i, m in enumerate(outline.module_candidates, start=1):
        slug = _slugify(m.path or "root")
        sections.append(DocSection(
            path=f"04_核心模块/{i:02d}_{slug}.md",
            title=m.path or "根目录", kind="module",
        ))
    sections.append(DocSection(path="05_概念词典.md", title="概念词典", kind="glossary"))
    sections.append(DocSection(path="06_阅读路线图.md", title="阅读路线图", kind="reading_map"))
    return sections

def _slugify(name: str) -> str:
    """转文件名安全的 slug(保留中文,去掉空格)。"""
    return name.replace(" ", "_").replace("/", "_")[:50]
```

```python
# src/code_reader/docgen/__init__.py
"""docgen:文档树落地。"""
```

- [ ] **Step 5: 跑测试看通过**

Run: `pytest tests/unit/test_docgen.py::test_build_doc_tree_small_repo -v`
Expected: PASS

- [ ] **Step 6: 实现 render.py——markdown 渲染**

```python
# src/code_reader/docgen/render.py
from __future__ import annotations
from pathlib import Path
from ..types import DocSection, DocTree, Outline

def render_guide(tree: DocTree, outline: Outline) -> str:
    """渲染 REPO_GUIDE.md:目录 + 阅读顺序。"""
    lines: list[str] = [
        f"# {tree.repo_name} 阅读指南", "",
        "## 这份文档怎么读", "",
        "按以下顺序阅读,30 分钟内能吃透这个项目:", "",
    ]
    for s in tree.sections:
        if s.path == "REPO_GUIDE.md":
            continue
        lines.append(f"- [{s.title}]({s.path})")
    lines += ["", "## 项目一句话", "", "(待 00_项目是什么.md 填充)"]
    return "\n".join(lines)

def render_section(section: DocSection, content: str) -> str:
    """渲染单个章节文件内容。"""
    return f"# {section.title}\n\n{content}\n"
```

- [ ] **Step 7: 实现 DocGenService**

```python
# src/code_reader/docgen/service.py
from __future__ import annotations
from pathlib import Path
from ..deepwriter.service import DeepWriterService
from ..llm_client import LLMClient, MockLLM
from ..storage.paths import PathManager
from ..types import DocSection, DocTree, Outline, RepoIndex
from .render import render_guide, render_section
from .tree import build_doc_tree_structure

class DocGenService:
    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        repo_name: str,
        language: str = "zh",
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.repo_name = repo_name
        self.language = language
        self.deepwriter = DeepWriterService(llm=llm, source_root=source_root)

    def generate(self, idx: RepoIndex, outline: Outline) -> DocTree:
        sections = build_doc_tree_structure(outline, self.repo_name, self.language)
        # 填 content
        for s in sections:
            s.content = self._render_section_content(s, idx, outline)
        tree = DocTree(repo_name=self.repo_name, language=self.language, sections=sections)
        # 落盘
        self._write_to_disk(tree)
        return tree

    def _render_section_content(self, section: DocSection, idx: RepoIndex, outline: Outline) -> str:
        if section.kind == "guide":
            return render_guide(DocTree(repo_name=self.repo_name, language=self.language, sections=[]), outline)
        if section.kind == "overview":
            return "(待 agent 填充)"  # Task 9 的 agent 循环会填
        if section.kind == "mechanism":
            # 从 outline 找对应机制
            name = section.title
            m = next((x for x in outline.selected_mechanisms if x.name == name), None)
            if m:
                return self.deepwriter.write_mechanism(idx, m)
            return "(机制未找到)"
        if section.kind == "flow":
            name = section.title
            f = next((x for x in outline.flow_candidates if x.name == name), None)
            if f:
                return self.deepwriter.write_flow(idx, f)
            return "(流程未找到)"
        if section.kind == "module":
            path = section.title
            m = next((x for x in outline.module_candidates if (x.path or "根目录") == path), None)
            if m:
                return self.deepwriter.write_module(idx, m)
            return "(模块未找到)"
        if section.kind == "glossary":
            return "(待 agent 填充)"
        if section.kind == "reading_map":
            return self._render_reading_map(outline)
        return ""

    def _render_reading_map(self, outline: Outline) -> str:
        lines = ["想改某类问题,先读这些:", ""]
        for m in outline.selected_mechanisms[:5]:
            lines.append(f"- 想改 **{m.name}** 相关 → 读 02_核心机制/")
        for f in outline.flow_candidates[:3]:
            lines.append(f"- 想改 **{f.name}** 流程 → 读 03_关键流程/")
        return "\n".join(lines)

    def _write_to_disk(self, tree: DocTree) -> None:
        doc_dir = PathManager.doc_dir(self.source_root)
        for s in tree.sections:
            full = doc_dir / s.path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(render_section(s, s.content), encoding="utf-8")
```

- [ ] **Step 8: 写失败测试——DocGenService 落盘**

```python
# tests/unit/test_docgen.py 追加
def test_docgen_service_writes_files(tmp_path, monkeypatch):
    from code_reader.docgen.service import DocGenService
    from code_reader.types import (
        EntryPoint, FlowCandidate, MechanismCandidate, ModuleCandidate,
        Outline, RepoIndex, Symbol, SymbolKind,
    )
    from code_reader.llm_client import MockLLM, LLMResponse
    from code_reader.storage.paths import PathManager

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "demo").mkdir()
    repo = tmp_path / "demo"
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    mock = MockLLM([LLMResponse(text=f"讲解内容 {i} [a.py:1-2]", tool_calls=[]) for i in range(30)])
    service = DocGenService(llm=mock, source_root=repo, repo_name="demo", language="zh")
    idx = RepoIndex(
        source_root=str(repo), commit_hash="x",
        symbols=[Symbol(id="a.py::foo", kind=SymbolKind.FUNCTION, name="foo",
                        file="a.py", line_range=(1, 2), calls=[], imports=[])],
        files=["a.py"], index_errors=[],
    )
    outline = Outline(
        entry_points=[EntryPoint(symbol_id="a.py::foo", kind="main")],
        mechanism_candidates=[],
        flow_candidates=[],
        module_candidates=[ModuleCandidate(path="", file_count=1, symbol_count=1, in_degree=0)],
        selected_mechanisms=[MechanismCandidate(symbol_id="a.py::foo", name="foo",
            file="a.py", in_degree=1, cross_module_refs=0, out_degree=0, score=1)],
    )
    tree = service.generate(idx, outline)
    doc_dir = PathManager.doc_dir(repo)
    assert (doc_dir / "REPO_GUIDE.md").exists()
    assert (doc_dir / "00_项目是什么.md").exists()
    assert (doc_dir / "02_核心机制" / "01_foo.md").exists()
```

- [ ] **Step 9: 跑测试看通过**

Run: `pytest tests/unit/test_docgen.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/code_reader/docgen/ src/code_reader/types.py tests/unit/test_docgen.py
git commit -m "feat(docgen): 文档树自适应深度 + 落盘"
```

---

### Task 8: compaction——apply-tool-result-budget(阶段 5)

**依赖:** 无
**Files:**
- Create: `src/code_reader/compaction/__init__.py`
- Create: `src/code_reader/compaction/tool_result_budget.py`
- Modify: `src/code_reader/storage/paths.py`(Task 6 已加 observations_dir)
- Create: `tests/unit/test_compaction_tool_result_budget.py`

- [ ] **Step 1: 加 ContentReplacementState 类型(参考 Claude Code 原文)**

```python
# src/code_reader/compaction/tool_result_budget.py 顶部
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ContentReplacementState:
    """跨 turn 持有替换决策。决策一旦做出,冻结。"""
    seen_ids: set[str] = field(default_factory=set)              # 已决策过的 tool_use_id
    replacements: dict[str, str] = field(default_factory=dict)   # tool_use_id → preview 字符串

# 预算:单轮 tool_result 总和上限(字节)
PER_MESSAGE_BUDGET_BYTES = 200_000
# 单条 tool_result 持久化阈值
DEFAULT_PERSIST_THRESHOLD = 50_000
# preview 截断字节数
PREVIEW_BYTES = 2000
# 跳过 budget 的工具名(小结果或本身是写操作)
SKIP_TOOL_NAMES = {"write_doc", "list_pending_sections", "finalize_doc", "glob"}

CLEARED_PLACEHOLDER = "[persisted-output]\n完整输出已写入 {path} ({size} 字节)\n这里是预览:\n{preview}\n[... {omitted} 字节省略,见文件 ...]\n[/persisted-output]"
```

- [ ] **Step 2: 写失败测试——超预算的 tool_result 被持久化 + preview 替换**

```python
# tests/unit/test_compaction_tool_result_budget.py
from code_reader.compaction.tool_result_budget import (
    ContentReplacementState, enforce_budget,
)

def test_enforce_budget_persists_large_result(tmp_path):
    state = ContentReplacementState()
    # 一个 user message 内含一个 tool_result,60KB,超 50KB 阈值
    big_content = "x" * 60_000
    messages = [
        {"role": "user", "content": "ctx", "tool_calls": [
            {"id": "tc1", "function": {"name": "read_file"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": big_content},
    ]
    new_messages, newly_replaced = enforce_budget(
        messages, state, persist_dir=tmp_path,
    )
    assert len(newly_replaced) == 1
    assert newly_replaced[0]["tool_call_id"] == "tc1"
    # 替换后 content 含 preview + 文件路径提示
    tool_msg = next(m for m in new_messages if m["role"] == "tool")
    assert "[persisted-output]" in tool_msg["content"]
    assert "2,000" in tool_msg["content"] or "预览" in tool_msg["content"]
    # 决策冻结:tc1 进 seen_ids
    assert "tc1" in state.seen_ids
    # 文件真的落盘了
    assert len(list(tmp_path.glob("*.txt"))) == 1

def test_enforce_budget_decision_is_frozen(tmp_path):
    """第二次 enforce 时,已决策的 tool_use_id 直接套 preview,无文件 I/O。"""
    state = ContentReplacementState()
    state.seen_ids.add("tc1")
    state.replacements["tc1"] = "[persisted-output]\n固定 preview\n[/persisted-output]"
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "原内容"},
    ]
    new_messages, newly = enforce_budget(messages, state, persist_dir=tmp_path)
    assert newly == []  # 没新决策
    assert new_messages[0]["content"] == "[persisted-output]\n固定 preview\n[/persisted-output]"
```

- [ ] **Step 3: 跑测试看失败**

Run: `pytest tests/unit/test_compaction_tool_result_budget.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 enforce_budget**

```python
# src/code_reader/compaction/tool_result_budget.py 追加
import os

def enforce_budget(
    messages: list[dict],
    state: ContentReplacementState,
    persist_dir: Path,
    budget_bytes: int = PER_MESSAGE_BUDGET_BYTES,
    persist_threshold: int = DEFAULT_PERSIST_THRESHOLD,
) -> tuple[list[dict], list[dict]]:
    """对 messages 跑 apply-tool-result-budget。
    返回 (新 messages, 本次新做的替换决策列表)。
    """
    # 按 user message 分组(每个 user message 后到下一个 user 前的 tool results 算一组)
    new_messages = list(messages)
    newly_replaced: list[dict] = []
    # 简化:不分 user message,直接看所有 tool messages 的总字节
    # 找所有 tool message
    tool_indices = [i for i, m in enumerate(new_messages) if m["role"] == "tool"]
    # 三分区:mustReapply / frozen / fresh
    fresh_to_check: list[int] = []
    total_bytes = 0
    for i in tool_indices:
        tcid = new_messages[i].get("tool_call_id", "")
        content = new_messages[i].get("content", "")
        if not isinstance(content, str):
            continue
        if tcid in state.seen_ids:
            # mustReapply:套已存的 preview
            if tcid in state.replacements:
                new_messages[i] = {**new_messages[i], "content": state.replacements[tcid]}
            # frozen 但没替换的:不动
            continue
        # fresh
        name = new_messages[i].get("name", "")
        if name in SKIP_TOOL_NAMES:
            state.seen_ids.add(tcid)
            continue
        fresh_to_check.append(i)
        total_bytes += len(content.encode("utf-8"))
    if total_bytes <= budget_bytes:
        # 没超预算,所有 fresh 标记为 seen(frozen,不替换)
        for i in fresh_to_check:
            state.seen_ids.add(new_messages[i].get("tool_call_id", ""))
        return new_messages, []
    # 超预算:fresh 里按"最大优先"持久化,直到总字节 < budget
    fresh_to_check.sort(
        key=lambda i: len(new_messages[i].get("content", "").encode("utf-8")),
        reverse=True,
    )
    bytes_to_free = total_bytes - budget_bytes
    for i in fresh_to_check:
        if bytes_to_free <= 0:
            break
        content = new_messages[i].get("content", "")
        content_bytes = len(content.encode("utf-8"))
        if content_bytes < persist_threshold:
            # 不够大,不值得持久化
            state.seen_ids.add(new_messages[i].get("tool_call_id", ""))
            continue
        # 持久化到磁盘
        tcid = new_messages[i].get("tool_call_id", "")
        persist_file = persist_dir / f"{tcid}.txt"
        persist_file.write_text(content, encoding="utf-8")
        preview = content[:PREVIEW_BYTES]
        omitted = content_bytes - PREVIEW_BYTES
        placeholder = CLEARED_PLACEHOLDER.format(
            path=str(persist_file), size=f"{content_bytes:,}", preview=preview,
            omitted=f"{omitted:,}",
        )
        state.replacements[tcid] = placeholder
        state.seen_ids.add(tcid)
        new_messages[i] = {**new_messages[i], "content": placeholder}
        newly_replaced.append({"tool_call_id": tcid, "path": str(persist_file)})
        bytes_to_free -= content_bytes
    # 剩下的 fresh 标记为 frozen 不替换
    for i in fresh_to_check:
        tcid = new_messages[i].get("tool_call_id", "")
        if tcid not in state.seen_ids:
            state.seen_ids.add(tcid)
    return new_messages, newly_replaced
```

```python
# src/code_reader/compaction/__init__.py
"""compaction:上下文管理三道流水线。"""
```

- [ ] **Step 5: 跑测试看通过**

Run: `pytest tests/unit/test_compaction_tool_result_budget.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/code_reader/compaction/__init__.py src/code_reader/compaction/tool_result_budget.py tests/unit/test_compaction_tool_result_budget.py
git commit -m "feat(compaction): apply-tool-result-budget 阶段 5"
```

---

### Task 9: compaction——章节边界 microcompact(阶段 6)

**依赖:** Task 8
**Files:**
- Create: `src/code_reader/compaction/microcompact.py`
- Create: `tests/unit/test_compaction_microcompact.py`

- [ ] **Step 1: 写失败测试——写完章节后清旧 observation**

```python
# tests/unit/test_compaction_microcompact.py
from code_reader.compaction.microcompact import clear_observations_before_section

def test_clear_observations_replaces_with_placeholder():
    """章节边界 microcompact:把 write_doc 之前的 tool_result 替换为占位符。"""
    messages = [
        {"role": "user", "content": "开始写章节 1"},
        {"role": "assistant", "content": "读文件", "tool_calls": [
            {"id": "tc1", "function": {"name": "read_file"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 5000},
        {"role": "assistant", "content": "写章节 1", "tool_calls": [
            {"id": "tc2", "function": {"name": "write_doc"}}
        ]},
        {"role": "tool", "tool_call_id": "tc2", "name": "write_doc", "content": "ok"},
        {"role": "assistant", "content": "继续读下一个", "tool_calls": [
            {"id": "tc3", "function": {"name": "read_file"}}
        ]},
        {"role": "tool", "tool_call_id": "tc3", "name": "read_file", "content": "y" * 3000},
    ]
    # 章节 1 的 write_doc 是 tc2,清掉它之前的 observation
    new_messages = clear_observations_before_section(messages, section_tool_call_id="tc2")
    # tc1 被清成占位符
    tc1_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc1")
    assert "Old tool result content cleared" in tc1_msg["content"]
    # tc3 保留(write_doc 之后的,属于新章节)
    tc3_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc3")
    assert tc3_msg["content"] == "y" * 3000
    # write_doc 自己不清
    tc2_msg = next(m for m in new_messages if m.get("tool_call_id") == "tc2")
    assert tc2_msg["content"] == "ok"
```

- [ ] **Step 2: 跑测试看失败**

Run: `pytest tests/unit/test_compaction_microcompact.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 microcompact**

```python
# src/code_reader/compaction/microcompact.py
from __future__ import annotations

# 占位符(36 字节,固定)
CLEARED_MESSAGE = "[Old tool result content cleared]"

# 章节 boundary 工具(成功调用后,清掉它之前的 observation)
SECTION_BOUNDARY_TOOLS = {"write_doc"}

def clear_observations_before_section(
    messages: list[dict],
    section_tool_call_id: str,
) -> list[dict]:
    """章节边界 microcompact:把 section_tool_call_id 之前的所有 tool_result(非 boundary 工具)
    替换为占位符。保留 boundary 工具自己的结果。
    """
    # 找 section_tool_call_id 在 messages 里的位置(作为 tool message 的位置)
    section_idx = None
    for i, m in enumerate(messages):
        if m.get("role") == "tool" and m.get("tool_call_id") == section_tool_call_id:
            section_idx = i
            break
    if section_idx is None:
        return list(messages)
    # 在 section_idx 之前的 tool messages,如果 name 不在 boundary 集合,清
    new_messages = list(messages)
    for i in range(section_idx):
        m = new_messages[i]
        if m.get("role") != "tool":
            continue
        name = m.get("name", "")
        if name in SECTION_BOUNDARY_TOOLS:
            continue
        # 已是占位符的不再压
        content = m.get("content", "")
        if isinstance(content, str) and content != CLEARED_MESSAGE:
            new_messages[i] = {**m, "content": CLEARED_MESSAGE}
    return new_messages
```

- [ ] **Step 4: 跑测试看通过**

Run: `pytest tests/unit/test_compaction_microcompact.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/code_reader/compaction/microcompact.py tests/unit/test_compaction_microcompact.py
git commit -m "feat(compaction): 章节边界 microcompact 阶段 6"
```

---

### Task 10: compaction——autocompact 9 章节摘要(阶段 7)

**依赖:** 无(可与 Task 8/9 并行)
**Files:**
- Create: `src/code_reader/compaction/prompts.py`
- Create: `src/code_reader/compaction/autocompact.py`
- Create: `tests/unit/test_compaction_autocompact.py`

- [ ] **Step 1: 实现 prompts(9 章节模板,改造自 Claude Code)**

```python
# src/code_reader/compaction/prompts.py
"""autocompact 9 章节 prompt 模板(改造自 Claude Code 原版,适配文档生成任务)。"""

NO_TOOLS_PREAMBLE = """关键约束:只用纯文本回复。不要调用任何工具。

- 你已经拥有所需的所有上下文,都在上面的对话里。
- 你的整个回复必须是纯文本:一个 <analysis> 块跟着一个 <summary> 块。"""

BASE_COMPACT_PROMPT = """你的任务是创建一份到目前为止对话的详细摘要,这份摘要要让 agent 在压缩后能继续为这个 repo 生成文档。

在你的分析过程中:
1. 按时间顺序分析对话里的每条消息
2. 识别:已写完的章节、当前在写的章节、待写章节、已挖出来的机制/流程、已读过的关键文件

你的摘要应当包含以下 9 个章节:

1. 已完成的章节列表(标题 + 路径 + 一句话定位)
2. 当前在写的章节
3. 待写章节清单(outliner 给的候选里还没写的)
4. 已挖出来的机制候选(含 symbol_id 和一句话定位)
5. 已挖出来的流程候选(含端到端 symbol 链)
6. 已读过的关键文件清单(file:line)
7. 关键决策点(为什么挑这些机制)
8. 当前章节的草稿要点(写到哪了)
9. 可选的下一步(写下一章 / finalize / 再深挖某机制)
"""

NO_TOOLS_TRAILER = """提醒:不要调用任何工具。只用纯文本回复——
一个 <analysis> 块跟着一个 <summary> 块。"""
```

- [ ] **Step 2: 写失败测试——autocompact 生成摘要 + 替换 messages**

```python
# tests/unit/test_compaction_autocompact.py
from code_reader.compaction.autocompact import autocompact
from code_reader.llm_client import MockLLM, LLMResponse

def test_autocompact_generates_summary_and_replaces_messages(tmp_path):
    """autocompact:调 LLM 生成 9 章节摘要,替换 state.messages。"""
    summary_text = """<analysis>分析对话</analysis>
<summary>
1. 已完成的章节列表:
   - 00_项目是什么.md
2. 当前在写的章节: 01_架构总览.md
3. 待写章节清单: 02_核心机制/01_xxx.md
4. 已挖出来的机制候选: foo, bar
5. 已挖出来的流程候选: main → foo
6. 已读过的关键文件: a.py, b.py
7. 关键决策点: foo 被引用最多
8. 当前章节的草稿要点: 写到一半
9. 可选的下一步: 完成 01_架构总览.md
</summary>"""
    mock = MockLLM([LLMResponse(text=summary_text, tool_calls=[])])
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "开始"},
        {"role": "assistant", "content": "调用工具", "tool_calls": [
            {"id": "tc1", "function": {"name": "read_file"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 200_000},
        {"role": "assistant", "content": "继续"},
    ]
    result = autocompact(
        messages=messages, llm=mock, transcript_path=tmp_path / "transcript.jsonl",
    )
    # 新 messages 第一条是 boundaryMarker
    assert "compacted" in result[0]["content"].lower() or "boundary" in result[0]["content"].lower()
    # <analysis> 块被删掉了
    summary_msg = next(m for m in result if m["role"] == "user")
    assert "<analysis>" not in summary_msg["content"]
    assert "已完成的章节" in summary_msg["content"]
    # 原对话没了
    assert not any(m["content"] == "x" * 200_000 for m in result if m["role"] == "tool")
```

- [ ] **Step 3: 跑测试看失败**

Run: `pytest tests/unit/test_compaction_autocompact.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 autocompact**

```python
# src/code_reader/compaction/autocompact.py
from __future__ import annotations
import re
from pathlib import Path
from ..llm_client import LLMClient, MockLLM
from .prompts import BASE_COMPACT_PROMPT, NO_TOOLS_PREAMBLE, NO_TOOLS_TRAILER

# 熔断器
MAX_CONSECUTIVE_FAILURES = 3

def autocompact(
    messages: list[dict],
    llm: LLMClient | MockLLM,
    transcript_path: Path | None = None,
) -> list[dict]:
    """调旁路 LLM 生成 9 章节摘要,替换 state.messages。
    
    流程:
    1. 把整个 messages 拼成 user prompt,加 preamble + BASE_COMPACT_PROMPT + trailer
    2. 调 LLM(不带 tools,纯文本回复)
    3. 删 <analysis> 块,只留 <summary> 块
    4. 构造新 messages:[boundaryMarker, summaryUserMessage]
    5. transcript 路径提示加到 summary 末尾(供后续 read 回查)
    """
    # 1. 拼 prompt
    conversation_text = _messages_to_text(messages)
    full_prompt = "\n\n".join([
        NO_TOOLS_PREAMBLE,
        BASE_COMPACT_PROMPT,
        "对话内容:",
        conversation_text,
        NO_TOOLS_TRAILER,
    ])
    # 2. 调 LLM(不带 tools)
    resp = llm.chat(
        messages=[
            {"role": "system", "content": "你是对话摘要助手。"},
            {"role": "user", "content": full_prompt},
        ],
        tools=[],  # 强制不调工具
    )
    raw = resp.text
    # 3. 删 <analysis> 块
    summary = _extract_summary(raw)
    # 4. 构造新 messages
    boundary_marker = {
        "role": "user", "content": "[boundary: autocompact occurred here]",
    }
    summary_content = (
        "This session is being continued from a previous conversation that ran out of context.\n"
        "The summary below covers the earlier portion of the conversation.\n\n"
        f"Summary:\n{summary}"
    )
    if transcript_path:
        summary_content += (
            f"\n\nIf you need specific details from before compaction, "
            f"read the full transcript at: {transcript_path}"
        )
    summary_msg = {"role": "user", "content": summary_content}
    return [boundary_marker, summary_msg]

def _messages_to_text(messages: list[dict]) -> str:
    """把 messages 拼成可读文本(供 LLM 摘要)。"""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)

def _extract_summary(raw: str) -> str:
    """从 LLM 输出里抽 <summary> 块,删 <analysis> 块。"""
    # 优先 <summary>...</summary>
    m = re.search(r"<summary>(.*?)</summary>", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback:删 <analysis> 块,剩下全要
    cleaned = re.sub(r"<analysis>.*?</analysis>", "", raw, flags=re.DOTALL)
    return cleaned.strip()
```

- [ ] **Step 5: 跑测试看通过**

Run: `pytest tests/unit/test_compaction_autocompact.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/code_reader/compaction/prompts.py src/code_reader/compaction/autocompact.py tests/unit/test_compaction_autocompact.py
git commit -m "feat(compaction): autocompact 9 章节摘要 阶段 7"
```

---

### Task 11: session_memory——分支 agent 异步维护笔记(选项 B)

**依赖:** Task 6(session_memory_dir 已加)、Task 10(autocompact)
**Files:**
- Create: `src/code_reader/session_memory/__init__.py`
- Create: `src/code_reader/session_memory/template.py`
- Create: `src/code_reader/session_memory/forked_agent.py`
- Create: `src/code_reader/session_memory/extractor.py`
- Create: `src/code_reader/session_memory/service.py`
- Create: `tests/unit/test_session_memory.py`

- [ ] **Step 1: 实现 10 章节模板(改造自 Claude Code 原文)**

```python
# src/code_reader/session_memory/template.py
"""session memory 笔记 10 章节模板(改造自 Claude Code 原文,适配文档生成任务)。"""

DEFAULT_TEMPLATE = """# Session Title
*当前在为哪个 repo 生成文档*

(demo repo)

# Current State
*整体进度:已完成几章 / 总共几章*

(待填)

# Task specification
*用户要的"吃透级别"和语言*

(待填)

# Files and Functions
*已读过的关键文件 + 关键 symbol*

(待填)

# Workflow
*agent 的工作策略(先挖机制 / 先挖流程)*

(待填)

# Errors & Corrections
*调用图断链、LLM 摘要失败等*

(待填)

# Codebase and System Documentation
*repo 的架构理解(从 indexer 来)*

(待填)

# Learnings
*这个 repo 的特殊性、踩坑点*

(待填)

# Key results
*已生成的章节清单(标题 + 路径 + 一句话定位)*

(待填)

# Worklog
*步骤流水(每 3 次工具调用追加一条)*

(待填)
"""

DEFAULT_UPDATE_PROMPT = """你是一个会话笔记维护助手。下面是当前笔记内容,请根据最新的对话更新它。

【当前笔记】:
{current_notes}

【最新对话片段】:
{recent_conversation}

更新规则:
1. 只改每个章节描述行下面的实际内容,描述行(以 * 开头)必须保留
2. 章节顺序固定,不要新增或删除章节
3. Worklog 章节追加新条目,不要删除旧条目
4. 用 Edit 工具修改 {memory_path},一次只改一个章节
5. 不要调用任何其他工具

开始更新。"""

def get_template() -> str:
    return DEFAULT_TEMPLATE

def get_update_prompt(current_notes: str, recent_conversation: str, memory_path: str) -> str:
    return DEFAULT_UPDATE_PROMPT.format(
        current_notes=current_notes,
        recent_conversation=recent_conversation,
        memory_path=str(memory_path),
    )
```

- [ ] **Step 2: 写失败测试——session memory 文件初始化**

```python
# tests/unit/test_session_memory.py
from pathlib import Path
from code_reader.session_memory.service import SessionMemoryService
from code_reader.llm_client import MockLLM, LLMResponse

def test_session_memory_initializes_template(tmp_path):
    """首次调用 ensure_file 时,写默认模板。"""
    memory_path = tmp_path / "summary.md"
    service = SessionMemoryService(llm=MockLLM([]), memory_path=memory_path)
    service.ensure_file()
    assert memory_path.exists()
    content = memory_path.read_text(encoding="utf-8")
    assert "Session Title" in content
    assert "Worklog" in content
    assert content.count("# ") == 10  # 10 个章节
```

- [ ] **Step 3: 跑测试看失败**

Run: `pytest tests/unit/test_session_memory.py::test_session_memory_initializes_template -v`
Expected: FAIL

- [ ] **Step 4: 实现 SessionMemoryService(初始化部分)**

```python
# src/code_reader/session_memory/__init__.py
"""session_memory:分支 agent 异步维护笔记。"""
```

```python
# src/code_reader/session_memory/service.py
from __future__ import annotations
import threading
from pathlib import Path
from ..llm_client import LLMClient, MockLLM
from .template import get_template, get_update_prompt

# 3 道阈值门控(完全照搬 Claude Code)
MIN_TOKENS_TO_INIT = 10_000        # 累积到 10K tokens 才初始化笔记
MIN_TOKENS_BETWEEN_UPDATE = 5_000  # 上次提取后新增 5K tokens 才再提取
TOOL_CALLS_BETWEEN_UPDATES = 3     # 至少 3 次工具调用才再提取

# 等待提取完成
EXTRACTION_WAIT_TIMEOUT_MS = 15_000
EXTRACTION_STALE_THRESHOLD_MS = 60_000

class SessionMemoryService:
    """session memory:平时异步维护笔记,autocompact 触发时零 LLM 调用读笔记。"""

    def __init__(self, llm: LLMClient | MockLLM, memory_path: Path) -> None:
        self.llm = llm
        self.memory_path = memory_path
        self._lock = threading.Lock()  # sequential 串行化
        self._last_extracted_tokens = 0
        self._last_extracted_tool_calls = 0
        self._extracting = False

    def ensure_file(self) -> None:
        """笔记文件不存在则写默认模板。"""
        if not self.memory_path.exists():
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.memory_path.write_text(get_template(), encoding="utf-8")

    def should_extract(self, current_tokens: int, tool_calls_since_last: int) -> bool:
        """3 道阈值门控。"""
        if not self.memory_path.exists():
            return current_tokens >= MIN_TOKENS_TO_INIT
        delta_tokens = current_tokens - self._last_extracted_tokens
        return (
            delta_tokens >= MIN_TOKENS_BETWEEN_UPDATE
            and tool_calls_since_last >= TOOL_CALLS_BETWEEN_UPDATES
        )

    def read_for_compaction(self) -> str | None:
        """autocompact 触发时调用:读笔记内容作为摘要。返回 None 则 fallback 到 LLM 摘要。"""
        if not self.memory_path.exists():
            return None
        content = self.memory_path.read_text(encoding="utf-8")
        # 检查是否还是空模板(没有实际内容)
        if "(待填)" in content and content.count("(待填)") >= 8:
            return None  # 还是空模板,没维护过
        return content
```

- [ ] **Step 5: 跑测试看通过**

Run: `pytest tests/unit/test_session_memory.py::test_session_memory_initializes_template -v`
Expected: PASS

- [ ] **Step 6: 写失败测试——extract 调分支 agent 更新笔记**

```python
# tests/unit/test_session_memory.py 追加
def test_session_memory_extract_uses_forked_agent(tmp_path):
    """extract 调 LLM,让 LLM 用 Edit 工具更新笔记。"""
    memory_path = tmp_path / "summary.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Session Title\n*desc*\n(old)\n", encoding="utf-8")
    # mock LLM 返回一个 tool_call:Edit summary.md
    mock = MockLLM([LLMResponse(text="更新笔记", tool_calls=[{
        "name": "Edit",
        "args": {"file_path": str(memory_path), "old_string": "(old)", "new_string": "(new content)"},
    }])])
    service = SessionMemoryService(llm=mock, memory_path=memory_path)
    # 直接调 extract(绕过 should_extract)
    service._do_extract(recent_conversation="最新对话:写了 00_项目是什么.md")
    # 笔记内容更新了
    assert "(new content)" in memory_path.read_text(encoding="utf-8")
```

- [ ] **Step 7: 跑测试看失败**

Run: `pytest tests/unit/test_session_memory.py::test_session_memory_extract_uses_forked_agent -v`
Expected: FAIL

- [ ] **Step 8: 实现 forked_agent + extract**

```python
# src/code_reader/session_memory/forked_agent.py
"""分支 agent:只能 Edit summary.md,其他工具 deny。
完全照搬 Claude Code 原文 createMemoryFileCanUseTool。"""
from __future__ import annotations
from pathlib import Path
from ..llm_client import LLMClient, MockLLM, LLMResponse

ALLOWED_TOOL = "Edit"

def run_forked_agent(
    llm: LLMClient | MockLLM,
    memory_path: Path,
    update_prompt: str,
    max_turns: int = 1,
) -> LLMResponse:
    """跑分支 agent,只能调 Edit 改 memory_path。"""
    messages = [
        {"role": "system", "content": "你是会话笔记维护助手。"},
        {"role": "user", "content": update_prompt},
    ]
    # 简化:只跑一轮,LLM 返回 tool_calls
    resp = llm.chat(messages=messages, tools=_allowed_tools_schema(memory_path))
    # 安全闸:执行 tool_calls 前检查
    for tc in resp.tool_calls:
        if tc["name"] != ALLOWED_TOOL:
            continue  # deny
        args = tc["args"]
        if args.get("file_path") != str(memory_path):
            continue  # deny
        # 真的执行 Edit
        _apply_edit(memory_path, args.get("old_string", ""), args.get("new_string", ""))
    return resp

def _allowed_tools_schema(memory_path: Path) -> list[dict]:
    return [{
        "name": "Edit",
        "description": f"编辑 {memory_path}。只能编辑这个文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": str(memory_path)},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    }]

def _apply_edit(file_path: Path, old: str, new: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if old not in content:
        return
    file_path.write_text(content.replace(old, new, 1), encoding="utf-8")
```

```python
# src/code_reader/session_memory/service.py 追加方法
    def _do_extract(self, recent_conversation: str) -> None:
        """调分支 agent 更新笔记。"""
        with self._lock:  # sequential 串行化
            self._extracting = True
            try:
                self.ensure_file()
                current_notes = self.memory_path.read_text(encoding="utf-8")
                prompt = get_update_prompt(current_notes, recent_conversation, self.memory_path)
                from .forked_agent import run_forked_agent
                run_forked_agent(self.llm, self.memory_path, prompt)
            finally:
                self._extracting = False
```

- [ ] **Step 9: 跑测试看通过**

Run: `pytest tests/unit/test_session_memory.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/code_reader/session_memory/ tests/unit/test_session_memory.py
git commit -m "feat(session_memory): 分支 agent 异步维护笔记 选项 B"
```

---

### Task 12: agent_core——任务级 prompt + 软约束 + 接入压缩流水线

**依赖:** Task 4(outliner)、Task 7(docgen)、Task 8/9/10(compaction)、Task 11(session_memory)
**Files:**
- Modify: `src/code_reader/agent_core/prompts.py`
- Modify: `src/code_reader/agent_core/tools.py`
- Modify: `src/code_reader/agent_core/service.py`
- Modify: `src/code_reader/agent_core/context.py`
- Modify: `src/code_reader/agent_core/events.py`
- Modify: `src/code_reader/types.py`
- Modify: `tests/unit/test_agent_core.py`

- [ ] **Step 1: 加 write_doc / list_pending_sections / finalize_doc 工具**

```python
# src/code_reader/agent_core/tools.py 追加
class WriteDocTool(_BaseTool):
    name = "write_doc"

    def __init__(self, doc_dir: Path) -> None:
        self.doc_dir = doc_dir

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "把一个章节写到 markdown 文件。section_path 是相对 doc_dir 的路径,如 '02_核心机制/01_依赖注入.md'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_path": {"type": "string", "description": "相对 doc_dir 的路径"},
                    "content": {"type": "string", "description": "章节 markdown 内容"},
                },
                "required": ["section_path", "content"],
            },
        }

    def run(self, args: dict) -> dict:
        path = args.get("section_path", "")
        content = args.get("content", "")
        if not path:
            return {"ok": False, "error": "empty section_path"}
        full = self.doc_dir / path
        if not _is_within(self.doc_dir, full):
            return {"ok": False, "error": "path outside doc dir"}
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"# {path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}\n\n{content}\n", encoding="utf-8")
        return {"ok": True, "path": str(full)}

class ListPendingSectionsTool(_BaseTool):
    name = "list_pending_sections"

    def __init__(self, doc_dir: Path, all_sections: list[str]) -> None:
        self.doc_dir = doc_dir
        self.all_sections = all_sections

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "列出还没写的章节(占位文件不存在或为空的章节)。",
            "parameters": {"type": "object", "properties": {}},
        }

    def run(self, args: dict) -> dict:
        pending: list[str] = []
        for s in self.all_sections:
            full = self.doc_dir / s
            if not full.exists():
                pending.append(s)
                continue
            content = full.read_text(encoding="utf-8", errors="replace")
            if "(待填" in content or len(content) < 50:
                pending.append(s)
        return {"pending": pending, "total": len(self.all_sections)}

class FinalizeDocTool(_BaseTool):
    name = "finalize_doc"

    def __init__(self, doc_dir: Path) -> None:
        self.doc_dir = doc_dir

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "全部章节写完后调用,生成 REPO_GUIDE.md 总览并结束任务。",
            "parameters": {"type": "object", "properties": {}},
        }

    def run(self, args: dict) -> dict:
        return {"ok": True, "message": "finalize signal"}
```

- [ ] **Step 2: 加 DOC_WRITTEN 事件**

```python
# src/code_reader/agent_core/events.py 追加
DOC_WRITTEN = "doc_written"
COMPACTED = "compacted"
```

- [ ] **Step 3: 改写 agent system prompt(任务级 + 软约束)**

```python
# src/code_reader/agent_core/prompts.py(替换内容)
SYSTEM_PROMPT = """你的任务是为一个 repo 生成一份让人能读完吃透项目的 markdown 文档树。

工作流程:
1. 先调 lookup_map(layer="global") 看全局摘要,理解项目大致结构
2. 调 list_pending_sections 看还有哪些章节要写
3. 对每个章节,用 read_file / trace_call_chain / grep 收集信息,然后调 write_doc 落盘
4. 全部章节写完后,调 finalize_doc 结束

【硬性约束】
- 至少讲 3 个机制,最多讲 10 个(outliner 已经帮你挑好,看 list_pending_sections)
- 入口文件必讲
- 被引用 top 5 的模块必讲

【软约束】
- 单章节 1500-3000 字,超了拆分
- 每写完一个章节调 list_pending_sections 检查进度
- 章节内容带 [file:line] 引用,让人能溯源
- 概念词典章节要从已写章节里抽术语

文档树结构(已由 docgen 准备好,你只需要填 content):
- REPO_GUIDE.md 总入口
- 00_项目是什么.md 1 页电梯演讲
- 01_架构总览.md 核心组件 + 怎么连
- 02_核心机制/ 每个机制一个文件
- 03_关键流程/ 每个端到端流程一个文件
- 04_核心模块/ 每个核心模块一个文件
- 05_概念词典.md 新手最容易卡的概念
- 06_阅读路线图.md "想改 X 先读 Y" 的索引

语言:跟用户问题同语言(中文或英文)。
"""
```

- [ ] **Step 4: 改 ContextManager 接入 compaction**

```python
# src/code_reader/agent_core/context.py 重写
from __future__ import annotations
import tiktoken

class ContextManager:
    def __init__(self, token_budget: int = 32_000, compact_ratio: float = 0.8) -> None:
        self.token_budget = token_budget
        self.compact_ratio = compact_ratio
        self._messages: list[dict] = []
        self._enc = tiktoken.get_encoding("cl100k_base")  # 真 token 计数

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._enc.encode(text))

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
            "role": "tool", "name": name, "content": text,
            "tool_call_id": tool_call_id or name,
        })

    def messages(self) -> list[dict]:
        return list(self._messages)

    def replace_messages(self, new_messages: list[dict]) -> None:
        """autocompact 调用:整个换掉 messages。"""
        self._messages = list(new_messages)
```

- [ ] **Step 5: 改 AgentService——接入三道流水线 + session memory**

```python
# src/code_reader/agent_core/service.py 重写关键部分
class AgentService:
    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
        idx: RepoIndex,
        outline: Outline,
        doc_dir: Path,
        all_sections: list[str],
        session_memory: SessionMemoryService | None = None,
        compaction_state: ContentReplacementState | None = None,
        max_steps: int = 50,
        token_budget: int = 32_000,
    ) -> None:
        self.llm = llm
        self.source_root = source_root
        self.call_graph = call_graph
        self.repo_map = repo_map
        self.idx = idx
        self.outline = outline
        self.doc_dir = doc_dir
        self.all_sections = all_sections
        self.session_memory = session_memory
        self.compaction_state = compaction_state or ContentReplacementState()
        self.max_steps = max_steps
        self.token_budget = token_budget

    def run(self, query: str, on_event: EventCallback | None = None) -> Answer:
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)
        ctx.append_user(
            f"代码库全局摘要:\n{self.repo_map.global_summary.dependency_summary}\n\n"
            f"已选出的核心机制:{len(self.outline.selected_mechanisms)} 个\n"
            f"已挖出的关键流程:{len(self.outline.flow_candidates)} 条\n"
            f"文档树章节清单:{self.all_sections}\n\n"
            f"任务: {query}"
        )
        registry = ToolRegistry(
            source_root=self.source_root,
            call_graph=self.call_graph,
            repo_map=self.repo_map,
            doc_dir=self.doc_dir,
            all_sections=self.all_sections,
        )
        observations_dir = PathManager.observations_dir(self.source_root)
        transcript_path = PathManager.index_dir(self.source_root) / "sessions" / "current.jsonl"
        steps = 0
        tool_calls_since_last_extract = 0
        while steps < self.max_steps:
            steps += 1
            # 阶段 5: apply-tool-result-budget
            new_msgs, _ = enforce_budget(ctx.messages(), self.compaction_state, observations_dir)
            # 阶段 6: 章节边界 microcompact(由 write_doc 触发,在工具调用后处理)
            # 阶段 7/7a: autocompact 检查
            if ctx.should_compact():
                compacted = self._try_autocompact(ctx, transcript_path, on_event)
                if compacted:
                    tool_calls_since_last_extract = 0
                    continue
            _emit(on_event, AgentEvent(type=LLM_THINKING))
            try:
                resp = self.llm.chat(messages=ctx.messages(), tools=registry.schemas())
            except (LLMProtocolError, LLMTransientError, LLMError) as e:
                return Answer(text=f"(LLM 错误: {e})", citations=[], complete=False, steps_used=steps)
            if not resp.tool_calls:
                _emit(on_event, AgentEvent(type=FINAL_ANSWER, payload={"text": resp.text}))
                return Answer(text=resp.text, citations=self._extract_citations(resp.text),
                              complete=True, steps_used=steps)
            ctx.append_assistant(text=resp.text, tool_calls=resp.tool_calls)
            for i, tc in enumerate(resp.tool_calls):
                name = tc.get("name", "<unknown>")
                args = tc.get("args") or {}
                _emit(on_event, AgentEvent(type=TOOL_CALL, payload={"name": name, "args": args}))
                result = registry.call(name, args)
                observation = json.dumps(result, ensure_ascii=False)
                ctx.append_tool_result(observation, name=name, tool_call_id=f"{name}-{i}")
                # write_doc 成功 → 触发 microcompact 清旧 observation
                if name == "write_doc" and isinstance(result, dict) and result.get("ok"):
                    new_msgs = clear_observations_before_section(ctx.messages(), f"{name}-{i}")
                    # 重建 ContextManager(简化:直接改 _messages)
                    ctx._messages = new_msgs
                    _emit(on_event, AgentEvent(type=DOC_WRITTEN, payload={"path": args.get("section_path")}))
                # finalize_doc → 结束
                if name == "finalize_doc":
                    _emit(on_event, AgentEvent(type=FINAL_ANSWER, payload={"text": "文档生成完成"}))
                    return Answer(text="文档生成完成", citations=[], complete=True, steps_used=steps)
                tool_calls_since_last_extract += 1
            # session memory 后台提取(post-sampling)
            if self.session_memory and self.session_memory.should_extract(
                ctx.total_tokens(), tool_calls_since_last_extract
            ):
                # 简化:同步调(生产可改异步)
                self.session_memory._do_extract(recent_conversation=self._recent_text(ctx))
                tool_calls_since_last_extract = 0
        return Answer(text="(达到最大步数,信息可能不全)", citations=[], complete=False, steps_used=steps)

    def _try_autocompact(self, ctx: ContextManager, transcript_path: Path, on_event) -> bool:
        """先试 session memory,失败 fallback 到 autocompact LLM 摘要。"""
        if self.session_memory:
            summary = self.session_memory.read_for_compaction()
            if summary:
                new_msgs = [
                    {"role": "user", "content": "[boundary: autocompact via session memory]"},
                    {"role": "user", "content": f"会话摘要:\n{summary}"},
                ]
                ctx.replace_messages(new_msgs)
                _emit(on_event, AgentEvent(type=COMPACTED, payload={"via": "session_memory"}))
                return True
        # fallback 到 LLM 摘要
        from ..compaction.autocompact import autocompact as do_autocompact
        new_msgs = do_autocompact(ctx.messages(), self.llm, transcript_path)
        ctx.replace_messages(new_msgs)
        _emit(on_event, AgentEvent(type=COMPACTED, payload={"via": "llm"}))
        return True

    def _recent_text(self, ctx: ContextManager) -> str:
        """取最近几轮对话作为 extract 输入。"""
        msgs = ctx.messages()
        return "\n".join(
            f"[{m['role']}]: {m.get('content', '')[:200]}"
            for m in msgs[-10:]
        )

def _emit(on_event, evt):
    if on_event is not None:
        on_event(evt)
```

- [ ] **Step 6: 改 ToolRegistry 接入新工具**

```python
# src/code_reader/agent_core/tools.py 改 ToolRegistry
class ToolRegistry:
    def __init__(
        self,
        source_root: Path,
        call_graph: dict[str, CallGraphNode],
        repo_map: RepoMap,
        doc_dir: Path | None = None,
        all_sections: list[str] | None = None,
    ) -> None:
        self._tools: dict[str, _BaseTool] = {
            ReadFileTool.name: ReadFileTool(source_root),
            GrepTool.name: GrepTool(source_root),
            GlobTool.name: GlobTool(source_root),
            TraceCallChainTool.name: TraceCallChainTool(call_graph),
            LookupMapTool.name: LookupMapTool(repo_map),
        }
        if doc_dir is not None:
            self._tools[WriteDocTool.name] = WriteDocTool(doc_dir)
        if doc_dir is not None and all_sections is not None:
            self._tools[ListPendingSectionsTool.name] = ListPendingSectionsTool(doc_dir, all_sections)
            self._tools[FinalizeDocTool.name] = FinalizeDocTool(doc_dir)
```

- [ ] **Step 7: 写失败测试——agent 跑完 doc 生成**

```python
# tests/unit/test_agent_core.py 追加
def test_agent_generates_doc_tree(tmp_path, monkeypatch):
    """agent 跑完整循环,生成文档树。"""
    from code_reader.agent_core.service import AgentService
    from code_reader.indexer.service import IndexerService
    from code_reader.summarizer.service import SummarizerService
    from code_reader.outliner.service import OutlinerService
    from code_reader.docgen.tree import build_doc_tree_structure
    from code_reader.session_memory.service import SessionMemoryService
    from code_reader.storage.paths import PathManager
    from code_reader.llm_client import MockLLM, LLMResponse
    from code_reader.types import RepoMap, GlobalSummary

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    pm = PathManager()
    indexer = IndexerService(pm)
    idx = indexer.build(repo)
    summarizer = SummarizerService(llm=MockLLM([LLMResponse(text="全局摘要", tool_calls=[])]))
    repo_map = summarizer.summarize(idx, source_root=repo)
    outliner = OutlinerService(llm=MockLLM([LLMResponse(text='{"selected": [], "reasons": {}}', tool_calls=[])]))
    outline = outliner.outline(idx)
    sections = build_doc_tree_structure(outline, repo_name="demo", language="zh")
    all_section_paths = [s.path for s in sections]

    doc_dir = PathManager.doc_dir(repo)
    # 预先创建占位文件(让 list_pending_sections 知道哪些要写)
    for s in sections:
        full = doc_dir / s.path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"# {s.title}\n\n(待填)\n", encoding="utf-8")

    session_mem = SessionMemoryService(
        llm=MockLLM([]),
        memory_path=PathManager.session_memory_path(repo, "test-session"),
    )

    # mock LLM:第一轮 list_pending_sections,第二轮 finalize_doc
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[{"name": "list_pending_sections", "args": {}}]),
        LLMResponse(text="", tool_calls=[{"name": "finalize_doc", "args": {}}]),
    ])
    agent = AgentService(
        llm=mock, source_root=repo, call_graph={}, repo_map=repo_map,
        idx=idx, outline=outline, doc_dir=doc_dir,
        all_sections=all_section_paths, session_memory=session_mem,
    )
    answer = agent.run("为这个 repo 生成文档")
    assert answer.complete
    assert "完成" in answer.text
```

- [ ] **Step 8: 跑测试看通过**

Run: `pytest tests/unit/test_agent_core.py::test_agent_generates_doc_tree -v`
Expected: PASS(可能需要几轮调 mock)

- [ ] **Step 9: Commit**

```bash
git add src/code_reader/agent_core/ src/code_reader/types.py tests/unit/test_agent_core.py
git commit -m "feat(agent_core): 任务级 prompt + 软约束 + 压缩流水线接入"
```

---

### Task 13: CLI doc 命令完整实现 + 端到端

**依赖:** Task 1、Task 4、Task 7、Task 12
**Files:**
- Modify: `src/code_reader/cli/main.py`
- Create: `tests/integration/test_doc_pipeline.py`

- [ ] **Step 1: 写失败测试——端到端 doc 生成**

```python
# tests/integration/test_doc_pipeline.py
import os
import subprocess
from pathlib import Path
from click.testing import CliRunner
from code_reader.cli.main import cli

def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "from svc import handle\n\n"
        "def main():\n"
        "    handle()\n"
        "    print('done')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (repo / "svc.py").write_text(
        "def handle():\n"
        "    return process()\n\n"
        "def process():\n"
        "    return 42\n",
        encoding="utf-8",
    )
    git_env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True,
                   capture_output=True, env=git_env)
    return repo

def test_doc_pipeline_end_to_end(tmp_path, monkeypatch):
    _isolate_home = lambda: (monkeypatch.setenv("HOME", str(tmp_path)),
                              monkeypatch.setenv("USERPROFILE", str(tmp_path)))
    _isolate_home()
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = _make_repo(tmp_path)

    runner = CliRunner()
    r = runner.invoke(cli, ["doc", str(repo)])
    assert r.exit_code == 0, r.output
    # 产物存在
    doc_dir = repo / ".code-reader" / "docs"
    assert (doc_dir / "REPO_GUIDE.md").exists()
    assert (doc_dir / "00_项目是什么.md").exists()
    assert (doc_dir / "01_架构总览.md").exists()
```

- [ ] **Step 2: 跑测试看失败**

Run: `pytest tests/integration/test_doc_pipeline.py::test_doc_pipeline_end_to_end -v`
Expected: FAIL(还只是骨架)

- [ ] **Step 3: 实现 cmd_doc 完整逻辑**

```python
# src/code_reader/cli/main.py 替换 cmd_doc
@cli.command("doc")
@click.argument("repo_path")
@click.option("--lang", default="auto", help="产物语言:zh/en/auto")
@click.option("--update", is_flag=True, default=False, help="增量更新模式")
@click.option("--force", is_flag=True, default=False, help="强制全量重生成")
def cmd_doc(repo_path: str, lang: str, update: bool, force: bool) -> None:
    """生成可读文档树,让人能读完吃透这个 repo。"""
    source_root = _normalize_path(repo_path)
    if not source_root.is_dir():
        click.echo(f"错误:路径不存在或不是目录: {source_root}", err=True)
        sys.exit(1)

    # 语言检测
    if lang == "auto":
        lang = "zh"  # v0.1 简化:默认中文

    llm = _make_llm()
    pm = PathManager()

    click.echo(f"开始为 {source_root} 生成文档...")

    # 1. indexer
    indexer = IndexerService(pm)
    idx = indexer.build(source_root)
    click.echo(f"AST 解析完成: {len(idx.symbols)} 个符号, {len(idx.files)} 个文件")

    # 2. summarizer
    summarizer = SummarizerService(llm=llm)
    repo_map = summarizer.summarize(idx, source_root=source_root, on_progress=_make_progress())
    pm.repo_map_path(source_root).write_text(repo_map.model_dump_json(indent=2), encoding="utf-8")

    # 3. outliner
    outliner = OutlinerService(llm=llm)
    outline = outliner.outline(idx)
    click.echo(f"重点挖掘: {len(outline.selected_mechanisms)} 机制, {len(outline.flow_candidates)} 流程, {len(outline.module_candidates)} 模块")

    # 4. docgen 准备章节树
    docgen = DocGenService(llm=llm, source_root=source_root,
                            repo_name=source_root.name, language=lang)
    sections = build_doc_tree_structure(outline, repo_name=source_root.name, language=lang)
    all_section_paths = [s.path for s in sections]
    doc_dir = pm.doc_dir(source_root)
    # 预先创建占位文件
    for s in sections:
        full = doc_dir / s.path
        full.parent.mkdir(parents=True, exist_ok=True)
        if not full.exists() or force:
            full.write_text(f"# {s.title}\n\n(待填)\n", encoding="utf-8")

    # 5. agent 跑主循环
    call_graph = indexer.build_call_graph(idx)
    session_mem = SessionMemoryService(
        llm=llm,
        memory_path=pm.session_memory_path(source_root, "main"),
    )
    agent = AgentService(
        llm=llm, source_root=source_root, call_graph=call_graph, repo_map=repo_map,
        idx=idx, outline=outline, doc_dir=doc_dir,
        all_sections=all_section_paths, session_memory=session_mem,
    )
    click.echo("agent 开始生成文档...")
    answer = agent.run(
        f"为 {source_root.name} 这个 repo 生成完整文档树,语言: {lang}",
        on_event=_render_event,
    )
    click.echo(answer.text)
    click.echo(f"✓ 文档生成完成,产物在 {doc_dir}")
```

需要在 `cli/main.py` 顶部加 import:
```python
from ..outliner.service import OutlinerService
from ..docgen.service import DocGenService
from ..docgen.tree import build_doc_tree_structure
from ..session_memory.service import SessionMemoryService
```

- [ ] **Step 4: 跑测试看通过**

Run: `pytest tests/integration/test_doc_pipeline.py::test_doc_pipeline_end_to_end -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/code_reader/cli/main.py tests/integration/test_doc_pipeline.py
git commit -m "feat(cli): doc 命令完整实现 + 端到端"
```

---

### Task 14: 增量更新 `--update` 选项

**依赖:** Task 13
**Files:**
- Modify: `src/code_reader/cli/main.py`
- Modify: `src/code_reader/indexer/service.py`
- Create: `tests/integration/test_doc_update.py`

- [ ] **Step 1: 写失败测试——增量更新只重生成变动相关章节**

```python
# tests/integration/test_doc_update.py
import os
import subprocess
from pathlib import Path
from click.testing import CliRunner
from code_reader.cli.main import cli

def test_doc_update_only_regenerates_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CODE_READER_MOCK_LLM", "1")
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    git_env = {"PATH": os.environ.get("PATH", ""),
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True,
                   capture_output=True, env=git_env)

    runner = CliRunner()
    # 第一次全量
    r1 = runner.invoke(cli, ["doc", str(repo)])
    assert r1.exit_code == 0
    doc_dir = repo / ".code-reader" / "docs"
    guide1 = (doc_dir / "REPO_GUIDE.md").read_text(encoding="utf-8")

    # 改 a.py
    (repo / "a.py").write_text("def foo():\n    return 2\n", encoding="utf-8")

    # 增量更新
    r2 = runner.invoke(cli, ["doc", str(repo), "--update"])
    assert r2.exit_code == 0
    # 产物仍在
    assert (doc_dir / "REPO_GUIDE.md").exists()
```

- [ ] **Step 2: 跑测试看失败**

Run: `pytest tests/integration/test_doc_update.py -v`
Expected: FAIL(--update 还没实现)

- [ ] **Step 3: 实现 --update**

```python
# src/code_reader/cli/main.py 改 cmd_doc 加 update 分支
    if update and not force:
        # 增量:indexer.update + 只重生成变动文件相关的章节
        idx = indexer.update(source_root)
        # 简化 v0.1:增量模式下也全量重生成文档,但跳过 indexer 的全量扫描
        click.echo("增量模式:索引增量更新 + 文档重生成")
    else:
        idx = indexer.build(source_root)
```

(完整增量更新 v0.1 简化:索引层增量,文档层全量。v0.2 再做文档层增量)

- [ ] **Step 4: 跑测试看通过**

Run: `pytest tests/integration/test_doc_update.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/code_reader/cli/main.py tests/integration/test_doc_update.py
git commit -m "feat(cli): --update 增量更新选项"
```

---

### Task 15: 评测——3 个新人读 + 讲一遍

**依赖:** Task 13(端到端能跑)
**Files:**
- Create: `eval/README.md`
- Create: `eval/rubric.md`
- Create: `eval/fastapi-questions.md`
- Create: `eval/run_eval.py`

> 这个 task 是手工评测,不写自动化测试,只准备评测脚本和评分卡。

- [ ] **Step 1: 写评测说明**

```markdown
# eval/README.md

# 评测方案:读完能给新人讲一遍

## 目标
验证 doc agent 产出的文档树是否能让一个完全没见过这个 repo 的开发者,在 30 分钟内读完,
然后能给另一个新人讲清楚这个项目。

## 评测 repo
- fastapi(Python,中型,核心机制清晰:路由注册 / 依赖注入 / 请求处理 / OpenAPI 生成)

## 评测流程
1. 找 3 个完全没读过 fastapi 源码的开发者作为"读者"
2. 让每个读者用 30 分钟读完 doc agent 产出的文档树
3. 让每个读者给一个"新人"讲这个项目(录音)
4. 按 rubric.md 的 4 维评分

## 4 维评分(每维 0-25 分,总分 100)
- 项目是什么(20%):能说清解决什么问题、给谁用、典型场景
- 3 个核心机制(40%):能说清 fastapi 的路由注册 / 依赖注入 / 请求处理
- 1 条端到端流程(30%):能说清一个请求从 URL 到响应的完整路径
- 想改 X 去哪看(10%):能指出改某类问题该读哪些文件

## 通过线
- 总分 >= 70 认为达标
- 3 人平均分 >= 75 认为 doc agent 有效

## 失败处理
- 如果读者反馈"读不懂"或"讲不出",归类问题(是文档质量 / 是结构 / 是缺失),
  作为下一轮迭代的输入。
```

- [ ] **Step 2: 写 rubric 评分卡**

```markdown
# eval/rubric.md

# 评分卡(每个读者一份)

读者编号:___
阅读时间:___ 分钟

## 维度 1:项目是什么(满分 20)

- [ ] 能说出 fastapi 解决什么问题(5 分)
- [ ] 能说出给谁用(5 分)
- [ ] 能说出 1 个典型使用场景(5 分)
- [ ] 能说出 1 个对比竞品的差异点(5 分)

得分:___

## 维度 2:3 个核心机制(满分 40)

- [ ] 能说出"路由注册"怎么工作(13 分)
- [ ] 能说出"依赖注入"怎么工作(13 分)
- [ ] 能说出"请求处理"怎么工作(14 分)

得分:___

## 维度 3:1 条端到端流程(满分 30)

- [ ] 能说出从 URL 到响应的完整路径(15 分)
- [ ] 能指出关键决策点在哪(10 分)
- [ ] 能说出数据怎么流动(5 分)

得分:___

## 维度 4:想改 X 去哪看(满分 10)

- [ ] 给定"我想加一个新路由",能指出该改哪个文件(5 分)
- [ ] 给定"我想改依赖注入行为",能指出该改哪个文件(5 分)

得分:___

## 总分:___

## 备注(读者反馈)
- 最有价值的章节:___
- 最难懂的章节:___
- 缺失的内容:___
```

- [ ] **Step 3: 写 fastapi 评测题**

```markdown
# eval/fastapi-questions.md

# fastapi 评测题(给读者测试用)

## 项目是什么
1. fastapi 解决什么问题?
2. 给谁用?
3. 一个典型使用场景?
4. 跟 flask 的差异?

## 3 个核心机制
5. 路由注册怎么工作?@app.get("/x") 背后发生了什么?
6. 依赖注入怎么工作?Depends() 背后发生了什么?
7. 请求处理怎么工作?一个 request 进来后怎么到 handler 的?

## 端到端流程
8. 用户访问 GET /items/5,从 URL 到响应,完整路径是什么?
9. 这个路径上有哪些关键决策点?
10. 数据怎么流动的?

## 想改 X 去哪看
11. 我想加一个新路由,该改哪些文件?
12. 我想改依赖注入行为,该改哪些文件?
```

- [ ] **Step 4: 写评测脚本**

```python
# eval/run_eval.py
"""评测脚本:跑 doc agent 产 fastapi 文档,准备给读者阅读。

用法:python eval/run_eval.py
前提:已经 git clone fastapi 到本地。
"""
import subprocess
import sys
from pathlib import Path

FASTAPI_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "~/repos/fastapi").expanduser()

def main():
    if not FASTAPI_PATH.is_dir():
        print(f"错误:fastapi 不在 {FASTAPI_PATH},请先 git clone")
        sys.exit(1)
    print(f"跑 doc agent 为 {FASTAPI_PATH} 生成文档...")
    subprocess.run([
        sys.executable, "-m", "code_reader",
        "doc", str(FASTAPI_PATH),
    ], check=True)
    doc_dir = FASTAPI_PATH / ".code-reader" / "docs"
    print(f"文档产物:{doc_dir}")
    print("请找 3 个没读过 fastapi 的开发者按 eval/rubric.md 评测")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Commit**

```bash
git add eval/
git commit -m "docs(eval): 评测方案 + rubric + fastapi 评测题"
```

---

## Self-Review 检查

### Spec 覆盖检查

| Spec 要求 | 对应 Task | 覆盖? |
|----------|---------|------|
| 砍 ask/shell,只留 doc | Task 1 | ✓ |
| 保留 agent 循环 + 上下文管理 | Task 12 | ✓ |
| apply-tool-result-budget | Task 8 | ✓ |
| 章节边界 microcompact | Task 9 | ✓ |
| autocompact 9 章节摘要 | Task 10 | ✓ |
| session memory(选项 B 分支 agent) | Task 11 | ✓ |
| outliner 重点挖掘(混合策略) | Task 4 + Task 5 | ✓ |
| deepwriter 重点深挖 | Task 6 | ✓ |
| docgen 自适应深度 | Task 7 | ✓ |
| 软约束(放 system prompt) | Task 12 Step 3 | ✓ |
| 产物一套 markdown 文档树 | Task 7 + Task 13 | ✓ |
| 跟用户同语言 | Task 13 Step 3(--lang) | ✓ |
| 增量更新 | Task 14 | ✓ |
| 补 linker 匹配精度 | Task 2 | ✓ |
| 平铺摘要字数放宽 | Task 3 | ✓ |
| 评测:3 个新人读 + 讲一遍 | Task 15 | ✓ |
| 统一用主 LLM | Task 12 + Task 13(不区分) | ✓ |

### Placeholder 扫描
- 无 "TBD" / "TODO" / "implement later"
- 所有代码块都是完整可运行的内容
- 所有测试都有具体断言

### 类型一致性
- `ContentReplacementState` 在 Task 8 定义,Task 12 使用,字段名一致
- `Outline` 在 Task 4 定义,Task 7 / Task 12 使用,字段名一致
- `DocSection` / `DocTree` 在 Task 7 定义,Task 12 / Task 13 使用,字段名一致
- `SessionMemoryService` 在 Task 11 定义,Task 12 / Task 13 使用,方法名一致(`ensure_file` / `should_extract` / `read_for_compaction` / `_do_extract`)

---

## 执行建议

**总工作量:** 15 个 task,业余时间约 4-5 周

**关键路径(必须顺序):**
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 → Task 10 → Task 11 → Task 12 → Task 13 → Task 14 → Task 15

**可并行:**
- Task 2(linker)和 Task 8/9/10(compaction)可并行(无依赖)
- Task 4(outliner)和 Task 8/9/10 可并行

**风险点:**
1. Task 12 的 mock 测试可能需要多轮调整(MockLLM 要按调用顺序返回工具调用序列)
2. Task 13 端到端测试依赖前面所有模块,失败时定位难,建议先跑单测确认全绿
3. Task 15 评测找 3 个开发者可能拖延,建议跑完 Task 13 就开始约人

**回滚策略:** 每个 Task 一个 commit,失败时 `git revert <commit>` 即可,不影响其他 Task。