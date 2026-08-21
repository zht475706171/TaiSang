# Code Reader Agent

> 3 分钟让陌生代码库变成可问答、可追踪调用链、可生成 onboarding 文档。

**当前状态:v0.1 开发中(Plan 1: Python-only MVP 闭环)**

## Quick Start

```bash
# 安装(开发模式)
pip install -e ".[dev]"

# 配置 LLM(支持任意 OpenAI 兼容 endpoint)
export CODE_READER_LLM_BASE_URL=https://api.deepseek.com
export CODE_READER_LLM_API_KEY=sk-xxx
export CODE_READER_LLM_MODEL=deepseek-chat

# 先 clone 到本地(v1 不支持远程 clone)
git clone https://github.com/tiangolo/fastapi ~/repos/fastapi

# 建索引(产物落 ~/repos/fastapi/.code-reader/)
code-reader index ~/repos/fastapi

# 问问题
code-reader ask "FastAPI 的路由是怎么注册的" --repo ~/repos/fastapi
```

## 跟 Claude Code / Cursor 的区别

| 维度 | Claude Code + 手写 CLAUDE.md | Code Reader Agent |
|------|------------------------------|-------------------|
| 建索引成本 | 手写半个月 | 自动 3 分钟 |
| 知识形态 | 自然语言笔记 | 结构化 AST + 调用图 |
| 使用门槛 | 高手才能写好 INDEX | 丢 URL 即可 |
| 团队复用 | 个人笔记 | 索引建一次,N 人共享 |
| 可量化 | 体感 | eval set + baseline |
| 调用链追踪 | O(N) 次 LLM 推理 | O(1) 次图查询 |

## 开发路线

- **Plan 1(v0.1,进行中)**:Python-only MVP 闭环
- Plan 2:多语言扩展(JS/TS/Java/Go)
- Plan 3:评测体系(10 题 eval set + baseline)
- Plan 4:session/trace/增量完善
- Plan 5:Web 端(FastAPI + frontend-design)
- Plan 6:开源化(README 完整 + 引流)

详见 `docs/superpowers/specs/2026-08-20-repo-onboarding-agent-design.md`。

## License

MIT