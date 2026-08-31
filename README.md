# Code Reader Agent

> 简化版 Claude Code / Trae —— 一个能读写、修改、调试代码的交互式 coding agent。

**当前状态:v0.1(重构后首版,交互式 REPL)**

## Quick Start

```bash
# 安装(开发模式)
pip install -e ".[dev]"

# 配置 LLM(支持任意 OpenAI 兼容 endpoint)
export CODE_READER_LLM_BASE_URL=https://api.deepseek.com
export CODE_READER_LLM_API_KEY=sk-xxx
export CODE_READER_LLM_MODEL=deepseek-chat

# cd 到你要操作的 repo
cd ~/repos/my-project

# 进 REPL
code-reader chat
# 或指定 repo
code-reader chat --repo ~/repos/my-project
```

REPL 里：
- 输入自然语言目标,agent 调工具查/改/跑代码
- `/exit` 退出,`/reset` 清上下文
- Edit/Write 改文件前会弹 y/n 确认
- Bash 只跑白名单命令(git/python/pytest/ruff/black/ls/cat 等),限定当前目录

## 工具集

| 工具 | 作用 |
|------|------|
| Read | 读文件 |
| Edit | old_string → new_string 改文件(用户确认) |
| Write | 创建/覆盖文件(用户确认) |
| Grep | 正则搜 |
| Glob | 文件名匹配 |
| Bash | 跑 shell 命令(白名单 + cwd 限定) |

## 上下文管理(长对话三道机制)

1. **apply-tool-result-budget**:单轮 tool_result 总字节超预算时,最大的几条持久化到磁盘,原 content 替换成 preview 占位符
2. **autocompact**:对话 token 逼近预算时,旁路 LLM 生成 7 项摘要替换整个 messages
3. **session memory**:平时异步维护 10 章节笔记,autocompact 触发时零 LLM 调用读笔记注入主 prompt

## 测试

```bash
pytest tests/ -q       # 140 passed
ruff check src/ tests/ # 全绿
black --check src/ tests/ # 全绿
```

## License

MIT