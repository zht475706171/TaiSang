# Repo Onboarding Agent 项目上下文

> 跨 session 共享的项目理解。下次开 session 先读这份 + 设计文档，立刻接续。

## 一句话项目定位

把 Claude Code + 手写 CLAUDE.md 的高手玩法**自动化、结构化、团队化、产品化**——3 分钟自动建索引 vs 手写半个月、结构化调用图查询 vs 自然语言笔记推理、团队共享 vs 个人笔记、可评测 vs 体感。

## 项目元信息

- **路径**：`D:/GoProject/Repo-Onboarding-Agent/`
- **License**：MIT
- **技术栈**：Python
- **支持语言（v1）**：Python / JS / TS / Java / Go（5 门）
- **时间投入**：业余 2-3 个月
- **首发渠道**：开发者社区引流（开源免费）
- **目标用户**：开发者（开源社区引流来的）
- **商业目标**：v1 上线 + 几个真实用户（不追营收）

## 前传故事（面试叙事核心）

泰哥先用 Claude Code + 手写笔记（CLAUDE.md + INDEX.md + notes.md）花半个月读完 Claude Code 51 万行 TypeScript 源码，项目在 `D:/GoProject/claude-learn/`。读完后把这套高手玩法做成 Agent 工具——让普通人 3 分钟 onboard 陌生 repo。

## 架构三层

1. **接入层**：CLI + 极简 Web（共享 agent_core）
2. **Agent 内核**：从 claude-code 抽的核心循环（plan→act→observe→reflect）+ 5 工具（read_file/grep/glob/trace_call_chain/lookup_map）+ 上下文预算管理
3. **索引层**：tree-sitter 多语言解析 + 跨文件 linker + 三层摘要 + Chroma 向量库 + BM25 + SQLite

## 6 个核心组件

1. `indexer` —— 抓取 + tree-sitter 解析 + 跨文件调用图（best-effort，弱类型 Agent 用 grep 兜底）
2. `summarizer` —— 三层摘要（文件 100 字 / 模块 300 字 / 全局 1000 字）+ prompt caching
3. `retriever` —— 向量 + BM25 混合 + 分层检索（global→module→file）
4. `agent_core` —— Agent 循环（项目心脏）+ 5 工具 + token 32K 预算 + compaction
5. `evaluator` —— 10 题 eval set + 3 套 baseline + Claude LLM-as-judge，**面试杀手锏**
6. `cli` + `web` —— 双入口

## 关键设计决策（防止下次 session 又问一遍）

- **eval set v1 = 10 题**（单文件3/跨文件4/多跳3），多跳 3 题必须用大 repo >20 万行作为杀手锏
- **三类落盘文件职责分离**：trace（默认开+7天/100MB清理）/ session state（--resume/--continue）/ memory（v1.5）
- **并发锁 v1 只做 URL hash 一级**，content hash 兜底 v1.5
- **LLM 摘要失败 → 跳过文件 + 记 index_errors + Agent 自决 read_file 兜底**
- **indexer 准确率验证**：Python 用 ast、Go 用 go/ast 交叉验证（白嫖准）；JS/TS/Java v1 人工标 50 ground truth
- **核心模块 v1 不接外部 PR**：agent_core / indexer / summarizer
- **Web demo 用户自带 API key**（省 token 钱）

## 进度

| 阶段 | 状态 |
|------|------|
| brainstorming | ✅ 完成 |
| 设计文档落盘 | ✅ 完成（commit 3755c52，527 行）|
| 用户 review 设计文档 | ⏳ 等待中 |
| writing-plans 出实现计划 | ⏳ 待启动 |
| 实现 | ⏳ 未开始 |

## 下一步

调用 writing-plans 技能，基于设计文档出详细实现计划。

## 相关文件

- 设计文档：`docs/superpowers/specs/2026-08-20-repo-onboarding-agent-design.md`
- 今日日志：`memory/2026-08-20.md`
- 本文件：`memory/project-context.md`
- 前传项目：`D:/GoProject/claude-learn/`（参考其笔记结构和 CLAUDE.md 模式）