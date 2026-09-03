# Sidebar + 会话 CRUD + 空状态首页设计(Plan 2)

**日期**: 2026-09-03
**状态**: 设计已完成
**作者**: 泰哥 + Claude

## 背景

Plan 1 搭好 Vue 脚手架(占位页)。Plan 2 实现完整布局骨架:Sidebar + ChatView 空状态 + 输入框。Plan 3 在 ChatView 里填消息列表 + SSE 流。

## 目标

Plan 2 结束时:
- 完整布局:左侧 Sidebar(logo + 新对话 + 会话列表 + 设置按钮)+ 右侧 ChatView(顶栏 + 空状态/消息区 + 输入框)
- 会话 CRUD 全通:新建 / 列表 / 删除 / 切换(点列表项)
- 空状态首页(WeKnora 风):居中大标题"开始对话" + 输入框,无推荐问题卡片
- 输入框发消息 → 创建会话(如果没选中)+ 跳到 ChatView(Plan 3 才真正发消息到后端)
- LLM 配置页入口:Sidebar 底部"设置"按钮(Plan 4 实现配置页内容,Plan 2 只做入口跳转或占位)
- TDesign 组件:Button / Input / Dialog(配置页用,Plan 2 先引入)
- TypeScript 类型就位:Session / Config 类型定义

## 非目标(Plan 2 不做)

- SSE 流式对话 / 消息列表渲染 / 斜杠命令(Plan 3)
- LLM 配置页表单(Plan 4,Plan 2 只留入口)
- Playwright e2e(Plan 5)

## 组件结构

```
App.vue
├── Sidebar.vue                    # 左侧栏(固定宽度 260px,可折叠)
│   ├── brand(◆ TaiSang + coding agent)
│   ├── 新对话按钮(t-button)
│   ├── 会话列表(SessionItem.vue v-for)
│   └── 底部设置按钮
├── RouterView → ChatView.vue      # 右侧主区
│   ├── TopBar(session 标题 + /reset /debug 按钮)
│   ├── 空状态(居中大标题 + 输入框)/ 消息区(Plan 3)
│   └── MessageInput.vue           # 输入框(t-textarea + 发送按钮)
└── ConfigModal.vue(Plan 4,Plan 2 只留占位)
```

## 文件清单

```
src/taisang/web/frontend/src/
├── types/
│   └── index.ts                   # Session / Config 类型
├── api/
│   ├── request.ts                 # fetch 封装
│   ├── session.ts                 # 会话 CRUD API
│   └── config.ts                  # GET/POST /api/config(Plan 4 用,先建)
├── stores/
│   ├── session.ts                 # Pinia:会话列表 + 当前会话 + CRUD actions
│   └── ui.ts                      # Pinia:sidebar 折叠状态(预留,Plan 2 暂不用)
├── components/
│   ├── Sidebar.vue
│   ├── SessionItem.vue
│   └── MessageInput.vue
├── views/
│   └── ChatView.vue               # 替换 HomeView.vue
└── router/index.ts                # 路由:/ → ChatView(空状态),/chat/:id → ChatView
```

## 关键设计

### 类型 types/index.ts

```typescript
export interface Session {
  id: string
  title: string
  active: boolean
  updated_at: number
  relative_time: string
}

export interface LLMConfig {
  model: string
  base_url: string
  api_key: string          // 打码后的值或明文(POST 时)
  api_key_set: boolean
}
```

### API 层

**api/request.ts** — fetch 封装,统一错误处理:
```typescript
export async function apiGet<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`GET ${url} failed: ${r.status}`)
  return r.json() as Promise<T>
}

export async function apiPost(url: string, body: unknown): Promise<unknown> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`POST ${url} failed: ${r.status}`)
  return r.json()
}

export async function apiDelete(url: string): Promise<unknown> {
  const r = await fetch(url, { method: 'DELETE' })
  if (!r.ok) throw new Error(`DELETE ${url} failed: ${r.status}`)
  return r.json()
}
```

**api/session.ts** — 会话 CRUD:
- `listSessions(): Promise<Session[]>` → GET /api/sessions
- `createSession(title?: string): Promise<{id, title}>` → POST /api/sessions
- `deleteSession(id: string): Promise<{deleted: boolean}>` → DELETE /api/sessions/:id
- `resetSession(id: string): Promise<{reset: boolean}>` → POST /api/sessions/:id/reset
- `setDebug(id: string, on: boolean): Promise<{debug: boolean}>` → POST /api/sessions/:id/debug

### Pinia store stores/session.ts

```typescript
state: {
  sessions: Session[]
  currentId: string | null
  loading: boolean
}
actions:
  fetchSessions()       // 调 listSessions,刷新 sessions
  createNew()           // 调 createSession,返回新 sid,router.push
  remove(id)            // 调 deleteSession,从 sessions 移除,若当前则跳空状态
  select(id)            // 设 currentId,router.push
  reset()               // 调 resetSession(currentId)
```

### 路由

```typescript
routes: [
  { path: '/', name: 'home', component: ChatView },           // 空状态
  { path: '/chat/:id', name: 'chat', component: ChatView },   // 指定会话
]
```

ChatView 内部根据 `route.params.id` 判断是空状态还是指定会话。

### 空状态首页(WeKnora 风)

- 居中布局,`max-width: 800px`,`justify-content: center`
- 大标题"开始对话"(28px / 600 字重,brand 色)
- 副标题"输入问题,Enter 发送"(14px,placeholder 色)
- 底部 MessageInput(静态定位,不是 fixed)
- **不放推荐问题卡片**

### MessageInput.vue

- t-textarea(自适应高度,Enter 发送,Shift+Enter 换行)
- 发送按钮(t-button,brand 色)
- 空内容禁用发送
- emit `send(query: string)`

### Sidebar.vue

- 固定宽度 260px
- 顶部:brand(◆ TaiSang + coding agent 小字)
- 新对话按钮(t-button,block)
- 会话列表(滚动,每项 SessionItem)
- 底部:设置按钮(emit 'open-config' 或 router.push 到配置页)

### SessionItem.vue

- title(截断)+ relative_time
- hover 显示删除按钮(×)
- 点击 → emit 'select'
- 删除按钮 → emit 'delete'(带 confirm)

### ChatView.vue 结构

```vue
<template>
  <div class="chat-view">
    <TopBar v-if="currentId" :title="..." @reset @debug />
    <div class="chat-body">
      <EmptyState v-if="!currentId" @send="handleSend" />
      <MessageList v-else :messages="..." />  <!-- Plan 3 -->
    </div>
    <MessageInput v-if="currentId" @send="handleSend" />
  </div>
</template>
```

**Plan 2 的 handleSend**:如果有 currentId,先跳到 Plan 3 的占位(发消息但还没 SSE),只把 query append 到本地消息列表显示。没有 currentId 则先 createSession 再跳。

实际上 Plan 2 为了能独立验证,handleSend 可以先调 `POST /api/sessions/:id/messages`(后端已有),但不接 SSE 流 — 消息列表显示"发送中..."占位。Plan 3 再接 SSE。

**简化:Plan 2 的 handleSend 只创建会话 + 路由跳转,不发消息。** 这样 Plan 2 验证:输入框 → 创建会话 → 跳到 ChatView 空状态(顶栏显示 title)。Plan 3 再接消息发送 + SSE。

## 验证标准(Plan 2 完成)

1. `npm run type-check` 无错误
2. `npm run build` 成功
3. FastAPI serve 后:
   - 访问 / 看到 Sidebar + 空状态首页
   - 点"新对话" → 创建会话 → 跳到 /chat/:id → 顶栏显示 title
   - 会话列表显示新会话
   - 点会话项切换
   - 点删除按钮 → confirm → 删除
   - 点设置按钮 → 路由跳转或占位(Plan 4 填内容)
4. Python 测试回归 188/188