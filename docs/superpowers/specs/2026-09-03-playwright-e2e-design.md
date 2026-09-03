# Playwright 端到端验收设计(Plan 5)

**日期**: 2026-09-03
**状态**: 已实施(2026-09-03)
**作者**: 泰哥 + Claude

## 背景

Plan 1-4 把 Vue 前端搭起来:
- Plan 1 脚手架
- Plan 2 Sidebar + 会话 CRUD + 空状态首页
- Plan 3 SSE 流式对话 + 消息列表 + 斜杠命令
- Plan 4 Vue 版 ConfigModal 表单

代码层单测覆盖了组件渲染和后端 API,但端到端"用户真实点按钮 → 看到结果"的链路没验证。Plan 5 用 Playwright 跑一遍真实用户流程,把整个前端 + 后端 + SSE + 会话持久化全部串起来验证。

## 目标

用 Playwright MCP 工具(非截图,纯 DOM 快照 + 点击 + 文本断言)跑通以下用户流程:

1. **会话管理 e2e**
   - 新建对话 → URL 跳转 /chat/:id → 标题自动生成
   - 切换会话 → URL 变化 + 历史消息加载
   - 删除会话 → confirm dialog → 自动回首页
   - Sidebar 列表实时刷新

2. **SSE 流式对话 e2e**
   - 发消息 → thinking → final_answer → usage_report 事件链
   - 多轮对话(同一会话连续发送)
   - session_title_updated 事件触发标题更新

3. **斜杠命令 e2e**
   - /clear(前端清空消息,会话保留)
   - /reset(后端清理 + 前端清空)
   - /debug(后端设置 debug 模式)
   - 顶栏 /reset 和 /debug 按钮等价触发

4. **视觉验收**(跳过 — session 限制不能截图)
   - 用 `browser_snapshot`(纯文本 accessibility tree)替代截图,验证页面结构
   - 或直接基于 5.1-5.3 的 DOM 断言收工

## 非目标

- tool_call / ToolCard / ConfirmCard 渲染验证 — MockLLM 不触发 tool_call,真实 LLM 流程留手动验证
- 跨浏览器兼容性 — 只用 chromium
- 性能测试 — 不测响应时间

## 验证环境

- 后端: FastAPI 端口 8765,`TAISANG_MOCK_LLM=1` 启用 MockLLM(返回 `(mock) ok`)
- 前端: Vite 构建产物 serve 在 `/`,API 走 `/api/*`
- Playwright: 通过 MCP 工具 `browser_navigate` / `browser_click` / `browser_snapshot` / `browser_type` 操作

## 验证清单(已全部通过)

### 5.1 会话管理 e2e ✅
- 新建对话 → URL 跳转 `/chat/04428c25`
- 标题自动更新为"你好,这是测试消息"
- 用户消息显示
- assistant 回复"(mock) ok"
- usage_report 显示
- Sidebar 列表新增会话
- 切换会话 → URL 跳 `/chat/1a53e8ab` + 历史加载
- hover 当前会话项出现删除按钮
- 删除 → TDesign confirm dialog → 接受 → URL 回 `/` + sidebar 移除项

### 5.2 SSE 流式对话 e2e ✅
- 事件链: thinking → final_answer → usage_report
- 多轮对话: 第二条消息发送成功 + 标题更新为"第二条消息" + 两条消息按序渲染 + 每轮都有 usage_report
- session_title_updated 事件触发标题更新

### 5.3 斜杠命令 e2e ✅
- /clear → 主区域消息列表清空,会话标题和 sidebar 项保留
- /reset → 后端清空 + 前端清空
- /debug → POST /api/sessions/:id/debug 返回 200
- 顶栏 /reset 和 /debug 按钮等价触发

### 5.4 视觉验收 ⏸ 跳过
- session 限制不能截图
- 5.1-5.3 的 DOM 断言已覆盖页面结构,视觉验收留后续 session 补

## 发现的体验优化点(非 bug,不阻塞)

- `/chat/:id` 路由下,会话存在但消息为空时,显示空 MessageList 而不是 EmptyState
- 改进方向: `v-if="!messages.length"` 替代 `v-if="!currentSession"`,空会话也显示 EmptyState 欢迎页
- 改动很小,后续顺手改

## 相关文件

- 前端组件: `src/taisang/web/frontend/src/components/` + `views/ChatView.vue`
- 后端路由: `src/taisang/web/app.py`
- 后端 session: `src/taisang/web/session_registry.py`
- MockLLM: `src/taisang/llm_client.py`