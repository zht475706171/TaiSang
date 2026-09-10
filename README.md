<p align="center">
  <h1 align="center">🤖 TaiSang</h1>
</p>

<p align="center">
  <b>简体中文</b> | <a href="./README_EN.md">English</a>
</p>

> **私人 agent · 总结习惯**
>
> 一个会总结你习惯的私人 AI agent —— 读写代码、跑命令、调工具,同时学习你的偏好与工作流。

**当前状态:** v0.1 —— REPL + Web UI 双入口,带 Skill 系统 + 多 Agent 调度 + MCP 客户端 + 用户画像

---

## 🚀 快速开始

### 安装

```bash
pip install -e ".[web,dev]"
```

### 配置 LLM

支持任意 OpenAI 兼容 endpoint(DeepSeek / Kimi / OpenAI / 自部署 ollama 都 OK)。

**方式一:** `~/.taisang/settings.json`

```json
{"llm": {"base_url": "https://api.deepseek.com", "api_key": "sk-xxx", "model": "deepseek-chat"}}
```

**方式二:** 环境变量

```bash
export TAISANG_LLM_BASE_URL=https://api.deepseek.com
export TAISANG_LLM_API_KEY=sk-xxx
export TAISANG_LLM_MODEL=deepseek-chat
```

### 启动

```bash
# Web UI(豆包风格,自动开浏览器)
taisang web

# 指定工作目录
taisang web --repo ~/repos/my-project

# CLI REPL
taisang chat
taisang chat --repo ~/repos/my-project
```

### 首次使用 3 步走

1. **配 LLM key** —— 打开 Web UI 后点右上角 ⚙️ 配置 model / api_key / base_url,保存即生效
2. **导入项目** —— 输入栏左侧 `+` 按钮 → "导入项目" → 系统目录选择器选定你的 repo,成为当前会话工作目录
3. **开始对话** —— 自然语言提需求,agent 会自己调工具查/改/跑代码

---

## 📊 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TaiSang                                     │
│                                                                     │
│   ┌──────────────┐         ┌──────────────────────────────────┐    │
│   │   CLI REPL   │         │            Web UI                │    │
│   │ taisang chat │         │   Vue 3.5 + Vite + TDesign       │    │
│   └──────┬───────┘         │  Sidebar / ChatView / ConfigModal│    │
│          │                 └──────────────┬───────────────────┘    │
│          │                                │ SSE (15 AgentEvent)    │
│          │                                │                        │
│          └────────────┬───────────────────┘                        │
│                       ▼                                            │
│   ┌───────────────────────────────────────────────────────────┐   │
│   │              Agent Core (主循环,每轮顺序如下)              │   │
│   │                                                            │   │
│   │   ┌─────────────────────────────────────────────────┐     │   │
│   │   │  ① Context Management (三道闸,LLM 调用前预处理) │     │   │
│   │   │   • tool-result-budget  → 超大结果落盘          │     │   │
│   │   │   • autocompact         → LLM 摘要压缩          │     │   │
│   │   │   • session memory      → 长效笔记零 LLM 注入   │     │   │
│   │   └────────────────────┬────────────────────────────┘     │   │
│   │                        ▼                                  │   │
│   │   ┌─────────────────────────────────────────────────┐     │   │
│   │   │  ② LLM 调用 (chat_stream)                        │     │   │
│   │   │     ↓ 产出 text / reasoning / tool_calls         │     │   │
│   │   └────────────────────┬────────────────────────────┘     │   │
│   │                        ▼                                  │   │
│   │   ┌─────────────────────────────────────────────────┐     │   │
│   │   │  ③ 工具执行 (ToolRegistry)                       │     │   │
│   │   │     6 内置: Read / Grep / Glob / Edit/Write/Bash │     │   │
│   │   │     ┌─────────┐ ┌─────────┐ ┌─────────┐          │     │   │
│   │   │     │ Skill   │ │ Agent   │ │  MCP    │ ← 三扩展 │     │   │
│   │   │     │ Tool    │ │ Tool    │ │  Tool   │          │     │   │
│   │   │     └────┬────┘ └────┬────┘ └────┬────┘          │     │   │
│   │   │          │          │           │                │     │   │
│   │   │     ┌────▼────┐ ┌───▼─────┐ ┌───▼──────────┐      │     │   │
│   │   │     │ Skills  │ │ Agents  │ │ MCP Manager  │      │     │   │
│   │   │     │ 三源加载 │ │ 4 内置  │ │ stdio + sse  │      │     │   │
│   │   │     └─────────┘ └─────────┘ └──────────────┘      │     │   │
│   │   └────────────────────┬────────────────────────────┘     │   │
│   │                        │ observation                       │   │
│   │                        └──────┐                            │   │
│   │                               │ 下一轮回到 ①               │   │
│   └───────────────────────────────┼────────────────────────────┘   │
│                                   │                                │
│                       LLM Client (任意 OpenAI 兼容)                │
│            DeepSeek / Kimi / OpenAI / Ollama / MockLLM             │
│                                                                     │
│   ┌───────────────────────────────────────────────────────────┐   │
│   │             Personalization (个性化,跨循环注入)            │   │
│   │  • user_profile  —— 学习你的技术栈/代码风格/沟通/环境/禁忌│   │
│   │  • TodoWrite     —— 任务追踪,顶部 sticky 渲染进度         │   │
│   │  • Prompt 管理   —— 4 份核心 prompt 前端可视化编辑         │   │
│   └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ✨ 目前支持的功能

### Agent 核心

- **主循环:** LLM ⇄ 6 工具循环直到产出最终答案
- **持久 shell:** Bash `cd` 跨调用保留;危险命令黑名单拦截(`rm -rf /`、`mkfs`、强推 main、fork bomb 等)
- **流式输出:** LLM 响应逐 chunk 流式输出(text + thinking reasoning),Web 和 CLI 都支持
- **即时中断:** cancel 信号贯穿全链路 —— 前端 stop 立刻反馈,后端真关 HTTP 连接,Bash 执行中 kill shell + 重启,延迟 ms 级
- **工具确认:** Web 端 Edit/Write 改文件前弹卡片;CLI 端 y/n 确认
- **权限模型:** 首次访问新目录问用户批准,批准后该目录树放行
- **TodoWrite 任务追踪:** LLM 判断任务复杂(3+ 步)时主动拆 todo,前端顶部 sticky 区渲染进度,resume 时从 jsonl 重建

### Skill 系统(渐进披露)

- `SKILL.md` 目录格式,frontmatter 定义 `name` / `description` / `when_to_use` / `allowed_tools`
- **三源加载:** `project > user > system`
  - `project`: `<repo>/.taisang/skills/`
  - `user`: `~/.taisang/skills/`
  - `system`: 包内内置 `commit` 和 `review`
- 启动时全量读入,SYSTEM_PROMPT 只注入轻量清单(每条 ≤250 字符,超限降级)
- **前端管理页:** `/skills` 页支持表格、启用开关、重载、导入(MD / zip)、删除

### 多 Agent 调度 (M3)

- `Agent({subagent_type, prompt, run_in_background})` 派子 agent
- **4 内置 agent:** `general-purpose` / `explore`(只读) / `plan`(只读) / `verification`(对抗,默认 async)
- **两种模式:** 传 `subagent_type` 走 A(全新上下文),省略走 B(fork 父 messages 继承对话)
- sync + async 执行,async 后台跑完注入主循环
- `AGENT.md` 目录格式,三源加载,前端 `/agents` 管理页
- 递归防护:子 agent 物理不注册 `AgentTool` + `is_fork_child` flag 阻止 fork-in-fork

### MCP 客户端

- 接入第三方 MCP server,把其 tool / resource / prompt 注入 agent 工具体系
- **两种 transport:** `stdio`(本地子进程)+ `sse`(HTTP+SSE)
- 每个 MCP tool 注册成 `mcp__<server>__<tool>`,LLM 调用走 `manager.call_tool()`
- **前端 `/mcp` 管理页:** 增删改、启用/禁用、重连、三种快速添加(CLI 一行 / JSON 文本 / 文件上传,兼容 claude-code `mcpServers` 格式)

### 个性化

- **用户画像:** 单栏 markdown,`### 技术栈 / 代码风格 / 沟通 / 环境 / 禁忌` 分段,agent 对话中发现偏好时自动更新
- **零额外废 cache:** 画像更新不碰当前 session,只在 autocompact 和新 session 时注入
- **变更历史:** `~/.taisang/profile_history.jsonl` 存最近 5 条,前端可回滚
- **前端 `/profile` 管理页:** 整篇编辑 + 恢复默认 + 回滚 + 变更历史

### Prompt 管理

- 4 份核心 prompt 前端可视化编辑,持久化到 `~/.taisang/settings.json`:
  - `system_prompt` / `autocompact_prompt` / `session_memory_template` / `session_memory_update_prompt`
- 可切回默认,`system_prompt` 变更后广播到所有活跃 session 即时生效
- **前端 `/prompts` 管理页**

### Web UI / CLI

- **Web UI** (Vue 3.5 + Vite + TDesign):多会话列表 / 中对话流 / 底一体式输入框(Claude 风格),Markdown 渲染 + 代码高亮 + 工具卡片可折叠,SSE 实时事件流
- **CLI** (`taisang chat`):REPL 交互,`/exit` / `/reset` / `/debug`

### 可观测性

- **token 用量:** 每轮 + session 累计
- **/debug 模式:** 打印发给 LLM 的完整 messages + 响应 + 工具完整 observation
- **15 种 AgentEvent:** CLI 和 Web UI 共用同一套渲染逻辑

---

## 🗺️ 后续计划

按需求强度排序:

**高频**
- **Slash Commands:** `/commit`、`/review` 等斜杠命令(曾实现后 revert,待重做)
- **多 skill 批量导入:** importer 现在一个 zip 一个 skill,扩展后可一次导入 N 个
- **Hooks:** PreToolUse / PostToolUse / SessionStart 等钩子
- **Plugin 清单 + marketplace:** `plugin.json` 解析 + 插件市场

**Skill 增强**
- 运行时 SKILL.md 修改生效(目前需新开会话)
- frontmatter 高级字段(`version` / `model` / `context:fork` / `agent` / `paths` / `argument-hint`)
- fork 执行模式:把 skill 放到子 agent 里跑

**Web UI**
- 暗色主题 / 主题切换
- 移动端适配
- 断线自动重连(EventSource 断了不会自动续)

**Agent 行为**
- 图片 / 多模态输入(目前只支持文本)
- Resume 中断的会话(进程死了会话就死;todos 已支持 resume)

**工程**
- 国际化:UI 文本写死中文

---

## 🙏 致谢

感谢 Claude Code 和 Trae 带来的设计灵感,感谢 MCP 协议让工具生态可以互通。

如果 TaiSang 对你有帮助,欢迎 ⭐ Star 支持一下!

[github.com/zht475706171/TaiSang](https://github.com/zht475706171/TaiSang)

---

## License

MIT