# SSE 断连重连 + 错误处理健壮性(Plan 7)

**日期**: 2026-09-03
**状态**: 已实施(2026-09-03)
**作者**: 泰哥 + Claude

## 背景

当前 `useChatStream.ts` 的 SSE 实现:
- `EventSource` 没接 `onerror` 处理 — 网络断开/服务器重启时,浏览器默认重连但用户看不到提示
- `JSON.parse(e.data)` 没 try/catch — 畸形数据会让事件监听器崩
- `send()` 没 try/catch — POST `/api/sessions/:id/messages` 网络错误会静默失败,用户看到消息发出去但没回复
- `loadHistory()` 失败只 `console.error` — 用户看不到错误

## 目标

Plan 7 结束时:
- SSE 连接断开时,UI 显示"连接断开,正在重连..."提示,重连成功后自动消失
- SSE 事件 `JSON.parse` 失败时,记录 console.error 但不崩,跳过该事件
- `send()` 失败时,消息列表显示 `run_error` 消息卡片("发送失败: ...")
- `loadHistory()` 失败时,显示 `run_error` 消息卡片
- SSE 重连次数超过 5 次时,停止重连,显示"连接失败,请刷新页面"
- 用户切走会话/关闭 ConfigModal 时,SSE 正常 close,不泄漏

## 非目标

- 后端 SSE 重连机制 — 后端已有 run_end 事件,前端检测 EventSource onerror 即可
- 真实网络抖动测试 — 单测覆盖逻辑分支,e2e 用 Playwright 模拟断开
- 离线消息队列 — 超出 v1 范围

## 关键设计

### 1. SSE 状态 ref

```typescript
const connectionState = ref<'connected' | 'reconnecting' | 'failed'>('connected')
const reconnectCount = ref(0)
```

### 2. EventSource onerror 处理

EventSource 自带重连,但 `readyState` 会变成 CLOSED(2) 表示彻底断了。监听 `onerror`:
- `readyState === EventSource.CLOSED` → 连接彻底断,显示"连接失败,请刷新"
- `readyState === EventSource.CONNECTING` → 浏览器在重连,显示"正在重连..."
- 重连计数器:每次 onerror +1,超过 5 次 close + 显示失败

### 3. 事件 JSON.parse 容错

```typescript
function safeParse<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T
  } catch (e) {
    console.error('SSE event parse failed:', e, data)
    return null
  }
}
```

每个事件监听器用 `safeParse`,返回 null 则跳过。

### 4. send/loadHistory 错误显示

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

### 5. 连接状态 UI

在 `ChatView.vue` 顶栏下方加一条状态条:
- `connected`: 不显示
- `reconnecting`: 黄色背景"连接断开,正在重连..."
- `failed`: 红色背景"连接失败,请刷新页面"

## 文件清单

- Modify: `src/taisang/web/frontend/src/composables/useChatStream.ts` — 加 connectionState + onerror + safeParse + send/loadHistory 错误处理
- Modify: `src/taisang/web/frontend/src/views/ChatView.vue` — 加连接状态条
- Test: `tests/unit/test_use_chat_stream.py` — 不适用(Vue composable 单测在 frontend,但项目没建 Vue 测试框架,跳过单测,靠 e2e 验证)

## 验证标准

1. type-check + build 通过
2. Playwright e2e(Plan 9):
   - 模拟 SSE 断开(后端停服务)→ 前端显示"正在重连..."
   - 重启后端 → 前端自动重连成功
   - 发消息时后端停 → 显示"发送失败"run_error 卡片
3. Python 188 测试无回归