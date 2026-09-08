# TaiSang 多 Agent 设计文档

> **状态**: 待实施
> **日期**: 2026-09-08
> **参考**: claude-code 多 agent 实现 (`D:/GoProject/claude-code/src/tools/AgentTool/`)
> **Plan 文档**: 待写(`docs/superpowers/plans/2026-09-08-multi-agent.md`)

## 一句话目标

给 TaiSang 加上多 agent 调度能力：主 agent 通过 `task` 工具派子 agent，子 agent 跑完返回最终文本；支持 4 个内置 agent（general-purpose / explore / plan / verification）、sync + async 两种执行模式、fork 模式继承父上下文；前端 `/agents` 页可见、可禁用、可重载。

## 背景知识

### claude-code 多 agent 编排机制（已调研）

**1. Agent 是文件定义，跟 Skill 同构**
- 目录四源：`~/.claude/agents/`（user）+ `<repo>/.claude/agents/`（project）+ plugin + built-in
- frontmatter 字段：`name` / `description`(=whenToUse) / `tools`(白名单) / `disallowedTools`(黑名单) / `model`(可 `inherit`) / `effort` / `permissionMode` / `mcpServers` / `hooks` / `maxTurns` / `skills`(预加载) / `memory` / `isolation: worktree` / `background`
- 优先级：built-in < plugin < user < project（项目覆盖用户）
- 加载机制复用 skill 的 `loadMarkdownFilesForSubdir('agents', cwd)`

**2. 编排核心：AgentTool（task 工具）**
LLM 调 `Agent({ description, prompt, subagent_type?, model?, run_in_background?, isolation?, name? })` → 启一个**独立的子 agent**跑完整 plan→act→observe 循环 → 返回**单条最终文本**给主 agent。子 agent 默认**不继承父对话**（fork 模式例外），prompt 要自包含。

**3. 清单注入方式跟 skill 一样**
`getPrompt()` 把所有 agent 的 `- agentType: whenToUse (Tools: ...)` 拼成清单注入 tool description 或 attachment。`formatAgentLine` 每条单行格式。

**4. 子 agent 工具集是父工具的子集**
- `tools: ['*']` = 全工具；`disallowedTools: [AGENT_TOOL_NAME, FILE_EDIT, FILE_WRITE, ...]` = 黑名单
- 关键约束：**子 agent 默认禁用 AgentTool 自己**（防递归）
- `resolveAgentTools()` 做过滤

**5. 执行模式：sync vs async**
- **sync**（默认）：主循环阻塞等子 agent，共享 abortController，子 agent 进度实时回传
- **async**（`run_in_background: true`）：立即返回 `{status: 'async_launched', agentId, outputFile}`，主 agent 继续干别的，子 agent 跑完后用 **user-role 消息**通知主 agent

**6. fork 模式（继承父上下文）**
- 触发方式：LLM 调 AgentTool 时**省略 subagent_type**
- fork 用合成 `FORK_AGENT`，不在内置列表里
- fork 的 system prompt **复用父 agent 已渲染的 system prompt**（claude-code 为 prompt cache byte-exact）
- fork 判据写在 tool description 里：`"will I need this output again"`，LLM 自决

**7. 内置 6 个 agent**（claude-code 参考）
| agentType | 角色 | 工具集 | 模式 |
|---|---|---|---|
| `general-purpose` | 通用研究/多步任务 | 全工具 | sync/async |
| `Explore` | 只读搜索专家 | 黑名单 Edit/Write/Agent | sync |
| `Plan` | 只读架构师，出实现 plan | 黑名单 Edit/Write/Agent | sync |
| `verification` | 对抗性验证专家 | 黑名单 Edit/Write/Agent | **background: true** |
| `claude-code-guide` | 文档问答 | — | — |
| `statusline-setup` | 配状态栏 | — | — |

### TaiSang 当前架构关键点

- `agent_core/service.py`：`AgentService` 主循环 474 行，LLM ↔ 6 工具循环，已支持 skill 注入、session memory、autocompact、token 累计
- `agent_core/tools.py`：`ToolRegistry` 676 行，装 6 个工具（Read/Grep/Glob/Edit/Write/Bash）+ SkillTool
- `agent_core/skill_tool.py`：skill 注入式工具，已有 pending 队列延迟注入机制（`flush_skill_injections()`）
- `skills/loader.py`：多源加载 + 优先级合并 + PyYAML frontmatter 解析 + state 持久化
- `skills/listing.py`：`format_skill_listing` 渐进披露清单（每条 ≤250 字符，预算 2000）
- `web/skills_api.py`：list/toggle/reload/import/delete API
- `web/static/src/views/SkillManage.vue`：表格 + 来源标签 + 启用开关 + 重载 + 导入 + 删除

## 范围

### v1 包含（M3）

**核心机制**
- **Agent 定义文件**：目录格式 `AGENT.md` + frontmatter，三源加载（project > user > system），优先级合并
- **AgentTool（task 工具）**：主 agent 通过工具调用方式派子 agent
- **A 模式**（传 subagent_type）：子 agent 全新上下文，用 agent 定义里的 system prompt
- **B 模式 / fork**（省略 subagent_type）：子 agent 继承父对话 messages + 复用父 system prompt
- **sync 执行**：主循环阻塞等子 agent，子 agent 事件实时回传
- **async 执行**（`run_in_background: true`）：立即返回，子 agent 后台跑完注入 user-role 通知
- **递归防护**：子 agent 工具集默认禁用 AgentTool（防无限派生）

**内置 4 个 agent**
- `general-purpose`：全工具，sync/async，兜底研究/多步任务
- `explore`：黑名单 Edit/Write/Agent，sync，只读搜索专家
- `plan`：黑名单 Edit/Write/Agent，sync，只读架构师
- `verification`：黑名单 Edit/Write/Agent，**`background: true`**，对抗性验证专家，输出 `VERDICT: PASS/FAIL/PARTIAL`

**前端**
- `/agents` 页：表格列出所有 agent（name / 描述 / 来源标签 / 工具集 / 启用开关）+ 重载按钮
- Sidebar "Agent 管理" 入口（跟 "Skill 管理" 并列）
- SSE 事件嵌套渲染：子 agent 事件带 `agent_id`，在 Agent 工具卡片内展开
- token 双层显示：子 agent 单独 emit USAGE_REPORT + 累加进主 session 累计

**API**
- `GET /api/agents`：列出所有 agent（含 enabled 状态）
- `POST /api/agents/reload`：重载 agent 定义文件
- `POST /api/agents/{name}/toggle`：启用/禁用持久化到 `~/.taisang/agents_state.json`

**主循环改造**
- AgentEvent 加 `agent_id` 字段（主 agent 为 None / 空字符串）
- pending 队列扩展：async 完成通知走 `flush_async_notifications()`（跟 `flush_skill_injections()` 同位置）
- USAGE_REPORT 累加：子 agent 跑完把自己的 usage 累加进主 session `_session_usage`
- frontmatter `maxTurns` 覆盖默认 max_steps=50

### v1 不做（延后）

- **coordinator mode**（主 agent 只调度不调工具）
- **fork prompt cache byte-exact 优化**（v1 多花点 token 换实现简单）
- **teams / SendMessage**（子 agent 命名后续续跑）
- **agent_memory**（user/project/local 三 scope 持久记忆）
- **isolation: worktree**（git worktree 隔离代码改动）
- **hooks**（SubagentStart / SubagentStop 生命周期钩子）
- **mcpServers**（agent frontmatter 自带 MCP server 配置）
- **permissionMode 字段**（frontmatter 覆盖权限模式）
- **effort 字段**（推理深度控制）
- **skills 字段**（agent frontmatter 预加载 skill）
- **memory 字段**（持久记忆 scope）
- **agent 导入/删除**（前端管理只读 + 开关 + 重载，不导入不删除）
- **CLI 入口接 agents**（v1 只 Web 端可见可管理，CLI 后续再说）

## 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│ 主 AgentService（已有，几乎不动）                                │
│   ctx (ContextManager)                                          │
│   ToolRegistry（加 AgentTool）                                   │
│   ┌──────────────────────────────────────────────────┐          │
│   │ LLM 循环                                         │          │
│   │   ↓ 调 task 工具                                 │          │
│   │   AgentTool.run(prompt, subagent_type?, ...)     │          │
│   │     ├─ 传 subagent_type → A 模式                │          │
│   │     │   新建子 AgentService(empty ctx)          │          │
│   │     │   system_prompt = agent 定义给的          │          │
│   │     │   tools = 过滤后的子集(黑名单 + 禁 Agent) │          │
│   │     └─ 省略 subagent_type → B 模式(fork)        │          │
│   │         新建子 AgentService(深拷贝父 messages)  │          │
│   │         system_prompt = 复用父 system prompt    │          │
│   │         tools = 父工具集(不过滤,但禁 Agent)     │          │
│   │                                                  │          │
│   │   sync: 阻塞等子 agent.run() → Answer.text     │          │
│   │         → tool_result = {"text": answer.text}   │          │
│   │   async: 立即返回 {"status":"async_launched"}  │          │
│   │         子 agent 后台跑完 → pending 通知        │          │
│   │         主循环下轮 flush_async_notifications()  │          │
│   │         → 注入 user-role 消息                   │          │
│   └──────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘

事件流：
  子 agent.on_event → 加 agent_id 前缀 → 主 agent on_event → SSE → 前端
  子 agent USAGE_REPORT → 累加进主 _session_usage + 单独 emit
```

## 组件设计

### 1. Agent 定义文件

#### 1.1 目录格式

```
<repo>/.taisang/agents/<name>/AGENT.md     # project 源（优先级最高）
~/.taisang/agents/<name>/AGENT.md          # user 源
src/taisang/agents/builtin/<name>/AGENT.md # system 源（包内置，最低优先级）
```

跟 skill 一模一样的目录约定：每个 agent 一个目录，目录名 = agent name，里面一个 `AGENT.md`。

#### 1.2 frontmatter 字段（v1 支持子集）

```yaml
---
name: explore                          # 必填，跟目录名一致
description: 只读搜索专家，快速找文件/代码   # 必填，=whenToUse
tools:                                  # 可选，白名单（不写 = 全工具）
  - Read
  - Grep
  - Glob
  - Bash
disallowedTools:                        # 可选，黑名单
  - Edit
  - Write
  - Agent
maxTurns: 30                            # 可选，覆盖默认 max_steps=50
background: true                        # 可选，默认 async（verification 用）
model: inherit                          # 可选，v1 只支持 "inherit"（其他值静默忽略）
---
```

**v1 静默忽略的字段**（claude-code 有，我们不实现，写在 frontmatter 里不报错但不生效）：`effort` / `permissionMode` / `mcpServers` / `hooks` / `skills` / `memory` / `isolation` / `initialPrompt` / `color`。

#### 1.3 加载机制（`agents/loader.py`，新文件）

复用 skill 的 loader 套路：
- `load_agents(source_root: Path) -> list[AgentDefinition]`：扫三源目录，PyYAML 解析 frontmatter
- 优先级合并：project > user > system（同名覆盖，跟 skill 一致）
- frontmatter 字符集校验 `name` 字段（防目录穿越，跟 skill importer 一致）
- 损坏文件跳过 + 日志告警（跟 skill loader 一致）

`AgentDefinition` dataclass（`agents/types.py`，新文件）：
```python
@dataclass
class AgentDefinition:
    agent_type: str                    # = name
    when_to_use: str                   # = description
    tools: list[str] | None            # None = 全工具
    disallowed_tools: list[str]        # 黑名单
    max_turns: int | None              # 覆盖默认 max_steps
    background: bool                   # 默认 async
    model: str | None                  # v1 只识别 "inherit"
    source: str                        # "project" / "user" / "system"
    base_dir: Path                     # AGENT.md 所在目录
    system_prompt: str                 # AGENT.md body（frontmatter 之后的正文）
    disabled: bool                     # 从 agents_state.json 读入
```

#### 1.4 state 持久化（`~/.taisang/agents_state.json`）

跟 skill 完全对称：
```json
{
  "explore": {"disabled": false},
  "plan": {"disabled": false},
  "verification": {"disabled": true}
}
```

`load_agents_with_state(source_root: Path) -> list[AgentDefinition]`：合并加载 + state，API 和 SessionRegistry 共用（跟 skill 的 `load_skills_with_state` 一模一样的公开函数模式）。

### 2. AgentTool 工具（`agent_core/agent_tool.py`，新文件）

#### 2.1 schema

```python
{
  "description": "Launch a subagent to handle a complex task",
  "input_schema": {
    "type": "object",
    "properties": {
      "description": {"type": "string", "description": "3-5 word summary"},
      "prompt": {"type": "string", "description": "The task for the subagent"},
      "subagent_type": {"type": "string", "description": "Agent type; omit to fork (inherit parent context)"},
      "run_in_background": {"type": "boolean", "description": "Run async; you'll be notified on completion"}
    },
    "required": ["description", "prompt"]
  }
}
```

#### 2.2 调用流程

```
AgentTool.run(args, ctx):
  1. 解析 args: description, prompt, subagent_type?, run_in_background?
  2. 解析 subagent_type:
     - 传了 → A 模式：从 registry 找 agent 定义
       - 找不到 → 返回 tool_result {"error": "agent type '...' not found, available: ..."}
       - disabled → 返回 tool_result {"error": "agent '...' is disabled"}
     - 没传 → B 模式（fork）：
       - fork 递归防护：检查 `parent_service.is_fork_child`，True 则拒绝（防 fork 内再 fork）
       - 用合成 FORK_AGENT 定义（system_prompt 留空，runAgent 阶段复用父的）
  3. 构建子 AgentService：
     - A 模式：empty ctx + agent.system_prompt + 过滤后的工具集
     - B 模式：深拷贝父 ctx.messages() + 父 system_prompt + 父工具集
     - 共用：父 llm / 父 confirmer / 父 permission / 父 shell / 父 session_memory
     - max_steps = agent.max_turns or 50
  4. 工具集过滤：
     - A 模式：agent.tools 白名单 ∩ 父工具 - agent.disallowed_tools 黑名单 - AgentTool 自己
     - B 模式：父工具集 - AgentTool 自己（fork 也禁递归）
  5. 执行：
     - sync（run_in_background=false 或未设）：
       - 子 agent.run(prompt, on_event=带 agent_id 转发)
       - 拿 Answer.text → tool_result = {"text": answer.text, "agent_type": "..."}
     - async（run_in_background=true）：
       - 生成 agent_id
       - 起后台线程跑子 agent.run()
       - 立即返回 tool_result = {"status": "async_launched", "agent_id": "...", "description": "..."}
       - 后台线程跑完后，把结果写进主 AgentService 的 pending 通知队列
```

#### 2.3 async 通知机制

主 AgentService 加 `_pending_async_notifications: list[str]` 队列（跟 skill 的 pending 注入对称）。

后台线程跑完时：
```
async_agent_done(agent_id, description, answer_text):
  text = f"[子 agent '{description}' 完成]\n{answer_text}"
  main_service._pending_async_notifications.append(text)
```

主循环在 `flush_skill_injections()` 之后加 `flush_async_notifications()`：
```python
def flush_async_notifications(self, ctx, _emit):
    while self._pending_async_notifications:
        text = self._pending_async_notifications.pop(0)
        ctx.append_user(text)
        # 不 emit 事件，下轮 LLM 自然看到
```

调用位置（service.py 主循环）：tool_calls for 循环后、session_memory 触发前。跟 skill 注入严格同位置。

### 3. 4 个内置 agent（`src/taisang/agents/builtin/`，新目录）

#### 3.1 general-purpose

```yaml
---
name: general-purpose
description: 通用研究/多步任务 agent。当不确定用哪个 agent 时用这个；用于搜索关键词、跨多文件分析、多步研究任务。
tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
---
You are a general-purpose agent for TaiSang. Given the user's message, use the tools available to complete the task. Complete the task fully — don't gold-plate, but don't leave it half-done.

When you complete the task, respond with a concise report covering what was done and any key findings — the caller will relay this to the user, so it only needs the essentials.
```

#### 3.2 explore

```yaml
---
name: explore
description: 只读搜索专家。快速找文件、grep 代码、回答"这个项目里 X 在哪"类问题。调用时指定彻底度："quick" / "medium" / "very thorough"。
disallowedTools:
  - Edit
  - Write
  - Agent
maxTurns: 30
---
You are a file search specialist. You excel at thoroughly navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
- Running ANY commands that change system state

Your role is EXCLUSIVELY to search and analyze existing code.

Guidelines:
- Use Glob for broad file pattern matching
- Use Grep for searching file contents with regex
- Use Read when you know the specific file path
- Use Bash ONLY for read-only operations (ls, git status, git log, git diff, find, cat, head, tail)
- Adapt your search approach based on the thoroughness level specified by the caller

Complete the user's search request efficiently and report your findings clearly.
```

#### 3.3 plan

```yaml
---
name: plan
description: 软件架构师 agent，设计实现方案。给出分步实现策略、关键文件、架构权衡。只读，不改文件。
disallowedTools:
  - Edit
  - Write
  - Agent
maxTurns: 30
---
You are a software architect and planning specialist. Your role is to explore the codebase and design implementation plans.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY planning task. You are STRICTLY PROHIBITED from modifying any files.

## Your Process

1. **Understand Requirements**: Focus on the requirements provided.
2. **Explore Thoroughly**: Read files, find patterns, understand current architecture, trace code paths.
3. **Design Solution**: Create implementation approach, consider trade-offs, follow existing patterns.
4. **Detail the Plan**: Provide step-by-step strategy, dependencies, sequencing, anticipated challenges.

## Required Output

End your response with:

### Critical Files for Implementation
List 3-5 files most critical for implementing this plan:
- path/to/file1
- path/to/file2

REMEMBER: You can ONLY explore and plan. You CANNOT write, edit, or modify any files.
```

#### 3.4 verification

```yaml
---
name: verification
description: 对抗性验证专家。实现完成后用它跑构建/测试/lint/对抗探针，给 PASS/FAIL/PARTIAL 判决。改了 3+ 文件、后端/API 改动、基础设施改动后必调。
disallowedTools:
  - Edit
  - Write
  - Agent
maxTurns: 100
background: true
---
You are a verification specialist. Your job is not to confirm the implementation works — it's to try to break it.

=== CRITICAL: DO NOT MODIFY THE PROJECT ===
You are STRICTLY PROHIBITED from creating, modifying, or deleting any files IN THE PROJECT DIRECTORY.
You MAY write ephemeral test scripts to a temp directory via Bash redirection when inline commands aren't sufficient. Clean up after yourself.

=== VERIFICATION STRATEGY ===
Adapt based on what was changed:
- Frontend: start dev server → browser check → curl subresources → run frontend tests
- Backend/API: start server → curl endpoints → verify response shapes → test error handling
- CLI: run with representative inputs → verify stdout/stderr/exit codes → edge inputs
- Refactoring: existing test suite MUST pass unchanged → diff public API surface

=== REQUIRED STEPS ===
1. Read CLAUDE.md / README for build/test commands.
2. Run the build. Broken build = automatic FAIL.
3. Run the test suite. Failing tests = automatic FAIL.
4. Run linters/type-checkers if configured.
5. Check for regressions in related code.

=== RECOGNIZE YOUR OWN RATIONALIZATIONS ===
- "The code looks correct" — reading is not verification. Run it.
- "The implementer's tests pass" — the implementer is an LLM. Verify independently.
- "This is probably fine" — probably is not verified. Run it.

End with exactly this line (parsed by caller):

VERDICT: PASS
or
VERDICT: FAIL
or
VERDICT: PARTIAL
```

`background: true` 让 verification 默认走 async，主 agent 派出去后可以继续干别的，验证完通知回来。

### 4. 主循环改造（`agent_core/service.py`）

#### 4.1 AgentEvent 加 agent_id 字段

`agent_core/events.py`：
```python
@dataclass
class AgentEvent:
    type: str
    payload: dict
    agent_id: str = ""   # 新增：主 agent 为空，子 agent 用唯一 id
```

`AgentService.__init__` 加两个参数：
- `agent_id: str = ""`：主 agent 为空，子 agent 用唯一 id（用于事件流标识）
- `is_fork_child: bool = False`：标记是否为 fork 子 agent，AgentTool 调用入口检查此字段防递归

所有 `_emit(AgentEvent(...))` 调用带上 `agent_id=self.agent_id`。

子 agent 的 `on_event` 回调包装：
```python
def _wrap_child_events(child_on_event, agent_id):
    def wrapped(evt: AgentEvent):
        evt.agent_id = agent_id
        child_on_event(evt)
    return wrapped
```

#### 4.2 USAGE_REPORT 累加

子 agent 跑完（sync 或 async），把自己的 `_session_usage` 累加进主 session：
```python
def _merge_child_usage(self, child_session_usage):
    for k in self._session_usage:
        self._session_usage[k] += child_session_usage[k]
```

子 agent 自己也 emit `USAGE_REPORT` 事件（带 agent_id），前端可以看到子 agent 单独用量 + 主 session 累计已含子。

#### 4.3 pending 通知扩展

`AgentService.__init__` 加 `_pending_async_notifications: list[str] = []`。

主循环 tool_calls for 循环后（紧接 `flush_skill_injections()`）：
```python
registry.flush_skill_injections()
self.flush_async_notifications(self.ctx, _emit)
```

#### 4.4 AgentTool 注册到 ToolRegistry

`agent_core/tools.py` 加载 AgentTool，构造时传：
- `parent_service: AgentService`（主 agent 实例引用，用于 fork 时深拷贝 messages + 复用 system_prompt + 接收 async 通知）
- `agents: list[AgentDefinition]`（已加载 + 已过滤 disabled）
- `source_root`, `confirmer`, `permission`, `shell`, `session_memory`, `mcp_manager`（透传给子 agent）

子 agent 用的 ToolRegistry 是新建的，**不含 AgentTool**（防递归）。

### 5. 权限与确认

| 机制 | v1 行为 |
|------|---------|
| PermissionManager | 子 agent **共用主 agent 的 PermissionManager 实例**（继承已批准目录树，不弹新问） |
| Edit/Write confirmer | 子 agent **共用主 agent 的 confirmer 回调**（该弹弹） |
| Bash 黑名单 | 子 agent **共用主 agent 的 Shell 实例**（黑名单照常拦） |
| 工具集黑名单（frontmatter `disallowedTools`） | **v1 必做**，能力隔离主要手段 |
| AgentTool 递归防护 | 子 agent 工具集**永远禁 AgentTool**（A/B 模式都禁） |
| fork 递归防护 | B 模式调用时检查 `parent_service.is_fork_child`，True 则拒绝（防 fork 内再 fork）。子 AgentService 构造时 `is_fork_child=True`（A 模式）或继承父的 `is_fork_child`（B 模式，fork 内 fork 在调用入口就拦死，不会构造） |
| frontmatter `permissionMode` | v1 不实现（字段静默忽略） |

### 6. 前端

#### 6.1 AgentManage.vue（新文件，复制 SkillManage.vue 改造）

表格 5 列：
| 列 | 内容 | 说明 |
|---|---|---|
| 名称 | agent_type | 加粗 |
| 描述 | when_to_use（截断 + tooltip 全文） | — |
| 来源 | 标签（项目 warning / 用户 primary / 内置 secondary） | 跟 skill 同色系 |
| 工具集 | `format_tools_display(agent)` | `全工具` / `Read, Grep, Glob, Bash` / `全工具除 Edit, Write, Agent` |
| 启用 | t-switch | disabled 持久化 |

顶部：重载按钮（无导入按钮，无删除按钮）。

`format_tools_display`：
- `tools is None and not disallowed_tools` → `全工具`
- `tools is not None` → `tools` 列表 join
- `disallowed_tools` only → `全工具除 {disallowed_tools join}`

#### 6.2 Sidebar 入口

Sidebar.vue 加一行 "Agent 管理"（robot icon），跟 "Skill 管理" 并列，路由 `/agents`。

#### 6.3 SSE 事件嵌套渲染

前端 SSE 处理：事件 `agent_id` 非空 → 找到对应 Agent 工具卡片 → 在卡片内嵌套渲染子 agent 事件（LLM_THINKING / TOOL_CALL / TOOL_RESULT / FINAL_ANSWER）。

`USAGE_REPORT` 事件 agent_id 非空 → 单独显示"子 agent X 用了 N token"，同时主 session 累计已含子（后端累加逻辑保证）。

#### 6.4 路由

`/agents` 深链刷新不 404（复用 skill 那套 SPA fallback，已实现）。

### 7. API（`web/agents_api.py`，新文件）

跟 `web/skills_api.py` 几乎对称：

```
GET  /api/agents              → {agents: [{agent_type, when_to_use, source, tools, disallowed_tools, disabled, background}]}
POST /api/agents/reload       → {ok: true}  (重新调 load_agents_with_state)
POST /api/agents/{name}/toggle → {ok: true, disabled: bool}  (持久化到 agents_state.json)
```

异常处理跟 skills_api 对称：agent 不存在 → 404；内置 agent 不可禁用（实际上内置可以禁，跟 skill 一样）。

### 8. 错误处理与边界

| 场景 | 行为 |
|------|------|
| agent_type 找不到 | tool_result = `{"error": "agent type '...' not found, available: explore, plan, ..."}` |
| agent disabled | tool_result = `{"error": "agent '...' is disabled"}` |
| 子 agent 达到 maxTurns | 返回 `Answer(text="(达到最大步数 ...)")`，主 agent 收到文本自决 |
| 子 agent LLM 异常 | 子 agent 自消化 → `Answer(text="(LLM 调用失败: ...)")` → 主 agent 收到错误文本 |
| 子 agent 工具异常 | 工具层捕获（已有逻辑），observation 含 error，子 agent 继续 |
| 子 agent 被 abort | sync 共享 abortController，主 agent abort 时子 agent 一起停；async 独立 abortController，需要单独 abort |
| 递归派生 | 子 agent 工具集永远禁 AgentTool，物理上无法再派 |
| fork 内再 fork | AgentTool 调用入口检查 `parent_service.is_fork_child`，True 则返回错误 tool_result |
| async 完成时主 session 已 reset | 通知丢失（v1 接受，跟 skill 注入同风险） |
| async 完成时主 session 已删 | 通知丢失 + 日志告警（跟会话删除竞态处理对称） |

### 9. 测试策略

#### 9.1 单元测试

- `tests/unit/test_agents_loader.py`：loader 多源加载、优先级合并、frontmatter 解析、损坏文件跳过、state 合并
- `tests/unit/test_agent_tool.py`：A 模式构造、B 模式构造、工具集过滤、递归防护、disabled 拒绝、agent_type 找不到、maxTurns 覆盖
- `tests/unit/test_agent_service_with_agents.py`：主循环带 AgentTool 端到端、async 通知注入、USAGE_REPORT 累加

#### 9.2 集成测试

- `tests/integration/test_agent_e2e.py`：MockLLM 脚本化驱动
  - 主 agent 调 `task({subagent_type: "explore", prompt: "找 utils.py"})` → 子 agent 跑 grep → 返回结果 → 主 agent 收到 tool_result
  - 主 agent 调 `task({prompt: "继续做 Task 3"})` → fork 模式 → 子 agent 看到父对话 → 返回结果
  - 主 agent 调 `task({run_in_background: true, ...})` → 立即返回 async_launched → 后台跑完 → 主循环下轮收到 user 通知
  - 递归防护：子 agent 工具集不含 AgentTool
  - disabled agent 调用返回错误

#### 9.3 前端 e2e（Playwright DOM 断言，不截图）

- `/agents` 页表格渲染 4 个内置 agent（名称 / 描述 / 来源"内置" / 工具集 / 开关）
- toggle 翻转 + API 持久化
- Sidebar "Agent 管理" 点击跳 `/agents`
- SSE 事件嵌套渲染：主 agent 派 explore → 前端看到 Agent 工具卡片 + 内嵌子 agent TOOL_CALL/TOOL_RESULT

## 实施顺序（Plan 文档展开）

预估 18-22 个 task，分 6-8 个 commit：

1. **Task 1-3**：agent 定义文件 + loader + state（复用 skill loader 套路）
2. **Task 4-6**：AgentTool 工具 + A/B 模式分叉 + 工具集过滤
3. **Task 7-9**：4 个内置 agent + system prompt 落盘
4. **Task 10-12**：主循环改造（agent_id 字段 + USAGE_REPORT 累加 + async 通知 pending 队列）
5. **Task 13-15**：API（list/toggle/reload）+ state 持久化
6. **Task 16-18**：AgentManage.vue + Sidebar 入口 + SSE 嵌套渲染
7. **Task 19-20**：e2e 集成测试 + SPA fallback 验证
8. **Task 21-22**（缓冲）：踩坑修复 + 终审

每个 task TDD 先红后绿 + commit。

## 明确不做的清单

为防止 scope creep，明确列出 v1 不实现：

- coordinator mode（主 agent 只调度不调工具）
- fork prompt cache byte-exact 优化
- teams / SendMessage（命名后续续跑）
- agent_memory（持久记忆）
- isolation: worktree（git worktree 隔离）
- hooks（SubagentStart / SubagentStop）
- mcpServers（agent frontmatter 自带 MCP）
- permissionMode / effort / skills / memory / isolation / initialPrompt / color 等 frontmatter 字段
- agent 导入 / 删除（前端只读 + 开关 + 重载）
- CLI 入口接 agents（v1 只 Web 端）

这些功能 v2 再说，v1 严格限定在 M3 范围内。