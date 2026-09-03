# Playwright e2e 增强覆盖(Plan 9)

**日期**: 2026-09-03
**状态**: 已实施(2026-09-03)
**作者**: 泰哥 + Claude

## 背景

Plan 5 的 e2e 验证了基础流程(会话管理/SSE/斜杠命令)。Plan 9 针对 Plan 6-8 的新功能(构建优化/SSE 健壮性/键盘快捷键+ARIA)做 e2e 回归 + 新场景覆盖。

## 目标

用 Playwright MCP 工具(不截图,用 `browser_evaluate` + DOM 断言)验证:

1. **Plan 8 键盘快捷键**
   - Cmd/Ctrl+K 新对话
   - Cmd/Ctrl+, 打开配置
   - Esc 关闭配置
   - ARIA 标签正确

2. **Plan 7 SSE 断连重连**
   - 后端停 → 前端显示"正在重连..."
   - 后端启 → 前端自动重连,状态条消失
   - 重连超 5 次 → 显示"连接失败,请刷新页面"
   - send 失败 → 显示 run_error 卡片

3. **Plan 4 配置页功能**
   - Ctrl+, 打开配置,字段正确加载(model/api_key 打码/base_url)
   - 改 model 保存 → settings.json 更新,api_key 保留(`__unchanged__` sentinel)

4. **Plan 6 构建优化**
   - 静态验证:build 产物 chunks 列表(tdesign/vue-vendor/业务 chunk 分离)

## 非目标

- tool_call 渲染 — MockLLM 不触发
- 真实 LLM 闭环 — 留手动验证
- 视觉回归 — session 限制不截图

## 验证环境

- 后端: `TAISANG_MOCK_LLM=1 python -m taisang web --repo <path> --no-browser --port 8765`
- 前端: Vite 构建产物 serve 在 `/`,API 走 `/api/*`
- Playwright: 通过 MCP 工具 `browser_navigate` / `browser_evaluate` / `browser_click` / `browser_fill` / `browser_press_key`

## 验证清单(已全部通过)

### 9.1 Plan 8 键盘快捷键 ✅
- Ctrl+K → URL 跳 `/chat/29d74605`(新对话创建)
- Ctrl+, → `.t-dialog__ctx` style 从 `display: none` 变空(visible)
- Esc → `.t-dialog__ctx` 整个 DOM 移除(destroy-on-close)
- ARIA:
  - 新对话按钮 `aria-label="新建对话(Cmd/Ctrl+K)"`
  - 设置按钮 `aria-label="LLM 配置(Cmd/Ctrl+,)"`
  - textarea `aria-label="输入消息,Enter 发送,Shift+Enter 换行"`
  - session-item `role="button" + aria-label="会话: <id>"`
  - topbar /reset `aria-label="重置会话(/reset)"`
  - topbar /debug `aria-label="切换 debug 模式(/debug)"`

### 9.2 Plan 7 SSE 断连重连 ✅
- 后端停 → `.connection-bar.reconnecting` 显示"连接断开,正在重连..."
- 后端启 → connection-bar 消失(connected)
- 重连超 5 次 → `.connection-bar.failed` 显示"连接失败,请刷新页面"
- send 失败 → chat-body 显示"错误: 发送失败: Failed to fetch"

### 9.3 Plan 4 配置页 ✅
- Ctrl+, 打开,三个字段加载(model=Kimi-K2.6, api_key=sk-***ca89, base_url=aitoken521.com)
- 改 model=test-model-e2e 保存 → settings.json 写入 model,api_key 保留原值(`__unchanged__` 生效)

### 9.4 Plan 6 构建产物 ✅
- 静态验证: build 输出 chunks(tdesign 1.3MB / vue-vendor 107KB / index 9KB / ChatView 12KB)
- 业务 chunk 显著缩小,tdesign 独立缓存

## 相关文件

- `src/taisang/web/frontend/src/composables/useChatStream.ts` — SSE 断连处理
- `src/taisang/web/frontend/src/App.vue` — 全局键盘监听
- `src/taisang/web/frontend/src/components/ConfigModal.vue` — 配置页表单
- `src/taisang/web/frontend/src/views/ChatView.vue` — 连接状态条
- `src/taisang/web/frontend/vite.config.ts` — manualChunks