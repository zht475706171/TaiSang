<p align="center">
  <h1 align="center">🤖 TaiSang</h1>
</p>

<p align="center">
  <b>简体中文</b> | <a href="./README_EN.md">English</a>
</p>

> **私人 agent · 总结习惯**
>
> 一个会总结你习惯的私人 AI agent —— 读写代码、跑命令、调工具,同时学习你的偏好与工作流。

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

## ✨ 功能概览

### Agent 核心

- **主循环:** LLM ⇄ 6 工具循环直到产出最终答案
- **流式输出:** LLM 响应逐 chunk 流式输出(text + thinking reasoning),Web 和 CLI 都支持
- **即时中断:** cancel 信号贯穿全链路,前端 stop 立刻反馈,后端真关 HTTP 连接 + kill shell,延迟 ms 级
- **消息队列:** turn 在跑时新消息排队,跑完自动 drain,不丢消息
- **工具确认:** Web 端 Edit/Write 改文件前弹卡片;CLI 端 y/n 确认
- **免确认模式:** 全局 skip_permissions 开关,开启后跳过所有确认/权限/危险命令拦截
- **权限模型:** 首次访问新目录问用户批准,批准后该目录树放行
- **持久 shell:** Bash `cd` 跨调用保留;危险命令黑名单拦截
- **TodoWrite 任务追踪:** LLM 判断任务复杂(3+ 步)时主动拆 todo,前端顶部 sticky 区渲染进度

### Skill 系统(渐进披露)

- `SKILL.md` 目录格式,frontmatter 定义 `name` / `description` / `when_to_use` / `allowed_tools`
- **三源加载:** `project > user > system`,启动时全量读入,SYSTEM_PROMPT 只注入轻量清单
- **前端管理页:** 表格、启用开关、导入(MD / zip)、删除
- **Plugin 安装:** 输入 GitHub 仓库地址,git clone 后自动识别 `skills/` 目录或单 skill 形态,批量导入;支持卸载和已安装列表

### 多 Agent 调度

- `Agent({subagent_type, prompt, run_in_background})` 派子 agent
- **4 内置 agent:** `general-purpose` / `explore`(只读) / `plan`(只读) / `verification`(对抗)
- **两种模式:** 传 `subagent_type` 走全新上下文,省略则 fork 父对话继承
- sync + async 执行,async 后台跑完注入主循环
- **SubAgent 独立 LLM 配置:** 子 agent 可用不同 model / api_key / base_url
- `AGENT.md` 目录格式,三源加载,前端 `/agents` 管理页

### MCP 客户端

- 接入第三方 MCP server,把其 tool / resource / prompt 注入 agent 工具体系
- **两种 transport:** `stdio`(本地子进程)+ `sse`(HTTP+SSE)
- **前端 `/mcp` 管理页:** 增删改、启用/禁用、重连,三种快速添加(CLI 一行 / JSON 文本 / 文件上传)

### 个性化

- **用户画像:** 自动学习你的技术栈 / 代码风格 / 沟通习惯 / 环境偏好 / 禁忌,跨会话生效
- **变更历史:** 存最近 5 条,前端可回滚
- **前端 `/profile` 管理页:** 整篇编辑 + 恢复默认 + 回滚

### Prompt 管理

- 4 份核心 prompt 前端可视化编辑,持久化到 settings.json
- 可切回默认,`system_prompt` 变更后广播到所有活跃 session 即时生效
- **前端 `/prompts` 管理页**

### Web UI / CLI

- **Web UI** (Vue 3.5 + Vite + TDesign):多会话列表 / 对话流 / 一体式输入框(Claude 风格),Markdown 渲染 + 代码高亮 + 工具卡片可折叠,SSE 实时事件流
- **CLI** (`taisang chat`):REPL 交互,`/exit` / `/reset` / `/debug`
- **模型配置:** model_context_window 映射表,按模型名设定上下文窗口大小

### 可观测性

- **token 用量:** 每轮 + session 累计
- **/debug 模式:** 打印发给 LLM 的完整 messages + 响应 + 工具完整 observation

---

## 🗺️ 后续计划

**高频**
- **Slash Commands:** `/commit`、`/review` 等斜杠命令
- **Hooks:** PreToolUse / PostToolUse / SessionStart 等钩子
- **Plugin marketplace:** `marketplace.json` 浏览 + 一键安装

**Skill 增强**
- 运行时 SKILL.md 修改生效(目前需新开会话)
- frontmatter 高级字段(`version` / `model` / `context:fork` / `agent` / `paths`)
- fork 执行模式:把 skill 放到子 agent 里跑

**Web UI**
- 暗色主题 / 主题切换
- 移动端适配
- 断线自动重连

**Agent 行为**
- 图片 / 多模态输入

**工程**
- 国际化:UI 文本写死中文

---

## 🙏 致谢

感谢 Claude Code 和 Trae 带来的设计灵感,感谢 MCP 协议让工具生态可以互通。

如果 TaiSang 对你有帮助,欢迎 ⭐ Star 支持一下!

[github.com/zht475706171/TaiSang](https://github.com/zht475706171/TaiSang)

---

## 🛠️ 故障排查

### 装不上 / `pip install` 报错

- **Python 版本:** 需要 3.11+,跑 `python --version` 确认
- **权限问题:** Windows 不要装到 `C:\Program Files`,用 `pip install --user -e .` 或 venv
- **网络慢:** 国内可加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- **uv 同步:** 用 uv 的话 `uv sync --extra web --extra dev`

### 启动报 `port already in use`(端口被占)

默认端口 `7392`。两种解法:

```bash
# 方式一:换端口
taisang web --port 8000

# 方式二:找出占用进程关掉
# Windows
netstat -ano | findstr :7392
taskkill /PID <PID> /F
# Linux/Mac
lsof -i :7392
kill -9 <PID>
```

### LLM 连不上 / 响应 401 / 超时

- **api_key 错:** Web UI 右上角 ⚙️ 重新填,或检查 `~/.taisang/settings.json`
- **base_url 末尾:** 不要带 `/v1`,TaiSang 会自己拼(`/v1/chat/completions`)
- **模型名拼错:** DeepSeek 用 `deepseek-chat` / `deepseek-reasoner`,Kimi 用 `moonshot-v1-8k` 等
- **本地 ollama:** `base_url=http://localhost:11434`,model 填 ollama 拉下来的 tag
- **代理问题:** 公司网络下设置 `HTTPS_PROXY` 环境变量

### MCP server 启动失败

- **stdio 类型:** 检查 `command` 在 PATH 里(跑 `which <cmd>` / `where <cmd>`)
- **sse 类型:** URL 要包含完整路径(如 `https://xxx/sse`),不是只给 host
- **看日志:** MCP 启动错误会落到 `~/.taisang/logs/taisang.log`,grep `MCP` 看详情
- **重连:** Web UI `/mcp` 页点「重连」按钮,不用重启服务

### settings.json 损坏

启动时会弹 warning 带文件路径 + 行号。两种修法:

- **手动改:** 按行号修 JSON 语法错误
- **删掉重来:** 删 `~/.taisang/settings.json`,重启会生成默认配置

### session 数据丢失 / resume 失败

- **断电保护:** conversation.jsonl 每次 append 都 fsync,断电不丢已完成 turn
- **session 列表空:** 检查 `~/.taisang/sessions/` 目录,每个 session 一个子目录
- **超 50 条被删:** 默认上限 50,超过会自动删最早的;想保留更多在 settings.json 设 `"max_sessions": 100`

### 报 bug 要附什么

报 bug 时请附上 **trace_id** + **log 片段**,一秒还原现场:

1. **trace_id:** Web UI 出现 run_error 卡片时,点「复制 trace_id」按钮
2. **log:** 把 trace_id 贴给开发者,开发者跑:
   ```bash
   grep <trace_id> ~/.taisang/logs/taisang.log
   ```
   一秒看到整个 turn:哪个 turn 开始、调了哪些 LLM(model/mode/step/duration)、调了哪些工具(tool_name/duration)、哪一步失败
3. **复现步骤:** 越细越好(用什么 model、输入什么、点了什么按钮)

log 位置:
- Windows: `C:\Users\<你>\.taisang\logs\taisang.log`(rotating 10MB×5)
- Linux/Mac: `~/.taisang/logs/taisang.log`

---

## License

MIT