# 消息队列 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 思考期间用户连续发消息 → 后端排队 → turn 结束后自动拼接跑下一轮；点停止时先清队列再中断

**Architecture:** 后端 `_Session` 加 `queue: list[str]` 字段，`_run_next()` 统一入口用 `acquire(blocking=False)` 防竞态，`send_message` 无条件 append + `_run_next`，`interrupt` 先清队列再中断。前端 `pendingQueue` 镜像后端队列，`send/stop` 本地管理气泡，SSE `queue_updated` 事件同步。

**Tech Stack:** Python 3.11 + FastAPI + Pydantic + pytest (后端);Vue 3.5 + TypeScript + TDesign Vue Next + Vite (前端)

**Spec:** `docs/superpowers/specs/2026-09-11-message-queue-design.md`

---

## File Structure

**后端改动:**
- `src/taisang/web/session_registry.py` — `_Session` 加 `queue: list[str]` 字段
- `src/taisang/web/app.py` — 新增 `_run_next` + 改 `send_message` / `interrupt` + 新增 `GET /queue`

**前端改动:**
- `src/taisang/web/frontend/src/composables/useChatStream.ts` — 加 `pendingQueue` + 改 `send` / `stop` / `loadHistory` + SSE `queue_updated`
- `src/taisang/web/frontend/src/components/MessageInput.vue` — 思考时 placeholder 改提示
- `src/taisang/web/frontend/src/api/chat.ts` — 加 `getQueue` 函数

**测试:**
- `tests/unit/test_message_queue.py` — 新增 15 个单元测试

---

## Task 1: 后端 _Session 加 queue 字段

**Files:**
- Modify: `src/taisang/web/session_registry.py:44-58`

**Interfaces:**
- Consumes: nothing new
- Produces: `_Session.queue: list[str]` — 后续 task 读写此字段

- [ ] **Step 1: 加 queue 字段**

在 `src/taisang/web/session_registry.py` 的 `_Session` dataclass 里，`lock` 字段之后加一行:

```python
    queue: list[str] = field(default_factory=list)  # 待发消息队列(思考期间发的)
```

- [ ] **Step 2: 跑现有测试确认没破坏**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_web_session_registry.py -v 2>&1 | tail -10
```
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/session_registry.py
git commit -m "feat(session): add queue field to _Session for message queuing"
```

---

## Task 2: 后端 _run_next 辅助函数

**Files:**
- Modify: `src/taisang/web/app.py` — 在 `send_message` 之前新增 `_run_next`

**Interfaces:**
- Consumes: `_Session.queue`, `_Session.lock`, `_Session.broker`
- Produces: `_run_next(sess, session_id)` — `send_message` 和 `_run` finally 块调此函数

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_message_queue.py`:

```python
"""消息队列单元测试: _run_next / send_message / interrupt / GET /queue"""
import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from taisang.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    app = create_app(tmp_path)
    return TestClient(app)


def test_run_next_empty_queue_noop(client, tmp_path):
    """queue 空,_run_next 不拿锁直接 return。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    from taisang.web.app import _run_next
    # queue 空,不拿锁
    _run_next(sess, sid)
    assert not sess.lock.locked()
    assert sess.queue == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py::test_run_next_empty_queue_noop -v 2>&1 | tail -10
```
Expected: FAIL with `ImportError: cannot import name '_run_next'`

- [ ] **Step 3: 实现 _run_next**

在 `src/taisang/web/app.py` 的 `send_message` 路由之前(约 190 行),插入:

```python
def _run_next(sess, session_id) -> None:
    """尝试跑下一个 turn: 拿锁 + 拼接 queue + 跑。
    拿不到锁(return False) → 已有 turn 在跑, run_end 会自动调本函数。
    """
    if not sess.queue:  # 空队列没东西跑
        return
    if not sess.lock.acquire(blocking=False):  # 已锁(run 在跑或 flush 在跑)
        return
    # 拿到锁: 拼接 queue 为一条 prompt
    queries = list(sess.queue)
    sess.queue.clear()
    sess.broker.publish("queue_updated", {"queue": [], "len": 0})
    prompt = "\n".join(queries)

    def _run():
        try:
            sess.agent.run(
                prompt,
                on_event=lambda e: sess.broker.publish(
                    e.type, {**e.payload, "agent_id": e.agent_id}
                ),
            )
        except Exception as e:
            log.exception("agent run failed: %s", e)
            sess.broker.publish("run_error", {"error": f"agent run failed: {e}"})
        finally:
            try:
                registry.update_meta_after_turn(session_id, prompt)
            except Exception as e:
                log.warning("update_meta_after_turn failed: %s", e)
            sess.broker.publish(
                "session_title_updated",
                {"id": session_id, "title": sess.title},
            )
            sess.broker.publish("run_end", {})
            sess.lock.release()
            _run_next(sess, session_id)  # 递归 drain

    asyncio.get_running_loop().run_in_executor(None, _run)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py::test_run_next_empty_queue_noop -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/app.py tests/unit/test_message_queue.py
git commit -m "feat(web): add _run_next helper for message queue drain"
```

---

## Task 3: 后端 send_message 改造 — 去掉 409,无条件 append

**Files:**
- Modify: `src/taisang/web/app.py:197-240` (`send_message` 路由)

**Interfaces:**
- Consumes: `_run_next` (Task 2)
- Produces: 改造后的 `send_message` — 不再返回 409,改为 append + `_run_next`

- [ ] **Step 1: 写失败测试 — send_message 不再返回 409**

追加到 `tests/unit/test_message_queue.py`:

```python
def test_send_message_no_409_when_busy(client, tmp_path):
    """思考时 POST /messages 不再返回 409,改为排队。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    # 模拟 lock 已锁(turn 在跑)
    sess.lock.acquire(blocking=False)
    try:
        r = client.post(f"/api/sessions/{sid}/messages", json={"query": "排队消息"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["queued"] is True
        assert "排队消息" in sess.queue
    finally:
        sess.lock.release()


def test_send_message_triggers_run_when_idle(client, tmp_path):
    """lock 未锁时 POST /messages → append + _run_next 拿锁跑 turn。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"query": "直接跑"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # lock 已被 _run_next 拿走(跑完会 release)
    sess = client.app.state.registry.get_or_load(sid)
    # 等 run 跑完
    deadline = time.time() + 5
    while sess.lock.locked() and time.time() < deadline:
        time.sleep(0.01)
    # queue 已被清空(flush 了)
    assert sess.queue == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py::test_send_message_no_409_when_busy tests/unit/test_message_queue.py::test_send_message_triggers_run_when_idle -v 2>&1 | tail -15
```
Expected: FAIL (现状 send_message 返回 409)

- [ ] **Step 3: 改造 send_message**

把 `src/taisang/web/app.py` 的 `send_message` 路由(197-240 行)改成:

```python
    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageReq) -> dict:
        """发消息: 无条件 append 到 queue, 尝试 _run_next。

        turn 在跑时消息进队列, turn 结束后 _run_next 自动 drain。
        turn 没在跑时直接拿锁跑 turn。
        返回 {ok: true, queued: bool}(queued=True 表示进了队列, False 表示直接跑了)。
        """
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")

        sess.queue.append(req.query)
        queued = len(sess.queue) > 1  # 队列里不止这一条 → 已有 turn 在跑
        sess.broker.publish("queue_updated", {
            "queue": list(sess.queue), "len": len(sess.queue)
        })
        _run_next(sess, session_id)  # 尝试跑(没拿到锁会 return)
        return {"ok": True, "queued": queued}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py -v -k "send_message" 2>&1 | tail -15
```
Expected: 2 PASS

- [ ] **Step 5: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/app.py tests/unit/test_message_queue.py
git commit -m "feat(web): send_message 去掉 409,改为无条件 append + _run_next"
```

---

## Task 4: 后端 interrupt 改造 — 先清队列再中断

**Files:**
- Modify: `src/taisang/web/app.py:449-463` (`interrupt_session` 路由)

**Interfaces:**
- Consumes: `_Session.queue`, `_Session.broker`
- Produces: 改造后的 `interrupt_session` — 先 queue.clear() 再 agent.interrupt()

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_message_queue.py`:

```python
def test_interrupt_clears_queue_then_interrupts(client, tmp_path):
    """queue 有 2 条 + lock 已锁,POST interrupt 后 queue 空 + agent.interrupt() 被调。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    # 模拟 turn 在跑: 拿锁 + 往 queue 塞 2 条
    sess.lock.acquire(blocking=False)
    try:
        sess.queue.append("排队1")
        sess.queue.append("排队2")
        with patch.object(sess.agent, "interrupt") as mock_interrupt:
            r = client.post(f"/api/sessions/{sid}/interrupt")
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["interrupted"] is True
        assert sess.queue == []  # 队列已清空
        mock_interrupt.assert_called_once()
    finally:
        sess.lock.release()


def test_interrupt_clears_queue_even_when_idle(client, tmp_path):
    """queue 有 2 条 + lock 未锁(turn 刚结束),POST interrupt 后 queue 空, agent.interrupt() 不调。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    sess.queue.append("排队1")
    sess.queue.append("排队2")
    with patch.object(sess.agent, "interrupt") as mock_interrupt:
        r = client.post(f"/api/sessions/{sid}/interrupt")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["interrupted"] is False  # lock 未锁,没中断
    assert sess.queue == []  # 队列仍清空
    mock_interrupt.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py -v -k "interrupt_clears" 2>&1 | tail -15
```
Expected: FAIL (现状 interrupt 不清 queue)

- [ ] **Step 3: 改造 interrupt_session**

把 `src/taisang/web/app.py` 的 `interrupt_session` 路由(449-463 行)改成:

```python
    @app.post("/api/sessions/{session_id}/interrupt")
    async def interrupt_session(session_id: str) -> dict:
        """请求中断当前 turn: 先清队列, 再设 agent._cancel_event。

        幂等: turn 已结束或未开始时调用无副作用(返回 interrupted=False)。
        并发安全: threading.Event.set() thread-safe。
        不等中断生效就返回: 前端通过 FINAL_ANSWER(interrupted=True) 事件知道中断生效。
        """
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        # 先清队列(即使 lock 未锁也要清,用户可能发了排队消息但 turn 刚好结束还没 flush)
        sess.queue.clear()
        sess.broker.publish("queue_updated", {"queue": [], "len": 0})
        if not sess.lock.locked():
            return {"ok": True, "interrupted": False}
        sess.agent.interrupt()
        return {"ok": True, "interrupted": True}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py -v -k "interrupt" 2>&1 | tail -15
```
Expected: 4 PASS (2 个新 test + 2 个已有 test)

- [ ] **Step 5: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/app.py tests/unit/test_message_queue.py
git commit -m "feat(web): interrupt 先清 queue 再中断,推 queue_updated([])"
```

---

## Task 5: 后端 GET /queue 路由

**Files:**
- Modify: `src/taisang/web/app.py` — 在 `interrupt_session` 之后新增路由

**Interfaces:**
- Consumes: `_Session.queue`
- Produces: `GET /api/sessions/{session_id}/queue` — 返回当前队列状态

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_message_queue.py`:

```python
def test_get_queue_returns_current_state(client, tmp_path):
    """queue 有 2 条,GET 返回 {queue: [...], len: 2}。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    sess.queue.append("消息1")
    sess.queue.append("消息2")
    r = client.get(f"/api/sessions/{sid}/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["queue"] == ["消息1", "消息2"]
    assert data["len"] == 2


def test_get_queue_empty(client, tmp_path):
    """queue 空,GET 返回 {queue: [], len: 0}。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    r = client.get(f"/api/sessions/{sid}/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["queue"] == []
    assert data["len"] == 0


def test_get_queue_session_not_found(client):
    """不存在的 session_id → 404。"""
    r = client.get("/api/sessions/nonexistent/queue")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py -v -k "get_queue" 2>&1 | tail -15
```
Expected: FAIL (路由不存在,404)

- [ ] **Step 3: 新增 GET /queue 路由**

在 `src/taisang/web/app.py` 的 `interrupt_session` 路由之后(约 470 行),插入:

```python
    @app.get("/api/sessions/{session_id}/queue")
    async def get_queue(session_id: str) -> dict:
        """返回当前排队队列(前端刷新页面 SSE 重连后恢复 pendingQueue 用)。"""
        sess = registry.get_or_load(session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        return {"queue": list(sess.queue), "len": len(sess.queue)}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py -v -k "get_queue" 2>&1 | tail -15
```
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/app.py tests/unit/test_message_queue.py
git commit -m "feat(web): add GET /api/sessions/{id}/queue for queue state recovery"
```

---

## Task 6: 后端 _run 末尾递归 drain + 更多单元测试

**Files:**
- Modify: `src/taisang/web/app.py` — `_run_next` 的 finally 块已含递归
- Test: `tests/unit/test_message_queue.py` — 追加更多测试

**Interfaces:**
- Consumes: `_run_next` (Task 2)
- Produces: 递归 drain 行为 + 并发竞态测试

- [ ] **Step 1: 写失败测试 — 递归 drain**

追加到 `tests/unit/test_message_queue.py`:

```python
def test_run_next_pops_and_joins_queue(client, tmp_path):
    """queue 有 2 条,_run_next 拿锁后拼接 \\n 跑 turn。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    sess.queue.append("先改A")
    sess.queue.append("再改B")
    # 直接调 _run_next(拿锁 + 拼接 + 跑)
    from taisang.web.app import _run_next
    _run_next(sess, sid)
    # 等 run 跑完
    deadline = time.time() + 5
    while sess.lock.locked() and time.time() < deadline:
        time.sleep(0.01)
    # queue 已清空
    assert sess.queue == []


def test_run_next_lock_busy_return(client, tmp_path):
    """lock 已锁,_run_next 不阻塞直接 return。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    sess.queue.append("消息")
    sess.lock.acquire(blocking=False)
    try:
        from taisang.web.app import _run_next
        _run_next(sess, sid)
        # queue 没被消费(没拿到锁)
        assert sess.queue == ["消息"]
    finally:
        sess.lock.release()


def test_send_message_appends_to_queue_when_busy(client, tmp_path):
    """lock 已锁,POST 返回 {ok, queued: true},queue 增长。"""
    sid = client.post("/api/sessions", json={"title": ""}).json()["id"]
    sess = client.app.state.registry.get_or_load(sid)
    sess.lock.acquire(blocking=False)
    try:
        r = client.post(f"/api/sessions/{sid}/messages", json={"query": "q1"})
        assert r.status_code == 200
        assert r.json()["queued"] is True
        assert "q1" in sess.queue
        r2 = client.post(f"/api/sessions/{sid}/messages", json={"query": "q2"})
        assert r2.json()["queued"] is True
        assert sess.queue == ["q1", "q2"]
    finally:
        sess.lock.release()
```

- [ ] **Step 2: 跑测试确认通过**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit/test_message_queue.py -v 2>&1 | tail -20
```
Expected: 全部 PASS (已有测试 + 新测试)

- [ ] **Step 3: 提交**

```bash
cd D:/Project/TaiSang && git add tests/unit/test_message_queue.py
git commit -m "test(web): add message queue unit tests for _run_next/send_message"
```

---

## Task 7: 前端 api/chat.ts 加 getQueue

**Files:**
- Modify: `src/taisang/web/frontend/src/api/chat.ts`

**Interfaces:**
- Consumes: nothing new
- Produces: `getQueue(id)` 函数 — 前端调此函数恢复队列状态

- [ ] **Step 1: 加 getQueue 函数**

在 `src/taisang/web/frontend/src/api/chat.ts` 末尾追加:

```typescript
export function getQueue(id: string): Promise<{ queue: string[]; len: number }> {
  return apiGet<{ queue: string[]; len: number }>(`/api/sessions/${id}/queue`)
}
```

- [ ] **Step 2: 跑类型检查**

```bash
cd D:/Project/TaiSang/src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | head -20
```
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/frontend/src/api/chat.ts
git commit -m "feat(frontend): add getQueue API function"
```

---

## Task 8: 前端 useChatStream.ts 改造

**Files:**
- Modify: `src/taisang/web/frontend/src/composables/useChatStream.ts`

**Interfaces:**
- Consumes: `getQueue` (Task 7)
- Produces: 改造后的 `send` / `stop` / `loadHistory` + `pendingQueue` + SSE `queue_updated`

- [ ] **Step 1: 改造 useChatStream.ts**

做以下改动:

**1) import 加 getQueue:**

```typescript
import { getHistory, sendMessage, respondConfirm, respondPermission, interruptSession, getQueue } from '@/api/chat'
```

**2) 在 `stop()` 函数之前加 `pendingQueue` ref:**

```typescript
  const pendingQueue = ref<string[]>([])  // 镜像后端队列(用于本地气泡管理)
```

**3) 改造 `send()` 函数:**

```typescript
  async function send(query: string) {
    if (!sessionId.value) return
    pushUser(query)  // 立即 push user 气泡(无 thinking 守卫)
    pendingQueue.value.push(query)  // 本地镜像
    try {
      await sendMessage(sessionId.value, query)
    } catch (e) {
      // 发送失败: 从 pendingQueue 移除刚 push 的 query
      pendingQueue.value = pendingQueue.value.filter(q => q !== query)
      // 同时从 messages 删除刚 push 的 user 气泡
      messages.value = messages.value.filter(
        m => !(m.kind === 'user' && m.text === query)
      )
      pushRunError(`发送失败: ${(e as Error).message}`)
    }
  }
```

**4) 改造 `stop()` 函数:**

```typescript
  function stop() {
    if (!sessionId.value) return
    if (!thinking.value && !stopping.value && pendingQueue.value.length === 0) return
    // 本地立即删排队气泡
    const toRemove = new Set(pendingQueue.value)
    messages.value = messages.value.filter(
      m => !(m.kind === 'user' && toRemove.has(m.text))
    )
    pendingQueue.value = []
    thinking.value = false
    stopping.value = true
    interruptSession(sessionId.value).catch((e) => console.error('interrupt failed:', e))
  }
```

**5) 在 `openEventStream` 里加 `queue_updated` 监听(在 `session_title_updated` 监听之后):**

```typescript
    eventSource.addEventListener('queue_updated', (e: MessageEvent) => {
      const data = safeParse<{ queue: string[]; len: number }>(e.data)
      if (!data) return
      // 后端队列变化: 同步本地镜像
      // 注意: queue_updated([]) 有两种来源
      //   - interrupt 清空(stop() 已本地删气泡, 这里不动)
      //   - flush 处理(气泡保留作为已发送, 这里也不动)
      // 所以这里只同步 pendingQueue 镜像, 不操作 messages
      pendingQueue.value = data.queue || []
    })
```

**6) 改造 `loadHistory()` 函数:**

```typescript
  async function loadHistory(id: string) {
    try {
      const records = await getHistory(id)
      renderHistory(records)
      // 重建队列状态
      const q = await getQueue(id)
      pendingQueue.value = q.queue || []
    } catch (e) {
      pushRunError(`加载历史失败: ${(e as Error).message}`)
    }
  }
```

**7) 在 return 里加 `pendingQueue`:**

```typescript
  return {
    messages,
    thinking,
    stopping,
    retryInfo,
    reasoningText,
    streamingMessage,
    connectionState,
    todos,
    debugEnabled,
    pendingQueue,
    send,
    stop,
    loadHistory,
    openEventStream,
    closeEventStream,
    answerConfirm,
    setDebugEnabled,
  }
```

- [ ] **Step 2: 跑类型检查**

```bash
cd D:/Project/TaiSang/src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | head -20
```
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/frontend/src/composables/useChatStream.ts
git commit -m "feat(frontend): useChatStream 加 pendingQueue + 改 send/stop/loadHistory + queue_updated 监听"
```

---

## Task 9: 前端 MessageInput.vue placeholder 改造

**Files:**
- Modify: `src/taisang/web/frontend/src/components/MessageInput.vue`

**Interfaces:**
- Consumes: `streaming` prop
- Produces: 思考时 placeholder 改友好提示

- [ ] **Step 1: 改 placeholder**

把 `src/taisang/web/frontend/src/components/MessageInput.vue` 的 textarea:

```html
        :placeholder="placeholder"
```

改成:

```html
        :placeholder="streaming ? '思考中,可继续输入消息排队等待...' : placeholder"
```

- [ ] **Step 2: 跑类型检查**

```bash
cd D:/Project/TaiSang/src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | head -20
```
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/frontend/src/components/MessageInput.vue
git commit -m "feat(frontend): MessageInput 思考时 placeholder 改排队提示"
```

---

## Task 10: 全量回归测试 + 前端 build

**Files:**
- 无文件改动,纯验证

- [ ] **Step 1: 跑全部后端单测**

```bash
cd D:/Project/TaiSang && python -m pytest tests/unit -v 2>&1 | tail -30
```
Expected: 全部 PASS

- [ ] **Step 2: 跑全部后端集成测试**

```bash
cd D:/Project/TaiSang && python -m pytest tests/integration -v 2>&1 | tail -20
```
Expected: 全部 PASS

- [ ] **Step 3: 跑前端 build**

```bash
cd D:/Project/TaiSang/src/taisang/web/frontend && npm run build 2>&1 | tail -20
```
Expected: build 成功

- [ ] **Step 4: 同步前端 build 产物到 static**

```bash
cd D:/Project/TaiSang && ls src/taisang/web/static/assets/ | head -5
```
Expected: 有 index-*.js / index-*.css 等文件

- [ ] **Step 5: 提交 build 产物(如有变化)**

```bash
cd D:/Project/TaiSang && git add src/taisang/web/static/
git commit -m "chore: 同步前端 build 产物"
```

---

## Self-Review Checklist

- [x] **Spec 覆盖**: queue 字段 → Task 1; _run_next → Task 2; send_message 改造 → Task 3; interrupt 改造 → Task 4; GET /queue → Task 5; 递归 drain → Task 6; 前端 API → Task 7; useChatStream → Task 8; MessageInput → Task 9; 回归测试 → Task 10
- [x] **占位符扫描**: 无 TBD/TODO
- [x] **类型一致性**: `pendingQueue` / `getQueue` / `queue_updated` 跨 task 命名一致
