# Session 存储统一到 ~/.taisang/sessions/ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** session 产物从 `<source_root>/.taisang/sessions/` 统一迁移到 `~/.taisang/sessions/`，跟 repo 解耦，换 repo / 不指定 repo 都能看到全部历史会话。

**Architecture:** PathManager 新增 `sessions_dir()` 返回 `~/.taisang/sessions`；`session_memory_dir/path` 和 `observations_dir` 签名从 `(source_root, ...)` 改成 `(session_id)`，路径改用 `~/.taisang/sessions/<id>/`。AgentService 加 `session_id` 参数驱动 observations_dir/transcript_path。启动时自动迁移旧 `source_root/.taisang/sessions/` 到新位置。

**Tech Stack:** Python 3.11 + pathlib + pytest

**Spec 背景:** 用户实际遇到——server 不带 `--repo` 启动时 cwd 变了，`list_all` 扫的 sessions 目录变了，历史会话全找不到。会话历史不应跟 repo 绑定，应统一放用户家目录。

---

## 产物路径迁移

| 产物 | 旧路径 | 新路径 |
|------|--------|--------|
| conversation.jsonl + meta.json | `source_root/.taisang/sessions/id/` | `~/.taisang/sessions/id/` |
| session-memory | `source_root/.taisang/sessions/id/session-memory/` | `~/.taisang/sessions/id/session-memory/` |
| observations | `source_root/.taisang/observations/`（全局共享） | `~/.taisang/sessions/id/observations/`（按 session 隔离） |
| CLI transcript | `source_root/.taisang/sessions/current.jsonl` | `~/.taisang/sessions/main/conversation.jsonl` |

**observations 跟 session 走的理由**：是 session 上下文的一部分（enforce_budget 把超长 tool_result 替换成 persisted-output 引用）。删 session 一次 rmtree 全清；换 repo 后旧 session 的 observation 引用不失效。旧 observations 不迁移（全局共享无法按 session 归属）。

**source_root 恢复**：meta.json 已有 `source_root` 字段（`switch_source_root` 写的），`get_or_load` 已有 resume 逻辑切回该目录。旧 session meta 没 source_root 时 fallback `registry.source_root`（已有逻辑，不改）。

---

## File Structure

- `src/taisang/storage/paths.py` — PathManager：新增 `sessions_dir()`，`session_memory_dir/path` 和 `observations_dir` 签名改 `(session_id)`，新增 `migrate_legacy_sessions(source_root)`
- `src/taisang/agent_core/service.py` — AgentService 加 `session_id` 参数，observations_dir/transcript_path 用 session_id
- `src/taisang/agent_core/tools.py` — ToolRegistry observations_dir 默认值改 `observations_dir("default")`
- `src/taisang/web/session_registry.py` — 6 处路径引用改 `PathManager.sessions_dir()`，AgentService 构造加 session_id
- `src/taisang/cli/main.py` — session_memory_path 去掉 source_root，AgentService 加 session_id="main"
- `src/taisang/web/app.py` — create_app 后调 `PathManager.migrate_legacy_sessions(source_root)`
- 测试：test_paths / test_web_session_registry / test_web_app / test_agent_core / test_tools* — 加 monkeypatch HOME+USERPROFILE，签名适配

---

## Task 1: PathManager 改造

**Files:**
- Modify: `src/taisang/storage/paths.py`

- [ ] **Step 1: 新增 sessions_dir + 改签名**

```python
class PathManager:
    # ... __init__ / settings_path 不变 ...

    @classmethod
    def sessions_dir(cls) -> Path:
        """所有 session 的统一存储目录:~/.taisang/sessions/。
        跟 repo 解耦,换 repo / 不指定 repo 都能看到全部历史。
        必须在方法体内调 Path.home()(非类常量),否则 monkeypatch HOME 不生效。
        """
        d = Path.home() / ".taisang" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_dir(cls, session_id: str) -> Path:
        """session memory 目录:~/.taisang/sessions/<id>/session-memory/"""
        d = cls.sessions_dir() / session_id / "session-memory"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def session_memory_path(cls, session_id: str) -> Path:
        """session memory summary 路径。"""
        return cls.session_memory_dir(session_id) / "summary.md"

    @classmethod
    def observations_dir(cls, session_id: str) -> Path:
        """大 observation 持久化目录:~/.taisang/sessions/<id>/observations/。
        按 session 隔离(跟 session 走),删 session 一次 rmtree 全清。
        """
        d = cls.sessions_dir() / session_id / "observations"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def migrate_legacy_sessions(cls, source_root: Path) -> int:
        """启动时迁移旧 source_root/.taisang/sessions/ 到 ~/.taisang/sessions/。
        目标已存在则跳过(不覆盖)。返回迁移数量。旧 observations 不迁移(全局共享无法归属)。
        """
        import shutil
        legacy = source_root / ".taisang" / "sessions"
        if not legacy.is_dir():
            return 0
        dest = cls.sessions_dir()
        count = 0
        for sub in legacy.iterdir():
            if not sub.is_dir():
                continue
            target = dest / sub.name
            if target.exists():
                continue  # 不覆盖
            shutil.move(str(sub), str(target))
            count += 1
        return count
```

更新模块 docstring:session 产物落 `~/.taisang/sessions/`,不再跟 repo 走。

- [ ] **Step 2: 跑现有 paths 测试确认签名变化**
Run: `python -m pytest tests/unit/test_paths.py -v`
Expected: 部分失败(签名改了),Task 8 修

---

## Task 2: AgentService 加 session_id

**Files:**
- Modify: `src/taisang/agent_core/service.py`

- [ ] **Step 1: __init__ 加 session_id 参数**

`__init__` 加 `session_id: str = ""`,存 `self.session_id = session_id`。

- [ ] **Step 2: observations_dir + transcript_path 用 session_id**

```python
# 原 L388
observations_dir = PathManager.observations_dir(self.session_id)
# 原 L389
transcript_path = PathManager.sessions_dir() / self.session_id / "conversation.jsonl"
```

L375 ToolRegistry 构造显式传 `observations_dir=observations_dir`(已有则确认)。

**注意**:默认值 `""` 让漏传不报错,但 observations 落 `~/.taisang/sessions//observations/`。生产路径(Web `_build_session` / CLI)必须传。

---

## Task 3: ToolRegistry observations_dir 默认值

**Files:**
- Modify: `src/taisang/agent_core/tools.py`

- [ ] **Step 1: 默认值改**

L730-731:
```python
# 原
observations_dir = PathManager.observations_dir(cwd)
# 改
observations_dir = PathManager.observations_dir("default")
```

AgentService 已显式传(Task 2),默认值只影响直接构造 ToolRegistry 的测试。

---

## Task 4: SessionRegistry 改造

**Files:**
- Modify: `src/taisang/web/session_registry.py`

6 处路径引用从 `self.source_root / ".taisang" / "sessions"` 改为 `PathManager.sessions_dir()`:

- [ ] **Step 1: _build_session**
  - L108: `session_mem = SessionMemoryService(memory_path=PathManager.session_memory_path(session_id))`(去掉 source_root)
  - L111: `sessions_dir = PathManager.sessions_dir()`
  - L125 AgentService 构造: 加 `session_id=session_id`

- [ ] **Step 2: get_or_load / list_all / delete**
  - get_or_load L202: `sess_dir = PathManager.sessions_dir() / session_id`
  - list_all L251: `sessions_dir = PathManager.sessions_dir()`
  - list_all L281: `d = sessions_dir / sid`
  - delete L345: `sess_dir = PathManager.sessions_dir() / session_id`

- [ ] **Step 3: docstring 更新**(L5/L9 sessions 路径说明)

---

## Task 5: CLI main.py 改造

**Files:**
- Modify: `src/taisang/cli/main.py`

- [ ] **Step 1: session_memory_path 去 source_root**
L217: `PathManager.session_memory_path("main")`

- [ ] **Step 2: AgentService 加 session_id**
L222-230: `AgentService(..., session_id="main")`

- [ ] **Step 3: 启动时迁移旧 session**
chat 命令启动时调 `PathManager.migrate_legacy_sessions(source_root)`

---

## Task 6: app.py 调迁移

**Files:**
- Modify: `src/taisang/web/app.py`

- [ ] **Step 1: create_app 后调迁移**
L178 后加:
```python
from ..storage.paths import PathManager
PathManager.migrate_legacy_sessions(source_root)
```

---

## Task 7: 测试更新

- [ ] **test_paths.py**: 路径断言改 `~/.taisang/sessions/...`,加 monkeypatch HOME,新增 `test_sessions_dir`、`test_migrate_legacy_sessions`
- [ ] **test_conversation_store.py**: 不改(sessions_dir 参数传入用 tmp_path)
- [ ] **test_web_session_registry.py**: fixture `mock_env` 加 `monkeypatch HOME+USERPROFILE` 到 tmp_path
- [ ] **test_web_app.py**: client fixture 加 monkeypatch HOME+USERPROFILE
- [ ] **test_agent_core.py**: `session_memory_path("test-session")`、`observations_dir("test")`、AgentService 构造加 `session_id="test"`、monkeypatch HOME
- [ ] **test_tools_bash.py / test_tools.py**: `observations_dir("test")` + monkeypatch HOME
- [ ] **test_skip_permissions.py**: 不改(不经过 PathManager)

---

## 风险点

1. **Path.home() 必须方法体内调**,不能类常量(类定义时求值固化,monkeypatch 失效)
2. **AgentService 所有构造处传 session_id**:Web `_build_session`、CLI、测试。默认 `""` 漏传不报错但 observations 落 default
3. **旧 observations 不迁移**:全局共享无法按 session 归属,旧 session resume 后 persisted-output 引用可能失效(可接受)
4. **测试 monkeypatch HOME**:大量测试需 monkeypatch HOME/USERPROFILE 到 tmp_path,否则 `~/.taisang/sessions` 写真实家目录污染

## 验证

1. `python -m pytest tests/unit tests/integration -v` 全绿
2. 启动 server 不带 `--repo`(任意 cwd) → 仍能看到全部历史会话
3. 删 session → `~/.taisang/sessions/<id>/` 整个目录消失(conversation + memory + observations 一次清)
4. 旧 session 自动迁移:`source_root/.taisang/sessions/` 放旧目录 → 启动后迁移到 `~/.taisang/sessions/`