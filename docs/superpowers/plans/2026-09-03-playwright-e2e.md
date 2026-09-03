# Playwright 端到端验收实施计划(Plan 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to verify this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Playwright MCP 工具跑通 Plan 1-4 实现的全部用户流程,把前端 + 后端 + SSE + 会话持久化串起来验证。**不截图**(session 限制),用 `browser_snapshot`(纯文本 accessibility tree)+ DOM 断言替代。

**Architecture:** 后端 FastAPI 端口 8765 启用 MockLLM,前端 Vite 构建产物 serve 在 `/`,Playwright 通过 MCP 工具操作浏览器。

**Spec:** `docs/superpowers/specs/2026-09-03-playwright-e2e-design.md`

---

### Task 1: 5.1 会话管理 e2e

- [ ] **Step 1: 启动后端**(MockLLM 模式)
- [ ] **Step 2: Playwright 打开首页,验证 Sidebar + 空状态首页**
- [ ] **Step 3: 输入消息发送 → 验证 URL 跳转 /chat/:id + 标题自动生成 + 消息显示 + assistant 回复 + usage_report**
- [ ] **Step 4: 验证 Sidebar 列表新增会话**
- [ ] **Step 5: 切换到旧会话 → 验证 URL 变化 + 历史消息加载**
- [ ] **Step 6: hover 当前会话项 → 验证删除按钮出现**
- [ ] **Step 7: 点删除 → TDesign confirm dialog → 接受 → 验证 URL 回 / + sidebar 移除项**

### Task 2: 5.2 SSE 流式对话 e2e

- [ ] **Step 1: 在新建会话中验证 thinking → final_answer → usage_report 事件链**
- [ ] **Step 2: 同一会话发送第二条消息 → 验证多轮对话(两条消息按序渲染)**
- [ ] **Step 3: 验证 session_title_updated 事件触发标题更新**

### Task 3: 5.3 斜杠命令 e2e

- [ ] **Step 1: 输入 /clear → 验证主区域消息清空,会话标题和 sidebar 保留**
- [ ] **Step 2: 输入 /reset → 验证后端清理 + 前端清空**
- [ ] **Step 3: 输入 /debug → 验证 POST /api/sessions/:id/debug 返回 200**
- [ ] **Step 4: 点顶栏 /reset 按钮验证等价触发**
- [ ] **Step 5: 点顶栏 /debug 按钮验证等价触发**

### Task 4: 5.4 视觉验收(跳过)

- [ ] **Step 1: session 限制不能截图,跳过此 task**
- [ ] **Step 2: 5.1-5.3 的 DOM 断言已覆盖页面结构,视觉验收留后续 session 补**

### Task 5: 收尾

- [ ] **Step 1: 更新 spec 状态为"已实施"**
- [ ] **Step 2: 更新 memory/project-context.md 进度表**
- [ ] **Step 3: 写入 memory/2026-09-03.md 会话日志**
- [ ] **Step 4: 提交 spec + plan + memory 更新**

---

## 自检 checklist

1. **Spec 覆盖**:
   - ✅ 5.1 会话管理 → Task 1
   - ✅ 5.2 SSE 流 → Task 2
   - ✅ 5.3 斜杠命令 → Task 3
   - ✅ 5.4 视觉验收 → Task 4(跳过)

2. **风险预案**:
   - 不能截图 → 用 `browser_snapshot`(纯文本 accessibility tree)替代
   - MockLLM 不触发 tool_call → tool_call 渲染留手动验证,记录在 spec 非目标章节

## 实施记录(回填)

Plan 5 已于 2026-09-03 实施完毕:
- Task 1(5.1 会话管理): ✅ 全部通过
- Task 2(5.2 SSE 流): ✅ 全部通过
- Task 3(5.3 斜杠命令): ✅ 全部通过
- Task 4(5.4 视觉验收): ⏸ 跳过(session 限制不能截图)
- Task 5(收尾): 本计划回填 + spec 状态更新 + memory 更新中