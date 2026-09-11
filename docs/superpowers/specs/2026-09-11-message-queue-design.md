# 消息队列方案设计 — 思考期间连续发送 + 中断清队列

> **状态**：设计已对齐，待写实现计划（下次 session 接续）
> **日期**：2026-09-11
> **背景**：当前思考期间前端发消息会触发后端 409 `session busy`，UI 出现 user 气泡 + error 条，看起来像「对话崩溃」。本方案解决这个体验问题。

## 目标

1. 思考期间前端**不禁用**输入，用户能连续发多条消息
2. 后端把思考期间发的消息**排队**，turn 结束后自动拼接跑下一轮
3. 点停止时**先清空队列再中断**，前端立即删除排队中的气泡
4. 前端刷新页面不丢队列状态（后端内存队列 + SSE 同步）

## 核心决策（已对齐）

| 决策点 | 选择 |
|--------|------|
| 拼接分隔符 | 单换行 `\n` |
| 多条消息 UI 显示 | 正常显示多个 user 气泡（不合并），后端拼接为一条 prompt |
| 中断实现 | 后端 interrupt 原子清队列 + 中断（一个 API） |
| 队列状态同步 | SSE 推 `queue_updated` 事件（条数 + 内容） |
| 中断后气泡处理 | 前端本地立即删（不等 SSE） |
| flush 时机 | run_end 立即 flush（不延迟） |
| flush 后气泡处理 | 保留排队气泡作为「已发送」（无闪烁） |
| 队列持久化 | 后端内存（不落盘），刷新页面通过 GET /queue 恢复 |
| 并发竞态处理 | 方案 C：无条件 append + `_run_next` 用 `acquire(blocking=False)` |
| 排队条数显示 | 不显示（用户通过气泡位置自己感知） |
| 撤回单条消息 | 不做（只有「点停止全清」一个入口） |

## 实现方案：方案 C（后端队列 + 统一 append 路径）

### 方案对比（为什么选 C）

- **方案 A（前端队列）**：后端零改动，但前端刷新丢队列、多标签不同步、前端要管状态机
- **方案 B（后端队列 + 标志位）**：单一来源，但要 `flushing` 标志位补 `lock.locked()` 判断的漏洞
- **方案 C（后端队列 + 统一 append）**：`send_message` 无条件 append + `_run_next` 用 `acquire(blocking=False)`，**无竞态、不需要标志位、逻辑统一**（第一次发和 flush 走同一条路径）

## 架构总览

**核心组件**：
- `_Session.queue: list[str]` — 后端内存队列，存待发 query
- `_run_next(sess, session_id)` — 统一入口：尝试拿锁 → 拼接 queue → 跑下一个 turn；没拿到锁就 return
- `send_message` — 无条件 `queue.append(query)` → `_run_next(sess)`
- `interrupt` — `queue.clear()` + `agent.interrupt()`
- SSE `queue_updated` 事件 — 队列变化时推给前端（条数 + 内容）
- 前端 `pendingQueue: ref<string[]>` — 镜像后端队列，用于本地 UI 气泡管理

**正常场景数据流**（用户思考时发 2 条）：
```
[turn 1 跑中]
  POST "先改 A" → queue=["先改 A"] → _run_next 没拿到锁 → return
  SSE queue_updated {queue: ["先改 A"], len: 1}
  POST "再改 B" → queue=["先改 A","再改 B"] → _run_next 没拿到锁 → return
  SSE queue_updated {queue: ["先改 A","再改 B"], len: 2}
[turn 1 结束 run_end]
  _run 末尾调 _run_next → 拿到锁 → 拼接 "先改 A\n再改 B" → 跑 turn 2
  SSE queue_updated {queue: [], len: 0}  ← flush 时后端推
[turn 2 跑中]
  前端收到 run_end (turn 1) → 保留排队气泡（已发送）
  前端收到 llm_thinking (turn 2) → thinking 动画
[turn 2 结束 run_end]
  _run 末尾调 _run_next → queue 空 → return
```

**中断场景数据流**（用户思考时发 2 条后点停止）：
```
[turn 1 跑中, queue=["先改 A","再改 B"]]
  POST /interrupt → queue.clear() + agent.interrupt()
  SSE queue_updated {queue: [], len: 0}  ← 后端清队列后推
  前端收到 queue_updated([]) → pendingQueue 同步为空（气泡已在 stop() 本地删过）
  前端收到 FINAL_ANSWER(interrupted=true) → 显示 (已中断)
```

## 后端组件设计

### `_Session` 数据结构（`src/taisang/web/session_registry.py`）
新增 1 个字段：
```python
queue: list[str] = field(default_factory=list)  # 待发消息队列(思考期间发的)
```
不加 `flushing` 标志位（方案 C 用 `acquire(blocking=False)` 替代）。

### `_run_next(sess, session_id)`（`src/taisang/web/app.py` 新增辅助函数）
```python
def _run_next(sess, session_id) -> None:
    """尝试跑下一个 turn:拿锁 + 拼接 queue + 跑。
    拿不到锁(return False)→ 已有 turn 在跑,run_end 会自动调本函数。
    """
    if not sess.queue:  # 空队列没东西跑
        return
    if not sess.lock.acquire(blocking=False):  # 已锁(run 在跑或 flush 在跑)
        return
    # 拿到锁:拼接 queue 为一条 prompt
    queries = list(sess.queue)
    sess.queue.clear()
    sess.broker.publish("queue_updated", {"queue": [], "len": 0})
    prompt = "\n".join(queries)
    # 后台线程跑(同现有 _run 结构)
    def _run():
        try:
            sess.agent.run(prompt, on_event=lambda e: sess.broker.publish(
                e.type, {**e.payload, "agent_id": e.agent_id}
            ))
        except Exception as e:
            log.exception("agent run failed: %s", e)
            sess.broker.publish("run_error", {"error": f"agent run failed: {e}"})
        finally:
            try:
                registry.update_meta_after_turn(session_id, prompt)
            except Exception as e:
                log.warning("update_meta_after_turn failed: %s", e)
            sess.broker.publish("session_title_updated",
                                {"id": session_id, "title": sess.title})
            sess.broker.publish("run_end", {})
            sess.lock.release()
            _run_next(sess, session_id)  # 递归 drain
    asyncio.get_running_loop().run_in_executor(None, _run)
```

**关键点**：
- `acquire(blocking=False)` 保证只在一个 turn 跑（并发 POST 不会触发多个 turn）
- 拿到锁后立即 `queue.clear()` + 推 `queue_updated([])`，前端知道这些消息已被处理
- `_run` 末尾 `release` 后递归调 `_run_next`，自动 drain 完所有排队消息
- 第一个消息也走这条路径（append → `_run_next` → 拿锁 → pop 跑），逻辑统一

### `send_message`（`src/taisang/web/app.py:191` 改造）
```python
@app.post("/api/sessions/{session_id}/messages")
async def send_message(session_id: str, req: SendMessageReq) -> dict:
    sess = registry.get_or_load(session_id)
    if sess is None:
        raise HTTPException(404, f"session not found: {session_id}")
    sess.queue.append(req.query)
    sess.broker.publish("queue_updated", {
        "queue": list(sess.queue), "len": len(sess.queue)
    })
    _run_next(sess, session_id)  # 尝试跑(没拿到锁会 return)
    return {"ok": True, "queued": len(sess.queue) > 0}
```
**变化**：去掉 409 拒绝，改为无条件 append + 尝试跑。

### `interrupt`（`src/taisang/web/app.py:435` 改造）
```python
@app.post("/api/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str) -> dict:
    sess = registry.get_or_load(session_id)
    if sess is None:
        raise HTTPException(404, f"session not found: {session_id}")
    sess.queue.clear()  # 先清队列
    sess.broker.publish("queue_updated", {"queue": [], "len": 0})
    if not sess.lock.locked():
        return {"ok": True, "interrupted": False}
    sess.agent.interrupt()
    return {"ok": True, "interrupted": True}
```
**变化**：先 `queue.clear()` + 推 `queue_updated([])`，再调 `agent.interrupt()`。即使 lock 未锁（turn 已结束）也清队列（用户可能发了排队消息但 turn 刚好结束还没 flush）。

### 新增 `GET /api/sessions/{id}/queue`（`src/taisang/web/app.py`）
```python
@app.get("/api/sessions/{session_id}/queue")
async def get_queue(session_id: str) -> dict:
    sess = registry.get_or_load(session_id)
    if sess is None:
        raise HTTPException(404, f"session not found: {session_id}")
    return {"queue": list(sess.queue), "len": len(sess.queue)}
```
**用途**：前端刷新页面 SSE 重连后，主动调此 API 拿当前队列状态重建 pendingQueue + 排队气泡。

## 前端组件设计

### `useChatStream.ts` 改造（`src/taisang/web/frontend/src/composables/useChatStream.ts`）

**新增状态**：
```ts
const pendingQueue = ref<string[]>([])  // 镜像后端队列(用于本地气泡管理)
```

**`send()` 改造**：
```ts
async function send(query: string) {
  if (!sessionId.value) return
  pushUser(query)  // 立即 push user 气泡(无 thinking 守卫)
  pendingQueue.value.push(query)  // 本地镜像
  try {
    await sendMessage(sessionId.value, query)
    // 后端返回 {ok, queued}:queued=true 表示进了队列(turn 在跑)
    // queued=false 表示直接跑了(turn 没在跑,但气泡仍保留)
  } catch (e) {
    // 发送失败:从 pendingQueue 移除刚 push 的 query
    pendingQueue.value = pendingQueue.value.filter(q => q !== query)
    // 同时从 messages 删除刚 push 的 user 气泡
    messages.value = messages.value.filter(
      m => !(m.kind === 'user' && m.text === query)
    )
    pushRunError(`发送失败: ${(e as Error).message}`)
  }
}
```
**变化**：去掉 thinking 守卫（思考时也允许发）；POST 失败时回滚 user 气泡 + pendingQueue。

**`stop()` 改造**：
```ts
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
  interruptSession(sessionId.value).catch(e => console.error('interrupt failed:', e))
}
```
**变化**：本地立即删 pendingQueue 里的气泡，再调 interrupt（后端会清队列 + 中断）。

**新增 SSE `queue_updated` 监听**：
```ts
eventSource.addEventListener('queue_updated', (e: MessageEvent) => {
  const data = JSON.parse(e.data)
  // 后端队列变化:同步本地镜像
  // 注意:queue_updated([]) 有两种来源
  //   - interrupt 清空(stop() 已本地删气泡,这里不动)
  //   - flush 处理(气泡保留作为已发送,这里也不动)
  // 所以这里只同步 pendingQueue 镜像,不操作 messages
  pendingQueue.value = data.queue || []
})
```
**关键**：`queue_updated([])` 有两种来源（interrupt 清空 / flush 处理），前端只同步 `pendingQueue` 镜像，不操作 `messages`（气泡已在 `stop()` 本地删或保留为已发送）。

**刷新页面重建队列**：
```ts
async function loadHistory(id: string) {
  try {
    const records = await getHistory(id)
    renderHistory(records)
    // 新增:重建队列状态
    const q = await getQueue(id)
    pendingQueue.value = q.queue || []
    // 注意:renderHistory 已经把历史 user 气泡渲染了,
    // pendingQueue 里的消息可能在历史里已经存在(如果 flush 跑过了)
    // 但 pendingQueue 只用于本地镜像,不影响 messages 渲染
  } catch (e) {
    pushRunError(`加载历史失败: ${(e as Error).message}`)
  }
}
```

### `MessageInput.vue` 改造（`src/taisang/web/frontend/src/components/MessageInput.vue`）
只调一个细节：思考时 placeholder 改成更友好的提示。
```vue
<textarea
  :placeholder="streaming ? '思考中,可继续输入消息排队等待...' : placeholder"
  ...  <!-- 不禁用,不加 disabled -->
/>
```
发送按钮逻辑不变（思考时变红色停止按钮，现状）。

### `ThinkingIndicator.vue` — **不改**
不加排队条数显示，用户通过气泡位置自己感知。

### `api/chat.ts` 新增
```ts
export function getQueue(id: string): Promise<{ queue: string[]; len: number }> {
  return apiGet<{ queue: string[]; len: number }>(`/api/sessions/${id}/queue`)
}
```

## 错误处理 & 边缘情况

### 1. POST 失败（网络/后端挂了）
- `send()` catch 里：从 `pendingQueue` + `messages` 移除刚 push 的 query + 气泡
- `pushRunError` 提示用户「发送失败」
- 不影响其他排队消息

### 2. 中断时 queue 刚好被 flush
**时序**：用户点停止 → 前端本地删气泡 + 调 interrupt → 后端 `queue.clear()` + `agent.interrupt()`。但如果此刻后端正好在 flush（`_run_next` 拿到锁正在拼接 queue），`queue.clear()` 可能和 `_run_next` 的 `list(sess.queue)` 竞争。

**处理**：`_run_next` 拿到锁后立即 `list(sess.queue)` + `clear()`（已经是这个顺序），`interrupt` 的 `queue.clear()` 在锁外执行但 `list` 已经 copy 走了——所以最坏情况是 `interrupt` 的 clear 清空了已 copy 的引用，但 `_run_next` 已经拿着 `queries` 副本，不受影响。`_run_next` 跑新 turn，`agent.interrupt()` 让当前 turn 中断。

**结论**：无需额外加锁保护，`list()` + `clear()` 顺序天然安全。

### 3. flush 跑下一轮时 LLM 失败
- `_run` 的 try/except 已捕获，emit `run_error`
- `finally` 里 `release` + `_run_next` 递归——如果 queue 还有消息会继续跑下一条
- **问题**：如果 LLM 持续失败（比如 key 过期），会无限 drain queue 失败
- **处理**：`_run_next` 不加重试限制（`run_error` 已经给前端信号，用户可以手动停止）；但避免无限循环——`_run` 失败时也 release + `_run_next`，但如果 queue 在失败期间被用户清空（点停止），`_run_next` 看到 queue 空 return，自然停止

### 4. 前端刷新页面重连
- 后端 `sess.queue` 在内存，刷新不丢
- 前端 SSE 重连后，后端不会主动推 `queue_updated`（只在变化时推）
- **处理**：前端 `loadHistory` 成功后，主动调 `GET /api/sessions/{id}/queue` 拿当前队列状态，重建 `pendingQueue`
- **注意**：刷新后历史 records 已经把 user 气泡渲染了，`pendingQueue` 只用于本地镜像后续操作，不影响 `messages` 渲染

### 5. 用户没发排队消息就点停止
- `stop()` 里 `pendingQueue.length === 0`，本地不删气泡
- 调 interrupt，后端 `queue.clear()`（空，no-op）+ `agent.interrupt()`
- 正常中断当前 turn

### 6. 思考时连续发 10 条
- queue 长到 10 条，`queue_updated` 推 10 次（每次 append 都推）
- 前端 10 个 user 气泡正常显示
- turn 结束后拼接成 `q1\nq2\n...\nq10` 跑一轮

### 7. turn 结束时 queue 为空
- `_run` 末尾 `_run_next` → queue 空 → return
- 不触发新 turn，正常结束

## 测试策略

### 后端单元测试（`tests/unit/test_message_queue.py` 新增）

**`_run_next` 核心逻辑**：
1. `test_run_next_empty_queue_noop` — queue 空，`_run_next` 不拿锁直接 return
2. `test_run_next_lock_busy_return` — lock 已锁，`_run_next` 不阻塞直接 return
3. `test_run_next_pops_and_joins_queue` — queue 有 2 条，`_run_next` 拿锁后拼接 `\n` 跑 turn
4. `test_run_next_clears_queue_after_pop` — 拿锁后 queue 立即清空 + 推 `queue_updated([])`

**`send_message` 改造**：
5. `test_send_message_appends_to_queue_when_busy` — lock 已锁，POST 返回 `{ok, queued: true}`，queue 增长
6. `test_send_message_triggers_run_when_idle` — lock 未锁，POST append → `_run_next` 拿锁跑 turn
7. `test_send_message_no_409` — 思考时 POST 不再返回 409（回归测试，关键）

**`interrupt` 改造**：
8. `test_interrupt_clears_queue_then_interrupts` — queue 有 2 条 + lock 已锁，POST interrupt 后 queue 空 + `agent.interrupt()` 被调
9. `test_interrupt_clears_queue_even_when_idle` — queue 有 2 条 + lock 未锁（turn 刚结束），POST interrupt 后 queue 空，`agent.interrupt()` 不调（无副作用）
10. `test_interrupt_emits_queue_updated_empty` — 清队列后推 `queue_updated({queue: [], len: 0})`

**递归 drain**：
11. `test_run_recurses_to_drain_queue` — turn 1 跑中用户发 2 条 → turn 1 结束 → `_run_next` 自动跑 turn 2（拼接 2 条）

**并发竞态**：
12. `test_concurrent_post_no_double_turn` — 2 个并发 POST（lock 未锁），只有一个触发 turn，另一个进队列

**新增 GET /queue**：
13. `test_get_queue_returns_current_state` — queue 有 2 条，GET 返回 `{queue: [...], len: 2}`
14. `test_get_queue_empty` — queue 空，GET 返回 `{queue: [], len: 0}`
15. `test_get_queue_session_not_found` — 不存在的 session_id → 404

### 前端验证（Playwright 文本模式，不截图）
16. 思考时发 2 条消息 → UI 显示 2 个 user 气泡（在 thinking 动画后面）
17. 思考时发 2 条 + 点停止 → 2 个气泡消失 + 显示 `(已中断)`
18. 思考时发 2 条 + 等 turn 结束 → 2 个气泡保留 + 接 assistant 回复（无闪烁）
19. 刷新页面 → 排队气泡重建（GET /queue 返回队列状态）

### 回归测试
- 现有 `test_skills_*` / `test_app_*` 全跑，确保 send_message / interrupt 改动不破坏现有行为
- 重点跑 `test_app.py` 里涉及 send_message 409 的测试（如果有，需要改成测 queued 行为）

## 改动文件清单

### 后端
- `src/taisang/web/session_registry.py` — `_Session` 加 `queue: list[str]` 字段
- `src/taisang/web/app.py` — 新增 `_run_next` 辅助函数 + 改造 `send_message` / `interrupt` + 新增 `GET /queue`

### 前端
- `src/taisang/web/frontend/src/composables/useChatStream.ts` — 加 `pendingQueue` + 改 `send` / `stop` / `loadHistory` + 加 `queue_updated` 监听
- `src/taisang/web/frontend/src/components/MessageInput.vue` — 思考时 placeholder 改提示
- `src/taisang/web/frontend/src/api/chat.ts` — 加 `getQueue` 函数

### 测试
- `tests/unit/test_message_queue.py` — 新增 15 个单元测试
- `tests/unit/test_app.py` — 改造现有 send_message 409 测试（如果有）为 queued 行为测试

## 下次 session 接续指引

1. **读这个 spec**：`docs/superpowers/specs/2026-09-11-message-queue-design.md`
2. **调用 writing-plans skill** 写实现计划：`docs/superpowers/plans/2026-09-11-message-queue.md`
3. **调用 subagent-driven-development skill** 执行计划（9 个 task 类似 plugin-install 那次）
4. **验收**：单元测试 + Playwright 文本模式端到端验证
5. **提交 + push**：commit message 格式参考 plugin-install 那次

## 风险 & 注意事项

- **现有 409 测试**：如果 `test_app.py` 里有测 send_message 返回 409 的用例，需要同步改成测 queued 行为
- **SSE 事件名冲突**：`queue_updated` 是新事件，确认前端 `useChatStream.ts` 的事件监听列表里没冲突
- **`_run_next` 递归深度**：理论上 queue 很深时递归调用栈会深，但每次递归都是新 turn（异步线程），不是同步递归，不会栈溢出
- **interrupt 时序**：`queue.clear()` 在锁外执行，`_run_next` 的 `list()` + `clear()` 在锁内，两者顺序天然安全（见边缘情况 2）
- **前端 pendingQueue 镜像一致性**：`queue_updated` 事件 + `GET /queue` + `send/stop` 本地操作三个来源都更新 `pendingQueue`，注意不要冲突（特别是刷新页面后收到旧 SSE 事件的情况）