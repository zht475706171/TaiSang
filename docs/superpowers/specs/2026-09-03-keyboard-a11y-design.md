# 键盘快捷键 + 可访问性(Plan 8)

**日期**: 2026-09-03
**状态**: 已实施(2026-09-03)
**作者**: 泰哥 + Claude

## 背景

当前前端所有操作只能鼠标点。键盘用户(包括屏幕阅读器用户)无法高效使用。Plan 8 加全局快捷键 + ARIA 标签 + 焦点管理。

## 目标

- **Cmd/Ctrl+K**: 新对话(替代点"新对话"按钮)
- **Cmd/Ctrl+,**: 打开配置页(替代点"设置"按钮)
- **Esc**: 关闭 ConfigModal(已有 destroy-on-close,但需确认 Esc 触发)
- **输入框自动聚焦**: 新会话/空状态时,焦点自动到 MessageInput
- **ARIA 标签**: 所有交互按钮加 `aria-label`(屏幕阅读器可读)
- **焦点可见**: 按钮焦点轮廓不被 TDesign 默认样式吃掉

## 非目标

- 完整 WCAG 2.1 AA 合规 — 超出 v1 范围
- 跳过链接(skip to main) — 单页应用暂不需要
- 高对比度模式 — 主题系统后续做

## 关键设计

### 1. 全局键盘监听(App.vue)

```typescript
import { onMounted, onUnmounted } from 'vue'

function handleGlobalKeydown(e: KeyboardEvent) {
  // Cmd/Ctrl+K → 新对话
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    handleNewSession()
  }
  // Cmd/Ctrl+, → 打开配置
  if ((e.metaKey || e.ctrlKey) && e.key === ',') {
    e.preventDefault()
    configOpen.value = true
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
  store.fetchSessions()
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
})
```

`handleNewSession` 提到 App.vue 层(或用 event bus),Sidebar 也调它。

### 2. Esc 关闭 ConfigModal

TDesign Dialog 自带 Esc 关闭(destroy-on-close),但 `v-model:visible` 要确认能被 Esc 触发。测一下,不行就手动加 `@keydown.esc`。

### 3. 输入框自动聚焦

EmptyState 的 MessageInput 和 ChatView 的 MessageInput,在会话切换/新建后自动 focus。Vue 用 `onMounted` + ref.focus()。

MessageInput 加 `autofocus` prop(默认 true),或用 ref + watch currentId 触发 focus。

### 4. ARIA 标签

- Sidebar "新对话"按钮: `aria-label="新建对话"`
- Sidebar "设置"按钮: `aria-label="LLM 配置"`
- Sidebar 每个 SessionItem: `aria-label="会话: {title}"`
- TopBar "/reset" / "/debug" 按钮: `aria-label`
- MessageInput textarea: `aria-label="输入消息,Enter 发送"`
- ConfigModal 各字段: label 已通过 t-form-item 关联

## 文件清单

- Modify: `src/taisang/web/frontend/src/App.vue` — 全局键盘监听 + handleNewSession 提取
- Modify: `src/taisang/web/frontend/src/components/Sidebar.vue` — handleNewSession 改成 emit 或调 store + ARIA
- Modify: `src/taisang/web/frontend/src/components/MessageInput.vue` — autofocus + aria-label
- Modify: `src/taisang/web/frontend/src/components/SessionItem.vue` — aria-label
- Modify: `src/taisang/web/frontend/src/views/ChatView.vue` — topbar 按钮 aria-label
- Modify: `src/taisang/web/frontend/src/components/ConfigModal.vue` — 确认 Esc 关闭(可能 TDesign 自带)

## 验证标准

1. type-check + build 通过
2. Playwright e2e(Plan 9):
   - Cmd/Ctrl+K 触发新对话
   - Cmd/Ctrl+, 打开配置页
   - Esc 关闭配置页
   - 新建会话后焦点在输入框
3. Python 188 测试无回归