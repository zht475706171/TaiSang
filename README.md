# TaiSang

> 简化版 Claude Code / Trae —— 一个能读写、修改、调试代码的交互式 coding agent。

**当前状态:v0.1(REPL + Web UI 双入口,带 Skill 系统 + 多 Agent 调度 + MCP 客户端)**

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
- **任务追踪(TodoWrite)**:LLM 判断任务复杂(3+ 步)时主动调 `TodoWrite({todos: [...]})` 拆解,前端顶部 sticky 区渲染 todo 列表(pending/in_progress/completed 三态 + activeForm 动效),用户随时可见进度。覆盖式更新,observation 自然落盘 jsonl,resume 时从最后一条 TodoWrite 调用重建。对标 Claude Code TodoWrite。
- **流式输出**:LLM 响应逐 chunk 流式输出(最终答案 text + thinking reasoning),Web 和 CLI 都支持;用户可中断当前 turn(Web 停止按钮 / CLI Ctrl+C),中断后保留半截答案 + `[interrupted]` 标记,上下文保持一致(LLM 阶段补半截 assistant,工具阶段补空 tool_result `{"_interrupted": true}`)
- **即时中断(对标 Claude Code abort signal)**:cancel 信号贯穿全链路 —— 前端点 stop 立刻切回发送按钮(stopping 状态显示"停止中…"),后端 pump 线程 + Queue 模式让主循环周期检查 cancel,触发时调 `raw_stream.close()` 真关 HTTP 连接(Kimi 服务端停生成),Bash 工具执行中 cancel 则 kill shell + 重启(cwd 从 Python state 保留)。中断延迟 ms 级,不等下一个 chunk 或命令跑完

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

**Prompt 管理**
- 4 份核心 prompt 可前端可视化编辑,持久化到 `~/.taisang/settings.json`:
  - `system_prompt`:agent 主系统提示
  - `autocompact_prompt`:autocompact 摘要提示(自定义文本必须含 `{conversation}` 占位符)
  - `session_memory_template`:session memory 10 章节模板
  - `session_memory_update_prompt`:session memory 更新提示
- 每个 prompt 返回 `{current, default, use_default, value}`:可切回默认(use_default)或自定义覆盖
- `system_prompt` 变更后广播到所有活跃 session,即时生效(其它 key 仅影响新会话)
- **前端 `/prompts` 管理页**:4 个编辑区 + 重置默认按钮 + Sidebar "Prompt 管理" 入口

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

**MCP 客户端(对标 Claude Code MCP)**
- 接入第三方 MCP server,把其暴露的 tool / resource / prompt 注入 agent 工具体系
- 两种 transport:`stdio`(本地子进程,command/args/env)+ `sse`(HTTP+SSE,url/headers);用官方 `mcp` SDK,真 handshake(initialize)→ 能力拉取 → 调用全链路
- 三类资源接入 ToolRegistry:
  - 每个 MCP tool 注册成 `MCPTool`,命名 `mcp__<server>__<tool>`,LLM 调用走 `manager.call_tool()`
  - `mcp_resource(server, uri)` 统一工具读资源
  - `mcp_prompt(server, name, args)` 获取 prompt 模板内容
- 配置 CRUD + 连接生命周期:`MCPManager` 单例(线程安全双重检查锁),配置持久化到 `~/.taisang/mcp_servers.json`(原子写 + chmod 0o600),状态机 connected/disconnected/failed/disabled
- **前端 `/mcp` 管理页**:server 列表(name / transport / 状态 / 工具数)、增删改、启用/禁用 toggle(禁用真断开,不残留工具暴露)、重连、**三种快速添加**:
  - CLI 一行:`myserver npx -y @some/mcp-server` 或 `myserver --transport sse https://...`
  - JSON 文本:支持 **claude-code `mcpServers` 格式** + TaiSang 单对象/数组/`{servers:[...]}` 三种格式
  - 文件上传:1MB 上限 + UTF-8 校验
  - 同名覆盖,批量导入部分失败不影响其他(返回 added/updated/failed)
- 安全:name 字符集校验(`/^[A-Za-z0-9][A-Za-z0-9_-]*$/`)+ stdio 必填 command / sse 必填 url
- Sidebar "MCP 管理" 入口绑定 `/mcp` 路由,真跳转

**Web UI** (Vue 3.5 + Vite + TDesign)
- 多会话列表(Sidebar) / 中对话流(ChatView) / 底一体式输入框(Claude 风格)
- 工具卡片可折叠 / Markdown 渲染 / 代码高亮
- SSE 实时事件流(8 种 AgentEvent)
- LLM 配置页(`/settings`):model / api_key(打码)/ base_url,保存后立即应用到所有活跃 session(MockLLM 实例除外)
- SPA history 路由:`/chat/:id`、`/skills` 深链刷新不 404
- Sidebar 入口:新对话、Skill 管理、MCP 管理、Prompt 管理、Agent 管理

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
- ~~**多 agent / subagent 调度**:无 orchestrator、无 Task 工具~~ ✅ 已实现(M3 — AgentTool + 4 内置 agent + sync/async + fork + 递归防护 + 前端 /agents 管理页,见上方"多 Agent 调度"章节)
- ~~**MCP 客户端**:不支持接入第三方 MCP server~~ ✅ 已实现(stdio + sse 两种 transport + tool/resource/prompt 三类资源 + 三种快速导入 + 前端 /mcp 管理页,见上方"MCP 客户端"章节)
- **流式 LLM 响应**:~~当前等完整 response 才一次性给前端(SSE 是事件层,不是 token 流)~~ ✅ 已实现(逐 chunk `LLM_CHUNK` 事件 + 用户中断,见上方"Agent 核心"章节)
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
- 暗色主题 / 主题切换
- 移动端适配
- Web 端断线重连(EventSource 断了不会自动续)

**Agent 行为**
- ~~TodoWrite / 任务列表:无任务追踪 UI~~ ✅ 已实现(LLM 主动调 `TodoWrite` 工具,顶部 sticky 区渲染,见上方"任务追踪"章节)
- 图片 / 多模态输入:只支持文本
- Resume 中断的会话:进程死了会话就死(todos 已支持 resume,从 jsonl 重建)
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
- SSE 实时事件流 + SPA history 路由(`/chat/:id`、`/skills`、`/mcp`、`/agents`、`/prompts` 深链刷新不 404)

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
- **事件流**:9 种 AgentEvent(含 `LLM_CHUNK` 流式 chunk 事件,text_delta / reasoning_delta),CLI 和 Web UI 共用同一套渲染逻辑
- **流式 chunk 事件**:`LLM_CHUNK` 事件实时推送 text_delta / reasoning_delta,前端 streamingMessage / reasoningText 累积渲染;子 agent 的 chunk 嵌套到父 Agent 工具卡片内

## 测试

```bash
pytest tests/ -q       # 532 passed(含 6 个 MCP 测试文件)
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