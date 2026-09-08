# TaiSang

> 简化版 Claude Code / Trae —— 一个能读写、修改、调试代码的交互式 coding agent。

**当前状态:v0.1(REPL + Web UI 双入口,带 Skill 系统 + 多 Agent 调度)**

## 功能

### ✅ 已实现

**Agent 核心**
- 单 agent 主循环:LLM ↔ 6 个工具(Read / Grep / Glob / Edit / Write / Bash),直到产出最终答案
- Bash 用持久 shell,cd 跨调用保留;危险命令**黑名单**拦截(rm -rf /, mkfs, 强推 main, fork bomb 等)
- 文件工具相对/绝对路径、offset/limit 分页读、自动跟随 Bash cd 后的 cwd
- 上下文管理三道闸:`apply-tool-result-budget` 落盘超大 tool_result → `autocompact` LLM 摘要 → `session memory` 长效笔记(autocompact 触发时零 LLM 注入)
- 工具确认:Web 端 Edit/Write 改文件前弹卡片,CLI 端 y/n 确认
- 权限模型:WebPermissionManager,首次访问新目录问用户批准,批准后该目录树放行
- 调试模式:`/debug` 打印完整 messages + 工具 observation;`/reset` 清对话上下文(保留 session memory)
- Token 用量:每轮 + session 累计

**Skill 系统(渐进披露)**
- `SKILL.md` 目录格式,frontmatter 字段:`name` / `description` / `when_to_use` / `allowed_tools`
- 三源加载,优先级 `project > user > system`:
  - `project`:`<repo>/.taisang/skills/`(自动)
  - `user`:`~/.taisang/skills/`(settings.json 可配 user_dirs)
  - `system`:包内 `taisang/skills/builtin/`,含 `commit` 和 `review` 两个内置 skill
- 加载机制:启动时全量读入内存(只 meta + 全文),SYSTEM_PROMPT 只注入轻量清单(每条 ≤250 字符、总预算 2000 字符,超限降级到只列名字)
- LLM 调 `skill` 工具时,SKILL.md 全文(替换 `${TAISANG_SKILL_DIR}` + `allowed_tools` 提示段 + 用户参数段)作为 user 消息注入
- **前端 Skill 管理页** (`/skills`):表格、来源标签(项目/用户/内置)、启用开关、重载、**导入**(MD 单文件 / zip 目录形式)+ 覆盖确认(同名 409 → confirm → `?overwrite=true`)、**删除**(内置不可删,顺带清 disabled 状态记录)
- 安全:frontmatter name 字符集校验(`/^[A-Za-z0-9][A-Za-z0-9_-]*$/` 防目录穿越)+ zip-slip 拦截(拒绝绝对路径/`..`/反斜杠/前缀外成员)+ 10MB 上限

**多 Agent 调度(M3)**
- Agent 工具(`AgentTool`):主 agent 通过 `Agent({subagent_type, prompt, run_in_background})` 派子 agent
- 4 个内置 agent:`general-purpose` / `explore`(只读) / `plan`(只读) / `verification`(对抗,默认 async)
- 两种模式:传 `subagent_type` 走 A(全新上下文,用 agent.system_prompt),省略走 B(fork 深拷贝父 messages 继承对话)
- sync + async 执行:async 立即返回 `async_launched`,后台 daemon 线程跑完把结果注入 `parent_service._pending_async_notifications`,主循环下轮 `flush_async_notifications()` 消费成 user 消息
- Agent 定义文件:目录格式 `AGENT.md`,三源加载(`project > user > system`),frontmatter 字段:`name` / `description` / `tools` / `disallowedTools` / `maxTurns` / `background` / `model`
- state 持久化:`~/.taisang/agents_state.json` 记录 disabled 状态,原子写(tmp + os.replace,chmod 0o600 best-effort)
- 渐进披露清单:`format_agent_listing` 每条 ≤250 字符描述、总预算 2000 字符,超限降级到 per-entry 截断 → names-only
- **前端 `/agents` 页**:表格(name / 描述 / 来源标签 / 工具集 / 启用开关)+ 重载按钮 + Sidebar "Agent 管理" 入口
- 事件嵌套:`AgentEvent.agent_id` 区分主/子,SSE 嵌套渲染到 Agent 工具卡片内(ToolCard 展开 `[data-sub-agent-event]` 列表)
- token 双层:子 agent 单独 emit `USAGE_REPORT`(`agent_id` 非空),同时 `_merge_child_usage` 累加进主 session 累计
- 递归防护:子 agent `ToolRegistry` 构造时 `agents=[]` 物理不注册 `AgentTool`;`is_fork_child` flag 阻止 fork-in-fork

**Web UI** (Vue 3.5 + Vite + TDesign)
- 多会话列表(Sidebar) / 中对话流(ChatView) / 底一体式输入框(Claude 风格)
- 工具卡片可折叠 / Markdown 渲染 / 代码高亮
- SSE 实时事件流(8 种 AgentEvent)
- LLM 配置页(`/settings`):model / api_key(打码)/ base_url,保存后立即应用到所有活跃 session(MockLLM 实例除外)
- SPA history 路由:`/chat/:id`、`/skills` 深链刷新不 404
- Sidebar 入口:新对话、Skill 管理(active)、MCP 管理(占位)

**CLI** (`taisang chat`)
- REPL 交互
- `/exit` / `/reset` / `/debug`

**LLM**
- 任意 OpenAI 兼容 endpoint(DeepSeek / Kimi / OpenAI / 自部署 ollama 都 OK)
- 实时切换:UI 保存 LLM 配置后所有 session 立刻换成新 client
- MockLLM(测试用,`TAISANG_MOCK_LLM=1`)

### 🚧 待实现

按需求强度排序:

**高频 / 跨项目**
- **多 agent / subagent 调度**:~~无 orchestrator、无 Task 工具~~ ✅ 已实现(M3,见上方"多 Agent 调度"章节)。剩余缺口:不支持并发多个 Agent 工具调用(同时只 1 个 in-flight),前端 `findLastAgentToolCall` 用"最后一个 Agent 卡片"匹配
- **MCP 客户端**:Sidebar 那个 server 图标是占位;不支持接入第三方 MCP server 的 tool/resource/prompt(stdio/sse/http 传输都没有)
- **流式 LLM 响应**:当前等完整 response 才一次性给前端(SSE 是事件层,不是 token 流)
- **多 skill 批量导入**:importer 现在一个 zip 一个 skill;扩展后可一次导入 N 个(像 superpowers plugin 那样)

**claude-code plugin 概念**(部分实现)
- Commands(slash command,如 `/commit`)
- ~~Agents(子 agent 类型定义)~~ ✅ 已实现(M3 — `AGENT.md` 定义文件 + 三源加载 + 4 内置 agent)
- Hooks(PreToolUse / PostToolUse / SessionStart 等)
- Plugin 清单解析(plugin.json + marketplace)

**Skill 相关**
- 运行时 SKILL.md 修改生效:会话期间改文件不会生效,必须新开会话(loader 无 mtime 监听)
- frontmatter 高级字段:`version` / `model` / `context:fork` / `agent` / `paths` / `argument-hint` 等 v1 静默忽略
- fork 执行模式:只 inline;claude-code 支持把 skill 放到子 agent 里跑
- 条件 paths / deny 规则 / 硬拦 allowed_tools:v1 全部自动允许 + 提示
- skill 描述超 250 字符的完整渲染:被 listing 预算截断,只能调工具看完整

**Web UI**
- Sidebar "MCP 管理" 入口点击无反应
- 暗色主题 / 主题切换
- 移动端适配
- Web 端断线重连(EventSource 断了不会自动续)

**Agent 行为**
- TodoWrite / 任务列表:无任务追踪 UI
- 图片 / 多模态输入:只支持文本
- Resume 中断的会话:进程死了会话就死
- Skill 全文驻内存:几十个无压力,几百个浪费 RAM(v2 改 lazy read)

**工程**
- 国际化:UI 文本写死中文

## Quick Start

```bash
# 安装(开发模式,含 web 依赖)
pip install -e ".[web,dev]"

# 配置 LLM(支持任意 OpenAI 兼容 endpoint)
# 方式一:写 ~/.taisang/settings.json
#   {"llm": {"base_url": "...", "api_key": "sk-xxx", "model": "..."}}
# 方式二:环境变量
export TAISANG_LLM_BASE_URL=https://api.deepseek.com
export TAISANG_LLM_API_KEY=sk-xxx
export TAISANG_LLM_MODEL=deepseek-chat

# cd 到你要操作的 repo
cd ~/repos/my-project

# 进 REPL
taisang chat
# 或指定 repo
taisang chat --repo ~/repos/my-project

# 或起 Web UI(豆包风格,自动开浏览器)
taisang web --repo .
```

## 两种入口

### CLI(`taisang chat`)
- REPL 交互,输入自然语言目标 → agent 调工具查/改/跑代码
- `/exit` 退出,`/reset` 清上下文(session memory 笔记保留),`/debug` 切调试输出
- Edit/Write 改文件前弹 y/n 确认
- Bash 用持久 shell,cd 跨调用保留;危险命令黑名单(rm -rf /, mkfs, 强推 main, fork bomb 等)直接拒

### Web UI(`taisang web`)
- Vue 3.5 + Vite + TDesign 实现的 SPA:左会话列表 / 中对话流 / 底一体式输入框(Claude 风格)
- Markdown 渲染 + 代码高亮 + 工具卡片可折叠
- 多会话隔离,会话标题从首条消息自动生成
- 异步文件确认(改文件时弹卡片,允许/拒绝)
- `/reset` `/debug` 按钮,token 用量底部小字
- SSE 实时事件流 + SPA history 路由(`/chat/:id`、`/skills` 深链刷新不 404)

## 工具集

| 工具 | 作用 | 上限 |
|------|------|------|
| Read | 读文件(支持 offset/limit 分页) | 32KB 字节闸门 |
| Grep | 正则搜 | 200 命中 + 500 字符长行跳过 |
| Glob | 文件名匹配 | 100 硬切 |
| Edit | old_string → new_string 改文件(用户确认) | — |
| Write | 创建/覆盖文件(用户确认) | — |
| Bash | 跑 shell 命令(持久 shell + 危险命令黑名单) | 30000 字符 + 超长落盘 |

## 上下文管理(长对话三道机制)

1. **apply-tool-result-budget**:单轮 tool_result 总字节超预算时,最大的几条持久化到磁盘,原 content 替换成 preview 占位符
2. **autocompact**:对话 token 逼近预算时,旁路 LLM 生成摘要替换整个 messages
3. **session memory**:平时异步维护 10 章节笔记,autocompact 触发时零 LLM 调用读笔记注入主 prompt

## 可观测性

- **token 用量**:每轮回答后显示此轮 + session 累计 token(cache 命中率因 endpoint 不报告固定 N/A)
- **/debug 模式**:打印发给 LLM 的完整 messages + 响应 + 工具完整 observation
- **事件流**:8 种 AgentEvent,CLI 和 Web UI 共用同一套渲染逻辑

## 测试

```bash
pytest tests/ -q       # 248 passed
ruff check src/ tests/ # 全绿
black --check src/ tests/ # 全绿
```

## 环境变量

| 变量 | 作用 |
|------|------|
| `TAISANG_LLM_BASE_URL` | LLM endpoint(覆盖 settings.json) |
| `TAISANG_LLM_API_KEY` | API key |
| `TAISANG_LLM_MODEL` | 模型名 |
| `TAISANG_MOCK_LLM=1` | 用 MockLLM(测试用,不需要真 key) |

## License

MIT