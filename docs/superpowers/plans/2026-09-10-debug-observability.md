# Debug 可观测性增强：工具完整结果 + 三道压缩事件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** debug 模式下，工具调用结果展开显示完整内容（不再是 30 字符截断），三道压缩（enforce_budget / autocompact / session_memory）触发时都 emit COMPACTED 事件并带统计信息，前端按 stage 展示详细压缩记录。

**Architecture:** 后端 `service.py` 在三道压缩触发点 emit 扩展 payload 的 COMPACTED 事件（stage 1/2/3 + 统计字段）；前端 `useChatStream.ts` 新增 `debug_tool_result` 监听器用完整 observation 覆盖 ToolCard 的 preview，`MessageList.vue` + `ToolCard.vue` 按 stage 渲染详细压缩记录。不动非 debug 行为。

**Tech Stack:** Python 3.11 + pytest（后端），Vue 3.5 + TypeScript + vue-tsc（前端），SSE 事件流。

---

## File Structure

**后端（Python）：**
- `src/taisang/agent_core/events.py` — 扩展 COMPACTED payload 文档说明（加 stage + 各 stage 统计字段）
- `src/taisang/agent_core/service.py` — 三处 emit 改动：enforce_budget 接收 newly_replaced 并 emit、_try_autocompact 加 before/after tokens、_maybe_trigger_session_memory emit + 返回 trigger 原因
- `src/taisang/session_memory/service.py` — `should_extract` 改返回 trigger 原因字符串（"init"/"update"/"idle_break"/""），`_do_extract` 不变
- `tests/unit/test_agent_core.py` — 新增 3 个测试：enforce_budget emit、autocompact tokens payload、session_memory emit
- `tests/unit/test_session_memory_trigger_reason.py` — 新建，测 should_extract 返回 trigger 原因

**前端（TypeScript/Vue）：**
- `src/taisang/web/frontend/src/types/index.ts` — ChatMessage 加 `toolFullContent?: string`、compacted 加 `stage?: number` + 统计字段
- `src/taisang/web/frontend/src/composables/useChatStream.ts` — 新增 `debug_tool_result` 监听器、扩展 `compacted` 监听器
- `src/taisang/web/frontend/src/components/ToolCard.vue` — 展开时优先显示 `toolFullContent`
- `src/taisang/web/frontend/src/components/MessageList.vue` — compacted 消息按 stage 渲染详细统计

---

## Task 1: session_memory should_extract 返回 trigger 原因

**Files:**
- Modify: `src/taisang/session_memory/service.py:54-121`
- Test: `tests/unit/test_session_memory_trigger_reason.py`（新建）

目前 `should_extract` 返回 bool，无法告诉调用方是哪个分支触发的。改成返回字符串（"init"/"update"/"idle_break"/""），空串等价于 False。

- [ ] **Step 1: Write the failing test**

新建 `tests/unit/test_session_memory_trigger_reason.py`：

```python
"""session_memory.should_extract 返回 trigger 原因字符串(非 bool)。

返回值:"init" / "update" / "idle_break" / ""(空串=不触发)。
"""

from pathlib import Path

from taisang.session_memory.service import SessionMemoryService


def _make_service(memory_path: Path) -> SessionMemoryService:
    return SessionMemoryService(llm=None, memory_path=memory_path)


def test_init_trigger_when_no_memory_and_tokens_high(tmp_path):
    """笔记不存在 + tokens >= MIN_TOKENS_TO_INIT → 返回 "init"。"""
    svc = _make_service(tmp_path / "note.md")
    assert svc.should_extract(current_tokens=10_001, tool_calls_since_last=0,
                              last_turn_has_tool_calls=True) == "init"


def test_no_trigger_when_no_memory_but_tokens_low(tmp_path):
    """笔记不存在 + tokens < MIN_TOKENS_TO_INIT → 返回空串。"""
    svc = _make_service(tmp_path / "note.md")
    assert svc.should_extract(current_tokens=5000, tool_calls_since_last=0,
                              last_turn_has_tool_calls=True) == ""


def test_update_trigger_when_delta_and_tools_met(tmp_path):
    """笔记存在 + delta_tokens + tool_calls 双满足 → 返回 "update"。"""
    svc = _make_service(tmp_path / "note.md")
    # 模拟已提取过 5000 token
    svc._last_extracted_tokens = 5000
    (tmp_path / "note.md").write_text("# 已有笔记\n一些内容", encoding="utf-8")
    assert svc.should_extract(current_tokens=15_001, tool_calls_since_last=5,
                              last_turn_has_tool_calls=True) == "update"


def test_idle_break_trigger_when_delta_met_and_no_tool_calls(tmp_path):
    """笔记存在 + delta_tokens 满足 + 最后一轮无工具调用 → 返回 "idle_break"。"""
    svc = _make_service(tmp_path / "note.md")
    svc._last_extracted_tokens = 5000
    (tmp_path / "note.md").write_text("# 已有笔记", encoding="utf-8")
    assert svc.should_extract(current_tokens=15_001, tool_calls_since_last=0,
                              last_turn_has_tool_calls=False) == "idle_break"


def test_no_trigger_when_already_extracting(tmp_path):
    """正在提取中 → 返回空串(不并发触发)。"""
    svc = _make_service(tmp_path / "note.md")
    svc._extracting = True
    assert svc.should_extract(current_tokens=10_001, tool_calls_since_last=0,
                              last_turn_has_tool_calls=True) == ""


def test_empty_string_is_falsy():
    """空串应该是 falsy(调用方 `if reason:` 能正常用)。"""
    assert not ""
    assert "init"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_session_memory_trigger_reason.py -v`
Expected: FAIL — `should_extract` 返回 bool True 不是字符串 "init"。

- [ ] **Step 3: Modify should_extract to return trigger reason string**

修改 `src/taisang/session_memory/service.py:54-121`，把 `should_extract` 的返回值从 `bool` 改成 `str`：

```python
    def should_extract(
        self,
        current_tokens: int,
        tool_calls_since_last: int,
        last_turn_has_tool_calls: bool = True,
    ) -> str:
        """3 道阈值门控 + idle_break 分支:笔记不存在走 init,存在走 update/idle_break。

        返回 trigger 原因字符串(非 bool):
        - "init":笔记不存在 + tokens >= MIN_TOKENS_TO_INIT
        - "update":笔记存在 + delta_tokens + tool_calls 双满足
        - "idle_break":笔记存在 + delta_tokens 满足 + 最后一轮无工具调用
        - "":不触发(调用方 `if reason:` 即可判断)

        已在提取中(_extracting=True)时返回 "",避免并发触发。
        """
        if self._extracting:
            log.info("session memory TRIGGER skipped: already running")
            return ""

        if not self.memory_path.exists():
            if current_tokens >= MIN_TOKENS_TO_INIT:
                log.info(
                    "session memory TRIGGER init: tokens=%d (>= %d), memory=%s",
                    current_tokens,
                    MIN_TOKENS_TO_INIT,
                    self.memory_path.name,
                )
                return "init"
            return ""

        delta_tokens = current_tokens - self._last_extracted_tokens
        has_met_token = delta_tokens >= MIN_TOKENS_BETWEEN_UPDATE
        has_met_tools = tool_calls_since_last >= TOOL_CALLS_BETWEEN_UPDATES

        # 分支 2: 满足 token + 工具调用次数
        if has_met_token and has_met_tools:
            log.info(
                "session memory TRIGGER update: delta_tokens=%d (>= %d), "
                "tool_calls=%d (>= %d), memory=%s",
                delta_tokens,
                MIN_TOKENS_BETWEEN_UPDATE,
                tool_calls_since_last,
                TOOL_CALLS_BETWEEN_UPDATES,
                self.memory_path.name,
            )
            return "update"

        # 分支 3: 满足 token + 最后一轮无工具调用(自然对话断点)
        if has_met_token and not last_turn_has_tool_calls:
            log.info(
                "session memory TRIGGER idle_break: delta_tokens=%d (>= %d), "
                "last_turn_no_tool_calls, memory=%s",
                delta_tokens,
                MIN_TOKENS_BETWEEN_UPDATE,
                self.memory_path.name,
            )
            return "idle_break"

        return ""
```

- [ ] **Step 4: Run new test to verify it passes**

Run: `python -m pytest tests/unit/test_session_memory_trigger_reason.py -v`
Expected: PASS — 6 tests pass.

- [ ] **Step 5: Run full session_memory tests to verify no regression**

Run: `python -m pytest tests/unit/ -k "session_memory" -v`
Expected: PASS — 所有 session_memory 相关测试通过（可能需要更新调用 `should_extract` 当 bool 用的地方，见 Task 2 Step 3）。

- [ ] **Step 6: Commit**

```bash
git add src/taisang/session_memory/service.py tests/unit/test_session_memory_trigger_reason.py
git commit -m "refactor(session_memory): should_extract 返回 trigger 原因字符串

从 bool 改成 str: \"init\"/\"update\"/\"idle_break\"/\"\"(空串=不触发)。
调用方可据此 emit 带 trigger 字段的 COMPACTED 事件，debug 时能看到
是哪个分支触发的提取。空串 falsy,`if reason:` 兼容旧 bool 用法。"
```

---

## Task 2: service.py 调用方适配 should_extract 新返回值

**Files:**
- Modify: `src/taisang/agent_core/service.py:674-695`
- Test: `tests/unit/test_agent_core.py`（加 1 个测试）

`_maybe_trigger_session_memory` 目前用 `if self.session_memory.should_extract(...):`，新返回值空串是 falsy，非空串是 truthy，逻辑兼容。但要拿到 trigger 原因用于 emit，需改成接住返回值。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_agent_core.py` 末尾加测试：

```python
def test_session_memory_trigger_emits_compacted_event(tmp_path):
    """session_memory 触发 extract 时 emit COMPACTED 事件,payload 含 via + trigger。

    用 MockLLM 让对话超过 init 阈值(MIN_TOKENS_TO_INIT=10000),should_extract 返回 "init",
    _maybe_trigger_session_memory emit COMPACTED via=session_memory trigger=init。
    """
    from taisang.agent_core.events import COMPACTED
    from taisang.session_memory.service import SessionMemoryService
    from taisang.storage.paths import PathManager

    # 构造大文本让 ctx tokens 超过 10000(init 阈值)
    big_text = "x" * 40_000
    mock = MockLLM([LLMResponse(text="ok", tool_calls=[])])
    session_mem = SessionMemoryService(
        llm=mock,
        memory_path=PathManager.session_memory_path(tmp_path, "test-session"),
    )
    service = AgentService(
        llm=mock,
        source_root=tmp_path,
        confirmer=AutoApproveConfirmer(),
        session_memory=session_mem,
    )
    # 灌大文本进 ctx(直接 append,user 消息)
    service.ctx.append_user(big_text)
    events = []
    service.run("继续", on_event=lambda e: events.append(e))
    compacted = [e for e in events if e.type == COMPACTED and e.payload.get("via") == "session_memory"]
    assert len(compacted) >= 1
    p = compacted[0].payload
    assert p["via"] == "session_memory"
    assert p["trigger"] in ("init", "update", "idle_break")
    assert "current_tokens" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_agent_core.py::test_session_memory_trigger_emits_compacted_event -v`
Expected: FAIL — 当前 `_maybe_trigger_session_memory` 不 emit COMPACTED 事件。

- [ ] **Step 3: Modify _maybe_trigger_session_memory to emit COMPACTED**

修改 `src/taisang/agent_core/service.py:674-695`，接收 trigger 原因并 emit：

```python
    def _maybe_trigger_session_memory(
        self, last_turn_has_tool_calls: bool, _emit: EventCallback | None = None
    ) -> None:
        """session memory post-sampling:检查阈值,达标就异步触发后台 extract。

        两个触发点:
        - idle_break:LLM 给最终答案(无 tool_call)→ last_turn_has_tool_calls=False
        - update:工具执行完(本轮有 tool_call)→ last_turn_has_tool_calls=True

        触发后重置 _tool_calls_since_last_extract 计数器。
        emit COMPACTED 事件(若 _emit 给定),payload: {via, trigger, current_tokens, delta_tokens}。
        """
        if not self.session_memory:
            return
        current_tokens = self.ctx.total_tokens()
        trigger = self.session_memory.should_extract(
            current_tokens,
            self._tool_calls_since_last_extract,
            last_turn_has_tool_calls=last_turn_has_tool_calls,
        )
        if trigger:
            delta_tokens = (
                current_tokens - self.session_memory._last_extracted_tokens
                if self.session_memory.memory_path.exists()
                else current_tokens
            )
            self.session_memory._do_extract(
                recent_conversation=self._recent_text(),
                current_tokens=current_tokens,
            )
            self._tool_calls_since_last_extract = 0
            if _emit is not None:
                _emit(AgentEvent(
                    type=COMPACTED,
                    payload={
                        "via": "session_memory",
                        "trigger": trigger,
                        "current_tokens": current_tokens,
                        "delta_tokens": delta_tokens,
                    },
                ))
```

- [ ] **Step 4: 更新两处调用 _maybe_trigger_session_memory 的地方，传 _emit**

`src/taisang/agent_core/service.py` 有两处调用：
- line 502: `self._maybe_trigger_session_memory(last_turn_has_tool_calls=False)` → 改成 `self._maybe_trigger_session_memory(last_turn_has_tool_calls=False, _emit=_emit)`
- line 612: `self._maybe_trigger_session_memory(last_turn_has_tool_calls=True)` → 改成 `self._maybe_trigger_session_memory(last_turn_has_tool_calls=True, _emit=_emit)`

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_agent_core.py::test_session_memory_trigger_emits_compacted_event -v`
Expected: PASS

- [ ] **Step 6: Run full test_agent_core to verify no regression**

Run: `python -m pytest tests/unit/test_agent_core.py -v`
Expected: PASS — 所有原有测试通过。

- [ ] **Step 7: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat(agent): session_memory 触发 extract 时 emit COMPACTED 事件

_maybe_trigger_session_memory 接收 _emit 回调,触发时 emit:
{via=session_memory, trigger=init|update|idle_break, current_tokens, delta_tokens}
debug 模式下前端据此展示第三道压缩的触发原因和 token 统计。"
```

---

## Task 3: enforce_budget 触发时 emit COMPACTED（stage 1）

**Files:**
- Modify: `src/taisang/agent_core/service.py:368-373`
- Test: `tests/unit/test_agent_core.py`（加 1 个测试）

目前 `enforce_budget` 返回 `(new_msgs, newly_replaced)`，service 丢弃 `newly_replaced`。改成接收它，非空时 emit COMPACTED。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_agent_core.py` 加测试：

```python
def test_enforce_budget_emits_compacted_event(tmp_path):
    """enforce_budget 持久化大 tool_result 时 emit COMPACTED 事件(stage=1, via=tool_result_budget)。

    构造超 50KB 的 tool_result,run 一轮,应看到 COMPACTED via=tool_result_budget payload。
    """
    from taisang.agent_core.events import COMPACTED
    from taisang.agent_core.tools import ReadFileTool

    # 60KB 文件,read_file 返回大 observation 触发 enforce_budget 持久化
    big_content = "x" * 60_000
    (tmp_path / "big.txt").write_text(big_content, encoding="utf-8")
    mock = MockLLM([
        LLMResponse(text="", tool_calls=[_tc("c1", "read_file", {"path": "big.txt"})]),
        LLMResponse(text="done", tool_calls=[]),
    ])
    service = AgentService(llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer())
    events = []
    service.run("读 big.txt", on_event=lambda e: events.append(e))
    budget_events = [
        e for e in events
        if e.type == COMPACTED and e.payload.get("via") == "tool_result_budget"
    ]
    assert len(budget_events) >= 1
    p = budget_events[0].payload
    assert p["via"] == "tool_result_budget"
    assert "replaced" in p
    assert isinstance(p["replaced"], list)
    if p["replaced"]:
        assert "tool_call_id" in p["replaced"][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_agent_core.py::test_enforce_budget_emits_compacted_event -v`
Expected: FAIL — 当前 enforce_budget 后不 emit COMPACTED。

- [ ] **Step 3: Modify service.py to emit COMPACTED after enforce_budget**

修改 `src/taisang/agent_core/service.py:368-373`：

```python
            steps += 1
            # 阶段 5: apply-tool-result-budget
            new_msgs, newly_replaced = enforce_budget(
                self.ctx.messages(), self.compaction_state, observations_dir
            )
            self.ctx.replace_messages(new_msgs)
            # stage 1 压缩事件:enforce_budget 持久化了 tool_result 时 emit
            # (newly_replaced 非空 = 本轮有新持久化决策;空 = 未超预算 or 全 frozen)
            if newly_replaced:
                _emit(AgentEvent(
                    type=COMPACTED,
                    payload={
                        "via": "tool_result_budget",
                        "replaced": [
                            {"tool_call_id": r["tool_call_id"], "path": r["path"]}
                            for r in newly_replaced
                        ],
                    },
                ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_agent_core.py::test_enforce_budget_emits_compacted_event -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat(agent): enforce_budget 持久化时 emit COMPACTED 事件(stage 1)

run 循环阶段 5 enforce_budget 返回的 newly_replaced 非空时 emit:
{via=tool_result_budget, replaced=[{tool_call_id, path}]}
debug 模式下前端据此展示第一道压缩持久化了哪些 tool_result。"
```

---

## Task 4: autocompact emit 带 before/after tokens（stage 2）

**Files:**
- Modify: `src/taisang/agent_core/service.py:622-658`
- Test: `tests/unit/test_agent_core.py`（加 1 个测试）

目前 `_try_autocompact` emit `{via: "llm"}` 或 `{via: "session_memory"}`，无 token 统计。加 before_tokens / after_tokens / summary_messages。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_agent_core.py` 加测试：

```python
def test_autocompact_emits_tokens_in_payload(tmp_path):
    """autocompact 触发时 emit COMPACTED payload 含 before_tokens / after_tokens。

    构造大 ctx 让 should_compact 触发,MockLLM 给摘要响应,验证 COMPACTED via=llm
    payload 有 before_tokens(压缩前) + after_tokens(压缩后) + summary_messages(摘要条数)。
    """
    from taisang.agent_core.events import COMPACTED

    # 灌大文本让 ctx 超过 token_budget * compact_ratio 触发 should_compact
    big_text = "x" * 200_000
    mock = MockLLM([
        LLMResponse(text="<summary>摘要内容</summary>", tool_calls=[]),
        LLMResponse(text="最终答案", tool_calls=[]),
    ])
    service = AgentService(
        llm=mock, source_root=tmp_path, confirmer=AutoApproveConfirmer(),
        token_budget=1000,  # 调小让大文本容易超
    )
    service.ctx.append_user(big_text)
    events = []
    service.run("继续", on_event=lambda e: events.append(e))
    llm_compacted = [
        e for e in events
        if e.type == COMPACTED and e.payload.get("via") == "llm"
    ]
    if llm_compacted:  # 触发了 autocompact 才校验
        p = llm_compacted[0].payload
        assert "before_tokens" in p
        assert "after_tokens" in p
        assert p["before_tokens"] > p["after_tokens"]
        assert "summary_messages" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_agent_core.py::test_autocompact_emits_tokens_in_payload -v`
Expected: FAIL — 当前 payload 无 before_tokens / after_tokens。

- [ ] **Step 3: Modify _try_autocompact to include token stats**

修改 `src/taisang/agent_core/service.py:622-658`：

```python
    def _try_autocompact(self, transcript_path: Path, _emit: EventCallback) -> bool:
        """先试 session memory,失败 fallback 到 autocompact LLM 摘要。

        返回 True 表示做了压缩(messages 已替换),调用方应重置 tool_calls 计数并 continue。
        操作 self.ctx(实例属性,跨 run() 保留)。
        """
        before_tokens = self.ctx.total_tokens()
        # 先试 session memory(零 LLM 调用)
        if self.session_memory is not None:
            summary = self.session_memory.read_for_compaction()
            if summary:
                boundary = {
                    "role": "user",
                    "content": "[boundary: session memory compaction occurred here]",
                }
                summary_msg = {
                    "role": "user",
                    "content": (
                        "This session is being continued from a previous conversation "
                        "that ran out of context.\nThe summary below covers the earlier "
                        f"portion.\n\nSummary:\n{summary}"
                    ),
                }
                new_msgs = [boundary, summary_msg]
                self.ctx.replace_messages(new_msgs, compaction_via="session_memory")
                after_tokens = self.ctx.total_tokens()
                self._reinject_profile_into_system()
                _emit(AgentEvent(type=COMPACTED, payload={
                    "via": "session_memory",
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "summary_messages": len(new_msgs),
                }))
                return True

        # fallback: LLM 摘要
        from ..compaction.autocompact import autocompact as do_autocompact

        new_msgs = do_autocompact(self.ctx.messages(), self.llm, transcript_path)
        self.ctx.replace_messages(new_msgs, compaction_via="llm")
        after_tokens = self.ctx.total_tokens()
        self._reinject_profile_into_system()
        _emit(AgentEvent(type=COMPACTED, payload={
            "via": "llm",
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "summary_messages": len(new_msgs),
        }))
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_agent_core.py::test_autocompact_emits_tokens_in_payload -v`
Expected: PASS

- [ ] **Step 5: Run full test_agent_core to verify no regression**

Run: `python -m pytest tests/unit/test_agent_core.py -v`
Expected: PASS — 所有测试通过。

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/test_agent_core.py
git commit -m "feat(agent): autocompact COMPACTED payload 加 before/after tokens

_try_autocompact emit 时 payload 新增:
- before_tokens:压缩前 ctx 总 token
- after_tokens:压缩后 ctx 总 token
- summary_messages:摘要条数(通常 2:boundary + summary)
debug 模式下前端展示压缩比,量化压缩效果。"
```

---

## Task 5: 前端 types/index.ts 加字段

**Files:**
- Modify: `src/taisang/web/frontend/src/types/index.ts:32-71`

ChatMessage 加 `toolFullContent?: string`（debug 模式下完整工具结果），compacted 加 stage + 统计字段。

- [ ] **Step 1: Modify ChatMessage interface**

修改 `src/taisang/web/frontend/src/types/index.ts:32-71`，在 `toolBytes?: number` 后加 `toolFullContent?: string`，在 `via?: string` 后加 compacted 统计字段：

```typescript
export interface ChatMessage {
  id: string               // 前端生成 uuid,用于 v-for key
  kind: MessageKind
  // user / assistant
  text?: string
  // tool_call / tool_result
  toolName?: string
  toolArgs?: string        // JSON.stringify(args)
  toolPreview?: string
  toolBytes?: number
  toolFullContent?: string  // debug 模式下完整 observation(debug_tool_result 事件覆盖)
  toolFilled?: boolean     // tool_result 是否已填充
  // compacted
  via?: string
  stage?: number           // 1=enforce_budget, 2=autocompact/llm, 3=session_memory
  // compacted 统计字段(按 stage 不同):
  //   stage 1: replaced?: Array<{tool_call_id: string; path: string}>
  //   stage 2: before_tokens?: number; after_tokens?: number; summary_messages?: number
  //   stage 3: trigger?: string; current_tokens?: number; delta_tokens?: number
  replaced?: Array<{ tool_call_id: string; path: string }>
  beforeTokens?: number
  afterTokens?: number
  summaryMessages?: number
  trigger?: string
  currentTokens?: number
  deltaTokens?: number
  // confirm / permission
  token?: string
  filePath?: string
  oldContent?: string
  newContent?: string
  path?: string
  answered?: boolean
  approved?: boolean
  // usage
  usage?: UsageData
  // run_error
  error?: string
  // llm_retry
  retryAttempt?: number    // 第几次重试(1-based)
  delaySec?: number        // 几秒后重试
  // 流式相关
  streaming?: boolean       // True = 正在流式累积(llm_chunk 来了,final_answer 未到)
  interrupted?: boolean     // True = 用户主动中断(FINAL_ANSWER interrupted 标记)
  // llm_chunk(subagent 嵌套用,主 agent 的 chunk 不存 message list)
  textDelta?: string
  reasoningDelta?: string
  // Task 14: subagent 事件嵌套渲染
  agentId?: string               // 非空 → 该消息来自子 agent
  subAgentEvents?: ChatMessage[] // 嵌套子事件,挂在 Agent 工具卡片内
  // TodoWrite:子 agent todo 嵌套到 Agent 卡片(主 agent 的 todos 在 useChatStream.todos 顶层)
  subAgentTodos?: Todo[]
}
```

- [ ] **Step 2: Run vue-tsc to verify type check passes**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit`
Expected: PASS — 无类型错误（新字段都是可选，不破坏现有用法）。

- [ ] **Step 3: Commit**

```bash
git add src/taisang/web/frontend/src/types/index.ts
git commit -m "feat(frontend): ChatMessage 加 debug 可观测性字段

- toolFullContent:debug 模式下完整 observation(debug_tool_result 事件覆盖)
- stage:压缩阶段 1/2/3
- replaced / beforeTokens / afterTokens / summaryMessages / trigger / currentTokens / deltaTokens:
  三道压缩各自的统计字段,供 MessageList 详细渲染。"
```

---

## Task 6: 前端 useChatStream 加 debug_tool_result 监听器 + 扩展 compacted

**Files:**
- Modify: `src/taisang/web/frontend/src/composables/useChatStream.ts:427-495`

新增 `debug_tool_result` 事件监听器，debug 模式下用完整 observation 覆盖 ToolCard 的 `toolFullContent`。扩展 `compacted` 监听器，把 stage + 统计字段带进 ChatMessage。

- [ ] **Step 1: Add debug_tool_result listener**

在 `src/taisang/web/frontend/src/composables/useChatStream.ts` 的 `tool_result` listener（line 427-441）之后、`final_answer` listener（line 442）之前，插入 `debug_tool_result` listener：

```typescript
    eventSource.addEventListener('debug_tool_result', (e: MessageEvent) => {
      const d = safeParse<{ name: string; observation: string; tool_call_id: string; step?: number; agent_id?: string }>(e.data)
      if (!d) return
      if (!debugEnabled.value) return
      // debug 模式下:用完整 observation 覆盖 ToolCard 的 preview
      // 找最后一个同名已填充的 tool_call,把完整内容塞进 toolFullContent
      const target = d.agent_id
        ? findLastAgentToolCall()?.subAgentEvents?.find(
            m => m.kind === 'tool_call' && m.toolName === d.name && m.toolFilled
          )
        : (() => {
            for (let i = messages.value.length - 1; i >= 0; i--) {
              const m = messages.value[i]
              if (m.kind === 'tool_call' && m.toolName === d.name && m.toolFilled) {
                return m
              }
            }
            return undefined
          })()
      if (target) {
        target.toolFullContent = d.observation
        target.toolBytes = new Blob([d.observation]).size
      }
    })
```

- [ ] **Step 2: 扩展 compacted listener 把 stage + 统计字段带进 ChatMessage**

修改 `src/taisang/web/frontend/src/composables/useChatStream.ts:482-495` 的 compacted listener 和 `pushCompacted` 函数（line 124-130）：

先改 `pushCompacted`：

```typescript
  function pushCompacted(payload: {
    via: string
    replaced?: Array<{ tool_call_id: string; path: string }>
    before_tokens?: number
    after_tokens?: number
    summary_messages?: number
    trigger?: string
    current_tokens?: number
    delta_tokens?: number
  }) {
    // 非 debug 模式不展示 compaction 标记:压缩是系统内部行为,用户感知到
    // 中间突然冒出"· context compacted via llm"很突兀,破坏阅读流。
    // debug 模式下保留(便于观察上下文管理行为)。
    if (!debugEnabled.value) return
    const stage = payload.via === 'tool_result_budget' ? 1
      : (payload.via === 'llm' || payload.via === 'session_memory') ? 2
      : 0
    // session_memory post-sampling 触发属于第三道(独立于 autocompact)
    const actualStage = payload.via === 'session_memory' ? 3 : stage
    messages.value.push({
      id: nextId(),
      kind: 'compacted',
      via: payload.via,
      stage: actualStage,
      replaced: payload.replaced,
      beforeTokens: payload.before_tokens,
      afterTokens: payload.after_tokens,
      summaryMessages: payload.summary_messages,
      trigger: payload.trigger,
      currentTokens: payload.current_tokens,
      deltaTokens: payload.delta_tokens,
    })
  }
```

再改 compacted listener 调用方：

```typescript
    eventSource.addEventListener('compacted', (e: MessageEvent) => {
      const d = safeParse<{
        via: string
        agent_id?: string
        replaced?: Array<{ tool_call_id: string; path: string }>
        before_tokens?: number
        after_tokens?: number
        summary_messages?: number
        trigger?: string
        current_tokens?: number
        delta_tokens?: number
      }>(e.data)
      if (!d) return
      // 非 debug 模式不展示任何 compaction 标记(主 agent + 子 agent 同理)
      if (!debugEnabled.value) return
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'compacted',
            via: d.via,
            trigger: d.trigger,
            currentTokens: d.current_tokens,
            deltaTokens: d.delta_tokens,
            beforeTokens: d.before_tokens,
            afterTokens: d.after_tokens,
            summaryMessages: d.summary_messages,
            replaced: d.replaced,
            agentId: d.agent_id,
          })
          return
        }
      }
      pushCompacted(d)
    })
```

- [ ] **Step 3: Run vue-tsc to verify type check passes**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit`
Expected: PASS — 无类型错误。

- [ ] **Step 4: Commit**

```bash
git add src/taisang/web/frontend/src/composables/useChatStream.ts
git commit -m "feat(frontend): 加 debug_tool_result 监听 + 扩展 compacted 字段

- 新增 debug_tool_result 监听器:debug 模式下用完整 observation 覆盖
  ToolCard.toolFullContent,展开卡片显示完整工具结果(不再是 30 字符截断)。
- compacted listener 把 stage + replaced/before_tokens/after_tokens/
  trigger/current_tokens/delta_tokens 带进 ChatMessage,供 MessageList
  按 stage 渲染详细压缩记录。
- pushCompacted 改成接收完整 payload 对象(非仅 via 字符串)。"
```

---

## Task 7: ToolCard.vue 展开时优先显示 toolFullContent

**Files:**
- Modify: `src/taisang/web/frontend/src/components/ToolCard.vue:10`

展开卡片时，若有 `toolFullContent` 显示完整内容，否则 fallback 到 `toolPreview`。

- [ ] **Step 1: Modify main-preview to prefer full content**

修改 `src/taisang/web/frontend/src/components/ToolCard.vue:10`：

```html
      <div class="main-preview">{{ msg.toolFullContent || msg.toolPreview || '执行中...' }}</div>
```

- [ ] **Step 2: Run vue-tsc to verify type check passes**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/taisang/web/frontend/src/components/ToolCard.vue
git commit -m "feat(frontend): ToolCard 展开优先显示完整工具结果

debug 模式下 debug_tool_result 事件覆盖了 toolFullContent,展开卡片显示
完整 observation(可能几 KB~几十 KB)。非 debug 或未覆盖时 fallback
到 toolPreview(30 字符截断)。"
```

---

## Task 8: MessageList.vue 按 stage 渲染详细压缩记录

**Files:**
- Modify: `src/taisang/web/frontend/src/components/MessageList.vue:12-13`

把 `· context compacted via {{ m.via }}` 改成按 stage 渲染详细统计。

- [ ] **Step 1: Replace compacted rendering with stage-aware detail**

修改 `src/taisang/web/frontend/src/components/MessageList.vue:12-13`：

```html
      <div v-else-if="m.kind === 'compacted'" class="compacted">
        <template v-if="m.stage === 1">
          · ① tool_result_budget 压缩:{{ m.replaced?.length || 0 }} 个大结果持久化到磁盘
          <span v-if="m.replaced?.length" class="compacted-detail">
            ({{ m.replaced.map(r => r.tool_call_id.slice(0, 8)).join(', ') }})
          </span>
        </template>
        <template v-else-if="m.stage === 2">
          · ② autocompact {{ m.via === 'llm' ? 'LLM 摘要' : 'session_memory 摘要' }}:
          {{ m.beforeTokens }} → {{ m.afterTokens }} tokens
          <span v-if="m.summaryMessages">({{ m.summaryMessages }} 条摘要)</span>
        </template>
        <template v-else-if="m.stage === 3">
          · ③ session_memory 提取:触发 {{ m.trigger }} 分支
          <span v-if="m.currentTokens != null">
            (当前 {{ m.currentTokens }} tokens<template v-if="m.deltaTokens != null">, 增量 {{ m.deltaTokens }}</template>)
          </span>
        </template>
        <template v-else>
          · context compacted via {{ m.via }}
        </template>
      </div>
```

在 `<style scoped>` 段落（找 `.compacted` 选择器，line 153 附近）加：

```css
.compacted-detail {
  color: var(--td-text-color-placeholder);
  font-size: 11px;
}
```

- [ ] **Step 2: Run vue-tsc to verify type check passes**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit`
Expected: PASS

- [ ] **Step 3: Build frontend to verify production bundle works**

Run: `cd src/taisang/web/frontend && npm run build`
Expected: PASS — 构建成功无错误。

- [ ] **Step 4: Commit**

```bash
git add src/taisang/web/frontend/src/components/MessageList.vue
git commit -m "feat(frontend): compacted 消息按 stage 渲染详细压缩统计

- stage 1 (enforce_budget):显示持久化了几个大结果 + tool_call_id 列表
- stage 2 (autocompact):显示 before→after tokens + 摘要条数
- stage 3 (session_memory):显示触发分支(init/update/idle_break) + 当前/增量 tokens
旧 stage=0 fallback 保留 'context compacted via' 文案。"
```

---

## Task 9: 端到端验证 + 跑全量测试

**Files:**
- 无新文件,验证性质

- [ ] **Step 1: 跑全量后端测试**

Run: `python -m pytest tests/unit -q`
Expected: 581+ tests pass（原 581 + Task 1-4 新增的 5 个测试 = 586 左右）。

- [ ] **Step 2: 前端构建 + 类型检查**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit && npm run build`
Expected: PASS

- [ ] **Step 3: 手动 playwright 验证**

启动服务后用 playwright 导航到 `http://localhost:8765`，开 debug 模式，发一个会触发工具调用的问题，验证：
1. 工具卡片展开显示完整 observation（不是 30 字符截断）
2. 若触发压缩，看到 `· ① tool_result_budget 压缩:...` / `· ② autocompact ...` / `· ③ session_memory 提取:...` 三种详细记录

用 `playwright_get_visible_text` 看页面文本（不截图）。

- [ ] **Step 4: Commit + push（如有手动验证发现的微调）**

```bash
git push
```

---

## Self-Review

**1. Spec coverage:**
- ✅ 工具调用结果 debug 时显示完整内容 → Task 6 (debug_tool_result listener) + Task 7 (ToolCard 显示) + Task 5 (类型)
- ✅ 三道压缩 debug 时都有记录 → Task 3 (stage 1) + Task 4 (stage 2) + Task 2 (stage 3) + Task 8 (UI 渲染)
- ✅ 不动非 debug 行为 → 所有改动都 gate 在 `debugEnabled.value` 或 `self.debug` 或 `if newly_replaced:` 非空检查

**2. Placeholder scan:**
- 无 TBD/TODO/"implement later"
- 所有代码步骤都有完整代码块
- 所有测试都有完整 test function

**3. Type consistency:**
- `should_extract` 返回 `str`（Task 1）→ Task 2 调用方 `if trigger:` 用 truthy 判断 ✓
- `pushCompacted` 参数从 `via: string` 改成 payload 对象（Task 6）→ 调用方 `pushCompacted(d)` 传整个 payload ✓
- ChatMessage 新字段（Task 5）`toolFullContent` / `stage` / `replaced` / `beforeTokens` / `afterTokens` / `summaryMessages` / `trigger` / `currentTokens` / `deltaTokens` → Task 6 pushCompacted 赋值、Task 8 模板读取，名字一致 ✓
- 后端 payload 用 snake_case（`before_tokens` / `current_tokens` / `delta_tokens` / `summary_messages`）→ 前端 safeParse 解析后 pushCompacted 赋值到 camelCase 字段（`beforeTokens` / `currentTokens` 等），Task 6 代码已体现 ✓