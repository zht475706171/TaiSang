# Playwright e2e 增强覆盖实施计划(Plan 9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to verify this plan task-by-task.

**Goal:** e2e 回归 Plan 6-8 + 配置页功能,不截图用 browser_evaluate DOM 断言。

**Architecture:** 后端 FastAPI + MockLLM,Playwright MCP 工具操作浏览器。

**Spec:** `docs/superpowers/specs/2026-09-03-e2e-enhanced-design.md`

---

### Task 1: 9.1 Plan 8 键盘快捷键 e2e

- [ ] **Step 1: 启动后端(MockLLM)**
- [ ] **Step 2: Playwright navigate 首页**
- [ ] **Step 3: Ctrl+K 触发新对话,验证 URL 跳 /chat/:id**
- [ ] **Step 4: Ctrl+, 打开 ConfigModal,验证 .t-dialog__ctx visible**
- [ ] **Step 5: Esc 关闭,验证 .t-dialog__ctx 移除**
- [ ] **Step 6: 检查 ARIA 标签(新对话/设置/textarea/session-item/reset/debug)**

### Task 2: 9.2 Plan 7 SSE 断连重连 e2e

- [ ] **Step 1: 新建对话发消息,验证 SSE 流正常**
- [ ] **Step 2: 停后端,验证 .connection-bar.reconnecting 显示**
- [ ] **Step 3: 重启后端,验证 connection-bar 消失**
- [ ] **Step 4: 停后端,等重连超 5 次,验证 .connection-bar.failed 显示**
- [ ] **Step 5: 停后端状态下发消息,验证 run_error 卡片"发送失败"**

### Task 3: 9.3 Plan 4 配置页 e2e

- [ ] **Step 1: Ctrl+, 打开配置**
- [ ] **Step 2: 验证 model/api_key/base_url 字段正确加载**
- [ ] **Step 3: 改 model,点保存**
- [ ] **Step 4: 验证 settings.json 更新 + api_key 保留**

### Task 4: 9.4 Plan 6 构建产物静态验证

- [ ] **Step 1: 检查 build 输出 chunks 列表**
- [ ] **Step 2: 验证 tdesign/vue-vendor/业务 chunk 分离**

### Task 5: 收尾

- [ ] **Step 1: 关闭 Playwright**
- [ ] **Step 2: 停后端**
- [ ] **Step 3: 更新 memory**
- [ ] **Step 4: 提交 + push**

---

## 自检 checklist

1. **Spec 覆盖**:
   - ✅ 9.1 键盘快捷键 → Task 1
   - ✅ 9.2 SSE 断连 → Task 2
   - ✅ 9.3 配置页 → Task 3
   - ✅ 9.4 构建产物 → Task 4
2. **Placeholder 扫描**:无 TBD
3. **风险预案**:
   - 不能截图 → 用 browser_evaluate DOM 断言
   - native setter 不触发 Vue v-model → 用 Playwright 的 fill/click

## 实施记录(回填)

Plan 9 已于 2026-09-03 实施完毕:
- Task 1(9.1 键盘快捷键): ✅ 全通过
- Task 2(9.2 SSE 断连): ✅ 全通过
- Task 3(9.3 配置页): ✅ 全通过
- Task 4(9.4 构建产物): ✅ 静态验证通过
- Task 5(收尾): 本计划回填 + memory 更新 + 提交 + push