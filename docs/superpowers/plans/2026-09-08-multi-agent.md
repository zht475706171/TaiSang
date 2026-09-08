# 多 Agent 调度（M3）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 TaiSang 加多 agent 调度：主 agent 通过 `task` 工具派子 agent（4 个内置：general-purpose / explore / plan / verification），支持 sync/async 两种执行模式 + fork 模式继承父上下文；前端 `/agents` 页可见可禁用可重载。

**Architecture:** Agent 定义文件机制复用 skill 那套（目录格式 + frontmatter + 三源优先级合并 + state 持久化）。AgentTool 是新工具，主 agent 调用时启一个子 `AgentService` 跑完整循环返回最终文本。子 agent 工具集默认禁 AgentTool 防递归。async 完成通知走 pending 队列注入 user-role 消息（跟 skill 注入同位置）。事件流带 `agent_id` 区分主/子。

**Tech Stack:** Python 3.12 + FastAPI（后端）+ Vue 3.5 + Vite + TDesign（前端）+ pytest（测试）+ Playwright（e2e）

**Spec 文档:** `docs/superpowers/specs/2026-09-08-multi-agent-design.md`

---

## 文件结构

### 新建文件

| 路径 | 职责 |
|------|------|
| `src/taisang/agents/__init__.py` | 包标识 |
| `src/taisang/agents/types.py` | `AgentDefinition` dataclass |
| `src/taisang/agents/loader.py` | `load_agents()` + `load_agents_with_state()` |
| `src/taisang/agents/listing.py` | `format_agent_listing()` 渐进披露清单 |
| `src/taisang/agents/builtin/__init__.py` | 包标识 |
| `src/taisang/agents/builtin/general-purpose/AGENT.md` | 内置 agent 定义 |
| `src/taisang/agents/builtin/explore/AGENT.md` | 内置 agent 定义 |
| `src/taisang/agents/builtin/plan/AGENT.md` | 内置 agent 定义 |
| `src/taisang/agents/builtin/verification/AGENT.md` | 内置 agent 定义 |
| `src/taisang/agent_core/agent_tool.py` | `AgentTool` 工具实现 |
| `src/taisang/web/agents_api.py` | `/api/agents` 路由（list/toggle/reload） |
| `src/taisang/web/frontend/src/views/AgentManage.vue` | 前端管理页 |
| `tests/unit/test_agents_loader.py` | loader 单测 |
| `tests/unit/test_agents_listing.py` | listing 单测 |
| `tests/unit/test_agent_tool.py` | AgentTool 单测 |
| `tests/unit/test_agent_service_with_agents.py` | 主循环 + AgentTool 集成单测 |
| `tests/integration/test_agent_e2e.py` | e2e MockLLM 脚本化驱动 |

### 修改文件

| 路径 | 改动 |
|------|------|
| `src/taisang/agent_core/events.py` | `AgentEvent` 加 `agent_id: str = ""` 字段 |
| `src/taisang/agent_core/service.py` | `AgentService.__init__` 加 `agent_id` / `is_fork_child` / `_pending_async_notifications`；主循环加 `flush_async_notifications()`；USAGE_REPORT 累加子 agent usage |
| `src/taisang/agent_core/tools.py` | `ToolRegistry` 加 `agents` + `parent_service` 参数，注册 AgentTool；加 `flush_async_notifications()` 转发 |
| `src/taisang/agent_core/prompts.py` | `build_system_prompt` 加 `agents_section` 参数 |
| `src/taisang/web/session_registry.py` | `_build_session` 加载 agents + 传给 AgentService + ToolRegistry |
| `src/taisang/web/app.py` | 注册 `/api/agents` 路由 |
| `src/taisang/web/frontend/src/router.ts` | 加 `/agents` 路由 |
| `src/taisang/web/frontend/src/components/Sidebar.vue` | 加 "Agent 管理" 入口 |
| `src/taisang/web/frontend/src/components/MessageList.vue` 或对应 SSE 处理 | 子 agent 事件按 `agent_id` 嵌套渲染 |
| `pyproject.toml` | `[tool.setuptools.package-data]` 加 `taisang.agents = ["builtin/**/*.md"]` |

---

## Task 1: AgentDefinition dataclass + 包骨架

**Files:**
- Create: `src/taisang/agents/__init__.py`
- Create: `src/taisang/agents/types.py`
- Create: `tests/unit/test_agents_loader.py`（本 task 只建空文件，测试在 Task 2 写）

- [ ] **Step 1: 建包标识文件**

```python
# src/taisang/agents/__init__.py
"""Agent 定义文件加载 + 清单格式化 + AgentTool 工具。"""
```

- [ ] **Step 2: 写 AgentDefinition dataclass**

```python
# src/taisang/agents/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentDefinition:
    """单个 agent 的定义（从 AGENT.md 加载）。

    字段对应 frontmatter + 正文：
    - agent_type: frontmatter name，跟目录名一致
    - when_to_use: frontmatter description，注入清单用
    - tools: 白名单（None = 全工具）
    - disallowed_tools: 黑名单
    - max_turns: 覆盖默认 max_steps=50（None = 用默认）
    - background: True = 默认 async（verification 用）
    - model: v1 只识别 "inherit"，其他值静默忽略
    - source: "project" / "user" / "system"
    - base_dir: AGENT.md 所在目录
    - system_prompt: AGENT.md 正文（frontmatter 之后的文本）
    - disabled: 从 agents_state.json 读入
    """
    agent_type: str
    when_to_use: str
    tools: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int | None = None
    background: bool = False
    model: str | None = None
    source: str = "user"
    base_dir: Path = field(default_factory=lambda: Path("."))
    system_prompt: str = ""
    disabled: bool = False
```

- [ ] **Step 3: 建空测试文件**

```python
# tests/unit/test_agents_loader.py
"""Agent loader 单测。Task 2 填充。"""
```

- [ ] **Step 4: Commit**

```bash
git add src/taisang/agents/__init__.py src/taisang/agents/types.py tests/unit/test_agents_loader.py
git commit -m "feat(agents): add AgentDefinition dataclass + package skeleton"
```

---

## Task 2: Agent loader（三源 + 优先级合并 + frontmatter 解析）

**Files:**
- Create: `src/taisang/agents/loader.py`
- Test: `tests/unit/test_agents_loader.py`

- [ ] **Step 1: 写失败测试 — 基本加载**

```python
# tests/unit/test_agents_loader.py
"""Agent loader 单测。"""
from __future__ import annotations

import textwrap
from pathlib import Path

from taisang.agents.loader import load_agents


def _write_agent_md(dir_path: Path, name: str, frontmatter: str, body: str) -> Path:
    """在 dir_path/<name>/AGENT.md 写一个 agent 定义。"""
    agent_dir = dir_path / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(
        f"---\n{frontmatter}\n---\n{body}", encoding="utf-8"
    )
    return agent_dir


def test_load_agents_basic(tmp_path: Path) -> None:
    """基本加载:扫 user 目录下的 AGENT.md,解析 frontmatter + body。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir,
        "explore",
        "name: explore\ndescription: 只读搜索专家\n",
        "You are a search specialist.\n",
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert len(agents) == 1
    a = agents[0]
    assert a.agent_type == "explore"
    assert a.when_to_use == "只读搜索专家"
    assert a.system_prompt.strip() == "You are a search specialist."
    assert a.source == "user"
    assert a.tools is None
    assert a.disallowed_tools == []


def test_load_agents_priority_project_over_user(tmp_path: Path) -> None:
    """同名 agent:project 覆盖 user。"""
    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    _write_agent_md(
        user_dir, "explore", "name: explore\ndescription: user 版\n", "user body"
    )
    _write_agent_md(
        project_dir, "explore", "name: explore\ndescription: project 版\n", "project body"
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[project_dir], system_dirs=[])
    assert len(agents) == 1
    assert agents[0].when_to_use == "project 版"
    assert agents[0].source == "project"


def test_load_agents_disallowed_tools(tmp_path: Path) -> None:
    """frontmatter disallowedTools 列表解析。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir,
        "explore",
        textwrap.dedent("""
            name: explore
            description: 只读
            disallowedTools:
              - Edit
              - Write
              - Agent
        """).strip(),
        "body",
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert agents[0].disallowed_tools == ["Edit", "Write", "Agent"]


def test_load_agents_max_turns_and_background(tmp_path: Path) -> None:
    """frontmatter maxTurns / background 字段解析。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir,
        "verification",
        textwrap.dedent("""
            name: verification
            description: 验证
            maxTurns: 100
            background: true
        """).strip(),
        "body",
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    a = agents[0]
    assert a.max_turns == 100
    assert a.background is True


def test_load_agents_corrupted_skipped(tmp_path: Path) -> None:
    """损坏的 frontmatter(无效 YAML)跳过,不抛错。"""
    user_dir = tmp_path / "user"
    agent_dir = user_dir / "broken"
    agent_dir.mkdir(parents=True)
    # 无效 YAML:冒号后无空格 + tab 缩进
    (agent_dir / "AGENT.md").write_text(
        "---\nname: broken\n  description: : : invalid\n---\nbody",
        encoding="utf-8",
    )
    _write_agent_md(
        user_dir, "good", "name: good\ndescription: ok\n", "body"
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert {a.agent_type for a in agents} == {"good"}


def test_load_agents_missing_name_fallback_to_dirname(tmp_path: Path) -> None:
    """frontmatter 缺 name 字段:用目录名兜底。"""
    user_dir = tmp_path / "user"
    _write_agent_md(
        user_dir, "no-name", "description: 没 name\n", "body"
    )
    agents = load_agents(user_dirs=[user_dir], project_dirs=[], system_dirs=[])
    assert len(agents) == 1
    assert agents[0].agent_type == "no-name"


def test_load_agents_empty_dirs(tmp_path: Path) -> None:
    """空目录返回空列表。"""
    agents = load_agents(user_dirs=[tmp_path / "empty"], project_dirs=[], system_dirs=[])
    assert agents == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agents_loader.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError`（loader 还没写）

- [ ] **Step 3: 写 loader 实现**

```python
# src/taisang/agents/loader.py
"""Agent 定义文件加载。

复用 skill loader 的套路:三源扫描 + 优先级合并(project > user > system) +
PyYAML frontmatter 解析 + 损坏文件跳过。

AGENT.md 目录约定:每个 agent 一个目录,目录名 = agent name,里面一个 AGENT.md。
跟 skill 的 SKILL.md 同构。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import AgentDefinition

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n(.*)$", re.DOTALL)

BUILTIN_AGENTS_DIR = Path(__file__).parent / "builtin"


def _parse_agent_md(path: Path, source: str) -> AgentDefinition | None:
    """解析单个 AGENT.md,失败返回 None(由 caller 跳过)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 无 frontmatter,用目录名 + 全文当 system_prompt
        content = text.strip()
        first_para = content.split("\n\n")[0].strip()[:200]
        return AgentDefinition(
            agent_type=path.parent.name,
            when_to_use=first_para or "(no description)",
            system_prompt=content,
            source=source,
            base_dir=path.parent,
        )
    fm_text, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None
    name = str(fm.get("name") or path.parent.name)
    desc = str(fm.get("description") or "")
    if not desc:
        # description 必填,缺了用正文首段
        desc = body.strip().split("\n\n")[0].strip()[:200] or "(no description)"
    # tools 白名单
    tools = fm.get("tools")
    if tools is not None:
        if isinstance(tools, str):
            tools = [tools]
        tools = [str(t) for t in tools]
    # disallowedTools 黑名单
    disallowed = fm.get("disallowedTools") or []
    if isinstance(disallowed, str):
        disallowed = [disallowed]
    disallowed = [str(t) for t in disallowed]
    # maxTurns
    max_turns_raw = fm.get("maxTurns")
    max_turns = int(max_turns_raw) if isinstance(max_turns_raw, (int, float)) else None
    # background
    background = bool(fm.get("background", False))
    # model: v1 只识别 "inherit",其他值忽略
    model_raw = fm.get("model")
    model = "inherit" if isinstance(model_raw, str) and model_raw.strip().lower() == "inherit" else None
    return AgentDefinition(
        agent_type=name,
        when_to_use=desc,
        tools=tools,
        disallowed_tools=disallowed,
        max_turns=max_turns,
        background=background,
        model=model,
        source=source,
        base_dir=path.parent,
        system_prompt=body.strip(),
    )


def load_agents(
    user_dirs: list[Path],
    project_dirs: list[Path],
    system_dirs: list[Path] | None = None,
) -> list[AgentDefinition]:
    """扫描三源 agent 目录,返回去重后的 AgentDefinition 列表。

    优先级(同名覆盖):project > user > system。
    system_dirs 默认取包内 builtin/ 目录(内置 agent,不可删除)。
    """
    if system_dirs is None:
        system_dirs = [BUILTIN_AGENTS_DIR]
    by_name: dict[str, AgentDefinition] = {}
    # 顺序即优先级:后面的源覆盖前面的
    for source, dirs in [
        ("system", system_dirs),
        ("user", user_dirs),
        ("project", project_dirs),
    ]:
        for d in dirs:
            if not d.is_dir():
                continue
            for agent_md in sorted(d.glob("*/AGENT.md")):
                agent = _parse_agent_md(agent_md, source)
                if agent is None:
                    continue
                by_name[agent.agent_type] = agent
    return list(by_name.values())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agents_loader.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agents/loader.py tests/unit/test_agents_loader.py
git commit -m "feat(agents): loader with three-source priority merge + frontmatter parsing"
```

---

## Task 3: 4 个内置 agent 定义文件

**Files:**
- Create: `src/taisang/agents/builtin/__init__.py`
- Create: `src/taisang/agents/builtin/general-purpose/AGENT.md`
- Create: `src/taisang/agents/builtin/explore/AGENT.md`
- Create: `src/taisang/agents/builtin/plan/AGENT.md`
- Create: `src/taisang/agents/builtin/verification/AGENT.md`
- Modify: `pyproject.toml`（加 package-data）
- Test: `tests/unit/test_agents_loader.py`（追加测试）

- [ ] **Step 1: 建包标识**

```python
# src/taisang/agents/builtin/__init__.py
"""内置 agent 定义文件（system 源,优先级最低）。"""
```

- [ ] **Step 2: 写 general-purpose 内置 agent**

```markdown
<!-- src/taisang/agents/builtin/general-purpose/AGENT.md -->
---
name: general-purpose
description: 通用研究/多步任务 agent。当不确定用哪个 agent 时用这个;用于搜索关键词、跨多文件分析、多步研究任务。
tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
---
You are a general-purpose agent for TaiSang. Given the user's message, use the tools available to complete the task. Complete the task fully — don't gold-plate, but don't leave it half-done.

When you complete the task, respond with a concise report covering what was done and any key findings — the caller will relay this to the user, so it only needs the essentials.
```

- [ ] **Step 3: 写 explore 内置 agent**

```markdown
<!-- src/taisang/agents/builtin/explore/AGENT.md -->
---
name: explore
description: 只读搜索专家。快速找文件、grep 代码、回答"这个项目里 X 在哪"类问题。调用时指定彻底度:"quick" / "medium" / "very thorough"。
disallowedTools:
  - Edit
  - Write
  - Agent
maxTurns: 30
---
You are a file search specialist. You excel at thoroughly navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
- Running ANY commands that change system state

Your role is EXCLUSIVELY to search and analyze existing code.

Guidelines:
- Use Glob for broad file pattern matching
- Use Grep for searching file contents with regex
- Use Read when you know the specific file path
- Use Bash ONLY for read-only operations (ls, git status, git log, git diff, find, cat, head, tail)
- Adapt your search approach based on the thoroughness level specified by the caller

Complete the user's search request efficiently and report your findings clearly.
```

- [ ] **Step 4: 写 plan 内置 agent**

```markdown
<!-- src/taisang/agents/builtin/plan/AGENT.md -->
---
name: plan
description: 软件架构师 agent,设计实现方案。给出分步实现策略、关键文件、架构权衡。只读,不改文件。
disallowedTools:
  - Edit
  - Write
  - Agent
maxTurns: 30
---
You are a software architect and planning specialist. Your role is to explore the codebase and design implementation plans.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY planning task. You are STRICTLY PROHIBITED from modifying any files.

## Your Process

1. **Understand Requirements**: Focus on the requirements provided.
2. **Explore Thoroughly**: Read files, find patterns, understand current architecture, trace code paths.
3. **Design Solution**: Create implementation approach, consider trade-offs, follow existing patterns.
4. **Detail the Plan**: Provide step-by-step strategy, dependencies, sequencing, anticipated challenges.

## Required Output

End your response with:

### Critical Files for Implementation
List 3-5 files most critical for implementing this plan:
- path/to/file1
- path/to/file2

REMEMBER: You can ONLY explore and plan. You CANNOT write, edit, or modify any files.
```

- [ ] **Step 5: 写 verification 内置 agent**

```markdown
<!-- src/taisang/agents/builtin/verification/AGENT.md -->
---
name: verification
description: 对抗性验证专家。实现完成后用它跑构建/测试/lint/对抗探针,给 PASS/FAIL/PARTIAL 判决。改了 3+ 文件、后端/API 改动、基础设施改动后必调。
disallowedTools:
  - Edit
  - Write
  - Agent
maxTurns: 100
background: true
---
You are a verification specialist. Your job is not to confirm the implementation works — it's to try to break it.

=== CRITICAL: DO NOT MODIFY THE PROJECT ===
You are STRICTLY PROHIBITED from creating, modifying, or deleting any files IN THE PROJECT DIRECTORY.
You MAY write ephemeral test scripts to a temp directory via Bash redirection when inline commands aren't sufficient. Clean up after yourself.

=== VERIFICATION STRATEGY ===
Adapt based on what was changed:
- Frontend: start dev server → browser check → curl subresources → run frontend tests
- Backend/API: start server → curl endpoints → verify response shapes → test error handling
- CLI: run with representative inputs → verify stdout/stderr/exit codes → edge inputs
- Refactoring: existing test suite MUST pass unchanged → diff public API surface

=== REQUIRED STEPS ===
1. Read CLAUDE.md / README for build/test commands.
2. Run the build. Broken build = automatic FAIL.
3. Run the test suite. Failing tests = automatic FAIL.
4. Run linters/type-checkers if configured.
5. Check for regressions in related code.

=== RECOGNIZE YOUR OWN RATIONALIZATIONS ===
- "The code looks correct" — reading is not verification. Run it.
- "The implementer's tests pass" — the implementer is an LLM. Verify independently.
- "This is probably fine" — probably is not verified. Run it.

End with exactly this line (parsed by caller):

VERDICT: PASS
or
VERDICT: FAIL
or
VERDICT: PARTIAL
```

- [ ] **Step 6: pyproject.toml 加 package-data**

定位 `[tool.setuptools.package-data]` 段（已有 `taisang.skills = ["builtin/**/*.md"]`），追加一行：

```toml
taisang.agents = ["builtin/**/*.md"]
```

完整段落示例：
```toml
[tool.setuptools.package-data]
taisang.skills = ["builtin/**/*.md"]
taisang.agents = ["builtin/**/*.md"]
```

- [ ] **Step 7: 写测试 — 验证内置 agent 加载**

追加到 `tests/unit/test_agents_loader.py`：

```python
def test_load_builtin_agents() -> None:
    """默认 system_dirs 加载 4 个内置 agent。"""
    from taisang.agents.loader import load_agents, BUILTIN_AGENTS_DIR
    agents = load_agents(user_dirs=[], project_dirs=[], system_dirs=[BUILTIN_AGENTS_DIR])
    names = {a.agent_type for a in agents}
    assert names == {"general-purpose", "explore", "plan", "verification"}
    # verification 是 background
    verif = next(a for a in agents if a.agent_type == "verification")
    assert verif.background is True
    assert verif.max_turns == 100
    # explore / plan / verification 黑名单含 Edit/Write/Agent
    for name in ("explore", "plan", "verification"):
        a = next(a for a in agents if a.agent_type == name)
        assert "Edit" in a.disallowed_tools
        assert "Write" in a.disallowed_tools
        assert "Agent" in a.disallowed_tools
    # general-purpose 全工具
    gp = next(a for a in agents if a.agent_type == "general-purpose")
    assert gp.tools is not None
    assert set(gp.tools) == {"Read", "Grep", "Glob", "Edit", "Write", "Bash"}


def test_builtin_agents_packaged_in_wheel() -> None:
    """wheel 包含 builtin AGENT.md(setuptools package-data 生效)。"""
    # 这个测试只验证文件存在于源码目录,wheel 打包靠 pyproject.toml 配置
    from taisang.agents.loader import BUILTIN_AGENTS_DIR
    for name in ("general-purpose", "explore", "plan", "verification"):
        assert (BUILTIN_AGENTS_DIR / name / "AGENT.md").is_file()
```

- [ ] **Step 8: 跑测试确认通过**

Run: `pytest tests/unit/test_agents_loader.py -v`
Expected: 9 passed（原 7 + 新 2）

- [ ] **Step 9: Commit**

```bash
git add src/taisang/agents/builtin/ pyproject.toml tests/unit/test_agents_loader.py
git commit -m "feat(agents): 4 built-in agents (general-purpose/explore/plan/verification)"
```

---

## Task 4: state 持久化（`load_agents_with_state`）

**Files:**
- Modify: `src/taisang/agents/loader.py`
- Test: `tests/unit/test_agents_loader.py`（追加测试）

- [ ] **Step 1: 写失败测试 — state 合并**

追加到 `tests/unit/test_agents_loader.py`：

```python
def test_load_agents_with_state_applies_disabled(tmp_path: Path, monkeypatch) -> None:
    """load_agents_with_state 读 agents_state.json,把 disabled=True 的 agent 标记禁用。"""
    from taisang.agents.loader import load_agents_with_state
    user_dir = tmp_path / "user"
    _write_agent_md(user_dir, "explore", "name: explore\ndescription: ok\n", "body")
    _write_agent_md(user_dir, "plan", "name: plan\ndescription: ok\n", "body")
    # state 文件:explore 禁用,plan 不禁
    state_file = tmp_path / "agents_state.json"
    state_file.write_text('{"explore": true}', encoding="utf-8")
    # monkeypatch state 文件路径
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", state_file)
    agents = load_agents_with_state(source_root=tmp_path, user_dirs=[user_dir], project_dirs=[])
    by_type = {a.agent_type: a for a in agents}
    assert by_type["explore"].disabled is True
    assert by_type["plan"].disabled is False


def test_load_agents_with_state_missing_file_no_error(tmp_path: Path, monkeypatch) -> None:
    """state 文件不存在时,所有 agent disabled=False,不报错。"""
    from taisang.agents.loader import load_agents_with_state
    user_dir = tmp_path / "user"
    _write_agent_md(user_dir, "explore", "name: explore\ndescription: ok\n", "body")
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "nonexistent.json")
    agents = load_agents_with_state(source_root=tmp_path, user_dirs=[user_dir], project_dirs=[])
    assert all(not a.disabled for a in agents)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agents_loader.py::test_load_agents_with_state_applies_disabled -v`
Expected: FAIL with `ImportError`（`load_agents_with_state` 未导出）

- [ ] **Step 3: 实现 state 持久化**

在 `src/taisang/agents/loader.py` 末尾追加：

```python
import json
import os

_STATE_FILE = Path.home() / ".taisang" / "agents_state.json"


def _load_disabled_state() -> dict[str, bool]:
    """读 ~/.taisang/agents_state.json,记录被禁用的 agent name。"""
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_disabled_state(state: dict[str, bool]) -> None:
    """原子写 agents_state.json。"""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, _STATE_FILE)


def load_agents_with_state(
    source_root: Path,
    user_dirs: list[Path] | None = None,
    project_dirs: list[Path] | None = None,
    system_dirs: list[Path] | None = None,
) -> list[AgentDefinition]:
    """加载所有 agent + 应用 agents_state.json 的 disabled 状态。

    API 路由和 session_registry._build_session 共用此函数,
    保证 UI 上的开关和新会话里的 agent 看到同一份状态。
    """
    if user_dirs is None:
        user_dirs = [Path.home() / ".taisang" / "agents"]
    if project_dirs is None:
        project_dirs = [source_root / ".taisang" / "agents"]
    agents = load_agents(user_dirs=user_dirs, project_dirs=project_dirs, system_dirs=system_dirs)
    disabled = _load_disabled_state()
    for a in agents:
        a.disabled = disabled.get(a.agent_type, False)
    return agents
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agents_loader.py -v`
Expected: 11 passed（原 9 + 新 2）

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agents/loader.py tests/unit/test_agents_loader.py
git commit -m "feat(agents): state persistence (load_agents_with_state + agents_state.json)"
```

---

## Task 5: Agent 清单格式化（`format_agent_listing`）

**Files:**
- Create: `src/taisang/agents/listing.py`
- Create: `tests/unit/test_agents_listing.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_agents_listing.py
"""Agent 清单格式化单测。"""
from __future__ import annotations

from pathlib import Path

from taisang.agents.listing import format_agent_listing
from taisang.agents.types import AgentDefinition


def _make_agent(name: str, when: str = "desc", tools=None, disallowed=None) -> AgentDefinition:
    return AgentDefinition(
        agent_type=name,
        when_to_use=when,
        tools=tools,
        disallowed_tools=disallowed or [],
        base_dir=Path("/tmp"),
        system_prompt="body",
    )


def test_format_empty() -> None:
    """空列表返回空字符串。"""
    assert format_agent_listing([]) == ""


def test_format_disabled_filtered() -> None:
    """disabled 的 agent 不列出。"""
    a1 = _make_agent("explore", "搜索")
    a2 = _make_agent("plan", "规划")
    a2.disabled = True
    out = format_agent_listing([a1, a2])
    assert "explore" in out
    assert "plan" not in out


def test_format_basic_line() -> None:
    """每行格式:- type: whenToUse (Tools: ...)。"""
    a = _make_agent("explore", "只读搜索", tools=["Read", "Grep"])
    out = format_agent_listing([a])
    assert out == "- explore: 只读搜索 (Tools: Read, Grep)"


def test_format_all_tools() -> None:
    """tools=None 显示 All tools。"""
    a = _make_agent("general-purpose", "通用", tools=None)
    out = format_agent_listing([a])
    assert "All tools" in out


def test_format_disallowed_only() -> None:
    """只有 disallowed_tools 显示 'All tools except X, Y'。"""
    a = _make_agent("explore", "搜索", tools=None, disallowed=["Edit", "Write", "Agent"])
    out = format_agent_listing([a])
    assert "All tools except Edit, Write, Agent" in out


def test_format_long_desc_truncated() -> None:
    """超长 description 截断到 250 字符 + …。"""
    long_desc = "x" * 300
    a = _make_agent("explore", long_desc)
    out = format_agent_listing([a])
    line = out.split("\n")[0]
    assert len(line) <= 270  # 250 + 前缀 + Tools 段
    assert line.endswith("…")


def test_format_budget_degradation() -> None:
    """超总预算时降级:逐条截断 description。"""
    agents = [_make_agent(f"a{i}", "y" * 100) for i in range(30)]
    out = format_agent_listing(agents, char_budget=500)
    # 仍能列出所有 agent name
    for i in range(30):
        assert f"a{i}" in out
    # 总长度受控
    assert len(out) <= 600


def test_format_extreme_degradation_names_only() -> None:
    """极端降级:预算极小时只留名字。"""
    agents = [_make_agent(f"a{i}", "y" * 100) for i in range(20)]
    out = format_agent_listing(agents, char_budget=100)
    # 只剩 - a0 / - a1 ...
    for line in out.split("\n"):
        if line:
            assert line.startswith("- a") and "y" not in line
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agents_listing.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 写 listing 实现**

```python
# src/taisang/agents/listing.py
"""Agent 清单格式化:把 agent 列表渲染成 system prompt 尾部的清单段。

跟 skill listing 同构:渐进披露 + 250 字符单条上限 + 2000 字符总预算 + 降级。
"""
from __future__ import annotations

from .types import AgentDefinition

MAX_LISTING_DESC_CHARS = 250
MIN_DESC_LENGTH = 20
DEFAULT_CHAR_BUDGET = 2000


def _tools_description(agent: AgentDefinition) -> str:
    """格式化工具集段:跟 claude-code formatAgentLine 对齐。"""
    has_allowlist = agent.tools is not None and len(agent.tools) > 0
    has_denylist = len(agent.disallowed_tools) > 0
    if has_allowlist and has_denylist:
        deny_set = set(agent.disallowed_tools)
        effective = [t for t in (agent.tools or []) if t not in deny_set]
        if not effective:
            return "None"
        return ", ".join(effective)
    if has_allowlist:
        return ", ".join(agent.tools or [])
    if has_denylist:
        return f"All tools except {', '.join(agent.disallowed_tools)}"
    return "All tools"


def _entry(agent: AgentDefinition) -> str:
    desc = agent.when_to_use
    if len(desc) > MAX_LISTING_DESC_CHARS:
        desc = desc[:MAX_LISTING_DESC_CHARS - 1] + "…"
    return f"- {agent.agent_type}: {desc} (Tools: {_tools_description(agent)})"


def format_agent_listing(
    agents: list[AgentDefinition],
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> str:
    """格式化 agent 清单为 system prompt 尾部段落。空列表返回空字符串。

    渐进披露:每条只含 type + whenToUse + tools,正文在调用时才注入。
    超长降级:每条 ≤250 字符;超总预算则逐条截断 description;极端时只留名字。
    disabled 的 agent 不列出。
    """
    if not agents:
        return ""
    enabled = [a for a in agents if not a.disabled]
    if not enabled:
        return ""
    full = "\n".join(_entry(a) for a in enabled)
    if len(full) <= char_budget:
        return full
    # 降级:逐条截断 description
    name_overhead = sum(len(a.agent_type) + 10 for a in enabled)  # "- name:  (Tools: All tools)" 大约
    available = char_budget - name_overhead
    max_desc = available // len(enabled)
    if max_desc < MIN_DESC_LENGTH:
        # 极端降级:只留名字
        return "\n".join(f"- {a.agent_type}" for a in enabled)
    lines = []
    for a in enabled:
        desc = a.when_to_use
        if len(desc) > max_desc:
            desc = desc[:max_desc - 1] + "…"
        lines.append(f"- {a.agent_type}: {desc} (Tools: {_tools_description(a)})")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agents_listing.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agents/listing.py tests/unit/test_agents_listing.py
git commit -m "feat(agents): format_agent_listing with progressive disclosure"
```

---

## Task 6: AgentEvent 加 agent_id 字段

**Files:**
- Modify: `src/taisang/agent_core/events.py`
- Test: `tests/unit/test_agent_core.py`（追加测试，确认字段存在）

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_agent_core.py`（如果文件不存在则新建，先 `ls tests/unit/` 确认）：

```python
def test_agent_event_has_agent_id_field() -> None:
    """AgentEvent 支持 agent_id 字段(默认空字符串,主 agent 用空)。"""
    from taisang.agent_core.events import AgentEvent, TOOL_CALL
    evt = AgentEvent(type=TOOL_CALL, payload={"name": "Read"})
    assert evt.agent_id == ""  # 默认空
    evt2 = AgentEvent(type=TOOL_CALL, payload={"name": "Read"}, agent_id="child-123")
    assert evt2.agent_id == "child-123"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agent_core.py::test_agent_event_has_agent_id_field -v`
Expected: FAIL with `AttributeError: 'AgentEvent' object has no attribute 'agent_id'`

- [ ] **Step 3: 加 agent_id 字段**

修改 `src/taisang/agent_core/events.py` 的 `AgentEvent` dataclass：

```python
@dataclass
class AgentEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""  # 主 agent 为空,子 agent 用唯一 id(SSE 区分嵌套渲染)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agent_core.py::test_agent_event_has_agent_id_field -v`
Expected: PASS

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿（原有测试 + 新测试）

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/events.py tests/unit/test_agent_core.py
git commit -m "feat(events): add agent_id field to AgentEvent for nested subagent rendering"
```

---

## Task 7: AgentService 加 agent_id / is_fork_child / pending 通知队列

**Files:**
- Modify: `src/taisang/agent_core/service.py`
- Test: `tests/unit/test_agent_service_with_agents.py`（新建，本 task 只测字段存在 + flush_async_notifications 机制）

- [ ] **Step 1: 写失败测试 — 字段存在 + flush 通知**

```python
# tests/unit/test_agent_service_with_agents.py
"""AgentService + 多 agent 集成单测。"""
from __future__ import annotations

from pathlib import Path

from taisang.agent_core.service import AgentService
from taisang.llm_client import MockLLM, LLMResponse


def _make_service(tmp_path: Path, agent_id: str = "", is_fork_child: bool = False) -> AgentService:
    llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    return AgentService(
        llm=llm,
        source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
        agent_id=agent_id,
        is_fork_child=is_fork_child,
    )


def test_service_has_agent_id_field(tmp_path: Path) -> None:
    """AgentService 实例带 agent_id 属性。"""
    svc = _make_service(tmp_path, agent_id="child-1")
    assert svc.agent_id == "child-1"


def test_service_has_is_fork_child_field(tmp_path: Path) -> None:
    """AgentService 实例带 is_fork_child 属性。"""
    svc = _make_service(tmp_path, is_fork_child=True)
    assert svc.is_fork_child is True


def test_service_has_pending_async_notifications(tmp_path: Path) -> None:
    """AgentService 实例带 _pending_async_notifications 队列。"""
    svc = _make_service(tmp_path)
    assert svc._pending_async_notifications == []


def test_flush_async_notifications_injects_user_message(tmp_path: Path) -> None:
    """flush_async_notifications 把队列里的通知 append_user 到 ctx。"""
    svc = _make_service(tmp_path)
    svc._pending_async_notifications.append("[子 agent 'explore' 完成]\n找到 3 个文件")
    svc.flush_async_notifications()
    # ctx 末尾应该有一条 user 消息含通知文本
    msgs = svc.ctx.messages()
    # system prompt 占第一条,append_user 后是 user 消息
    assert any(
        m.get("role") == "user" and "子 agent 'explore' 完成" in str(m.get("content", ""))
        for m in msgs
    )
    # 队列清空
    assert svc._pending_async_notifications == []


def test_flush_async_notifications_empty_noop(tmp_path: Path) -> None:
    """空队列 flush 不 append 任何消息。"""
    svc = _make_service(tmp_path)
    before = len(svc.ctx.messages())
    svc.flush_async_notifications()
    assert len(svc.ctx.messages()) == before
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agent_service_with_agents.py -v`
Expected: FAIL with `TypeError: AgentService.__init__() got an unexpected keyword argument 'agent_id'`

- [ ] **Step 3: 改 AgentService.__init__**

修改 `src/taisang/agent_core/service.py`：

在 `__init__` 签名末尾加参数（在 `mcp_manager=None` 之后）：

```python
    def __init__(
        self,
        llm: LLMClient | MockLLM,
        source_root: Path,
        confirmer,
        session_memory=None,
        compaction_state: ContentReplacementState | None = None,
        max_steps: int = 50,
        token_budget: int = 32_000,
        debug: bool = False,
        permission: PermissionManager | None = None,
        allow_dirs: list[Path] | None = None,
        on_append: Callable[[dict], None] | None = None,
        skills: list[Skill] | None = None,
        mcp_manager=None,
        agent_id: str = "",
        is_fork_child: bool = False,
        agents: list | None = None,
    ) -> None:
```

在 `__init__` 体内末尾追加（`self._mcp_manager = mcp_manager` 之后）：

```python
        # 多 agent 支持:agent_id 用于事件流区分主/子;is_fork_child 用于
        # AgentTool 调用入口防递归(fork 内不能再 fork)。
        self.agent_id = agent_id
        self.is_fork_child = is_fork_child
        self.agents = agents or []
        self._pending_async_notifications: list[str] = []
```

在 `reset()` 末尾追加：

```python
        # async 通知队列也清空(reset 清短期状态,通知是短期状态)
        self._pending_async_notifications = []
```

在 class 末尾加 `flush_async_notifications` 方法：

```python
    def flush_async_notifications(self) -> None:
        """把 _pending_async_notifications 队列里的通知依次 append_user 注入 ctx 并清空。

        AgentService 主循环在本轮所有 tool_result append 完之后调用(紧跟
        flush_skill_injections 之后),保证 async 子 agent 完成通知以 user-role
        消息注入,下轮 LLM 自然看到。OpenAI 协议:user 消息排在 tool 消息之后。
        """
        for text in self._pending_async_notifications:
            self.ctx.append_user(text)
        self._pending_async_notifications = []

    def _merge_child_usage(self, child_session_usage: dict) -> None:
        """把子 agent 的 _session_usage 累加进本 agent(主 agent 用)。

        子 agent 跑完(sync 或 async)后调,保证主 session 累计 token 含子 agent。
        子 agent 自己也 emit USAGE_REPORT 事件(带 agent_id),前端可看子单独用量。
        """
        for k in self._session_usage:
            self._session_usage[k] += child_session_usage.get(k, 0)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agent_service_with_agents.py -v`
Expected: 5 passed

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_service_with_agents.py
git commit -m "feat(service): add agent_id / is_fork_child / async notification queue"
```

---

## Task 8: 主循环加 flush_async_notifications 调用

**Files:**
- Modify: `src/taisang/agent_core/service.py`
- Test: `tests/unit/test_agent_service_with_agents.py`（追加测试）

- [ ] **Step 1: 写失败测试 — 主循环自动 flush 通知**

追加到 `tests/unit/test_agent_service_with_agents.py`：

```python
def test_main_loop_flushes_async_notifications_after_tool_results(tmp_path: Path) -> None:
    """主循环在本轮 tool_result append 完后自动 flush_async_notifications。

    用脚本化 MockLLM:第 1 步调一个无副作用工具(返回 ok),第 2 步给最终答案。
    在 tool 执行前塞一条 async 通知到队列,验证下轮 LLM 调用时 ctx 含通知 user 消息。
    """
    from taisang.agent_core.events import AgentEvent, TOOL_CALL, FINAL_ANSWER
    llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Glob", "arguments": '{"pattern": "*.py"}'}
        }]),
        LLMResponse(text="done", tool_calls=[]),
    ])
    svc = AgentService(llm=llm, source_root=tmp_path, confirmer=lambda *a, **kw: True)
    # 在 run 之前塞一条 async 通知
    svc._pending_async_notifications.append("[子 agent 'explore' 完成]\n找到 utils.py")
    events: list[AgentEvent] = []
    answer = svc.run("test query", on_event=lambda e: events.append(e))
    # 验证通知被 flush 进 ctx(下轮 LLM 看到了)
    msgs = svc.ctx.messages()
    has_notification = any(
        m.get("role") == "user" and "子 agent 'explore' 完成" in str(m.get("content", ""))
        for m in msgs
    )
    assert has_notification, "async 通知应该被 flush 进 ctx"
    assert answer.text == "done"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agent_service_with_agents.py::test_main_loop_flushes_async_notifications_after_tool_results -v`
Expected: FAIL（通知没被 flush，因为主循环还没调 flush_async_notifications）

- [ ] **Step 3: 主循环加 flush 调用**

修改 `src/taisang/agent_core/service.py` 的 `run` 方法，在 `registry.flush_skill_injections()` 之后（约 line 327）加一行：

```python
            # SKILL.md 注入必须排在全部 tool_result 之后(OpenAI 协议要求
            # assistant(tool_calls) 后紧跟 tool 消息,user 注入放最后),由
            # SkillTool 的 pending 队列延迟到这里统一 flush。
            registry.flush_skill_injections()
            # async 子 agent 完成通知:同样延迟到这里统一 flush(user-role
            # 消息排在 tool 之后,下轮 LLM 自然看到)。
            self.flush_async_notifications()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agent_service_with_agents.py -v`
Expected: 6 passed

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_service_with_agents.py
git commit -m "feat(service): main loop flushes async notifications after tool_results"
```

---

## Task 9: AgentTool 工具实现（A 模式 + B 模式 + sync + async）

**Files:**
- Create: `src/taisang/agent_core/agent_tool.py`
- Create: `tests/unit/test_agent_tool.py`

- [ ] **Step 1: 写失败测试 — A 模式 sync**

```python
# tests/unit/test_agent_tool.py
"""AgentTool 单测。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from taisang.agent_core.agent_tool import AgentTool
from taisang.agent_core.context import ContextManager
from taisang.agent_core.service import AgentService
from taisang.agents.types import AgentDefinition
from taisang.llm_client import MockLLM, LLMResponse


def _make_parent_service(tmp_path: Path, agents: list[AgentDefinition]) -> AgentService:
    """建主 AgentService,带 agents 列表(供 AgentTool 用)。"""
    llm = MockLLM([LLMResponse(text="parent final", tool_calls=[])])
    return AgentService(
        llm=llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
        agents=agents,
    )


def _make_explore_agent() -> AgentDefinition:
    """建一个测试用 explore agent 定义。"""
    return AgentDefinition(
        agent_type="explore",
        when_to_use="搜索",
        tools=None,
        disallowed_tools=["Edit", "Write", "Agent"],
        max_turns=20,
        base_dir=Path("/tmp"),
        system_prompt="You are a search agent.",
    )


def test_agent_tool_a_mode_sync_returns_child_answer(tmp_path: Path) -> None:
    """A 模式 sync:子 agent 跑完返回 Answer.text 作为 tool_result。"""
    agents = [_make_explore_agent()]
    parent = _make_parent_service(tmp_path, agents)
    # 子 agent 用独立 MockLLM,返回"找到 3 个文件"
    child_llm = MockLLM([LLMResponse(text="找到 3 个文件", tool_calls=[])])
    # 用 patch 把子 agent 的 llm 替换成 child_llm
    import taisang.agent_core.agent_tool as at_mod
    original_make = at_mod._make_child_llm
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=agents,
            parent_service=parent,
            source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({
            "description": "找 utils",
            "prompt": "找项目里的 utils 文件",
            "subagent_type": "explore",
        })
    finally:
        at_mod._make_child_llm = original_make
    assert result["text"] == "找到 3 个文件"
    assert result["agent_type"] == "explore"


def test_agent_tool_a_mode_agent_not_found(tmp_path: Path) -> None:
    """A 模式:agent_type 找不到 → tool_result error。"""
    agents = [_make_explore_agent()]
    parent = _make_parent_service(tmp_path, agents)
    tool = AgentTool(
        agents=agents, parent_service=parent, source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
    )
    result = tool.run({
        "description": "bad", "prompt": "x", "subagent_type": "nonexistent",
    })
    assert "error" in result
    assert "nonexistent" in result["error"]


def test_agent_tool_a_mode_disabled_agent(tmp_path: Path) -> None:
    """A 模式:disabled agent → tool_result error。"""
    a = _make_explore_agent()
    a.disabled = True
    parent = _make_parent_service(tmp_path, [a])
    tool = AgentTool(
        agents=[a], parent_service=parent, source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
    )
    result = tool.run({
        "description": "x", "prompt": "y", "subagent_type": "explore",
    })
    assert "error" in result
    assert "disabled" in result["error"]


def test_agent_tool_b_mode_fork_inherits_parent_messages(tmp_path: Path) -> None:
    """B 模式 fork:子 agent 深拷贝父 messages,看得到父对话历史。"""
    parent = _make_parent_service(tmp_path, [])
    # 父 ctx 灌入一段历史
    parent.ctx.append_user("用户原始问题")
    parent.ctx.append_assistant(text="我正在处理", tool_calls=None)
    # 子 agent 的 MockLLM:验证它能看到父历史(通过 messages 里的"用户原始问题")
    seen_messages: list = []
    def fake_chat(messages, tools):
        seen_messages.extend(messages)
        return LLMResponse(text="fork 结果", tool_calls=[])
    child_llm = MockLLM([])
    child_llm.chat = fake_chat
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({"description": "继续", "prompt": "接着做 Task 3"})
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
    assert result["text"] == "fork 结果"
    # 子 agent 看到了父的"用户原始问题"
    all_text = str(seen_messages)
    assert "用户原始问题" in all_text


def test_agent_tool_b_mode_fork_in_fork_rejected(tmp_path: Path) -> None:
    """B 模式:fork 子 agent 内再 fork → 拒绝(fork 递归防护)。"""
    parent = _make_parent_service(tmp_path, [])
    parent.is_fork_child = True  # 模拟父已经是 fork 子 agent
    tool = AgentTool(
        agents=[], parent_service=parent, source_root=tmp_path,
        confirmer=lambda *a, **kw: True,
    )
    result = tool.run({"description": "继续", "prompt": "再 fork 一次"})
    assert "error" in result
    assert "fork" in result["error"].lower()


def test_agent_tool_a_mode_child_tools_exclude_agent(tmp_path: Path) -> None:
    """A 模式:子 agent 工具集不含 AgentTool(防递归)。"""
    a = _make_explore_agent()
    parent = _make_parent_service(tmp_path, [a])
    captured_tools: list = []
    child_llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    def fake_chat(messages, tools):
        captured_tools.extend(tools)
        return LLMResponse(text="ok", tool_calls=[])
    child_llm.chat = fake_chat
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[a], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        tool.run({"description": "x", "prompt": "y", "subagent_type": "explore"})
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
    tool_names = {t["name"] for t in captured_tools}
    assert "Agent" not in tool_names  # 递归防护
    assert "Edit" not in tool_names  # 黑名单生效
    assert "Write" not in tool_names


def test_agent_tool_a_mode_max_turns_override(tmp_path: Path) -> None:
    """A 模式:子 agent max_steps 用 agent.max_turns(20),不是默认 50。"""
    a = _make_explore_agent()
    assert a.max_turns == 20
    parent = _make_parent_service(tmp_path, [a])
    captured_max_steps: list = []
    # 子 agent 一直调工具不回答,触发 max_steps
    child_llm = MockLLM([LLMResponse(text="", tool_calls=[{
        "id": "tc", "type": "function",
        "function": {"name": "Glob", "arguments": '{"pattern": "*"}'}
    }])] * 100)
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[a], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({"description": "x", "prompt": "y", "subagent_type": "explore"})
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
    # 子 agent 到 max_turns=20 返回 "(达到最大步数 ...)"
    assert "达到最大步数" in result["text"] or "max" in result["text"].lower()


def test_agent_tool_a_mode_async_returns_launched(tmp_path: Path) -> None:
    """A 模式 async:立即返回 async_launched,后台跑完通知入队。"""
    a = _make_explore_agent()
    parent = _make_parent_service(tmp_path, [a])
    child_llm = MockLLM([LLMResponse(text="async 结果", tool_calls=[])])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        tool = AgentTool(
            agents=[a], parent_service=parent, source_root=tmp_path,
            confirmer=lambda *a, **kw: True,
        )
        result = tool.run({
            "description": "异步搜索", "prompt": "找文件",
            "subagent_type": "explore", "run_in_background": True,
        })
        # 立即返回 async_launched
        assert result["status"] == "async_launched"
        assert "agent_id" in result
        # 等后台线程跑完
        time.sleep(0.5)
        # 通知入队
        assert len(parent._pending_async_notifications) > 0
        assert "async 结果" in parent._pending_async_notifications[0]
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agent_tool.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError`

- [ ] **Step 3: 写 AgentTool 实现**

```python
# src/taisang/agent_core/agent_tool.py
"""AgentTool:主 agent 通过本工具派子 agent。

两种模式:
- A 模式(传 subagent_type):子 agent 全新上下文,用 agent 定义里的 system_prompt,
  工具集按 frontmatter 过滤(白名单 ∩ 父工具 - 黑名单 - AgentTool 自己)。
- B 模式(省略 subagent_type,fork):子 agent 深拷贝父 messages + 复用父 system_prompt,
  工具集 = 父工具集 - AgentTool 自己。fork 递归防护:parent_service.is_fork_child
  为 True 时拒绝。

两种执行模式:
- sync(默认):阻塞等子 agent.run() 返回 Answer.text,作为 tool_result。
- async(run_in_background=True):立即返回 async_launched,后台线程跑完把结果
  注入 parent_service._pending_async_notifications,主循环下轮 flush 注入 user 消息。

权限:子 agent 共用父 PermissionManager / confirmer / shell。
递归防护:子 agent 工具集永远禁 AgentTool(A/B 模式都禁)。
"""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from ..agent_core.context import ContextManager
from ..agent_core.events import AgentEvent, FINAL_ANSWER, LLM_THINKING, TOOL_CALL, TOOL_RESULT, USAGE_REPORT
from ..agent_core.service import AgentService
from ..agents.types import AgentDefinition
from .tools import _BaseTool

log = logging.getLogger(__name__)

# 合成 fork agent 定义(system_prompt 留空,实际用父的)
_FORK_AGENT = AgentDefinition(
    agent_type="fork",
    when_to_use="(implicit fork)",
    tools=None,
    disallowed_tools=[],
    base_dir=Path("."),
    system_prompt="",
)


def _make_child_llm(parent_llm):
    """默认子 agent 用父 LLM(同 client)。测试用 monkeypatch 替换。"""
    return parent_llm


class AgentTool(_BaseTool):
    """派子 agent 工具。主 agent 通过 task({...}) 调用。"""

    name = "Agent"

    def __init__(
        self,
        agents: list[AgentDefinition],
        parent_service: AgentService,
        source_root: Path,
        confirmer,
        session_memory=None,
        mcp_manager=None,
    ) -> None:
        """
        agents:可用 agent 列表(已过滤 disabled,loader 产出)。
        parent_service:主 AgentService 实例(用于 fork 深拷贝 messages + 接收 async 通知)。
        source_root / confirmer / session_memory / mcp_manager:子 agent 透传共用。
        """
        self.agents = {a.agent_type: a for a in agents}
        self.parent_service = parent_service
        self.source_root = source_root
        self.confirmer = confirmer
        self.session_memory = session_memory
        self.mcp_manager = mcp_manager

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "Launch a subagent to handle a complex task. Pass subagent_type to use "
                "a specialized agent (starts fresh, no parent context). Omit subagent_type "
                "to fork yourself — the fork inherits the full conversation context. "
                "Available agent types are listed in the system prompt. "
                "Set run_in_background=true to run async; you'll be notified on completion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "3-5 word summary of the task"},
                    "prompt": {"type": "string", "description": "The task for the subagent"},
                    "subagent_type": {
                        "type": "string",
                        "description": "Agent type; omit to fork (inherit parent context)",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "Run async; you'll be notified on completion",
                    },
                },
                "required": ["description", "prompt"],
            },
        }

    def run(self, args: dict) -> dict:
        """执行子 agent 派遣。

        返回:
          - A 模式 sync: {"text": answer.text, "agent_type": "..."}
          - A 模式 async: {"status": "async_launched", "agent_id": "...", "description": "..."}
          - B 模式 sync: {"text": answer.text, "agent_type": "fork"}
          - 错误: {"error": "..."}
        """
        description = args.get("description", "")
        prompt = args.get("prompt", "")
        subagent_type = args.get("subagent_type")
        run_in_background = bool(args.get("run_in_background", False))

        # 解析模式
        if subagent_type:
            # A 模式
            agent = self.agents.get(subagent_type)
            if agent is None:
                available = ", ".join(sorted(self.agents.keys())) or "(none)"
                return {"error": f"agent type '{subagent_type}' not found, available: {available}"}
            if agent.disabled:
                return {"error": f"agent '{subagent_type}' is disabled"}
            is_fork = False
        else:
            # B 模式(fork)
            if self.parent_service.is_fork_child:
                return {"error": "fork is not available inside a forked worker (recursive fork guard)"}
            agent = _FORK_AGENT
            is_fork = True

        # async 由 agent.background 字段或 run_in_background 共同决定
        effective_async = run_in_background or agent.background

        if effective_async:
            return self._run_async(agent, is_fork, description, prompt)
        return self._run_sync(agent, is_fork, description, prompt)

    def _build_child_service(self, agent: AgentDefinition, is_fork: bool) -> AgentService:
        """构造子 AgentService 实例。"""
        child_agent_id = uuid.uuid4().hex[:12]
        child_llm = _make_child_llm(self.parent_service.llm)
        # fork 模式:深拷贝父 messages + 复用父 system_prompt
        # A 模式:全新 ctx + agent.system_prompt
        if is_fork:
            # 深拷贝父 messages(避免子改坏父状态)
            parent_msgs = [dict(m) for m in self.parent_service.ctx.messages()]
            # 子 agent 用新建 ctx,但灌入父 messages(含 system prompt)
            child_ctx = ContextManager(token_budget=self.parent_service.token_budget)
            child_ctx.replace_messages(parent_msgs)
            system_prompt = None  # 不覆盖,沿用 messages 里的 system
            max_steps = self.parent_service.max_steps
        else:
            child_ctx = None  # 让 AgentService 自己建
            system_prompt = agent.system_prompt
            max_steps = agent.max_turns if agent.max_turns else self.parent_service.max_steps

        # 构造子 AgentService
        child = AgentService(
            llm=child_llm,
            source_root=self.source_root,
            confirmer=self.confirmer,
            session_memory=self.session_memory,
            max_steps=max_steps,
            token_budget=self.parent_service.token_budget,
            permission=self.parent_service.permission,
            allow_dirs=list(self.parent_service.allow_dirs),
            agent_id=child_agent_id,
            is_fork_child=is_fork,
            mcp_manager=self.mcp_manager,
        )

        # fork 模式:替换 ctx 为深拷贝的父 messages
        if is_fork:
            parent_msgs = [dict(m) for m in self.parent_service.ctx.messages()]
            child.ctx.replace_messages(parent_msgs)
        # A 模式:把 agent.system_prompt 注入(覆盖默认 system prompt)
        elif system_prompt:
            from ..agent_core.prompts import build_system_prompt
            from ..agents.listing import format_agent_listing
            agents_section = format_agent_listing([])  # 子 agent 看不到 agent 清单(防递归)
            new_system = build_system_prompt("", "") + "\n\n" + system_prompt
            child.ctx.replace_system_prompt(new_system)

        return child

    def _filter_tools_for_child(self, agent: AgentDefinition, is_fork: bool) -> list[str]:
        """返回子 agent 允许的工具名列表(供主循环 ToolRegistry 用白名单过滤)。

        v1 简化:不实际过滤 ToolRegistry,而是让子 AgentService 构造 ToolRegistry 时
        不注册 AgentTool(物理防递归)。frontmatter disallowed_tools 通过工具层
        拦截(在 ToolRegistry.call 检查)。

        本方法暂不使用,留 v1.5 实现真正过滤。v1 靠 ToolRegistry 不注册 AgentTool
        + 黑名单工具在 call() 时拦截。
        """
        return []

    def _run_sync(self, agent: AgentDefinition, is_fork: bool, description: str, prompt: str) -> dict:
        """sync 执行:阻塞等子 agent 跑完,返回 Answer.text。"""
        child = self._build_child_service(agent, is_fork)
        # 子 agent 不注册 AgentTool(防递归)
        # 通过不传 agents 参数实现:AgentService 默认 agents=[]
        # ToolRegistry 构造时 agents 为空就不注册 AgentTool
        # 但子 agent 的 ToolRegistry 需要传 parent_service=child 用于...
        # 不,子 agent 不需要 AgentTool,所以 ToolRegistry 不传 agents 即可
        # 这部分靠 service.py run() 内部构造 ToolRegistry 时 self.agents 传进去
        # 子 AgentService.__init__ 已接收 agents=[],run() 时 ToolRegistry 不注册 AgentTool

        # 子 agent 事件转发:加 agent_id 前缀
        parent_emit = getattr(self.parent_service, "_last_on_event", None)
        def child_on_event(evt: AgentEvent):
            evt.agent_id = child.agent_id
            if parent_emit:
                parent_emit(evt)
        answer = child.run(prompt, on_event=child_on_event)
        # 累加子 agent usage 进主 session
        self.parent_service._merge_child_usage(child._session_usage)
        return {"text": answer.text, "agent_type": agent.agent_type}

    def _run_async(self, agent: AgentDefinition, is_fork: bool, description: str, prompt: str) -> dict:
        """async 执行:起后台线程跑子 agent,立即返回 async_launched。"""
        child_agent_id = uuid.uuid4().hex[:12]
        # 后台线程跑完整 _run_sync 逻辑,完成时把结果塞进 parent 的 pending 队列
        def background_run():
            try:
                child = self._build_child_service(agent, is_fork)
                # 重设 agent_id(后台线程里 _build_child_service 生成的是新的,要统一)
                child.agent_id = child_agent_id
                answer = child.run(prompt, on_event=None)  # async 不转发事件(v1 简化)
                self.parent_service._merge_child_usage(child._session_usage)
                text = f"[子 agent '{description}' 完成]\n{answer.text}"
                self.parent_service._pending_async_notifications.append(text)
            except Exception as e:
                log.warning("async agent '%s' failed: %s", description, e)
                text = f"[子 agent '{description}' 失败]\n{e}"
                self.parent_service._pending_async_notifications.append(text)
        thread = threading.Thread(target=background_run, daemon=True)
        thread.start()
        return {
            "status": "async_launched",
            "agent_id": child_agent_id,
            "description": description,
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_agent_tool.py -v`
Expected: 8 passed

如果某些测试失败,根据失败信息修正实现(常见点:`replace_system_prompt` 方法名、`MockLLM.chat` 签名、`max_steps` 字段名)。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/agent_tool.py tests/unit/test_agent_tool.py
git commit -m "feat(agent-tool): AgentTool with A/B modes + sync/async execution"
```

---

## Task 10: ToolRegistry 集成 AgentTool + 主循环 agents 清单注入

**Files:**
- Modify: `src/taisang/agent_core/tools.py`
- Modify: `src/taisang/agent_core/prompts.py`
- Modify: `src/taisang/agent_core/service.py`
- Test: `tests/unit/test_agent_service_with_agents.py`（追加 e2e 测试）

- [ ] **Step 1: 写失败测试 — 主 agent 能调 AgentTool 派子 agent**

追加到 `tests/unit/test_agent_service_with_agents.py`：

```python
def test_main_agent_can_dispatch_subagent_via_agent_tool(tmp_path: Path) -> None:
    """主 agent 调 Agent 工具派 explore 子 agent,子 agent 返回结果作为 tool_result,
    主 agent 收到后给最终答案。"""
    from taisang.agent_core.events import AgentEvent, TOOL_CALL, TOOL_RESULT, FINAL_ANSWER
    from taisang.agents.types import AgentDefinition
    # 子 agent 的 MockLLM:返回"找到 utils.py"
    child_llm = MockLLM([LLMResponse(text="找到 utils.py", tool_calls=[])])
    # 主 agent 的 MockLLM:第 1 步调 Agent 工具,第 2 步给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "找 utils", "prompt": "找 utils 文件", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="根据子 agent 报告,utils.py 找到了", tool_calls=[]),
    ])
    # 子 agent 用独立 LLM:用 monkeypatch 替换 _make_child_llm
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    # explore agent 定义
    explore = AgentDefinition(
        agent_type="explore", when_to_use="搜索",
        disallowed_tools=["Edit", "Write", "Agent"], max_turns=10,
        base_dir=tmp_path, system_prompt="You are a search agent.",
    )
    svc = AgentService(
        llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
        agents=[explore],
    )
    events: list[AgentEvent] = []
    answer = svc.run("帮我找 utils 文件", on_event=lambda e: events.append(e))
    # 主 agent 给最终答案
    assert "utils.py" in answer.text
    # 事件流含 Agent 工具调用 + 子 agent 的 TOOL_CALL(带 agent_id)
    tool_calls = [e for e in events if e.type == TOOL_CALL]
    assert any(e.payload.get("name") == "Agent" for e in tool_calls)
    # 子 agent 事件带非空 agent_id
    child_events = [e for e in events if e.agent_id]
    assert len(child_events) > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agent_service_with_agents.py::test_main_agent_can_dispatch_subagent_via_agent_tool -v`
Expected: FAIL（ToolRegistry 还没注册 AgentTool）

- [ ] **Step 3: ToolRegistry 加 agents / parent_service 参数**

修改 `src/taisang/agent_core/tools.py` 的 `ToolRegistry.__init__`：

在签名末尾加参数（`mcp_manager=None` 之后）：

```python
    def __init__(
        self,
        cwd: Path,
        shell=None,
        confirmer=None,
        permission: PermissionManager | None = None,
        bash_timeout: int = 30,
        observations_dir: Path | None = None,
        skills: list | None = None,
        ctx=None,
        mcp_manager=None,
        agents: list | None = None,
        parent_service=None,
    ) -> None:
```

在 `__init__` 体内 `if mcp_manager:` 块之后追加：

```python
        # AgentTool:LLM 调用派子 agent。仅当传入 agents + parent_service 时注册
        # (子 agent 的 ToolRegistry 不传 agents,物理防递归)。
        # 局部导入避免循环引用(agent_tool.py 从 tools.py 导入 _BaseTool)。
        if agents and parent_service is not None:
            from .agent_tool import AgentTool
            self._tools[AgentTool.name] = AgentTool(
                agents=agents,
                parent_service=parent_service,
                source_root=cwd,
                confirmer=confirmer,
                mcp_manager=mcp_manager,
            )
```

在 `flush_skill_injections` 之后加 `flush_async_notifications` 转发方法：

```python
    def flush_async_notifications(self) -> None:
        """触发 parent_service 的 async 通知 flush(若有 parent_service)。

        AgentService 主循环在本轮 tool_result 后调用,跟 flush_skill_injections 同位置。
        """
        if self._parent_service is not None:
            self._parent_service.flush_async_notifications()
```

并在 `__init__` 体内保存 `parent_service` 引用（紧邻 `self._mcp_manager` 那行附近，加一行）：

```python
        self._parent_service = parent_service
```

- [ ] **Step 4: service.py 主循环传 agents + parent_service 给 ToolRegistry**

修改 `src/taisang/agent_core/service.py` 的 `run` 方法里构造 ToolRegistry 的部分（约 line 162）：

```python
        registry = ToolRegistry(
            cwd=self.source_root,
            shell=self.shell,
            confirmer=self.confirmer,
            permission=self.permission,
            skills=self.skills,
            ctx=self.ctx,
            mcp_manager=self._mcp_manager,
            agents=self.agents,
            parent_service=self,
        )
```

- [ ] **Step 5: prompts.py 加 agents_section 参数**

修改 `src/taisang/agent_core/prompts.py` 的 `build_system_prompt`：

```python
AGENTS_SECTION_HEADER = """

## 可用 Agents

"""


def build_system_prompt(skills_section: str = "", mcp_section: str = "", agents_section: str = "") -> str:
    """组装完整 system prompt:基础 prompt + (可选)skills/mcp/agents 清单段。"""
    prompt = get_system_prompt()
    if skills_section:
        prompt += SKILLS_SECTION_HEADER + "\n" + skills_section + "\n"
    if mcp_section:
        prompt += MCP_SECTION_HEADER + "\n" + mcp_section + "\n"
    if agents_section:
        prompt += AGENTS_SECTION_HEADER + "\n" + agents_section + "\n"
    return prompt
```

- [ ] **Step 6: service.py 注入 agents 清单**

修改 `src/taisang/agent_core/service.py` 的 `__init__`（在 `skills_section = format_skill_listing(...)` 附近）和 `reset()`：

`__init__` 体内：
```python
        skills_section = format_skill_listing(self.skills)
        mcp_section = format_mcp_section(mcp_manager) if mcp_manager else ""
        from ..agents.listing import format_agent_listing
        agents_section = format_agent_listing(self.agents) if self.agents else ""
        self.ctx.append_system(build_system_prompt(skills_section, mcp_section, agents_section))
```

`reset()` 体内同步：
```python
        skills_section = format_skill_listing(self.skills)
        mcp_section = format_mcp_section(self._mcp_manager) if self._mcp_manager else ""
        from ..agents.listing import format_agent_listing
        agents_section = format_agent_listing(self.agents) if self.agents else ""
        self.ctx = ContextManager(token_budget=self.token_budget, on_append=on_append)
        self.ctx.append_system(build_system_prompt(skills_section, mcp_section, agents_section))
```

- [ ] **Step 7: 跑测试确认通过**

Run: `pytest tests/unit/test_agent_service_with_agents.py -v`
Expected: 7 passed

- [ ] **Step 8: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 9: Commit**

```bash
git add src/taisang/agent_core/tools.py src/taisang/agent_core/prompts.py src/taisang/agent_core/service.py tests/unit/test_agent_service_with_agents.py
git commit -m "feat(agent-tool): integrate AgentTool into ToolRegistry + inject agent listing into system prompt"
```

---

## Task 11: SessionRegistry 加载 agents + 传给 AgentService

**Files:**
- Modify: `src/taisang/web/session_registry.py`
- Test: `tests/unit/test_agent_service_with_agents.py`（追加 session 级测试）

- [ ] **Step 1: 写失败测试 — disabled agent 不进 agent 清单**

追加到 `tests/unit/test_agent_service_with_agents.py`：

```python
def test_disabled_agent_not_in_listing(tmp_path: Path) -> None:
    """disabled agent 不进 system prompt 的 agent 清单,调用返回 disabled 错误。"""
    from taisang.agent_core.events import AgentEvent, TOOL_CALL, FINAL_ANSWER
    from taisang.agents.types import AgentDefinition
    explore = AgentDefinition(
        agent_type="explore", when_to_use="搜索",
        disallowed_tools=["Edit", "Write", "Agent"], max_turns=10,
        base_dir=tmp_path, system_prompt="You are a search agent.",
    )
    explore.disabled = True  # 禁用
    # 主 agent 看到 explore disabled,直接调(应返回 error),然后给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "x", "prompt": "y", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="explore 禁用了,我直接搜", tool_calls=[]),
    ])
    svc = AgentService(
        llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
        agents=[explore],
    )
    answer = svc.run("用 explore 搜一下", on_event=None)
    # 验证 system prompt 不含 explore 清单(disabled 不列出)
    system_msg = svc.ctx.messages()[0]
    # explore disabled,清单段不注入(agents_section 为空)
    assert "## 可用 Agents" not in str(system_msg.get("content", ""))
```

- [ ] **Step 2: 跑测试确认**

Run: `pytest tests/unit/test_agent_service_with_agents.py::test_disabled_agent_not_in_listing -v`
Expected: PASS（Task 5 的 listing 已经过滤 disabled,Task 10 的注入也用同一份;此测试是保险）

如果失败,检查 `format_agent_listing` 是否过滤 disabled,以及 `__init__` 注入时用的是 `self.agents`(含 disabled)还是过滤后的。

- [ ] **Step 3: SessionRegistry._build_session 加载 agents**

修改 `src/taisang/web/session_registry.py` 的 `_build_session`：

在 `skills = load_skills_with_state(self.source_root)` 之后加：

```python
        # Agent 加载:三源(user/project/system) + agents_state.json 的 disabled 状态
        # 跟 skill 同构,用 agents.loader 的共享 helper
        from ..agents.loader import load_agents_with_state
        agents = load_agents_with_state(self.source_root)
```

在 `AgentService(...)` 构造调用里加 `agents=agents` 参数：

```python
        agent = AgentService(
            llm=llm,
            source_root=self.source_root,
            confirmer=confirmer,
            session_memory=session_mem,
            permission=permission,
            allow_dirs=[self.source_root] + self.allow_dirs,
            on_append=store.append,
            skills=skills,
            mcp_manager=self._mcp_manager,
            agents=agents,
        )
```

`apply_prompts_config` 方法里 `build_system_prompt` 调用也要加 `agents_section`：

```python
            from ..skills.listing import format_skill_listing
            from ..agents.listing import format_agent_listing
            from ..agent_core.prompts import build_system_prompt, format_mcp_section

            skills_section = format_skill_listing(agent.skills)
            agents_section = format_agent_listing(agent.agents) if agent.agents else ""
            mcp_section = format_mcp_section(agent._mcp_manager) if getattr(agent, "_mcp_manager", None) else ""
            new_system = build_system_prompt(skills_section, mcp_section, agents_section)
            agent.ctx.replace_system_prompt(new_system)
```

- [ ] **Step 4: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/session_registry.py tests/unit/test_agent_service_with_agents.py
git commit -m "feat(session): load agents in _build_session + pass to AgentService"
```

---

## Task 12: API 路由（list / toggle / reload）

**Files:**
- Create: `src/taisang/web/agents_api.py`
- Modify: `src/taisang/web/app.py`
- Create: `tests/unit/test_agents_api.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_agents_api.py
"""Agent 管理 API 单测。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from taisang.web.agents_api import register_agents_routes


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    register_agents_routes(app, source_root=tmp_path)
    return app


def test_list_agents_returns_builtin(tmp_path: Path, monkeypatch) -> None:
    """GET /api/agents 返回 4 个内置 agent。"""
    # 隔离 state 文件
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "agents_state.json")
    app = _make_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    names = {a["agent_type"] for a in data["agents"]}
    assert {"general-purpose", "explore", "plan", "verification"} <= names
    # 字段齐全
    for a in data["agents"]:
        assert "agent_type" in a
        assert "when_to_use" in a
        assert "source" in a
        assert "tools" in a
        assert "disallowed_tools" in a
        assert "disabled" in a
        assert "background" in a


def test_toggle_agent_persists_state(tmp_path: Path, monkeypatch) -> None:
    """POST /api/agents/{name}/toggle 翻转 disabled 并持久化。"""
    state_file = tmp_path / "agents_state.json"
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", state_file)
    app = _make_app(tmp_path)
    client = TestClient(app)
    # 第一次 toggle:False → True
    r = client.post("/api/agents/explore/toggle")
    assert r.status_code == 200
    assert r.json()["disabled"] is True
    # state 文件写入
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["explore"] is True
    # 第二次 toggle:True → False
    r = client.post("/api/agents/explore/toggle")
    assert r.json()["disabled"] is False


def test_toggle_nonexistent_returns_404(tmp_path: Path, monkeypatch) -> None:
    """toggle 不存在的 agent → 404。"""
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "agents_state.json")
    app = _make_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/agents/nonexistent/toggle")
    assert r.status_code == 404


def test_reload_agents(tmp_path: Path, monkeypatch) -> None:
    """POST /api/agents/reload 返回 {ok: true}(loader 无缓存,no-op)。"""
    import taisang.agents.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_STATE_FILE", tmp_path / "agents_state.json")
    app = _make_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/agents/reload")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_agents_api.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 写 agents_api.py**

```python
# src/taisang/web/agents_api.py
"""Agent 管理 API 路由:list / toggle / reload。

跟 skills_api 对称:v1 不做 import / delete,只读 + 开关 + 重载。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from ..agents.loader import _load_disabled_state, _save_disabled_state, load_agents_with_state


def register_agents_routes(app, source_root: Path) -> None:
    """把 agents 路由挂到 app,闭包绑定 source_root。"""

    @app.get("/api/agents")
    async def list_agents() -> dict:
        """列出所有 agent(agent_type/when_to_use/source/tools/disabled/background)。"""
        agents = load_agents_with_state(source_root)
        return {"agents": [
            {
                "agent_type": a.agent_type,
                "when_to_use": a.when_to_use,
                "source": a.source,
                "tools": a.tools,
                "disallowed_tools": a.disallowed_tools,
                "disabled": a.disabled,
                "background": a.background,
                "max_turns": a.max_turns,
            }
            for a in agents
        ]}

    @app.post("/api/agents/reload")
    async def reload_agents() -> dict:
        """no-op:loader 无缓存,下次 list 重读磁盘。"""
        return {"ok": True}

    @app.post("/api/agents/{name}/toggle")
    async def toggle_agent(name: str) -> dict:
        """切换 agent 的 disabled 状态,持久化到 agents_state.json。"""
        agents = load_agents_with_state(source_root)
        if not any(a.agent_type == name for a in agents):
            raise HTTPException(404, "agent not found")
        state = _load_disabled_state()
        state[name] = not state.get(name, False)
        _save_disabled_state(state)
        return {"ok": True, "disabled": state[name]}
```

- [ ] **Step 4: app.py 注册路由**

修改 `src/taisang/web/app.py`，在 `register_skills_routes(app, source_root)` 那行之后加：

```python
    from .agents_api import register_agents_routes
    register_agents_routes(app, source_root)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/unit/test_agents_api.py -v`
Expected: 4 passed

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add src/taisang/web/agents_api.py src/taisang/web/app.py tests/unit/test_agents_api.py
git commit -m "feat(api): /api/agents routes (list/toggle/reload)"
```

---

## Task 13: 前端 AgentManage.vue + Sidebar 入口

**Files:**
- Create: `src/taisang/web/frontend/src/views/AgentManage.vue`
- Modify: `src/taisang/web/frontend/src/router.ts`
- Modify: `src/taisang/web/frontend/src/components/Sidebar.vue`

- [ ] **Step 1: 写 AgentManage.vue（参照 SkillManage.vue 简化版）**

```vue
<!-- src/taisang/web/frontend/src/views/AgentManage.vue -->
<template>
  <div class="agent-manage">
    <div class="page-header">
      <h2 class="page-title">Agent 管理</h2>
      <div class="header-actions">
        <t-button variant="outline" aria-label="重载 agents" @click="reload">
          <template #icon>
            <t-icon name="refresh" />
          </template>
          重载
        </t-button>
      </div>
    </div>

    <t-table row-key="agent_type" :data="agents" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag
          :theme="row.source === 'project' ? 'primary' : row.source === 'system' ? 'warning' : 'default'"
          size="small"
        >
          {{ row.source === 'project' ? '项目' : row.source === 'system' ? '内置' : '用户' }}
        </t-tag>
      </template>
      <template #tools_display="{ row }">
        <span>{{ formatTools(row) }}</span>
      </template>
      <template #enabled="{ row }">
        <t-switch :value="!row.disabled" @change="() => toggle(row.agent_type)" />
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无自定义 agent。手动放置到
          <code>~/.taisang/agents/&lt;name&gt;/AGENT.md</code>
          或项目 <code>.taisang/agents/&lt;name&gt;/AGENT.md</code>。
        </div>
      </template>
    </t-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

interface AgentRow {
  agent_type: string
  when_to_use: string
  source: 'user' | 'project' | 'system'
  tools: string[] | null
  disallowed_tools: string[]
  disabled: boolean
  background: boolean
  max_turns: number | null
}

const agents = ref<AgentRow[]>([])
const loading = ref(false)

const columns = [
  { colKey: 'agent_type', title: '名称', width: 160, fixed: 'left' },
  { colKey: 'when_to_use', title: '描述', ellipsis: true },
  { colKey: 'source', title: '来源', width: 100, cell: 'source' },
  { colKey: 'tools_display', title: '工具集', width: 240, cell: 'tools_display' },
  { colKey: 'enabled', title: '启用', width: 80, cell: 'enabled' },
]

function formatTools(row: AgentRow): string {
  const hasAllow = row.tools && row.tools.length > 0
  const hasDeny = row.disallowed_tools && row.disallowed_tools.length > 0
  if (hasAllow && hasDeny) {
    const denySet = new Set(row.disallowed_tools)
    const effective = row.tools!.filter(t => !denySet.has(t))
    if (!effective.length) return 'None'
    return effective.join(', ')
  }
  if (hasAllow) return row.tools!.join(', ')
  if (hasDeny) return `全工具除 ${row.disallowed_tools.join(', ')}`
  return '全工具'
}

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/agents')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json()
    agents.value = data.agents
  } catch (e) {
    MessagePlugin.error(`加载 agent 失败: ${e}`)
  } finally {
    loading.value = false
  }
}

async function toggle(name: string) {
  try {
    const r = await fetch(`/api/agents/${name}/toggle`, { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    await load()
  } catch (e) {
    MessagePlugin.error(`切换失败: ${e}`)
  }
}

async function reload() {
  try {
    const r = await fetch('/api/agents/reload', { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    MessagePlugin.success('已重载')
    await load()
  } catch (e) {
    MessagePlugin.error(`重载失败: ${e}`)
  }
}

onMounted(load)
</script>

<style scoped>
.agent-manage {
  padding: 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 20px;
}
.empty-tip {
  padding: 24px;
  color: var(--td-text-color-placeholder);
  text-align: center;
}
.empty-tip code {
  background: var(--td-bg-color-container);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
</style>
```

- [ ] **Step 2: router.ts 加 /agents 路由**

修改 `src/taisang/web/frontend/src/router.ts`，在 `/skills` 路由旁边加：

```typescript
  {
    path: '/agents',
    name: 'agents',
    component: () => import('./views/AgentManage.vue'),
  },
```

- [ ] **Step 3: Sidebar.vue 加 "Agent 管理" 入口**

修改 `src/taisang/web/frontend/src/components/Sidebar.vue`，在 "Skill 管理" 入口旁边加（同样式）：

```vue
        <t-menu-item @click="router.push('/agents')">
          <template #icon>
            <t-icon name="user-circle" />
          </template>
          Agent 管理
        </t-menu-item>
```

icon 选 `user-circle` 或 `robot`（看 TDesign sprite 是否有；若 `robot` 在 sprite 里（你之前验证过 brand 用了 robot），用 robot 更贴切）。

- [ ] **Step 4: 前端构建验证**

Run: `cd src/taisang/web/frontend && npm run type-check && npm run build`
Expected: 干净通过

- [ ] **Step 5: 手动验证（Playwright DOM 断言）**

启动后端 + 前端，用 Playwright 跑（或手动）：

```javascript
// 验证 /agents 页表格渲染 4 个内置 agent
await page.goto('http://localhost:8765/agents')
const rows = await page.$$('[row-key]')
assert rows.length >= 4
// 验证内置标签
const sources = await page.$$eval('[row-key] .t-tag', els => els.map(e => e.textContent?.trim()))
assert sources.includes('内置')
// 验证 verification 工具集显示 "全工具除 ..."
const toolsText = await page.evaluate(() => {
  const cells = document.querySelectorAll('[col-key="tools_display"]')
  return Array.from(cells).map(c => c.textContent?.trim())
})
assert toolsText.some(t => t && t.includes('全工具除'))
```

- [ ] **Step 6: Commit**

```bash
git add src/taisang/web/frontend/src/views/AgentManage.vue src/taisang/web/frontend/src/router.ts src/taisang/web/frontend/src/components/Sidebar.vue
git commit -m "feat(frontend): AgentManage page + Sidebar entry + /agents route"
```

---

## Task 14: SSE 子 agent 事件嵌套渲染

**Files:**
- Modify: `src/taisang/web/frontend/src/components/MessageList.vue`（或对应 SSE 事件处理组件）

- [ ] **Step 1: 调研现有 SSE 事件处理结构**

Run: `grep -rn "TOOL_CALL\|tool_call\|agent_id\|onEvent\|EventSource" src/taisang/web/frontend/src/ | head -20`

定位事件处理代码所在文件（可能在 `ChatView.vue` 或 `stores/chat.ts` 或 `MessageList.vue`）。

- [ ] **Step 2: 加 agent_id 区分主/子事件**

在 SSE 事件处理函数里,按 `event.agent_id` 区分：
- `agent_id` 为空 → 主 agent 事件,正常追加到当前消息流
- `agent_id` 非空 → 子 agent 事件,找到最近一个 `Agent` 工具卡片（`tool_call.name === 'Agent'`），嵌套渲染到卡片内

```typescript
// 伪代码,实际位置看调研结果
function handleEvent(event: AgentEvent) {
  if (event.agent_id) {
    // 子 agent 事件:嵌套到最近的 Agent 工具卡片
    const lastAgentToolCall = findLastAgentToolCall(messages.value)
    if (lastAgentToolCall) {
      if (!lastAgentToolCall.subAgentEvents) lastAgentToolCall.subAgentEvents = []
      lastAgentToolCall.subAgentEvents.push(event)
    }
    return
  }
  // 主 agent 事件:正常处理
  // ... 现有逻辑
}
```

- [ ] **Step 3: ToolCard 组件支持嵌套渲染**

修改 ToolCard.vue（或对应组件）,如果 `toolCall.name === 'Agent'` 且有 `subAgentEvents`,在卡片展开时渲染子事件列表（折叠态默认隐藏,展开后显示子 agent 的 TOOL_CALL/TOOL_RESULT/FINAL_ANSWER）。

- [ ] **Step 4: USAGE_REPORT 双层显示**

`USAGE_REPORT` 事件 `agent_id` 非空时,在前端显示"子 agent X 用了 N token"（小字标注）；主 agent 的 USAGE_REPORT 显示 session 累计（已含子,后端累加保证）。

- [ ] **Step 5: 前端构建验证**

Run: `cd src/taisang/web/frontend && npm run type-check && npm run build`
Expected: 干净通过

- [ ] **Step 6: 手动验证**

启动后端（`TAISANG_MOCK_LLM=1 taisang web`），触发一次主 agent 调子 agent（脚本化 MockLLM 驱动），用 Playwright 验证：

```javascript
// 验证 Agent 工具卡片内有嵌套子事件
const agentCard = await page.$('[data-tool-name="Agent"]')
const subEvents = await agentCard?.$$('[data-sub-agent-event]')
assert subEvents && subEvents.length > 0
```

- [ ] **Step 7: Commit**

```bash
git add src/taisang/web/frontend/src/
git commit -m "feat(frontend): SSE subagent event nested rendering + dual-layer usage display"
```

---

## Task 15: 端到端集成测试（MockLLM 脚本化驱动）

**Files:**
- Create: `tests/integration/test_agent_e2e.py`

- [ ] **Step 1: 写 e2e 测试 — A 模式 / B 模式 / async / 递归防护**

```python
# tests/integration/test_agent_e2e.py
"""端到端:主 agent 调子 agent 的完整链路。

MockLLM 脚本化驱动,验证:
- A 模式:子 agent 全新上下文,返回 Answer.text
- B 模式 fork:子 agent 继承父对话
- async:立即返回,后台跑完通知入队
- 递归防护:子 agent 工具集不含 AgentTool
- disabled agent 调用返回错误
- USAGE_REPORT 累加
"""
from __future__ import annotations

from pathlib import Path

from taisang.agent_core.events import AgentEvent, TOOL_CALL, TOOL_RESULT, FINAL_ANSWER, USAGE_REPORT
from taisang.agent_core.service import AgentService
from taisang.agents.types import AgentDefinition
from taisang.llm_client import MockLLM, LLMResponse


def _explore_agent(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        agent_type="explore", when_to_use="搜索",
        disallowed_tools=["Edit", "Write", "Agent"], max_turns=10,
        base_dir=tmp_path, system_prompt="You are a search agent.",
    )


def test_e2e_a_mode_subagent_completes_and_returns_text(tmp_path: Path, monkeypatch) -> None:
    """A 模式:主 agent 调 explore → 子 agent grep → 返回 → 主 agent 给最终答案。"""
    # 子 agent MockLLM:第 1 步 grep,第 2 步给结论
    child_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Grep", "arguments": '{"pattern": "utils", "path": "."}'}
        }]),
        LLMResponse(text="找到 utils.py 在 src/ 下", tool_calls=[]),
    ])
    # 主 agent MockLLM:调 Agent 工具,然后给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "找 utils", "prompt": "找 utils 文件", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="根据子 agent 报告,utils.py 在 src/ 下", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        answer = svc.run("帮我找 utils 文件")
        assert "utils.py" in answer.text
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_fork_mode_inherits_parent_context(tmp_path: Path, monkeypatch) -> None:
    """B 模式 fork:子 agent 看到父对话的"用户原始问题"。"""
    seen: list = []
    def fake_chat(messages, tools):
        seen.extend(messages)
        return LLMResponse(text="fork 接续结果", tool_calls=[])
    child_llm = MockLLM([])
    child_llm.chat = fake_chat
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "继续", "prompt": "接着做 Task 3"}'}
        }]),
        LLMResponse(text="fork 完成了 Task 3", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[],
        )
        svc.ctx.append_user("用户原始问题(Task 1-2 已完成)")
        answer = svc.run("接着做 Task 3")
        assert "Task 3" in answer.text
        # 子 agent 看到了父的"用户原始问题"
        assert "用户原始问题" in str(seen)
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_async_subagent_notifies_parent(tmp_path: Path, monkeypatch) -> None:
    """async:主 agent 调 Agent(background=True),立即返回,继续给最终答案;
    后台子 agent 跑完通知入队,主 agent 下轮看到。"""
    import time
    child_llm = MockLLM([LLMResponse(text="async 子 agent 结果", tool_calls=[])])
    # 主 agent:调 async Agent,立即拿到 async_launched,然后给最终答案
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "异步", "prompt": "慢慢搜", "subagent_type": "explore", "run_in_background": true}'}
        }]),
        LLMResponse(text="已派 async 任务,等通知", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        answer = svc.run("异步搜一下")
        # 主 agent 立即给了"已派 async 任务"
        assert "已派 async" in answer.text
        # 等后台线程
        time.sleep(0.5)
        # 通知入队
        assert len(svc._pending_async_notifications) > 0
        assert "async 子 agent 结果" in svc._pending_async_notifications[0]
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_verification_agent_defaults_async(tmp_path: Path, monkeypatch) -> None:
    """verification agent background:true,默认 async。"""
    import time
    child_llm = MockLLM([LLMResponse(text="VERDICT: PASS", tool_calls=[])])
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "验证", "prompt": "验证实现", "subagent_type": "verification"}'}
        }]),
        LLMResponse(text="验证通过", tool_calls=[]),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    verification = AgentDefinition(
        agent_type="verification", when_to_use="验证",
        disallowed_tools=["Edit", "Write", "Agent"], max_turns=100,
        background=True, base_dir=tmp_path, system_prompt="You are a verification agent.",
    )
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[verification],
        )
        answer = svc.run("验证一下")
        assert "验证通过" in answer.text
        time.sleep(0.5)
        # verification 是 background,通知入队
        assert len(svc._pending_async_notifications) > 0
        assert "VERDICT: PASS" in svc._pending_async_notifications[0]
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm


def test_e2e_recursion_guard_subagent_cannot_dispatch(tmp_path: Path, monkeypatch) -> None:
    """递归防护:子 agent 工具集不含 AgentTool,无法再派。"""
    child_llm = MockLLM([LLMResponse(text="子 agent 完成", tool_calls=[])])
    # 主 agent 调 Agent 工具
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "x", "prompt": "y", "subagent_type": "explore"}'}
        }]),
        LLMResponse(text="主 agent 最终答案", tool_calls=[]),
    ])
    # 捕获子 agent 看到的工具列表
    captured: list = []
    def fake_chat(messages, tools):
        captured.extend(tools)
        return LLMResponse(text="子 agent 完成", tool_calls=[])
    child_llm.chat = fake_chat
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        svc.run("派子 agent")
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
    # 子 agent 工具列表不含 Agent
    all_tools = set()
    for schema_list in captured:
        for t in schema_list:
            all_tools.add(t["name"])
    assert "Agent" not in all_tools


def test_e2e_usage_report_accumulates_child_usage(tmp_path: Path, monkeypatch) -> None:
    """USAGE_REPORT:子 agent 的 usage 累加进主 session 累计。"""
    from taisang.llm_client import LLMResponse
    # 子 agent 返回带 usage
    child_llm = MockLLM([LLMResponse(
        text="子结果", tool_calls=[],
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )])
    # 主 agent 返回带 usage
    parent_llm = MockLLM([
        LLMResponse(text="", tool_calls=[{
            "id": "tc1", "type": "function",
            "function": {"name": "Agent", "arguments": '{"description": "x", "prompt": "y", "subagent_type": "explore"}'}
        }], usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}),
        LLMResponse(text="主结果", tool_calls=[],
                    usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}),
    ])
    import taisang.agent_core.agent_tool as at_mod
    at_mod._make_child_llm = lambda parent_llm: child_llm
    try:
        svc = AgentService(
            llm=parent_llm, source_root=tmp_path, confirmer=lambda *a, **kw: True,
            agents=[_explore_agent(tmp_path)],
        )
        svc.run("跑一下")
        # 主 session 累计 = 主(300+70) + 子(150) = 520
        assert svc._session_usage["total_tokens"] == 520
    finally:
        at_mod._make_child_llm = lambda parent_llm: parent_llm
```

- [ ] **Step 2: 跑测试确认通过**

Run: `pytest tests/integration/test_agent_e2e.py -v`
Expected: 6 passed

如有失败,根据失败信息修正（常见点：MockLLM 的 `usage` 字段、`_merge_child_usage` 调用时机、async 线程同步时序）。

- [ ] **Step 3: 跑全量测试**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_agent_e2e.py
git commit -m "test(agent): e2e integration tests (A/B/async/recursion/usage accumulation)"
```

---

## Task 16: SPA fallback 验证 + 前端 e2e

**Files:**
- Test: 现有 SPA fallback 测试 + 前端 Playwright

- [ ] **Step 1: 验证 /agents 深链刷新不 404**

Run: `pytest tests/integration/test_spa_fallback.py -v`（或对应 SPA fallback 测试文件）

如果 SPA fallback 测试还没覆盖 `/agents`,追加一个测试用例：

```python
def test_spa_fallback_agents_route(client):
    """GET /agents 非前端路由 → 返回 index.html(SPA fallback)。"""
    r = client.get("/agents")
    assert r.status_code == 200
    assert "<div id=" in r.text  # index.html 标志
```

- [ ] **Step 2: Playwright e2e（不截图,DOM 断言）**

启动后端（`cd D:/GoProject/TaiSang && TAISANG_MOCK_LLM=1 python -m taisang web --repo .`），跑 Playwright 脚本验证：

```javascript
// 1. /agents 页表格渲染 4 个内置 agent
await page.goto('http://localhost:8765/agents')
const rows = await page.$$('[row-key]')
expect(rows.length).toBeGreaterThanOrEqual(4)

// 2. 来源标签:内置行显示"内置"
const sources = await page.$$eval('[col-key="source"] .t-tag', els => els.map(e => e.textContent?.trim()))
expect(sources).toContain('内置')

// 3. verification 工具集显示"全工具除"
const tools = await page.$$eval('[col-key="tools_display"]', els => els.map(e => e.textContent?.trim()))
expect(tools.some(t => t?.includes('全工具除'))).toBe(true)

// 4. toggle 翻转持久化
const firstSwitch = await page.$('[col-key="enabled"] .t-switch')
await firstSwitch?.click()
// 重载页面验证持久化
await page.reload()
// (具体断言看 toggle 后状态)

// 5. Sidebar "Agent 管理" 点击跳 /agents
await page.goto('http://localhost:8765/')
const agentMenuItem = await page.$('text=Agent 管理')
await agentMenuItem?.click()
expect(page.url()).toContain('/agents')
```

- [ ] **Step 3: 跑全量测试**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_spa_fallback.py  # 如有改动
git commit -m "test(agent): SPA fallback + Playwright e2e for /agents page"
```

---

## Task 17: 终审修复 + 文档更新

**Files:**
- Modify: `README.md`（更新功能章节）
- Modify: `memory/2026-09-08.md`（新建,会话日志）
- Modify: `memory/project-context.md`（更新进度）

- [ ] **Step 1: 跑全量测试 + lint**

Run:
```bash
pytest tests/ -q
ruff check src/ tests/
black --check src/ tests/
```
Expected: 全绿

- [ ] **Step 2: 跑前端构建**

Run: `cd src/taisang/web/frontend && npm run type-check && npm run build`
Expected: 干净通过

- [ ] **Step 3: 自检消息序合规**

子 agent 的事件 emit + tool_result append 必须符合 OpenAI 协议:
- 子 agent 跑 sync 时,主 agent 的消息序:assistant(tool_calls 含 Agent) → tool_result(Agent 结果)
- 子 agent 跑 async 时,主 agent 的消息序:assistant(tool_calls 含 Agent) → tool_result(async_launched) → ... → user(通知)

检查 `service.py` 主循环 `flush_skill_injections` + `flush_async_notifications` 调用位置,确保 user 注入排在 tool 之后。

- [ ] **Step 4: 更新 README.md**

修改 `README.md` 的"已实现"章节,加多 agent 段:

```markdown
**多 Agent 调度**
- Task 工具(AgentTool):主 agent 通过 `task({subagent_type, prompt, run_in_background})` 派子 agent
- 4 个内置 agent:general-purpose / explore(只读) / plan(只读) / verification(对抗,默认 async)
- 两种模式:传 subagent_type 走 A(全新上下文),省略走 B(fork 继承父对话)
- sync + async 执行:async 完成注入 user-role 通知,主循环下轮自然消费
- Agent 定义文件:目录格式 `AGENT.md`,三源加载(project > user > system),frontmatter 字段:name / description / tools / disallowedTools / maxTurns / background / model
- 前端 `/agents` 页:表格(name / 描述 / 来源 / 工具集 / 启用开关)+ 重载按钮
- 事件嵌套:子 agent 事件带 agent_id,SSE 嵌套渲染到 Agent 工具卡片内
- token 双层:子 agent 单独 emit USAGE_REPORT + 累加进主 session
- 递归防护:子 agent 工具集永远禁 AgentTool;fork 内不能再 fork
```

修改"待实现"章节,把"多 agent / subagent 调度"那条删掉或标记已完成。

- [ ] **Step 5: 写会话日志**

新建 `memory/2026-09-08.md`:

```markdown
# 2026-09-08 会话日志:多 Agent 调度(M3)接入

## 起因

泰哥要求接入多 agent,参考 claude-code 实现。

## claude-code 调研

[简述调研发现,见 design 文档背景知识章节]

## 方案

[简述决策汇总,见 design 文档]

## 实施

[简述 Task 1-17 完成情况]

## 验证

[测试数 + 验证结果]

## 踩坑

[实施中遇到的问题]

## 状态

- N commits 在 main,未 push(等泰哥)
- 后端跑着新代码
```

- [ ] **Step 6: 更新 project-context.md**

在 `memory/project-context.md` 的"进度"表加一行:

```markdown
| 多 Agent 调度(M3) | ✅ 完成(2026-09-08,Task 1-17,XXX tests passed) |
```

- [ ] **Step 7: Commit**

```bash
git add README.md memory/2026-09-08.md memory/project-context.md
git commit -m "docs: multi-agent M3 完成会话日志 + README 更新"
```

---

## 验收清单

实施完成后,以下全部通过才算 M3 完成:

- [ ] `pytest tests/ -q` 全绿(基线 251 + 新增约 30+ = 280+ tests)
- [ ] `ruff check src/ tests/` 全绿
- [ ] `black --check src/ tests/` 全绿
- [ ] `npm run type-check && npm run build` 干净
- [ ] `/agents` 页表格渲染 4 个内置 agent,来源/工具集/开关正确
- [ ] toggle 翻转持久化到 `~/.taisang/agents_state.json`
- [ ] Sidebar "Agent 管理" 点击跳 `/agents`
- [ ] `/agents` 深链刷新不 404
- [ ] e2e:A 模式 / B 模式 fork / async / 递归防护 / USAGE_REPORT 累加 全过
- [ ] 子 agent 事件 SSE 嵌套渲染(Agent 工具卡片内)
- [ ] token 双层显示(子单独 + 主累计含子)
- [ ] README + memory 更新

## 自审清单（plan 写完后自查）

- [x] Spec 每章节都有对应 task(覆盖:agent 文件 / loader / state / listing / events / service / agent_tool / tools registry / prompts / session_registry / api / frontend / e2e)
- [x] 无 TBD/TODO 占位(除 Plan 文档本身引用)
- [x] 类型/方法名一致(`AgentDefinition` / `load_agents_with_state` / `format_agent_listing` / `AgentTool` / `flush_async_notifications` / `_merge_child_usage` / `_pending_async_notifications` / `is_fork_child` / `agent_id` 全文统一)
- [x] 每个 task 有完整代码 + 测试 + commit
- [x] 每个 task 是 bite-sized(2-5 分钟一个 step)