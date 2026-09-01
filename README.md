# TaiSang

> 简化版 Claude Code / Trae —— 一个能读写、修改、调试代码的交互式 coding agent。

**当前状态:v0.1(重构后首版,REPL + Web UI 双入口)**

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
- Bash 只跑白名单命令(git/python/pytest/ruff/black/ls/cat 等),限定当前目录

### Web UI(`taisang web`)
- 豆包风格:左会话列表 / 中对话流 / 底输入框
- Markdown 渲染 + 代码高亮 + 工具卡片可折叠
- 多会话隔离,会话标题从首条消息自动生成
- 异步文件确认(改文件时弹卡片,允许/拒绝)
- `/reset` `/debug` 按钮,token 用量底部小字
- 原生 JS + SSE,无前端构建工具

## 工具集

| 工具 | 作用 | 上限 |
|------|------|------|
| Read | 读文件(支持 offset/limit 分页) | 32KB 字节闸门 |
| Grep | 正则搜 | 200 命中 + 500 字符长行跳过 |
| Glob | 文件名匹配 | 100 硬切 |
| Edit | old_string → new_string 改文件(用户确认) | — |
| Write | 创建/覆盖文件(用户确认) | — |
| Bash | 跑 shell 命令(白名单 + cwd 限定) | 30000 字符 + 超长落盘 |

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
pytest tests/ -q       # 124 passed
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