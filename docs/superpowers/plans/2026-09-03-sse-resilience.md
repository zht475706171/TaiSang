# SSE 断连重连 + 错误处理实施计划(Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** SSE 断连重连 + 事件 JSON.parse 容错 + send/loadHistory 错误显示,提升健壮性。

**Architecture:** `useChatStream` 加 `connectionState` ref + `onerror` 处理 + `safeParse` 工具函数 + send/loadHistory try/catch;`ChatView` 加连接状态条。

**Spec:** `docs/superpowers/specs/2026-09-03-sse-resilience-design.md`

---

### Task 1: useChatStream 加 connectionState + onerror + safeParse

**Files:**
- Modify: `src/taisang/web/frontend/src/composables/useChatStream.ts`

- [ ] **Step 1: 加 connectionState ref + safeParse 工具**

在 `useChatStream` 顶部(refs 区)加:
```typescript
const connectionState = ref<'connected' | 'reconnecting' | 'failed'>('connected')
let reconnectCount = 0
const MAX_RECONNECT = 5

function safeParse<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T
  } catch (e) {
    console.error('SSE event parse failed:', e, data)
    return null
  }
}
```

- [ ] **Step 2: openEventStream 加 onerror + 重置连接状态**

`openEventStream` 末尾加:
```typescript
eventSource.onopen = () => {
  connectionState.value = 'connected'
  reconnectCount = 0
}
eventSource.onerror = () => {
  if (!eventSource) return
  if (eventSource.readyState === EventSource.CLOSED) {
    connectionState.value = 'failed'
    eventSource.close()
    eventSource = null
  } else {
    // CONNECTING,浏览器在重连
    reconnectCount += 1
    if (reconnectCount > MAX_RECONNECT) {
      connectionState.value = 'failed'
      eventSource.close()
      eventSource = null
    } else {
      connectionState.value = 'reconnecting'
    }
  }
}
```

- [ ] **Step 3: 所有事件监听器改用 safeParse**

把 7 个 `JSON.parse(e.data)` 改成 `safeParse`,返回 null 跳过。例如:
```typescript
eventSource.addEventListener('tool_call', (e: MessageEvent) => {
  const d = safeParse<{ name: string; args: Record<string, unknown> }>(e.data)
  if (!d) return
  clearThinking()
  pushToolCall(d.name, JSON.stringify(d.args))
})
```

同样改 `tool_result` / `final_answer` / `compacted` / `usage_report` / `confirm_request` / `permission_request` / `run_error`。

- [ ] **Step 4: send 加 try/catch**

```typescript
async function send(query: string) {
  if (!sessionId.value) return
  pushUser(query)
  try {
    await sendMessage(sessionId.value, query)
  } catch (e) {
    pushRunError(`发送失败: ${(e as Error).message}`)
  }
}
```

- [ ] **Step 5: loadHistory 加错误显示**

```typescript
async function loadHistory(id: string) {
  try {
    const records = await getHistory(id)
    renderHistory(records)
  } catch (e) {
    pushRunError(`加载历史失败: ${(e as Error).message}`)
  }
}
```

- [ ] **Step 6: return 暴露 connectionState**

```typescript
return {
  messages,
  thinking,
  connectionState,
  send,
  loadHistory,
  openEventStream,
  closeEventStream,
  answerConfirm,
}
```

- [ ] **Step 7: closeEventStream 重置 connectionState**

```typescript
function closeEventStream() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  clearThinking()
  connectionState.value = 'connected'
  reconnectCount = 0
}
```

- [ ] **Step 8: type-check 验证**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: 无错误

---

### Task 2: ChatView 加连接状态条

**Files:**
- Modify: `src/taisang/web/frontend/src/views/ChatView.vue`

- [ ] **Step 1: 从 useChatStream 解构 connectionState**

```typescript
const { messages, thinking, connectionState, send, loadHistory, openEventStream, closeEventStream, answerConfirm } =
  useChatStream(sessionIdRef, () => store.fetchSessions())
```

- [ ] **Step 2: template 加状态条**

在 `<header v-if="currentSession" class="topbar">` 后面、`<div class="chat-body">` 前面加:
```vue
<div
  v-if="currentSession && connectionState !== 'connected'"
  class="connection-bar"
  :class="connectionState"
>
  <span v-if="connectionState === 'reconnecting'">连接断开,正在重连...({{ reconnectDisplay }})</span>
  <span v-else-if="connectionState === 'failed'">连接失败,请刷新页面</span>
</div>
```

- [ ] **Step 3: 加 reconnectDisplay computed**

```typescript
const reconnectDisplay = computed(() => {
  // EventSource 自带重连,这里不暴露计数,简化显示
  return ''
})
```

实际上简化:去掉 reconnectDisplay,状态条只显示文字。template 改成:
```vue
<div
  v-if="currentSession && connectionState !== 'connected'"
  class="connection-bar"
  :class="connectionState"
>
  <span v-if="connectionState === 'reconnecting'">连接断开,正在重连...</span>
  <span v-else-if="connectionState === 'failed'">连接失败,请刷新页面</span>
</div>
```

- [ ] **Step 4: 加 CSS**

`<style scoped>` 区加:
```css
.connection-bar {
  padding: 8px 24px;
  font-size: 13px;
  text-align: center;
  font-family: var(--app-font-mono);
}
.connection-bar.reconnecting {
  background: #fff3e0;
  color: #b25803;
  border-bottom: 1px solid #ffcc80;
}
.connection-bar.failed {
  background: #fde7e7;
  color: #c0392b;
  border-bottom: 1px solid #f5b7b1;
}
```

- [ ] **Step 5: type-check + build 验证**

Run: `cd src/taisang/web/frontend && npm run type-check && npm run build`
Expected: 无错误,build 成功

- [ ] **Step 6: Python 测试回归**

Run: `python -m pytest --tb=short -q`
Expected: 188 passed

- [ ] **Step 7: Commit**

```bash
git add src/taisang/web/frontend/src/composables/useChatStream.ts src/taisang/web/frontend/src/views/ChatView.vue src/taisang/web/static/index.html src/taisang/web/static/assets/
git commit -m "feat(frontend): Plan 7 — SSE 断连重连 + 事件容错 + 错误显示"
```

---

## 自检 checklist

1. **Spec 覆盖**:
   - ✅ SSE 断开提示 → Task 1 Step 2 + Task 2
   - ✅ JSON.parse 容错 → Task 1 Step 3
   - ✅ send 错误显示 → Task 1 Step 4
   - ✅ loadHistory 错误显示 → Task 1 Step 5
   - ✅ 重连超 5 次停止 → Task 1 Step 2
2. **Placeholder 扫描**:无 TBD/TODO
3. **类型一致性**:`connectionState` 类型 `'connected' | 'reconnecting' | 'failed'` 在两处一致