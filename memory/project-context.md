# Code Reader Agent 项目上下文

> 跨 session 共享的项目理解。下次开 session 先读这份 + 设计文档，立刻接续。
> 项目原名 Repo Onboarding Agent，2026-08-21 改名为 Code Reader Agent。

## 一句话项目定位

把 Claude Code + 手写 CLAUDE.md 的高手玩法**自动化、结构化、团队化、产品化**——3 分钟自动建索引 vs 手写半个月、结构化调用图查询 vs 自然语言笔记推理、团队共享 vs 个人笔记、可评测 vs 体感。

## 项目元信息

- **路径**：`D:/GoProject/Repo-Onboarding-Agent/`（目录名暂不改,内部代码/包名用 code-reader）
- **License**：MIT
- **技术栈**：Python（后端）+ FastAPI（Web 后端）+ 前端用 frontend-design skill 设计
- **支持语言（v1）**：Python / JS / TS / Java / Go（5 门）
- **时间投入**：业余 2-3 个月
- **首发渠道**：开发者社区引流（开源免费）
- **目标用户**：开发者（开源社区引流来的）
- **商业目标**：v1 上线 + 几个真实用户（不追营收）
- **pip 包名**：`code-reader`
- **CLI 命令**：`code-reader <subcommand>`
- **配置目录**：`~/.code-reader/`

## 前传故事（面试叙事核心）

泰哥先用 Claude Code + 手写笔记（CLAUDE.md + INDEX.md + notes.md）花半个月读完 Claude Code 51 万行 TypeScript 源码，项目在 `D:/GoProject/claude-learn/`。读完后把这套高手玩法做成 Agent 工具——让普通人 3 分钟 onboard 陌生 repo。

## 架构三层

1. **接入层**：CLI + 极简 Web（共享 agent_core）
2. **Agent 内核**：从 claude-code 抽的核心循环（plan→act→observe→reflect）+ 5 工具（read_file/grep/glob/trace_call_chain/lookup_map）+ 上下文预算管理
3. **索引层**：tree-sitter 多语言解析 + 跨文件 linker + 三层摘要 + Chroma 向量库 + BM25 + SQLite

## LLM 接入（关键架构决策 2026-08-21）

**不绑死任何模型厂商**,支持用户自带任意 OpenAI 兼容 endpoint:
- 配置 `base_url` + `api_key` + `model_name`,agent_core 用这个调
- 兼容 OpenAI / DeepSeek / 通义千问 / Moonshot / 本地 Ollama / 自部署 vLLM 等
- 配置在 `~/.code-reader/settings.json` 或环境变量 `CODE_READER_LLM_*`
- 推荐组合:摘要用便宜模型(DeepSeek-V3),Agent 循环用强模型(Claude/GPT-4),可分别配置

## 6 个核心组件

1. `indexer` —— 抓取 + tree-sitter 解析 + 跨文件调用图（best-effort，弱类型 Agent 用 grep 兜底）
2. `summarizer` —— 三层摘要（文件 100 字 / 模块 300 字 / 全局 1000 字）+ prompt caching
3. `retriever` —— 向量 + BM25 混合 + 分层检索（global→module→file）
4. `agent_core` —— Agent 循环（项目心脏）+ 5 工具 + token 32K 预算 + compaction
5. `evaluator` —— 10 题 eval set + 3 套 baseline + Claude LLM-as-judge，**面试杀手锏**
6. `cli` + `web` —— 双入口

## 关键设计决策（防止下次 session 又问一遍）

- **eval set v1 = 10 题**（单文件3/跨文件4/多跳3），多跳 3 题必须用大 repo >20 万行作为杀手锏
- **大 repo 杀手锏题 → kubernetes**（Go，>20 万行，同时验证 Go AST 交叉验证）
- **TS 评测 repo → nest**（NestJS，中大型 TS 项目）
- **Python 评测 repo → fastapi**（已定）
- **三类落盘文件职责分离**：trace（默认开+7天/100MB清理）/ session state（--resume/--continue）/ memory（v1.5）
- **并发锁 v1 只做 URL hash 一级**，content hash 兜底 v1.5
- **LLM 摘要失败 → 跳过文件 + 记 index_errors + Agent 自决 read_file 兜底**
- **indexer 准确率验证**：Python 用 ast、Go 用 go/ast 交叉验证（白嫖准）；JS/TS/Java v1 人工标 50 ground truth
- **核心模块 v1 不接外部 PR**：agent_core / indexer / summarizer
- **Web demo 用户自带 LLM API key**（省 token 钱,与 CLI 共享配置）
- **Web 前端开发流程**：实现阶段调用 `superpowers:frontend-design` skill 设计前端页面
- **LLM mock 工具**：v1 自研轻量 MockLLM 类（约 50 行,按调用顺序返回预设响应）,不引外部库

## 进度

| 阶段 | 状态 |
|------|------|
| brainstorming | ✅ 完成 |
| 设计文档落盘（v1） | ✅ 完成（commit 3755c52，527 行）|
| 跨 session 记忆 | ✅ 完成（commit 787c396）|
| 改名 + 5 处澄清 + §7 全部澄清 | ✅ 完成（2026-08-21）|
| 用户 review 设计文档 | ✅ 完成 |
| writing-plans Plan 1 | ✅ 完成（docs/superpowers/plans/2026-08-21-plan-1-python-mvp.md）|
| Plan 1 实现 | ✅ 完成（19 个 task 全部实现,94 个测试通过,端到端闭环验证）|
| Plan 2-6 | ⏳ 待启动 |

## Plan 1 实现总结

- 19 个 task 全部完成（Task 1 项目骨架 → Task 19 README 收尾）
- 94 个测试全绿（单元 + 集成 + 端到端）
- 全链路验证:Fetcher → Parser → Linker → Summarizer → Storage → IndexerService → CLI → AgentService → TraceCallChainTool
- 技术债记录在 `memory/lessons-learned.md`（按 task 累积,高优项标注"必处理"）
- 已知简化:retriever BM25-only（向量库留 v1.5）、MockLLM 测试（真 LLM 留手动验证）、无 session/trace 落盘（留 Plan 4）

## 下一步

- Plan 1 收尾提交（README + project-context 进度更新）
- 可选:启动 Plan 2（多语言扩展）、Plan 3（评测体系）、或先处理 lessons-learned 里的高优技术债（Task 5/14/16 健壮性 + Task 14 安全加固）

## 相关文件

- 设计文档：`docs/superpowers/specs/2026-08-20-repo-onboarding-agent-design.md`（文件名保留原命名以保留历史）
- 今日日志：`memory/2026-08-20.md`（brainstorming 全过程）
- 本文件：`memory/project-context.md`
- 前传项目：`D:/GoProject/claude-learn/`（参考其笔记结构和 CLAUDE.md 模式）