# Code Reader Agent 设计文档

- **创建日期**：2026-08-20
- **最后更新**：2026-08-21（改名 + §7 待决问题全部澄清）
- **状态**：设计阶段（待 review）
- **目标版本**：v1 MVP
- **License**：MIT
- **作者**：泰哥

> **改名说明**：项目原名 "Repo Onboarding Agent"，2026-08-21 改名为 "Code Reader Agent"。设计文档文件名保留原命名以保留历史,内容统一用新名。

---

## 0. 项目定位（一句话 + 故事）

> Claude Code + 手写 CLAUDE.md 是个人高手读大 repo 的方案；Code Reader Agent 把这套高手玩法**自动化、结构化、团队化、产品化**——3 分钟自动建索引 vs 手写半个月、结构化调用图查询 vs 自然语言笔记推理、团队共享 vs 个人笔记、可评测 vs 体感。

### 前传故事（面试叙事核心）

作者先用 Claude Code + 手写笔记（CLAUDE.md + INDEX.md + 各目录 notes.md）的方式，花半个月读完 Claude Code 自己 51 万行 TypeScript 源码（见 `D:/GoProject/claude-learn/`）。读完后发现这套高手玩法可以自动化，于是做了这个工具——让普通人 3 分钟就能 onboard 一个陌生 repo。

### 四大差异化（扛住"Claude Code + 好 prompt 不就行了"的追问）

| 维度 | Claude Code + 手写 CLAUDE.md | Code Reader Agent |
|------|------------------------------|------------------------|
| 建索引成本 | 人类高手手写，单 repo 半个月 | Agent 自动建，3 分钟 |
| 知识形态 | 自然语言笔记（LLM 读） | 结构化 AST + 调用图（程序查） |
| 使用门槛 | 高手才能写好 INDEX/notes | 普通开发者丢个 URL 即可 |
| 团队复用 | 个人笔记，分享是 markdown | 索引建一次，团队 N 人共享 |
| 可量化 | 全凭体感 | eval set + baseline ablation |
| 调用链追踪 | O(N) 次 LLM 调用、可能中断 | O(1) 次图查询、确定性 |

---

## 1. 架构总览

### 一句话定位

丢一个 GitHub repo URL 进去，Agent 花 1-3 分钟构建"代码库地图"，然后能用自然语言问"支付模块怎么工作"这类问题，它跨文件追踪调用链、带源码引用回答；还能产出可分享的 onboarding 文档。

### LLM 接入说明（关键架构决策）

项目本身**不绑死任何模型厂商**，支持用户自带任意 **OpenAI 兼容 endpoint**：
- 用户配置 `base_url` + `api_key` + `model_name`，agent_core 用这个调
- 兼容 OpenAI / DeepSeek / 通义千问 / Moonshot / 本地 Ollama / 自部署 vLLM 等
- 配置项在 `~/.code-reader/settings.json` 或环境变量 `CODE_READER_LLM_*`
- 推荐组合：索引摘要用便宜模型（如 DeepSeek-V3），Agent 循环用强模型（如 Claude / GPT-4），用户可分别配置

### 三层架构

```
┌─────────────────────────────────────────────────────┐
│  接入层 (CLI + Web)                                  │
│  - CLI: 本地用,丢 repo URL 即可                       │
│  - Web: 给社区用户用,输入 URL 在线问答                │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│  Agent 内核  (从 claude-code 抽出来的核心循环)        │
│  - 主循环: plan → act → observe → reflect            │
│  - Prompt 模板系统 (system / user / tool 三层)        │
│  - 工具注册表 + schema 自动生成                       │
│  - 上下文预算管理 (token budget + compaction)        │
│  - Prompt caching breakpoint 设计                    │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│  索引层  (Repo → 代码库地图)                          │
│  - 抓取: git clone / GitHub API                      │
│  - 解析: tree-sitter 抽 AST → 符号/调用/依赖          │
│  - 摘要: LLM 分层摘要 (文件级 / 模块级 / 全局级)       │
│  - 索引: 向量库 (Chroma) + BM25 混合                  │
│  - 持久化: SQLite 存地图,文件指纹做增量更新           │
└─────────────────────────────────────────────────────┘
```

### 两个核心循环

1. **离线循环（索引时）**：repo → 抓取 → AST 解析 → 跨文件 linker → 分层摘要 → 入库。慢但只跑一次，repo 变了做增量。
2. **在线循环（问答时）**：用户问题 → 查地图 + 检索 → Agent 决定要不要 deep dive（调 read/grep/trace 工具）→ 带引用回答。

### MVP 边界（v1 必做）

- CLI + 极简 Web 双入口，共享同一套 agent_core
- 支持 5 门语言：Python / JS / TS / Java / Go
- 单 repo 输入，不做多 repo 关联
- 本地 SQLite + 本地向量库（Chroma），不依赖云
- eval set v1 = 10 题

### MVP 不做（YAGNI）

- 实时协作 / 团队共享地图（v2 再说）
- 私有 repo 鉴权复杂逻辑（v1 先支持公开 repo，私有 repo 走 GitHub token）
- IDE 插件（先做 CLI + Web，口碑起来再做插件）
- 自训练模型 / 微调
- content hash 二级并发锁（v1.5）
- 跨 session 长期记忆 memory（v1.5）

---

## 2. 核心组件

按职责拆成 6 个独立可测的组件，每个都有清晰边界。

### 2.1 indexer —— Repo 抓取与解析

**职责**：输入 repo URL → 输出结构化 AST 数据。

- `fetcher`：git clone 或 GitHub API 拉源码，存到本地缓存目录
- `parser`：基于 **tree-sitter** 的多语言 AST 解析器，每门语言一个 adapter
  - 抽取：符号（函数/类/方法）、签名、调用关系、import 依赖
- `linker`：跨文件符号表 join，建全局调用图（best-effort，弱类型语言有噪声）
- `fingerprint`：按文件内容 hash 做增量——只重新解析变动的文件
- **输出 schema**：`Symbol { id, kind, name, file, line_range, calls: [SymbolId], imports: [SymbolId] }`

**接口**：`indexer.build(repo_url) -> RepoIndex`，`indexer.update(repo_url) -> RepoIndex`（增量）

**依赖**：tree-sitter、gitpython、磁盘缓存

### 2.2 summarizer —— 分层摘要

**职责**：把 AST 数据压成 LLM 可用的"代码库地图"。

- **三层摘要**（从 claude-code 分层思想抽出）：
  - **文件级**：每个文件 100 字，说"它干啥"
  - **模块级**：同目录/同包的文件摘要聚合，300 字
  - **全局级**：入口、核心模块、依赖关系，1000 字
- **预算控制**：每层有 token 上限，超了就再压
- **缓存**：摘要按文件 hash 缓存，没变不重算
- **Prompt caching**：摘要的 system prompt 固定，命中缓存省钱

**接口**：`summarizer.summarize(repo_index) -> RepoMap`

### 2.3 retriever —— 混合检索

**职责**：问题来了，从地图里捞相关片段。

- **向量检索**：Chroma（本地、零运维），embedding 用 bge-small（开源、快）
- **BM25 检索**：rank-bm25，关键词召回
- **混合排序**：加权融合 + 可选 reranker（bge-reranker-base 本地跑）
- **分层检索**：先查全局级定位模块 → 再查模块级定位文件 → 再查文件级定位符号

**接口**：`retriever.search(query, layer) -> List[Snippet]`

### 2.4 agent_core —— Agent 循环（项目的心脏）

**职责**：从 claude-code 抽出来的核心循环，负责"决定下一步干啥"。

```
while not done and budget_remaining:
    plan = llm.plan(user_query, current_context, available_tools)
    if plan.needs_more_info:
        tool_call = pick_tool(plan)        # read_file / grep / glob / trace_call_chain / lookup_map
        observation = execute(tool_call)
        context.append(observation)
        if context_near_limit:
            context = compact(context)     # 上下文压缩
    else:
        answer = llm.synthesize(context, with_citations=True)
        done = True
```

- **工具集**（MVP 五个）：
  - `read_file(path)` — 读指定文件
  - `grep(pattern, scope)` — 正则搜
  - `glob(pattern)` — 文件名匹配
  - `trace_call_chain(symbol_id, depth)` — **差异化杀手锏**，调它返回 N 跳调用链（best-effort，弱类型语言无结果时 Agent 用 grep 兜底）
  - `lookup_map(layer, query)` — 查代码库地图
- **终止条件**：max_steps / max_tokens / 已有足够引用 / Agent 自判完成
- **上下文管理**（从 claude-code 抄）：
  - token 预算 32K（留余量给输出）
  - 逼近上限触发 compaction：保留 system + 最早摘要 + 最近 N 轮 + 引用源码
  - prompt caching breakpoint 在 system prompt + 代码库地图末尾

**接口**：`agent.run(query, repo_map) -> Answer`

### 2.5 evaluator —— 评测集（差异化的"证据"）

**职责**：量化"我们比 Claude/Cursor 强在哪"。没有它，叙事就是空话。

- **eval set v1（10 题）**：
  - 单文件问题（3 题）—— baseline 也能答好
  - 跨文件问题（4 题）—— 考检索
  - 多跳调用链问题（3 题）—— **Agent 主场，杀手锏题**，必须用大 repo（> 20 万行开源项目子模块）
- **baseline 三套**：
  1. Claude 裸答（不喂 repo，看它盲猜）
  2. Claude + 全 repo 塞上下文（看上下文塞得下的情况下它多强）
  3. 简单 RAG（向量检索 + 直接答，无 Agent 循环）
- **评测 repo**：v1 选 2 个（fastapi + 一个 TS repo），同一套 10 题跑
- **judge**：LLM-as-judge，用 Claude 当裁判，rubric 打分 0-5；人工抽检 30% 校准
- **指标**：
  - 答案准确率（LLM judge + 人工抽检）
  - 引用准确率（引用的文件行号对得上 ground truth 的比例）
  - 调用链完整率（多跳题追到的真实链长度 / 应有链长度）
- **输出**：一份 ablation 表格，行是三类问题，列是四种方法，格子里是分数——**面试杀手锏**
- **自动化**：`code-reader eval run --suite v1 --repo fastapi` 一条命令跑完，产出 HTML 报告

### 2.6 cli + web —— 入口

**CLI 命令**：
- `code-reader index <repo_url>` —— 建索引
- `code-reader ask "<question>"` —— 问问题
- `code-reader doc` —— 生成 onboarding 文档
- `code-reader eval <suite>` —— 跑评测
- `code-reader traces list/clean/export` —— trace 管理
- `code-reader ask --resume <session_id>` / `--continue` —— 恢复上次对话

**Web 端**：FastAPI 后端 + 前端页面（开发时使用 `frontend-design` skill 设计），输入 repo URL + 问题，在线问答。MVP 只支持公开 repo + 用户自带 LLM API key（省 token 钱，与 CLI 共享同一套 LLM 配置）。

### 组件依赖关系

```
cli/web → agent_core → retriever → summarizer → indexer
                      └→ trace_call_chain (用 indexer 的调用图)
evaluator → agent_core + 直接调 baseline API
```

每个组件可独立测试。

---

## 3. 数据流与错误处理

### 3.1 主数据流

**离线索引流**（一次性 + 增量）：

```
repo_url
  ↓ fetcher.git_clone         → 本地 cache 目录
  ↓ parser.tree_sitter_parse  → 每文件 CST (带行号/字节区间)
  ↓ parser.extract_symbols    → 每文件 Symbol 列表 (函数/类/方法 + 调用)
  ↓ parser.extract_imports    → 跨文件依赖边
  ↓ linker.join_symbols       → 全局符号表 + 跨文件调用图 (best-effort)
  ↓ summarizer.layered_summarize → 三层 RepoMap (文件/模块/全局)
  ↓ retriever.embed + index   → Chroma 向量库 + BM25 索引
  ↓ persist to SQLite         → 文件指纹 hash 用于增量
```

**在线问答流**（Agent 循环）：

```
user_question
  ↓ retriever.search(query, layer=global)   → 定位相关模块
  ↓ retriever.search(query, layer=file)     → 定位相关文件/符号
  ↓ agent_core.loop:
       plan → pick_tool → execute → observe → context.append
       工具: read_file / grep / glob / trace_call_chain / lookup_map
       逼近 token 上限 → compact(保留 system + 最早摘要 + 最近 N 轮 + 引用源码)
       终止: max_steps / 足够引用 / Agent 自判完成
  ↓ synthesize(带引用) → Answer { text, citations: [(file, line_range)] }
```

### 3.2 关键错误处理

| 错误点 | 处理策略 | 用户感知 |
|--------|---------|---------|
| git clone 失败 | 重试 2 次 → 失败提示检查 URL/权限 | 清晰错误，不崩 |
| tree-sitter 解析单文件失败 | 容错解析仍出 CST；若完全失败 → 跳过该文件并记录到 `index_errors` 表 | 索引继续，报告列失败文件 |
| LLM 摘要调用失败 | 重试 3 次（指数退避）→ 仍失败则跳过该文件 + 记录到 `index_errors` 表 + 问答时 Agent 自行决定是否 read_file 兜底 | 该文件摘要缺失，Agent 兜底 |
| 向量库写入失败 | 落盘前先写 WAL → 失败回滚 + 保留上一版索引 | 用户无感 |
| Agent 循环超 max_steps | 强制终止，返回当前最佳答案 + 标注"信息可能不全" | 透明，不装作答完了 |
| Agent 循环超 token 预算 | 触发 compaction；compaction 后仍超 → 终止并返回部分答案 | 同上 |
| `trace_call_chain` 在弱类型语言上无结果 | Agent 自动 fallback 调 `grep` 搜函数名 | 用户无感，Agent 自愈 |
| 工具调用返回超大结果（如 grep 命中 1000 行） | 截断到 top-N + 提示"结果已截断，可缩小 scope 重试" | 不污染上下文 |
| LLM 返回无引用的答案 | 后处理校验：引用必须能在索引里找到对应文件行 → 找不到的引用剔除或标注"未验证" | 防幻觉，引用可信 |
| Web 端用户并发索引同一 repo | 用 repo URL hash 做锁，命中则复用已有索引任务（v1 只做 URL hash 一级锁，content hash 二级锁 v1.5） | 省资源 |

### 3.3 三类落盘文件（职责分离）

```
~/.code-reader/
├── indices/<repo_hash>/         # 索引产物
│   ├── ast.db                    # AST/符号/调用图 (SQLite)
│   ├── repo_map.json             # 三层摘要
│   ├── chroma/                   # 向量库
│   └── index_errors.json         # 失败文件清单
│
├── sessions/<session_id>.json    # session state（轻量，可恢复对话）
│   ├── messages: [...]           # 消息序列
│   ├── repo_ref: {url, hash}     # 绑定的 repo 索引版本
│   └── created_at / updated_at
│
├── traces/<session_id>/<query_id>.jsonl   # 完整执行 trace（重，调试/评测用）
│   └── 每行一条 {step, plan, tool_call, observation, tokens}
│
└── memory/<repo_hash>.json       # 跨 session 长期记忆（v1.5 再做）
```

**trace 文件策略**：
- 默认开（评测/self-improvement/bug 复现都需要）
- `code-reader ask --no-trace` 给隐私敏感用户关闭选项
- 自动清理：traces 默认保留 7 天 + 总量上限 100MB，超了自动删最旧的
- `code-reader traces list/clean/export` 命令管理

**session resume**：
- CLI 启动时检测未结束 session
- `code-reader ask --resume <session_id>` 恢复：加载 messages + repo_ref → 继续对话
- `code-reader ask --continue`：恢复最近一次 session
- session 过期：30 天未更新归档，90 天清理

> **概念区分**：trace = 过去发生的事的录像（完整可复现）；memory = 从多次问答沉淀的知识（未来要用的，v1.5）；session state = 当前会话的轻量状态（可恢复对话）。三者职责不同，不混在一个文件里。

### 3.4 可观测性

- **结构化日志**：structlog，每个组件一条 pipeline id 贯穿
- **指标**：索引耗时、索引文件数、Agent 步数、token 消耗、cache 命中率、工具调用次数
- **trace 文件**：每次问答落一份 JSONL，方便调试和评测
- **`code-reader debug`** 命令：导出最近 N 次问答的 trace，用户提 issue 时附上

### 3.5 缓存与增量

- **文件级缓存**：hash → 摘要、hash → AST 抽取结果，没变不重算
- **repo 级增量**：第二次索引同一 repo，只对变动文件走 parser/summarizer，最后重算 linker（跨文件调用图可能受影响）
- **prompt cache**：system prompt + RepoMap 全局层作为 cache breakpoint，多轮问答省钱

---

## 4. 测试策略

按金字塔分四层。

### 4.1 单元测试

**indexer 单测**（重点）：

- **AST 抽取正确性**：每门语言 5-10 个 fixture 文件，断言 `Symbol` 字段（name / kind / line_range / calls / imports）符合预期
- **fixture 来源**：一半手写极简 fixture（覆盖边界：空文件、语法错误、单行函数、嵌套类），一半从开源 repo 截取真实片段
- **跨文件调用图**：3-5 个微型多文件 repo（手写 <10 文件项目），断言 `linker.join_symbols` 正确连"A 文件调 B 文件的函数"
- **增量索引**：先索引一版 → 改一个文件 → 调 `update()` → 断言只有该文件重算

**indexer 用 3-5 个真实开源 repo 跑集成式单测**：

| repo | 语言 | 规模 | 验证目标 |
|------|------|------|---------|
| fastapi | Python | 中 | Python AST 抽取、跨文件调用图 |
| flask | Python | 中 | 同上，对比 fastapi 结果差异 |
| express | JS | 中 | JS AST 抽取、弱类型调用追踪噪声率 |
| typescript-eslint | TS | 大 | TS AST 抽取、类型信息辅助调用追踪 |
| junit5 | Java | 大 | Java AST 抽取、强类型调用追踪准确率 |
| （待选）| Go | 中 | Go AST 抽取、go/ast 交叉验证 |

**解析准确率量化（不靠人评）**：
- **Python**：用标准库 `ast` 交叉验证符号召回率（白嫖、准）
- **Go**：用标准库 `go/ast` 交叉验证符号召回率（白嫖、准）
- **JS / TS / Java**：v1 人工标 50 个 ground truth 抽查（v1.5 补全原生 parser 交叉验证）
- **指标**：符号召回率、调用关系 precision/recall、`index_errors` 失败文件占比

**summarizer / retriever / agent_core 单测**：
- summarizer：mock LLM，测分层摘要 prompt 拼装 + 超 token 预算压缩策略
- retriever：小型 fixture 索引，测向量+BM25 混合排序 + 分层检索从 global 到 file 层正确收窄
- agent_core：mock LLM，测循环逻辑：终止条件、max_steps、compaction 触发、工具调度
- 各工具单测：read_file / grep / glob / trace_call_chain / lookup_map 输入输出符合 schema

### 4.2 集成测试

- **端到端索引 pipeline**：repo URL → 完整索引产物，断言产物 schema 完整
- **端到端问答**：已索引的小 fixture repo，问 5 个固定问题，断言答案包含预期引用文件
- **增量更新 E2E**：索引 v1 → 改文件 → 增量索引 → 问答用新索引
- **trace 落盘 + session resume**：跑一次问答 → 重启进程 → `--continue` 恢复 → 断言能继续

### 4.3 评测测试（v1 = 10 题）

**eval set v1（10 题结构）**：

| 类型 | 数量 | 示例 | 考什么 |
|------|------|------|--------|
| 单文件 | 3 | "fastapi 的 `Body` 函数是干啥的" | 基础检索 |
| 跨文件 | 4 | "FastAPI 处理一个 GET 请求经过哪些主要组件" | 跨文件理解 |
| 多跳调用链（杀手锏题） | 3 | "FastAPI 的路径参数是怎么从 URL 变成函数参数的，列出调用链" | Agent 主场，**必须用大 repo > 20 万行开源项目子模块** |

**baseline 三套**：
1. Claude 裸答（不喂 repo）
2. Claude + 全 repo 塞上下文（repo 不超 200K 的情况下）
3. 简单 RAG（向量检索 top-K + 直接答，无 Agent 循环）

**评测 repo**：v1 选 2 个（fastapi + 一个 TS repo），同一套 10 题跑。

**judge**：LLM-as-judge 用 Claude 当裁判，rubric 打分 0-5；人工抽检 30% 校准。

**指标**：
- 答案准确率（LLM judge + 人工抽检）
- 引用准确率（引用对得上 ground truth 的比例）
- 调用链完整率（追到的真实链长度 / 应有链长度）

**输出**：ablation 表格——行是三类问题，列是四种方法（本 Agent / Claude 裸 / Claude 塞 repo / RAG），格子里是分数。**面试杀手锏**。

**自动化**：`code-reader eval run --suite v1 --repo fastapi` 一条命令跑完，产出 HTML 报告。

### 4.4 手测 / 狗食

- 每次发版前 CLI + Web 各跑 3-5 个真实问题
- 拿 1-2 个真实 repo 实测，记录体感
- 上线后看 issue 里"答错了"案例，归类进 eval set 扩题

### 4.5 CI 集成

- GitHub Actions：push / PR 跑 4.1 单测（必须全绿）
- nightly：跑 4.2 集成 + 4.3 评测（评测费 token，不每次跑）
- 评测报告归档到 `eval-reports/<date>.html`，对比历史趋势看回归

### 4.6 测试基础设施

- **pytest** 单测框架
- **fixtures** 放 `tests/fixtures/`，按 `lang/` 分子目录
- **LLM mock**：自研轻量 mock，预设响应脚本，不依赖外部服务
- **开源 repo fixture**：不进 git（太大），`tests/conftest.py` 首次跑时 git clone 到本地缓存，后续复用
- **评测 fixture**：10 题的 ground truth + 标准答案放 `eval/v1/`，进 git

---

## 5. 开源相关

### 5.1 LICENSE + 基础元数据

- **LICENSE**：MIT
- **README.md**：门面，结构见 5.2
- **CONTRIBUTING.md**：贡献指南
- **CODE_OF_CONDUCT.md**：Contributor Covenant 标准模板
- **CHANGELOG.md**：发版记录
- **.github/**：issue/PR 模板 + CI workflow

### 5.2 README.md 结构

```
# Code Reader Agent
> 一句话：3 分钟让陌生代码库变成可问答、可追踪调用链、可生成 onboarding 文档。

## 为什么有这个项目
（claude-learn 前传故事——用 Claude Code + 手写笔记花半个月读完 Claude Code 51 万行源码，
  发现这套高手玩法可以自动化，于是做了这个工具）

## 跟 Claude Code / Cursor 的区别
（四大差距对比表）

## Quick Start
（3 条命令 onboard 一个真实 repo，30 秒内有体感）

## 它能干什么
（GIF / 截图：CLI 问答 + Web 端 + 自动生成 onboarding 文档）

## 评测数据
（ablation 表格——杀手锏）

## 工作原理
（架构图 + 三层架构简述）

## 支持语言
（Python / JS / TS / Java / Go + 每门语言解析准确率）

## Roadmap
（v1 MVP / v1.5 / v2）

## 贡献
（指向 CONTRIBUTING.md）

## License
MIT
```

### 5.3 贡献策略

- **good first issue** 标签：v1 发版后挂 5-10 个简单 issue（加一门语言 adapter、补一个工具、改文档章节）
- **贡献流程**：fork → branch → PR → CI 绿 → review → merge
- **commit 规范**：Conventional Commits（`feat:` / `fix:` / `docs:`），自动化 changelog
- **代码风格**：ruff + black，pre-commit hook 自动格式化
- **测试要求**：任何 PR 必须带单测，CI 不绿不 merge
- **核心模块维护**：agent_core / indexer / summarizer 三块 v1 自己维护（架构敏感），其他模块欢迎贡献

### 5.4 发版策略

- **语义化版本**：v0.x.x（v1 正式版前 API 不稳定）→ v1.0.0（API 稳定，承诺向后兼容）
- **发版节奏**：v1 MVP 发布后，2 周一个小版本，1 个月一个中版本
- **release notes**：每版本列 features / fixes / breaking changes，附评测报告链接
- **GitHub Releases**：打 tag + release notes + 附二进制（pip 包 + 可执行文件）

### 5.5 发布形态

| 形态 | 渠道 | 目标用户 |
|------|------|---------|
| pip 包 | PyPI | Python 开发者，`pip install code-reader` |
| 源码 clone | GitHub | 想看源码/自己改的开发者 |
| Web 端 | 自部署 / 免费托管（Vercel/Render） | 不想装 Python 的社区用户 |
| Docker | Docker Hub | 想自部署 Web 端的团队 |

**MVP 发版**：pip 包 + GitHub clone + 一个免费托管的 Web demo（demo 限定公开 repo + 用户自带 API key，不出 token 钱）。

### 5.6 引流动作

1. **技术博客 3 篇**（面试素材副产品）：
   - 《我读完 Claude Code 51 万行源码后，把它的高手玩法做成了 Agent 工具》——前传故事，V2EX / 掘金 / 知乎
   - 《用 tree-sitter + Agent 做 5 语言代码库地图：踩坑与效果数据》——技术深度，r/programming / Hacker News
   - 《评测 Claude Code vs 我的 Agent 在大 repo 多跳问题上的差距》——量化对比，最有争议也最吸流量
2. **Twitter/X**：demo gif + 数据，蹭 #AI #LLM #DevTools
3. **GitHub topic**：`agent` / `llm` / `code-exploration` / `tree-sitter` 等标签
4. **README 顶部 star history + trends**：早期靠朋友 star，过 100 star 后会被 GitHub Explore 推荐
5. **小红书/B站**：演示视频（中文社区开发者转化高）

**目标**：v1 发布后 1 个月，GitHub star 100+，Web demo 日活 50+，5-10 个真实用户反馈。

---

## 6. Roadmap

### v1 MVP（本次设计范围，业余 2-3 个月）

- 5 门语言 indexer（Python / JS / TS / Java / Go）
- 三层摘要 + 混合检索 + agent_core 五工具
- CLI + 极简 Web 双入口
- eval set 10 题 + 三套 baseline ablation
- trace / session / 索引三类落盘文件
- 开源 6 件套 + 3 篇引流博客

### v1.5

- memory 跨 session 长期记忆
- content hash 二级并发锁
- JS / TS / Java 原生 parser 交叉验证
- eval set 扩到 30 题
- IDE 插件（VS Code）

### v2

- 团队共享地图（多租户 + 鉴权）
- 私有 repo 完整鉴权
- 代码库地图可视化（Web 端交互图）
- 自动生成并维护 onboarding 文档（随 repo 更新自动更新）
- 自定义 Agent persona（不同团队风格）

---

## 7. 已决问题（原待决，2026-08-21 全部澄清）

- [x] **大 repo 杀手锏题** → **kubernetes**（Go，>20 万行，同时验证 Go AST 交叉验证能力）
- [x] **TS 评测 repo** → **nest**（NestJS，中大型 TS 项目）
- [x] **LLM mock 工具** → 自研轻量 `MockLLM` 类（约 50 行，按调用顺序返回预设响应），不引外部库
- [x] **Web 端技术栈** → **FastAPI 后端 + 前端页面用 `frontend-design` skill 设计**
- [x] **pip 包名** → `code-reader`（项目改名 code-reader-agent 后定）

## 8. 关键架构决策汇总（2026-08-21 新增）

1. **LLM 接入不绑死厂商**：支持任意 OpenAI 兼容 endpoint（base_url + api_key + model_name），用户自带。推荐组合：摘要用便宜模型、Agent 循环用强模型，可分别配置。
2. **Web 前端开发流程**：实现阶段调用 `superpowers:frontend-design` skill 设计前端页面（非凭空手写）。
3. **改名**：项目原名 Repo Onboarding Agent → Code Reader Agent。pip 包名 `code-reader`，CLI 命令 `code-reader`，配置目录 `~/.code-reader/`。