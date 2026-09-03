# Session 对话持久化 + Resume 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 session 对话内容持久化到 JSONL + meta.json,进程重启后能完整 resume,Web UI 点击历史会话能看到完整对话并继续。

**Architecture:** 在 `ContextManager` 加 `on_append` 回调,每次往内存加 message 时同步 append 到 `conversation.jsonl`;新增 `ConversationStore` 负责文件 IO;`SessionRegistry.get_or_load` lazy 重建时读 jsonl 灌回 ctx;前端 `switchSession` 拉历史渲染。

**Tech Stack:** Python 3.12 + fastapi + pytest(已有),无新依赖。前端纯 JS(已有,无框架)。

**Spec:** `docs/superpowers/specs/2026-09-02-session-persistence-design.md`

---

## 文件结构

**新增**:
- `src/taisang/storage/conversation_store.py` — `ConversationStore` 类,jsonl + meta.json 读写
- `tests/unit/test_conversation_store.py` — 单元测试

**修改**:
- `src/taisang/agent_core/context.py` — 加 `on_append` 回调 + `load_from_records` + `replace_messages` 加 `compaction_via` 参数
- `src/taisang/agent_core/service.py` — `__init__` 加 `on_append` 参数透传给 ctx;两处 `replace_messages` 调用加 `compaction_via`;`run` 结束返回 title
- `src/taisang/web/session_registry.py` — `_build_session` 注入 store + on_append;`get_or_load` 灌回;`list_all` 读 meta.json;turn 结束写 meta.json
- `src/taisang/web/app.py` — 新增 `GET /api/sessions/{id}/messages` 路由
- `src/taisang/web/static/index.html` — `switchSession` 拉历史 + 新增 `renderHistory`
- `tests/unit/test_context.py` — 补 on_append / load_from_records / compaction_via 测试
- `tests/unit/test_web_app.py` — 补 GET messages 路由测试 + resume 灌回集成测试

---

## Task 1: ConversationStore 基础 append + load_all

**Files:**
- Create: `src/taisang/storage/conversation_store.py`
- Test: `tests/unit/test_conversation_store.py`

- [ ] **Step 1: 写失败测试 — append 后 load_all 能读回**

```python
# tests/unit/test_conversation_store.py
"""ConversationStore 单元测试:jsonl append + load_all + meta.json 原子写。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taisang.storage.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    sessions_dir = tmp_path / ".taisang" / "sessions"
    sessions_dir.mkdir(parents=True)
    return ConversationStore(session_id="abc12345", sessions_dir=sessions_dir)


def test_append_and_load_all_roundtrip(store: ConversationStore) -> None:
    """append 3 条 record 后 load_all 返回同样的 3 条(dict 相等)。"""
    r1 = {"type": "user", "role": "user", "content": "你好", "uuid": "u1", "timestamp": 1.0}
    r2 = {"type": "assistant", "role": "assistant", "content": "你好!", "uuid": "a1", "timestamp": 1.1}
    r3 = {"type": "tool", "role": "tool", "name": "read_file", "content": "x", "tool_call_id": "t1", "uuid": "t1", "timestamp": 1.2}

    store.append(r1)
    store.append(r2)
    store.append(r3)

    loaded = store.load_all()
    assert len(loaded) == 3
    assert loaded[0] == r1
    assert loaded[1] == r2
    assert loaded[2] == r3
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_conversation_store.py::test_append_and_load_all_roundtrip -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'taisang.storage.conversation_store'` 或 `ImportError`

- [ ] **Step 3: 写最小实现**

```python
# src/taisang/storage/conversation_store.py
"""单个 session 的 conversation.jsonl + meta.json 读写。

线程安全:append 用 open(mode='a') 单行 write(POSIX 原子);meta.json 用
tmp + os.replace 原子替换。不同 session 不同文件,无跨 session 竞争。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class ConversationStore:
    """单个 session 的对话 transcript + 元数据读写。

    文件布局:
      <sessions_dir>/<session_id>/conversation.jsonl   # append-only 对话
      <sessions_dir>/<session_id>/meta.json            # session 元数据
    """

    def __init__(self, session_id: str, sessions_dir: Path) -> None:
        self.session_id = session_id
        self.session_dir = sessions_dir / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.session_dir / "conversation.jsonl"
        self.meta_path = self.session_dir / "meta.json"

    def append(self, record: dict) -> None:
        """追加一行 record 到 conversation.jsonl。

        单行 write 在 POSIX 上原子,崩溃最多丢最后一行。
        """
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(line)

    def load_all(self) -> list[dict]:
        """读 conversation.jsonl 全文,逐行 json.loads。

        损坏行跳过 + log warning,不抛异常。文件不存在返回 []。
        """
        if not self.jsonl_path.exists():
            return []
        records: list[dict] = []
        with open(self.jsonl_path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    log.warning(
                        "conversation.jsonl 损坏行已跳过: session=%s line=%d err=%s",
                        self.session_id, lineno, e,
                    )
        return records
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_conversation_store.py::test_append_and_load_all_roundtrip -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/taisang/storage/conversation_store.py tests/unit/test_conversation_store.py
git commit -m "feat(storage): 加 ConversationStore — jsonl append + load_all"
```

---

## Task 2: ConversationStore 损坏行跳过 + 文件不存在

**Files:**
- Modify: `tests/unit/test_conversation_store.py`(追加测试)

- [ ] **Step 1: 写失败测试 — 损坏行跳过**

```python
# 追加到 tests/unit/test_conversation_store.py

def test_load_all_skips_corrupt_lines(store: ConversationStore) -> None:
    """jsonl 里有损坏行(非法 JSON)时跳过,返回能解析的行。"""
    r1 = {"type": "user", "role": "user", "content": "ok", "uuid": "u1", "timestamp": 1.0}
    store.append(r1)
    # 手动追加一行损坏的
    with open(store.jsonl_path, "a", encoding="utf-8") as f:
        f.write("{this is not json\n")
    r3 = {"type": "user", "role": "user", "content": "ok2", "uuid": "u2", "timestamp": 2.0}
    store.append(r3)

    loaded = store.load_all()
    assert len(loaded) == 2
    assert loaded[0] == r1
    assert loaded[1] == r3


def test_load_all_file_not_exists(tmp_path: Path) -> None:
    """jsonl 不存在时(新建会话)load_all 返回 []。"""
    sessions_dir = tmp_path / ".taisang" / "sessions"
    sessions_dir.mkdir(parents=True)
    store = ConversationStore(session_id="nonexist", sessions_dir=sessions_dir)
    # 不调 append,文件不存在
    assert store.load_all() == []
```

- [ ] **Step 2: 跑测试验证通过(Task 1 实现已覆盖这两个 case)**

Run: `python -m pytest tests/unit/test_conversation_store.py -v`
Expected: 3 个测试全 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/unit/test_conversation_store.py
git commit -m "test(storage): 补损坏行跳过 + 文件不存在测试"
```

---

## Task 3: ConversationStore meta.json 读写

**Files:**
- Modify: `src/taisang/storage/conversation_store.py`
- Modify: `tests/unit/test_conversation_store.py`

- [ ] **Step 1: 写失败测试 — write_meta + load_meta 往返**

```python
# 追加到 tests/unit/test_conversation_store.py

def test_write_and_load_meta_roundtrip(store: ConversationStore) -> None:
    """write_meta 后 load_meta 返回同样内容。"""
    meta = {
        "id": "abc12345",
        "title": "帮我看看这个文件",
        "last_prompt": "帮我看看这个文件",
        "created_at": 1693622400.0,
        "updated_at": 1693622400.123,
    }
    store.write_meta(meta)
    assert store.load_meta() == meta


def test_load_meta_file_not_exists(store: ConversationStore) -> None:
    """meta.json 不存在时 load_meta 返回 None。"""
    assert store.load_meta() is None


def test_load_meta_corrupt_returns_none(store: ConversationStore) -> None:
    """meta.json 损坏时 load_meta 返回 None(不抛异常)。"""
    store.meta_path.write_text("{not json", encoding="utf-8")
    assert store.load_meta() is None
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_conversation_store.py::test_write_and_load_meta_roundtrip -v`
Expected: FAIL with `AttributeError: 'ConversationStore' object has no attribute 'write_meta'`

- [ ] **Step 3: 实现 write_meta + load_meta**

```python
# 追加到 src/taisang/storage/conversation_store.py 的 ConversationStore 类里

    def write_meta(self, meta: dict) -> None:
        """整体重写 meta.json。tmp 文件 + os.replace 原子替换。"""
        tmp = self.meta_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.meta_path)

    def load_meta(self) -> dict | None:
        """读 meta.json。损坏/不存在返回 None。"""
        if not self.meta_path.exists():
            return None
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("meta.json 损坏已忽略: session=%s err=%s", self.session_id, e)
            return None
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_conversation_store.py -v`
Expected: 6 个测试全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/taisang/storage/conversation_store.py tests/unit/test_conversation_store.py
git commit -m "feat(storage): ConversationStore 加 meta.json 读写(原子替换)"
```

---

## Task 4: ContextManager 加 on_append 回调

**Files:**
- Modify: `src/taisang/agent_core/context.py`
- Modify: `tests/unit/test_context.py`

- [ ] **Step 1: 写失败测试 — on_append 被调用**

```python
# 追加到 tests/unit/test_context.py 末尾

def test_on_append_called_on_each_append():
    """每次 append_user/assistant/tool_result 都触发 on_append 回调,传入完整 record。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    ctx.append_user("hello")
    ctx.append_assistant("hi", tool_calls=[{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}])
    ctx.append_tool_result("result", name="f", tool_call_id="t1")

    assert len(collected) == 3
    assert collected[0] == {"role": "user", "content": "hello"}
    assert collected[1]["role"] == "assistant"
    assert collected[1]["content"] == "hi"
    assert collected[1]["tool_calls"] is not None
    assert collected[2]["role"] == "tool"
    assert collected[2]["name"] == "f"
    assert collected[2]["tool_call_id"] == "t1"


def test_on_append_none_no_error():
    """on_append=None(默认)时不报错。"""
    ctx = ContextManager()
    ctx.append_user("hello")  # 不应抛异常
    assert len(ctx.messages()) == 1
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_context.py::test_on_append_called_on_each_append -v`
Expected: FAIL with `TypeError: ContextManager.__init__() got an unexpected keyword argument 'on_append'`

- [ ] **Step 3: 改 ContextManager 加 on_append**

```python
# src/taisang/agent_core/context.py — 改 __init__ 签名 + 4 个 append 方法

# __init__ 加参数:
    def __init__(
        self,
        token_budget: int = 32_000,
        compact_ratio: float = 0.8,
        keep_recent: int = 4,
        on_append: "Callable[[dict], None] | None" = None,
    ) -> None:
        self.token_budget = token_budget
        self.compact_ratio = compact_ratio
        self.keep_recent = keep_recent
        self._messages: list[dict] = []
        self.on_append = on_append
        if ContextManager._enc is None:
            try:
                ContextManager._enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                ContextManager._enc = None

# 文件顶部 import 加:
from typing import Callable

# append_system 加 on_append:
    def append_system(self, text: str) -> None:
        msg = {"role": "system", "content": text}
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

# append_user 加 on_append:
    def append_user(self, text: str) -> None:
        msg = {"role": "user", "content": text}
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

# append_assistant 加 on_append:
    def append_assistant(self, text: str, tool_calls: list[dict] | None = None) -> None:
        msg = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)

# append_tool_result 加 on_append:
    def append_tool_result(self, text: str, name: str, tool_call_id: str | None = None) -> None:
        msg = {
            "role": "tool",
            "name": name,
            "content": text,
            "tool_call_id": tool_call_id or name,
        }
        self._messages.append(msg)
        if self.on_append:
            self.on_append(msg)
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_context.py -v`
Expected: 所有测试 PASS(原有 6 个 + 新增 2 个)

- [ ] **Step 5: 提交**

```bash
git add src/taisang/agent_core/context.py tests/unit/test_context.py
git commit -m "feat(context): ContextManager 加 on_append 回调,内存更新同步触发磁盘写"
```

---

## Task 5: ContextManager.replace_messages 加 compaction_via + load_from_records

**Files:**
- Modify: `src/taisang/agent_core/context.py`
- Modify: `tests/unit/test_context.py`

- [ ] **Step 1: 写失败测试 — replace_messages 写 boundary + 新 messages**

```python
# 追加到 tests/unit/test_context.py

def test_replace_messages_with_compaction_writes_boundary_and_new_msgs():
    """replace_messages(new_msgs, compaction_via='llm') 先写 boundary system record,再写新 messages。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    ctx.append_user("old")  # 这条也会被 on_append 捕获

    collected.clear()  # 只看 replace_messages 的输出
    new_msgs = [
        {"role": "user", "content": "[boundary]"},
        {"role": "user", "content": "summary..."},
    ]
    ctx.replace_messages(new_msgs, compaction_via="llm")

    # 第一条是 boundary system record
    assert collected[0]["role"] == "system"
    assert collected[0]["content"] == "[compacted via llm]"
    # 后面是 new_msgs 逐条
    assert collected[1] == new_msgs[0]
    assert collected[2] == new_msgs[1]
    # 内存已替换
    assert ctx.messages() == new_msgs


def test_replace_messages_without_compaction_via_no_boundary():
    """replace_messages(new_msgs) 不传 compaction_via 时不写 boundary(向后兼容)。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    new_msgs = [{"role": "user", "content": "x"}]
    ctx.replace_messages(new_msgs)
    # 不写 boundary,也不写新 messages 到 on_append(避免 enforce_budget 路径重复写)
    assert collected == []
    assert ctx.messages() == new_msgs


def test_load_from_records_filters_boundary_and_skips_on_append():
    """load_from_records 灌回时过滤 boundary record,且不触发 on_append(避免重复写盘)。"""
    collected: list[dict] = []
    ctx = ContextManager(on_append=lambda r: collected.append(r))
    records = [
        {"role": "user", "content": "q1"},
        {"role": "system", "content": "[compacted via llm]"},  # boundary,过滤掉
        {"role": "user", "content": "q2"},
    ]
    ctx.load_from_records(records)
    # boundary 被过滤
    assert ctx.messages() == [
        {"role": "user", "content": "q1"},
        {"role": "user", "content": "q2"},
    ]
    # 不触发 on_append
    assert collected == []
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_context.py::test_replace_messages_with_compaction_writes_boundary_and_new_msgs -v`
Expected: FAIL with `TypeError: replace_messages() got an unexpected keyword argument 'compaction_via'` 或 `AttributeError: ... has no attribute 'load_from_records'`

- [ ] **Step 3: 改 replace_messages + 加 load_from_records**

```python
# src/taisang/agent_core/context.py — 替换 replace_messages 方法 + 加 load_from_records

    def replace_messages(
        self,
        new_messages: list[dict],
        compaction_via: str | None = None,
    ) -> None:
        """整体替换 messages。

        compaction_via 非 None 时(autocompact 触发):先写一条 system boundary
        record 到 on_append,再把 new_messages 逐条写到 on_append。这是压缩边界,
        resume 时读到这条知道这里压缩过(UI 显示分隔符,灌回 ctx 时跳过)。

        compaction_via=None 时(如 enforce_budget 路径):只替换内存,不写 on_append
        (避免每次 run 循环都重复写盘;enforce_budget 的替换是瞬态优化,不需要持久化)。
        """
        if self.on_append and compaction_via:
            self.on_append({"role": "system", "content": f"[compacted via {compaction_via}]"})
            for msg in new_messages:
                self.on_append(msg)
        self._messages = list(new_messages)

    def load_from_records(self, records: list[dict]) -> None:
        """resume 灌回专用:从 jsonl records 重建内存 _messages。

        - 过滤 compacted boundary record(role=system 且 content 以 [compacted 开头)
        - 直接赋值 _messages,不走 on_append(避免重复写盘)

        用于 SessionRegistry.get_or_load lazy 重建时,把磁盘 jsonl 灌回内存 ctx。
        """
        self._messages = [
            r for r in records
            if not (r.get("role") == "system"
                    and isinstance(r.get("content"), str)
                    and r["content"].startswith("[compacted"))
        ]
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_context.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add src/taisang/agent_core/context.py tests/unit/test_context.py
git commit -m "feat(context): replace_messages 加 compaction_via 写 boundary + load_from_records 灌回"
```

---

## Task 6: AgentService 加 on_append 参数 + replace_messages 调用点传 compaction_via

**Files:**
- Modify: `src/taisang/agent_core/service.py:68-114`(`__init__` 签名 + ctx 构造)
- Modify: `src/taisang/agent_core/service.py:169`(enforce_budget 后的 replace_messages — **不传 compaction_via**)
- Modify: `src/taisang/agent_core/service.py:335`(session_memory 压缩 — 传 `compaction_via="session_memory"`)
- Modify: `src/taisang/agent_core/service.py:343`(LLM autocompact — 传 `compaction_via="llm"`)
- Modify: `src/taisang/agent_core/service.py:127-128`(`reset` 里重建 ctx 也要传 on_append)
- Test: `tests/unit/test_agent_core.py`

- [ ] **Step 1: 写失败测试 — AgentService on_append 透传到 ctx**

```python
# 追加到 tests/unit/test_agent_core.py 末尾(看现有 import,复用 MockLLM 等 fixture)

def test_agent_service_on_append_propagates_to_ctx(tmp_path):
    """AgentService(on_append=...) 构造后,ctx.append_user 触发 on_append 回调。"""
    from taisang.agent_core.service import AgentService
    from taisang.llm_client import LLMClient, MockLLM, LLMResponse

    llm = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    collected: list[dict] = []
    agent = AgentService(
        llm=llm,
        source_root=tmp_path,
        confirmer=lambda file_path, old, new: True,
        on_append=lambda r: collected.append(r),
    )
    agent.ctx.append_user("hello")
    assert len(collected) == 1
    assert collected[0] == {"role": "user", "content": "hello"}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_agent_core.py::test_agent_service_on_append_propagates_to_ctx -v`
Expected: FAIL with `TypeError: AgentService.__init__() got an unexpected keyword argument 'on_append'`

- [ ] **Step 3: 改 AgentService.__init__ 加 on_append 透传**

```python
# src/taisang/agent_core/service.py — __init__ 签名加 on_append,ctx 构造传 on_append

# __init__ 签名加参数(在 allow_dirs 之后):
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
        on_append: "Callable[[dict], None] | None" = None,  # 新增
    ) -> None:

# ctx 构造改(原 107 行):
        self.ctx = ContextManager(token_budget=self.token_budget, on_append=on_append)

# reset 里重建 ctx 也要传 on_append(原 127-128 行):
    def reset(self) -> None:
        # ... 保留原注释 ...
        on_append = self.ctx.on_append  # 保留原 on_append(reset 不丢持久化回调)
        self.ctx = ContextManager(token_budget=self.token_budget, on_append=on_append)
        self.ctx.append_system(SYSTEM_PROMPT)
        # ... 其余不变 ...

# 文件顶部 import 加 Callable(若未有):
from typing import Callable
```

- [ ] **Step 4: 改 3 处 replace_messages 调用点**

```python
# src/taisang/agent_core/service.py:169 — enforce_budget 后的 replace_messages
# 这个是每轮循环都跑的瞬态优化,不持久化(否则每轮都重复写盘)
# 保持原样: self.ctx.replace_messages(new_msgs)  ← 不加 compaction_via

# src/taisang/agent_core/service.py:335 — session_memory 压缩
# 改成:
                self.ctx.replace_messages([boundary, summary_msg], compaction_via="session_memory")

# src/taisang/agent_core/service.py:343 — LLM autocompact
# 改成:
        self.ctx.replace_messages(new_msgs, compaction_via="llm")
```

- [ ] **Step 5: 跑测试验证通过 + 现有 agent_core 测试不破**

Run: `python -m pytest tests/unit/test_agent_core.py tests/unit/test_compaction_autocompact.py -v`
Expected: 全 PASS(新增 1 个 + 原有全过)

- [ ] **Step 6: 提交**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat(agent): AgentService 加 on_append 透传 + 2 处 replace_messages 传 compaction_via"
```

---

## Task 7: SessionRegistry 注入 store + get_or_load 灌回

**Files:**
- Modify: `src/taisang/web/session_registry.py:68-100`(`_build_session` 注入 store + on_append)
- Modify: `src/taisang/web/session_registry.py:134-152`(`get_or_load` 灌回)
- Modify: `src/taisang/web/session_registry.py:35-47`(`_Session` 加 `store` 字段)
- Test: `tests/unit/test_web_app.py`(补集成测试)

- [ ] **Step 1: 写失败测试 — 重启后 get_or_load 灌回历史**

```python
# 追加到 tests/unit/test_web_app.py 末尾

def test_get_or_load_restores_history_after_restart(tmp_path, monkeypatch):
    """模拟进程重启:registry1 跑对话 → 新建 registry2 → get_or_load 灌回历史。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry

    # 进程 1:创建 session,跑一轮对话(写 jsonl)
    reg1 = SessionRegistry(tmp_path)
    sid = reg1.create(title="")
    sess1 = reg1.get_or_load(sid)
    # 模拟 agent 跑了一轮:手动往 ctx 加 messages(on_append 会写到 jsonl)
    sess1.agent.ctx.append_user("你好")
    sess1.agent.ctx.append_assistant("你好!", tool_calls=None)

    # 进程 2:新建 registry(模拟重启,内存实例全丢)
    reg2 = SessionRegistry(tmp_path)
    sess2 = reg2.get_or_load(sid)
    # ctx 应该被灌回,包含刚才的两条 message(加 SYSTEM_PROMPT 是 3 条)
    msgs = sess2.agent.ctx.messages()
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    # 找到 user message 内容是"你好"
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert any(m["content"] == "你好" for m in user_msgs)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_get_or_load_restores_history_after_restart -v`
Expected: FAIL — 新建 reg2 后 get_or_load 灌回的 ctx 是空的(只有 SYSTEM_PROMPT),没有 user/assistant

- [ ] **Step 3: 改 _Session 加 store 字段**

```python
# src/taisang/web/session_registry.py — _Session dataclass 加 store 字段

from taisang.storage.conversation_store import ConversationStore

@dataclass
class _Session:
    session_id: str
    agent: AgentService
    broker: EventBroker
    confirmer: WebConfirmer
    permission: WebPermissionManager
    store: ConversationStore  # 新增
    lock: threading.Lock = field(default_factory=threading.Lock)
    title: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
```

- [ ] **Step 4: 改 _build_session 构造 store + 注入 on_append**

```python
# src/taisang/web/session_registry.py — _build_session 方法

    def _build_session(self, session_id: str) -> _Session:
        broker = EventBroker()
        confirmer = WebConfirmer(emit=broker.publish)
        permission = WebPermissionManager(
            emit=broker.publish,
            initial_dirs=[self.source_root] + self.allow_dirs,
        )
        llm = self._make_llm()
        session_mem = SessionMemoryService(
            llm=llm,
            memory_path=PathManager.session_memory_path(self.source_root, session_id),
        )
        # 新增:ConversationStore + on_append 回调
        sessions_dir = self.source_root / ".taisang" / "sessions"
        store = ConversationStore(session_id=session_id, sessions_dir=sessions_dir)
        agent = AgentService(
            llm=llm,
            source_root=self.source_root,
            confirmer=confirmer,
            session_memory=session_mem,
            permission=permission,
            allow_dirs=[self.source_root] + self.allow_dirs,
            on_append=store.append,  # 新增:ctx 每次 append 同步写 jsonl
        )
        return _Session(
            session_id=session_id,
            agent=agent,
            broker=broker,
            confirmer=confirmer,
            permission=permission,
            store=store,  # 新增
        )
```

- [ ] **Step 5: 改 get_or_load 灌回历史**

```python
# src/taisang/web/session_registry.py — get_or_load 方法

    def get_or_load(self, session_id: str) -> _Session | None:
        """取会话。内存没有但磁盘有目录则 lazy 重建;都没有返回 None。

        lazy 重建时从 conversation.jsonl 读历史灌回 ctx(resume)。
        """
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is not None:
            return sess
        sess_dir = self.source_root / ".taisang" / "sessions" / session_id
        if not sess_dir.is_dir():
            return None
        sess = self._build_session(session_id)
        # 新增:从 jsonl 灌回历史到 ctx(resume)
        records = sess.store.load_all()
        if records:
            sess.agent.ctx.load_from_records(records)
        sess.title = session_id  # 兜底;后面 list_all 会用 meta.json 覆盖
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing
            self._sessions[session_id] = sess
        return sess
```

- [ ] **Step 6: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全 PASS(原有 + 新增 resume 测试)

- [ ] **Step 7: 提交**

```bash
git add src/taisang/web/session_registry.py tests/unit/test_web_app.py
git commit -m "feat(web): SessionRegistry 注入 ConversationStore + get_or_load 灌回历史(resume)"
```

---

## Task 8: SessionRegistry.list_all 读 meta.json + turn 结束写 meta.json

**Files:**
- Modify: `src/taisang/web/session_registry.py:154-194`(`list_all` 改读 meta.json)
- Modify: `src/taisang/web/session_registry.py`(新增 `_update_meta_after_turn` 方法)
- Modify: `src/taisang/web/app.py:102-140`(`send_message` 路由 turn 结束调 `_update_meta_after_turn`)
- Test: `tests/unit/test_web_app.py`

- [ ] **Step 1: 写失败测试 — list_all 读 meta.json 拿 title**

```python
# 追加到 tests/unit/test_web_app.py

def test_list_all_reads_title_from_meta(tmp_path, monkeypatch):
    """list_all 从 meta.json 读 title(替代扫目录 mtime 兜底)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry
    from taisang.storage.conversation_store import ConversationStore

    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="")  # 空 title
    # 手动写 meta.json 模拟 turn 结束后的状态
    sess = reg.get_or_load(sid)
    sess.store.write_meta({
        "id": sid, "title": "最后问的问题", "last_prompt": "最后问的问题",
        "created_at": 1.0, "updated_at": 2.0,
    })
    # 释放内存实例,强制 list_all 从磁盘读
    reg._sessions.clear()

    items = reg.list_all()
    assert len(items) == 1
    assert items[0]["title"] == "最后问的问题"


def test_list_all_fallback_when_meta_missing(tmp_path, monkeypatch):
    """meta.json 不存在时 fallback 用 session_id 当 title。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry

    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="")
    reg._sessions.clear()  # 强制从磁盘读

    items = reg.list_all()
    assert len(items) == 1
    # title fallback 到 id(meta 没有)
    assert items[0]["title"] == sid
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_list_all_reads_title_from_meta -v`
Expected: FAIL — list_all 现在用 `sess.title`(内存)或空,读不到 meta.json 的 title

- [ ] **Step 3: 改 list_all 读 meta.json**

```python
# src/taisang/web/session_registry.py — 替换 list_all 方法

    def list_all(self) -> list[dict]:
        """列会话(内存 + 磁盘并集),按 updated_at 倒序。

        title / updated_at / last_prompt 从 meta.json 读;meta.json 不存在或损坏
        时 fallback 用目录 mtime + session_id 当 title。

        返回 [{id, title, active, updated_at, relative_time}]。
        """
        sessions_dir = self.source_root / ".taisang" / "sessions"
        disk_ids: set[str] = set()
        if sessions_dir.is_dir():
            for p in sessions_dir.iterdir():
                if p.is_dir():
                    disk_ids.add(p.name)
        with self._lock:
            mem_items = list(self._sessions.items())
        mem_ids = {sid for sid, _ in mem_items}
        all_ids = disk_ids | mem_ids
        now = time.time()
        items: list[dict] = []
        for sid in all_ids:
            with self._lock:
                sess = self._sessions.get(sid)
            # 优先:内存实例的 title(刚更新过,最准)
            # 其次:meta.json(重启后或别的进程写的)
            # 最后:fallback 用 session_id
            if sess is not None:
                title = sess.title
                ts = sess.updated_at
            else:
                # lazy 重建前从 meta.json 读
                store = ConversationStore(session_id=sid, sessions_dir=sessions_dir)
                meta = store.load_meta()
                if meta is not None:
                    title = meta.get("title") or sid
                    ts = meta.get("updated_at", now)
                else:
                    title = sid
                    d = sessions_dir / sid
                    ts = d.stat().st_mtime if d.exists() else now
            items.append(
                {
                    "id": sid,
                    "title": title,
                    "active": sess is not None,
                    "updated_at": ts,
                    "relative_time": _relative_time(now - ts),
                }
            )
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def update_meta_after_turn(self, session_id: str, last_user_query: str) -> None:
        """turn 结束后更新 meta.json。title 取 last_user_query 前 40 字。

        在 app.py 的 send_message 路由里,agent.run() 返回后调用。
        """
        sess = self.get_or_load(session_id)
        if sess is None:
            return
        first_line = last_user_query.strip().split("\n")[0].strip()
        title = first_line[:40] + ("…" if len(first_line) > 40 else "") if first_line else "新会话"
        if not title:
            title = "新会话"
        sess.title = title
        sess.updated_at = time.time()
        sess.store.write_meta({
            "id": session_id,
            "title": title,
            "last_prompt": last_user_query[:200],
            "created_at": sess.created_at,
            "updated_at": sess.updated_at,
        })
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/taisang/web/session_registry.py tests/unit/test_web_app.py
git commit -m "feat(web): list_all 读 meta.json + update_meta_after_turn 写 title(动态更新)"
```

---

## Task 9: app.py send_message 路由调 update_meta_after_turn

**Files:**
- Modify: `src/taisang/web/app.py:102-140`(`send_message` 路由)
- Test: `tests/unit/test_web_app.py`

- [ ] **Step 1: 写失败测试 — 发消息后 meta.json 被更新**

```python
# 追加到 tests/unit/test_web_app.py

def test_send_message_updates_meta(tmp_path, monkeypatch):
    """POST /messages 后,meta.json 的 title 是 query 前 40 字。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"query": "帮我看看这个文件"})

    # 释放内存实例,强制从 meta.json 读
    app.state.registry._sessions.clear()
    items = app.state.registry.list_all()
    assert items[0]["title"] == "帮我看看这个文件"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_send_message_updates_meta -v`
Expected: FAIL — title 还是空或 session_id,meta.json 没更新

- [ ] **Step 3: 改 send_message 路由 — 在 _run 函数里 agent.run 返回后调 update_meta_after_turn**

现有 send_message 路由是异步后台跑(agent.run 在 `run_in_executor` 里,handler 立即返回 `{ok: true}`)。所以 `update_meta_after_turn` 必须在后台 `_run` 函数里 agent.run 返回后调,不能在 handler 里调。

精确 Edit(替换 `src/taisang/web/app.py:125-137` 的 `_run` 函数):

```python
# src/taisang/web/app.py — 替换 _run 函数(125-137 行)

        # 后台线程跑 run。on_event 把事件 push 到 broker。
        def _run():
            with sess.lock:
                try:
                    sess.agent.run(
                        req.query,
                        on_event=lambda e: sess.broker.publish(e.type, e.payload),
                    )
                except Exception as e:  # noqa: BLE001
                    log.exception("agent run failed: %s", e)
                    sess.broker.publish("run_error", {"error": f"agent run failed: {e}"})
                finally:
                    # 新增:turn 结束更新 meta.json(title=最后 query 前40字)
                    try:
                        registry.update_meta_after_turn(session_id, req.query)
                    except Exception as e:  # noqa: BLE001
                        log.warning("update_meta_after_turn failed: %s", e)
                    # 通知前端更新顶栏 + 会话列表项(title 可能变了)
                    sess.broker.publish(
                        "session_title_updated",
                        {"id": session_id, "title": sess.title},
                    )
                    # run 结束哨兵:前端据此停止 thinking 动画
                    sess.broker.publish("run_end", {})
```

**注意**:
- `update_meta_after_turn` 放在 `finally` 里,确保即使 run 异常也更新 meta(异常也是 turn 结束)
- `update_meta_after_turn` 自己 try/except 包,失败不影响 `run_end` 哨兵
- `session_title_updated` 事件从原来 `set_title_from_query` 那里(116-122 行)挪到 `_run` 的 finally 里 — 因为现在 title 在 turn 结束才更新,不是首条消息时
- **同时删掉 115-122 行原有的 `set_title_from_query` + publish "session_title_updated"** 那段(被新的 update_meta_after_turn 替代)

完整改后的 send_message 路由应该是:

```python
    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageReq) -> dict:
        """发消息:后台线程跑 agent.run,事件经 SSE 推。立即返回 {ok: true}。

        前端 POST 后立刻去订阅 /events 收事件流。run 异步,不阻塞此响应。
        turn 结束(成功或异常)后更新 meta.json(title=最后 query 前40字)。
        """
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        if sess.lock.locked():
            raise HTTPException(409, "session busy: previous run still active")

        # 后台线程跑 run。on_event 把事件 push 到 broker。
        def _run():
            with sess.lock:
                try:
                    sess.agent.run(
                        req.query,
                        on_event=lambda e: sess.broker.publish(e.type, e.payload),
                    )
                except Exception as e:  # noqa: BLE001
                    log.exception("agent run failed: %s", e)
                    sess.broker.publish("run_error", {"error": f"agent run failed: {e}"})
                finally:
                    try:
                        registry.update_meta_after_turn(session_id, req.query)
                    except Exception as e:  # noqa: BLE001
                        log.warning("update_meta_after_turn failed: %s", e)
                    sess.broker.publish(
                        "session_title_updated",
                        {"id": session_id, "title": sess.title},
                    )
                    sess.broker.publish("run_end", {})

        asyncio.get_running_loop().run_in_executor(None, _run)
        return {"ok": True}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): send_message 路由 turn 结束调 update_meta_after_turn"
```

---

## Task 10: app.py 加 GET /api/sessions/{id}/messages 路由

**Files:**
- Modify: `src/taisang/web/app.py`(新增路由)
- Test: `tests/unit/test_web_app.py`

- [ ] **Step 1: 写失败测试 — GET messages 返回历史**

```python
# 追加到 tests/unit/test_web_app.py

def test_get_messages_returns_history(tmp_path, monkeypatch):
    """GET /api/sessions/{id}/messages 返回 conversation.jsonl 的所有 record。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    # 手动往 jsonl 写几条 record
    sess = app.state.registry.get_or_load(sid)
    sess.agent.ctx.append_user("q1")
    sess.agent.ctx.append_assistant("a1", tool_calls=None)

    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    data = r.json()
    # 至少 2 条(user + assistant)
    roles = [m.get("role") for m in data]
    assert "user" in roles
    assert "assistant" in roles


def test_get_messages_unknown_session_404(tmp_path, monkeypatch):
    """GET 不存在的 session 返回 404。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/sessions/nonexistent/messages")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_get_messages_returns_history -v`
Expected: FAIL — 404 或路由不存在

- [ ] **Step 3: 加路由**

```python
# src/taisang/web/app.py — 在现有路由区(看现有 @app.get 位置)加:

    @app.get("/api/sessions/{session_id}/messages")
    async def get_messages(session_id: str) -> list[dict]:
        """返回会话历史 messages(给前端 resume 渲染用)。"""
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        return sess.store.load_all()
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): 加 GET /api/sessions/{id}/messages 路由(返回历史给前端 resume)"
```

---

## Task 11: 前端 switchSession 拉历史 + renderHistory

**Files:**
- Modify: `src/taisang/web/static/index.html:748-757`(`switchSession`)
- Modify: `src/taisang/web/static/index.html`(新增 `renderHistory` 函数)

- [ ] **Step 1: 改 switchSession 拉历史**

```javascript
// src/taisang/web/static/index.html — 替换 switchSession 函数(748-757 行)

async function switchSession(id, title) {
  if (eventSource) eventSource.close();
  currentSessionId = id;
  const titleEl = document.getElementById('current-title');
  titleEl.textContent = title || '新会话';
  titleEl.classList.toggle('empty', !title);
  document.getElementById('messages').innerHTML = '';
  // 新增:拉历史并渲染
  try {
    const r = await fetch(`/api/sessions/${id}/messages`);
    if (r.ok) {
      const history = await r.json();
      renderHistory(history);
    }
  } catch (e) {
    console.error('load history failed:', e);
  }
  loadSessions();  // 刷新左侧 active 状态
  openEventStream(id);
}
```

- [ ] **Step 2: 新增 renderHistory 函数**

```javascript
// src/taisang/web/static/index.html — 在 renderCompacted 函数后面加(约 870 行附近)

function renderHistory(records) {
  const box = document.getElementById('messages');
  for (const r of records) {
    if (r.role === 'user') {
      const el = document.createElement('div');
      el.className = 'msg user';
      el.textContent = r.content || '';
      box.appendChild(el);
    } else if (r.role === 'assistant') {
      renderFinalAnswer({text: r.content || ''});
      // 如果有 tool_calls,渲染工具卡片(已执行完,直接展开态)
      if (r.tool_calls && r.tool_calls.length) {
        for (const tc of r.tool_calls) {
          const fn = tc.function || {};
          let args = {};
          try { args = JSON.parse(fn.arguments || '{}'); } catch (e) {}
          // 渲染已展开的工具卡片(filled=1,不等待 result)
          const el = document.createElement('div');
          el.className = 'tool-card expanded';
          el.dataset.name = fn.name;
          el.dataset.filled = '1';
          el.innerHTML = `
            <div class="tool-card-header">
              <span class="arrow">▶</span>
              <span class="name">${escapeHtml(fn.name || '')}</span>
              <span class="args">${escapeHtml(JSON.stringify(args))}</span>
            </div>
            <div class="tool-card-body">执行中...</div>`;
          el.querySelector('.tool-card-header').addEventListener('click', () => el.classList.toggle('expanded'));
          box.appendChild(el);
        }
      }
    } else if (r.role === 'tool') {
      // tool_result:补全上一个同 name 的 tool-card-body
      const cards = box.querySelectorAll('.tool-card');
      let target = null;
      for (const c of cards) {
        if (c.dataset.name === r.name && !c.dataset.filled) target = c;
      }
      if (target) {
        target.dataset.filled = '1';
        target.querySelector('.tool-card-body').textContent = (r.content || '').slice(0, 30);
        target.querySelector('.args').textContent = `${(r.content || '').length} bytes`;
      } else {
        // 没找到配对的 tool-call(可能 assistant record 没存 tool_calls),单独渲染
        const el = document.createElement('div');
        el.className = 'tool-card expanded';
        el.dataset.name = r.name;
        el.dataset.filled = '1';
        el.innerHTML = `
          <div class="tool-card-header">
            <span class="arrow">▶</span>
            <span class="name">${escapeHtml(r.name)}</span>
            <span class="args">${(r.content || '').length} bytes</span>
          </div>
          <div class="tool-card-body">${escapeHtml((r.content || '').slice(0, 30))}</div>`;
        el.querySelector('.tool-card-header').addEventListener('click', () => el.classList.toggle('expanded'));
        box.appendChild(el);
      }
    } else if (r.role === 'system' && typeof r.content === 'string' && r.content.startsWith('[compacted')) {
      // compacted boundary:从 content 提取 via
      const via = r.content.includes('session_memory') ? 'session_memory' : 'llm';
      renderCompacted({via});
    }
    // system role 的 SYSTEM_PROMPT(非 boundary)不渲染
  }
  scrollToBottom();
}
```

- [ ] **Step 3: 手动验证(无自动化测试,前端纯 JS)**

启动服务:
```bash
cd /d/GoProject/TaiSang
python -m taisang
```
浏览器打开 Web UI:
1. 新建会话 → 发几条消息 → 看到对话
2. 点左侧"+新对话" → 新建第二个会话 → 发几条消息
3. 点左侧第一个会话 → **应该看到完整历史对话 + 工具卡片渲染**(这是本次持久化的核心验证)
4. 点回第二个会话 → 也应该看到历史
5. Ctrl+C 杀进程 → 重新 `python -m taisang` → 点会话 → 历史还在(进程重启 resume 验证)

- [ ] **Step 4: 提交**

```bash
git add src/taisang/web/static/index.html
git commit -m "feat(web): 前端 switchSession 拉历史 + renderHistory 渲染对话/工具卡片/压缩分隔符"
```

---

## Task 12: 集成测试 — autocompact 后 resume 拿到压缩后快照

**Files:**
- Test: `tests/unit/test_web_app.py`(或 `tests/integration/` 若有集成目录)

- [ ] **Step 1: 写集成测试 — autocompact 后 jsonl 有 boundary + resume 灌回压缩后**

```python
# 追加到 tests/unit/test_web_app.py

def test_autocompact_writes_boundary_and_resume_gets_compacted(tmp_path, monkeypatch):
    """autocompact 触发后,jsonl 里有 [compacted via ...] boundary record;
    新建 registry(模拟重启)后 get_or_load 灌回的是压缩后的 messages(不含压缩前内容)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry
    from taisang.agent_core.context import ContextManager

    reg1 = SessionRegistry(tmp_path)
    sid = reg1.create(title="")
    sess1 = reg1.get_or_load(sid)

    # 模拟压缩前:ctx 有一些 messages,写进 jsonl
    sess1.agent.ctx.append_user("old message 1")
    sess1.agent.ctx.append_user("old message 2")

    # 模拟 autocompact 触发:replace_messages 带 compaction_via
    new_msgs = [
        {"role": "user", "content": "[boundary: compacted]"},
        {"role": "user", "content": "summary: 之前聊过 old message 1 和 2"},
    ]
    sess1.agent.ctx.replace_messages(new_msgs, compaction_via="llm")

    # 验证 jsonl 有 boundary record
    records = sess1.store.load_all()
    boundary_records = [r for r in records if r.get("role") == "system" and "[compacted" in r.get("content", "")]
    assert len(boundary_records) == 1
    assert "llm" in boundary_records[0]["content"]

    # 模拟重启:新建 registry
    reg2 = SessionRegistry(tmp_path)
    sess2 = reg2.get_or_load(sid)
    msgs = sess2.agent.ctx.messages()
    # 灌回的是压缩后的 new_msgs(boundary 被过滤)
    assert msgs == new_msgs
    # 不含压缩前的 old message
    contents = [m.get("content", "") for m in msgs]
    assert not any("old message 1" in c for c in contents)
```

- [ ] **Step 2: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py::test_autocompact_writes_boundary_and_resume_gets_compacted -v`
Expected: PASS(前序 Task 都完成后这个应该直接过)

- [ ] **Step 3: 跑全部测试确保无回归**

Run: `python -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 4: 提交**

```bash
git add tests/unit/test_web_app.py
git commit -m "test(web): 集成测试 — autocompact 后 jsonl 有 boundary + resume 拿到压缩后快照"
```

---

## Task 13: 更新 app.py 路由文档注释 + spec 状态

**Files:**
- Modify: `src/taisang/web/app.py:1-13`(文件头路由注释加新路由)
- Modify: `docs/superpowers/specs/2026-09-02-session-persistence-design.md`(状态改成"已实施")

- [ ] **Step 1: 更新 app.py 文件头路由注释**

```python
# src/taisang/web/app.py — 文件头注释区(1-13 行)加一行:

- GET  /api/sessions/{id}/messages → 取会话历史 messages(前端 resume 渲染用)
```

加在现有 `GET /api/sessions/{id}/events` 行上面或下面(保持顺序)。

- [ ] **Step 2: 更新 spec 状态**

```markdown
# docs/superpowers/specs/2026-09-02-session-persistence-design.md 第 4 行

**状态**: 已实施(2026-09-02)
```

- [ ] **Step 3: 提交**

```bash
git add src/taisang/web/app.py docs/superpowers/specs/2026-09-02-session-persistence-design.md
git commit -m "docs: 更新路由注释 + spec 状态改已实施"
```

---

## 完工验证清单

全部 Task 完成后,跑一遍:

- [ ] `python -m pytest tests/ -v` 全 PASS
- [ ] 手动 Web UI 验证:新建会话 → 发消息 → 切到别的会话 → 切回来 → 看到完整历史
- [ ] 手动重启验证:`python -m taisang` → 发消息 → Ctrl+C → 重启 → 点会话 → 历史还在
- [ ] 手动压缩验证(可选):发足够多消息触发 autocompact → jsonl 里有 `[compacted via ...]` → 重启 → resume 看到压缩后状态 + UI 有压缩分隔符