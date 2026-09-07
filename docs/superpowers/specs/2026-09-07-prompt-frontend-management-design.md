# Prompt 前端管理 设计

> **Date:** 2026-09-07
> **Status:** Approved → 待实施
> **Goal:** 把 TaiSang 的核心 prompt（主 System Prompt / Autocompact 摘要 Prompt / Session Memory 模板 + 更新指令）暴露到前端，用户可查看、编辑、保存，每类带"恢复默认"按钮。修改后全局持久化、立即对所有活跃 session 生效。

---

## 1. 范围

### 包含
- 管理四份 prompt 文本：
  1. **主 System Prompt** —— `agent_core/prompts.py::SYSTEM_PROMPT`（coding agent 基调）
  2. **Autocompact 摘要 Prompt** —— `compaction/prompts.py` 的 `NO_TOOLS_PREAMBLE` + `BASE_COMPACT_PROMPT` + `NO_TOOLS_TRAILER`，三段拼成一个整体编辑
  3. **Session Memory 模板** —— `session_memory/template.py::DEFAULT_TEMPLATE`（10 章节结构）
  4. **Session Memory 更新指令** —— `session_memory/template.py::DEFAULT_UPDATE_PROMPT`（给 LLM 的编辑规则）
- 全局持久化到 `~/.taisang/settings.json` 的 `prompts` 字段
- 修改后立即对所有活跃 session 生效（主 system prompt 同步替换 messages[0]，autocompact/session memory 触发时自然读新值）
- 独立路由 `/prompts`，Sidebar 入口与 Skills/MCP 平级
- 每个区块独立的"保存"和"恢复默认"按钮，独立确认弹窗
- 编辑态未保存改动提示 + 离开页面拦截

### 不做
- Per-session 或项目级覆盖（仅全局）
- Prompt 版本历史 / diff 回滚
- 多 prompt 批量保存（每个区块独立保存）
- 拖拽文件上传 prompt
- 前端 e2e 自动化（手动验证，与 LLM 配置页一致）

---

## 2. 数据模型

### `~/.taisang/settings.json` 新增 `prompts` 字段

```json
{
  "llm": { ... },
  "skills": { ... },
  "prompts": {
    "system_prompt": {
      "value": "...",
      "use_default": false
    },
    "autocompact_prompt": {
      "value": "...",
      "use_default": true
    },
    "session_memory_template": {
      "value": "...",
      "use_default": false
    },
    "session_memory_update_prompt": {
      "value": "...",
      "use_default": true
    }
  }
}
```

### 字段语义
- `use_default: true` → 运行时读代码常量，`value` 字段忽略（保留但不使用）
- `use_default: false` → 运行时读 `value`
- 字段缺失 → 按 `use_default: true` 处理（即首次使用无配置等价于全默认）
- "恢复默认"操作 = 把对应 key 设为 `use_default: true`
- "保存"操作 = 把对应 key 设为 `use_default: false` + 写入 `value`

### 四个 key 对应的默认常量

| key | 默认值来源 | 运行时读取函数 |
|---|---|---|
| `system_prompt` | `agent_core/prompts.py::SYSTEM_PROMPT` | `get_system_prompt()` |
| `autocompact_prompt` | `NO_TOOLS_PREAMBLE + "\n\n" + BASE_COMPACT_PROMPT + "\n\n对话内容:\n{conversation}\n\n" + NO_TOOLS_TRAILER`（运行时 `str.format` 把 `{conversation}` 替换为对话文本；用户自定义时必须含 `{conversation}` 占位符，否则保存 400） | `get_autocompact_prompt(conversation_text: str) -> str` |
| `session_memory_template` | `session_memory/template.py::DEFAULT_TEMPLATE` | `get_template()`（改造） |
| `session_memory_update_prompt` | `session_memory/template.py::DEFAULT_UPDATE_PROMPT` | `get_update_prompt()`（改造，保留 `{memory_path}` / `{current_notes}` 占位符填充逻辑） |

---

## 3. 后端改动

### 3.1 `config.py`

新增 `PromptsConfig` pydantic model：

```python
class PromptOverride(BaseModel):
    value: str = ""
    use_default: bool = True

class PromptsConfig(BaseModel):
    system_prompt: PromptOverride = PromptOverride()
    autocompact_prompt: PromptOverride = PromptOverride()
    session_memory_template: PromptOverride = PromptOverride()
    session_memory_update_prompt: PromptOverride = PromptOverride()
```

新增函数（复用现有 `_settings_path` / `_load_settings_file`，保留 llm / skills 等其他字段，原子写）：

- `load_prompts() -> PromptsConfig`
- `save_prompt_override(key: str, value: str) -> PromptsConfig` —— 设 `use_default=False`，返回最新完整 config
- `reset_prompt_override(key: str) -> PromptsConfig` —— 设 `use_default=True`，返回最新完整 config

校验：`value` 非空、长度 ≤ 50KB，否则抛 `ValueError`。

### 3.2 三个 prompt 源文件改造

#### `agent_core/prompts.py`
- 保留 `SYSTEM_PROMPT` 常量（作为默认值 + 前端展示用）
- 新增 `get_system_prompt() -> str`：读 `load_prompts().system_prompt`，`use_default` 或缺省返回 `SYSTEM_PROMPT`，否则返回 `value`
- `build_system_prompt(skills_section, mcp_section)` 内部改为调 `get_system_prompt()` 取基础 prompt，再拼 skills/mcp 段（段头逻辑不变）

#### `compaction/prompts.py`
- 保留三个常量
- 新增 `DEFAULT_AUTOCOMPACT_PROMPT` 常量 = `NO_TOOLS_PREAMBLE + "\n\n" + BASE_COMPACT_PROMPT + "\n\n对话内容:\n{conversation}\n\n" + NO_TOOLS_TRAILER`（含 `{conversation}` 占位符）
- 新增 `get_autocompact_prompt(conversation_text: str) -> str`：读 config，`use_default` 返回 `DEFAULT_AUTOCOMPACT_PROMPT.format(conversation=conversation_text)`，否则 `value.format(conversation=conversation_text)`（用户自定义文本必须含 `{conversation}`，保存时已校验）
- `autocompact.py` 调用处改为 `full_prompt = get_autocompact_prompt(conversation_text)`（删掉原来 `"\n\n".join([PREAMBLE, BASE, "对话内容:", conversation_text, TRAILER])` 那段拼接）

#### `session_memory/template.py`
- `get_template()` 改造：读 config 优先，`use_default` 返回 `DEFAULT_TEMPLATE`，否则返回 `value`
- `get_update_prompt(current_notes, memory_path)` 改造：读 config 的 `session_memory_update_prompt`，`use_default` 用 `DEFAULT_UPDATE_PROMPT`，否则用 `value`；**注意**：用户自定义文本里仍要支持 `{current_notes}` / `{memory_path}` 占位符填充（用 `str.format`），如果自定义文本缺占位符则不填充（用户自行负责）

### 3.3 `agent_core/service.py`

- 启动 `__init__` / `reset()` 调 `build_system_prompt(skills_section, mcp_section)` 时自动用新 `get_system_prompt()`，**无需改 service 签名**
- service 不感知 prompt 来源切换

### 3.4 `SessionRegistry.apply_prompts_config(key: str | None = None)`

新增方法，仿 `apply_llm_config`：

```python
def apply_prompts_config(self, key: str) -> None:
    """改 prompt 后广播到所有内存 session。

    - key == "system_prompt":
        重新调 build_system_prompt(skills_section, mcp_section),
        替换每个 session 的 ctx.messages[0]（system 消息）。
        skills/mcp 段从该 session 现有 manager 重新取，不丢。
    - 其他 key（autocompact / session_memory_*）:
        触发时才读 config，不需要 broadcast，直接返回。
    - 正在跑的 run 持有 sess.lock，等它跑完下一次 LLM 调用自然用新 system
      —— 与 apply_llm_config 同语义。
    - MockLLM session 也替换 messages[0]（system prompt 与 llm 类型无关）。
    """
    if key != "system_prompt":
        return
    with self._lock:
        sessions = list(self._sessions.values())
    for sess in sessions:
        agent = sess.agent
        # 重新组装 system prompt，保留 skills/mcp 段（与 service.__init__/reset 同逻辑）
        from ..skills.listing import format_skill_listing
        from .prompts import build_system_prompt, format_mcp_section
        skills_section = format_skill_listing(agent.skills)
        mcp_section = format_mcp_section(agent._mcp_manager) if agent._mcp_manager else ""
        new_system = build_system_prompt(skills_section, mcp_section)
        # 原地替换 messages[0]
        agent.ctx.replace_system_prompt(new_system)
```

`AgentContext` 需新增 `replace_system_prompt(text)` 方法（或直接在 `messages[0]` 上改 content —— 实现时看 `context.py` 现有 API 决定，倾向新增方法以保持封装）。

### 3.5 `web/prompts_api.py`（新增，仿 `skills_api.py`）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/prompts` | 返回 `{ key: { current: str, default: str, use_default: bool } }` 四条 |
| PUT | `/api/prompts` | body `{ key: str, value: str }` → 调 `save_prompt_override` + 调 `registry.apply_prompts_config(key)`（内部对非 system_prompt 直接 no-op） |
| POST | `/api/prompts/reset` | body `{ key: str }` → 调 `reset_prompt_override` + 调 `registry.apply_prompts_config(key)`（同上） |

校验：
- `key` 必须在四个合法 key 集合内，否则 400
- `value` 非空、≤ 50KB，否则 400
- 返回保存后的完整 `{ key: { current, default, use_default } }` 便于前端即时刷新

`app.py` 注册路由，路由顺序注意放在 catch-all 之前。

---

## 4. 前端改动

### 4.1 路由 + Sidebar
- `router/index.ts` 加 `{ path: '/prompts', name: 'prompts', component: PromptManage }`
- Sidebar 加入口，图标用 `edit-1` 或 `setting-1`，label "Prompt 管理"，与 Skills/MCP 平级

### 4.2 `api/prompts.ts`
```ts
export interface PromptItem {
  current: string
  default: string
  use_default: boolean
}
export interface PromptsMap {
  system_prompt: PromptItem
  autocompact_prompt: PromptItem
  session_memory_template: PromptItem
  session_memory_update_prompt: PromptItem
}
export function fetchPrompts(): Promise<PromptsMap>
export function savePrompt(key: keyof PromptsMap, value: string): Promise<PromptItem>
export function resetPrompt(key: keyof PromptsMap): Promise<PromptItem>
```

### 4.3 `PromptManage.vue` 布局

四个折叠面板（与 Skills 页的视觉风格一致）：

```
┌─ 主 System Prompt ─────────────── [使用默认] [恢复默认] [保存] ┐
│  <textarea monospace, rows=20, 可拖拽缩放>                    │
│  状态行: "未保存改动" / "已保存" / "使用默认值"                │
└──────────────────────────────────────────────────────────────┘
┌─ Autocompact 摘要 Prompt ──────── [使用默认] [恢复默认] [保存] ┐
│  ...                                                          │
└──────────────────────────────────────────────────────────────┘
┌─ Session Memory 模板 ──────────── [使用默认] [恢复默认] [保存] ┐
│  ...                                                          │
└──────────────────────────────────────────────────────────────┘
┌─ Session Memory 更新指令 ──────── [使用默认] [恢复默认] [保存] ┐
│  ...                                                          │
└──────────────────────────────────────────────────────────────┘
```

每个面板独立状态：
- `original`: 加载时的 `current`（用于 diff 检测未保存）
- `draft`: textarea v-model
- `useDefault`: 加载时的 `use_default`
- `dirty`: `draft !== original`

### 4.4 交互

**加载**：进入页面调 `fetchPrompts()`，填充四个面板的 `original` / `draft` / `useDefault`。

**编辑**：textarea 输入实时更新 `draft`，`dirty` 变 true 时状态行显示"未保存改动"（橙色）。

**保存按钮**：
- 主 System Prompt：弹确认对话框，文案：
  > ⚠️ 修改主 System Prompt 将立即应用到所有活跃会话。
  > - 当前进行中的对话，agent 行为指令会中途切换，可能导致前后风格/约束不一致；
  > - API 的 prompt cache 会失效，下一次响应稍慢、多消耗一次前缀 token，之后自动重建。
  >
  > 建议在新会话开始前修改。是否继续？
- Autocompact / Session Memory 模板 / Session Memory 更新指令：弹确认对话框，文案：
  > ⚠️ 修改后将立即保存。下次触发上下文压缩 / 笔记更新时使用新 prompt。
  > 当前进行中的对话不受影响（只有触发 compaction 时才用到）。
  >
  > 是否继续？
- 确认后调 `savePrompt(key, draft)`，成功后用返回的 `current` 更新 `original` / `draft`，状态行显示"已保存"（绿色，2 秒后恢复中性）

**恢复默认按钮**：
- 弹确认：
  > 将恢复为内置默认值，自定义内容会被覆盖。是否继续？
- 确认后调 `resetPrompt(key)`，成功后用返回的 `current`（即默认值）更新 `original` / `draft` / `useDefault=true`，状态行显示"使用默认值"

**离开页面**：`beforeRouteLeave` + `beforeunload`，若有任意面板 `dirty` 为 true，弹确认：
  > 有未保存的 prompt 修改，确定离开？

### 4.5 视觉细节
- textarea 用 monospace 字体，行高 1.5，支持纵向拖拽缩放
- 折叠面板默认全部展开（prompt 内容较多，用户进页面就是要看）
- 顶部加一行说明：`Prompt 修改全局生效，对所有会话立即应用。`
- 移动端响应式：折叠面板全宽，按钮折行

---

## 5. 错误处理 / 边界

| 场景 | 处理 |
|---|---|
| 保存时 value 为空 | 后端 400 "prompt 不能为空"；前端按钮 disable（draft 为空时） |
| value 超 50KB | 后端 400 "prompt 过长（>50KB）" |
| `use_default: true` 但用户在 textarea 改了 | 状态行提示"当前使用默认值，你的编辑未保存"，保存按钮可点（点了就覆盖为自定义） |
| settings.json 损坏 | `_load_settings_file` 已有容错（返回 {}），prompts 字段缺失走默认 |
| 改 system prompt 时 session 正在跑 run | 等 run 结束下次 LLM 调用生效（与 LLM 配置切换同语义，可接受） |
| MockLLM session | `apply_prompts_config` 也替换 messages[0]（system prompt 与 llm 类型无关） |
| 用户自定义 session_memory_update_prompt 缺 `{current_notes}` 占位符 | `str.format` 不报错（缺占位符就不替换），用户自行负责 |
| 用户自定义 autocompact_prompt 缺 `{conversation}` 占位符 | 保存时校验 400"prompt 必须包含 `{conversation}` 占位符"（缺了对话内容无法注入，硬错误） |

---

## 6. 测试

### 后端
- `tests/test_prompts_config.py`
  - `load_prompts()` 无配置 → 全 use_default=true
  - `save_prompt_override("system_prompt", "...")` → use_default=false, value 写入
  - `reset_prompt_override("system_prompt")` → use_default=true
  - 损坏 settings.json → fallback 默认
  - value 超长 / 为空 → ValueError
  - 保留 llm / skills 字段不丢
- `tests/test_prompts_api.py`
  - GET 返回四个 key 的 current/default/use_default
  - PUT 保存后 GET 反映新值
  - POST reset 后 use_default=true
  - 非法 key → 400
  - 空 value / 超长 → 400
  - PUT system_prompt 后 `registry.apply_prompts_config` 被调用，活跃 session 的 messages[0] 被替换且 skills/mcp 段保留
  - PUT autocompact_prompt 后不调 apply_prompts_config（不需要 broadcast）
- `tests/test_prompt_runtime.py`
  - `get_system_prompt()` use_default 时返回常量
  - `get_system_prompt()` 自定义时返回 value
  - `build_system_prompt` 用自定义 system prompt + skills 段拼接正确
  - `get_autocompact_prompt()` 三段拼接顺序正确
  - `get_template()` / `get_update_prompt()` 自定义时占位符填充正常

### 前端
- 暂不新增 e2e（与 LLM 配置页一致，手动验证）
- 手动验证清单：
  - [ ] 进入 /prompts，四个面板加载当前值
  - [ ] 编辑主 system prompt，状态行变"未保存改动"
  - [ ] 保存弹确认，确认后状态行变"已保存"
  - [ ] 恢复默认弹确认，确认后 textarea 替换为默认值
  - [ ] 离开页面有 dirty 时拦截
  - [ ] 改主 system prompt 后，活跃 session 下一轮 LLM 调用使用新 prompt（debug 模式验证 messages[0]）

---

## 7. 实施顺序建议

1. 后端 config + 三个 prompt 源文件改造（含 `get_xxx()` 函数）+ 单测
2. `SessionRegistry.apply_prompts_config` + `AgentContext.replace_system_prompt` + 单测
3. `web/prompts_api.py` + 路由注册 + API 单测
4. 前端 `api/prompts.ts` + `PromptManage.vue` + 路由 + Sidebar 入口
5. 手动验证清单跑一遍