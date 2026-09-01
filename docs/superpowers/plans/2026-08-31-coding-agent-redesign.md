# 重构 Plan:从文档生成流水线 → 简化版 Coding Agent

> **目标:** 把项目从"文档生成流水线(伪 agent)"重构为"简化版 Claude Code / Trae 式 coding agent"。
> 交互式 REPL,能读改写代码 + 跑命令,长对话用三道上下文管理机制。

## 决策表

| 维度 | 决策 |
|------|------|
| 工具集 | Read / Edit / Write / Grep / Glob / Bash |
| 交互 | REPL(进 `taisang` 进交互式对话) |
| 上下文机制 | apply-tool-result-budget + autocompact + session memory |
| microcompact | 删(doc 专用,通用 agent 用不上) |
| 文档功能 | 全砍(outliner / deepwriter / docgen / summarizer / eval) |
| Bash 限制 | 命令白名单 + 限定 cwd |
| Edit/Write 限制 | 用户确认(每次改文件前交互式 prompt) |
| 工作目录 | 用当前目录(cd 到 repo 再跑 `taisang`) |

---

## 重构范围

### 要删

```
src/taisang/
├── outliner/                    # 整个删
├── deepwriter/                  # 整个删
├── docgen/                      # 整个删
├── summarizer/                  # 整个删
├── compaction/microcompact.py   # doc 专用,删
├── agent_core/tools.py          # WriteDocTool/ListPendingSectionsTool/FinalizeDocTool 删

tests/
├── unit/test_outliner_*.py      # 删(4 个文件)
├── unit/test_deepwriter.py      # 删
├── unit/test_docgen.py          # 删
├── unit/test_summarizer.py      # 删
├── unit/test_compaction_microcompact.py  # 删
├── unit/test_cli.py             # 改(删 doc 命令测试)
├── integration/test_doc_pipeline.py       # 删
├── integration/test_doc_update.py         # 删
└── integration/test_end_to_end.py         # 改(删 doc 相关,留 indexer/linker)

eval/                            # 整个删
```

### 要改

```
src/taisang/
├── cli/main.py                  # 砍 doc/index 命令,加 REPL
├── agent_core/
│   ├── prompts.py               # 改:通用 coding agent system prompt
│   ├── service.py               # 改:纯对话循环,删 doc 分支
│   ├── tools.py                 # 改:加 Edit/Write/Bash,删 doc 工具
│   └── context.py               # 不动(已有 tiktoken + replace_messages)
├── compaction/
│   ├── tool_result_budget.py    # 不动(已有 enforce_budget)
│   ├── autocompact.py           # 不动(已有 9 章节摘要,改成通用对话摘要)
│   └── prompts.py               # 改:9 章节模板改成通用对话摘要模板
├── session_memory/
│   ├── template.py              # 改:10 章节模板改成通用 coding 笔记
│   ├── service.py               # 不大动,但加 read_for_compaction 内容注入主 prompt
│   └── forked_agent.py          # 不动
├── storage/paths.py             # 改:删 doc_dir / session_memory_path 调整为通用
└── types.py                     # 改:删 DocTree/DocSection/MechanismCandidate 等,加新工具相关
```

### 要加

```
src/taisang/agent_core/
├── tools.py 里新增:
│   ├── EditTool          # old_string → new_string 改文件,用户确认
│   ├── WriteTool         # 创建/覆盖文件,用户确认
│   └── BashTool          # 跑 shell,白名单 + 限定 cwd
└── confirm.py            # 交互式确认(prompt)的统一入口
```

---

## Task 列表(8 个 task)

### Task 1:删 doc 相关代码

**依赖:** 无
**Files:**
- Delete: `src/taisang/outliner/` 整个目录
- Delete: `src/taisang/deepwriter/` 整个目录
- Delete: `src/taisang/docgen/` 整个目录
- Delete: `src/taisang/summarizer/` 整个目录
- Delete: `src/taisang/compaction/microcompact.py`
- Delete: `eval/` 整个目录
- Delete: `tests/unit/test_outliner_*.py` (4 个)
- Delete: `tests/unit/test_deepwriter.py`
- Delete: `tests/unit/test_docgen.py`
- Delete: `tests/unit/test_summarizer.py`
- Delete: `tests/unit/test_compaction_microcompact.py`
- Delete: `tests/integration/test_doc_pipeline.py`
- Delete: `tests/integration/test_doc_update.py`
- Modify: `src/taisang/types.py` —— 删 DocTree/DocSection/EntryPoint/MechanismCandidate/FlowCandidate/ModuleCandidate/Outline
- Modify: `src/taisang/storage/paths.py` —— 删 doc_dir / observations_dir 调整(observations 仍要,给 apply-tool-result-budget)
- Modify: `src/taisang/cli/main.py` —— 删 cmd_doc / cmd_index / _make_progress / doc 相关 import
- Modify: `tests/integration/test_end_to_end.py` —— 删 doc 相关,留 indexer/linker
- Modify: `tests/unit/test_cli.py` —— 删 doc 测试
- Modify: `tests/unit/test_agent_core.py` —— 删 doc 工具测试

**Steps:**
1. 用 git rm 删文件
2. 改 types.py / paths.py / cli/main.py / 测试,清理 import
3. 跑 pytest 看哪些测试因 import 残留报错
4. 修 import 错误
5. 跑 pytest 看通过(只剩 indexer/linker/compaction/session_memory/config/agent_core 基础测试)
6. Commit: `refactor: 删除文档生成相关代码,为 coding agent 重构让路`

---

### Task 2:加 EditTool / WriteTool

**依赖:** Task 1
**Files:**
- Modify: `src/taisang/agent_core/tools.py`
- Create: `src/taisang/agent_core/confirm.py`
- Modify: `tests/unit/test_agent_core.py`(或新建 `tests/unit/test_tools_edit_write.py`)

**EditTool 设计:**
```python
class EditTool(_BaseTool):
    name = "Edit"
    
    def __init__(self, source_root: Path, confirmer):
        self.source_root = source_root
        self.confirmer = confirmer  # callable(file_path, old, new) -> bool
    
    def schema(self):
        return {
            "name": "Edit",
            "description": "用 old_string 替换 new_string 改文件。old_string 必须唯一。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "相对 cwd 的路径"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        }
    
    def run(self, args):
        path = args.get("file_path", "")
        full = self.source_root / path
        if not _is_within(self.source_root, full):
            return {"ok": False, "error": "path outside cwd"}
        if not full.exists():
            return {"ok": False, "error": f"file not found: {path}"}
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        content = full.read_text(encoding="utf-8")
        if old not in content:
            return {"ok": False, "error": "old_string not found"}
        if content.count(old) > 1:
            return {"ok": False, "error": "old_string not unique"}
        # 用户确认
        if not self.confirmer(str(full), old, new):
            return {"ok": False, "error": "user denied"}
        new_content = content.replace(old, new, 1)
        full.write_text(new_content, encoding="utf-8")
        return {"ok": True, "path": str(full), "bytes_changed": len(new) - len(old)}
```

**WriteTool 设计:**
```python
class WriteTool(_BaseTool):
    name = "Write"
    
    def __init__(self, source_root: Path, confirmer):
        self.source_root = source_root
        self.confirmer = confirmer
    
    def schema(self):
        return {
            "name": "Write",
            "description": "创建或覆盖文件。慎用,会覆盖已有内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        }
    
    def run(self, args):
        path = args.get("file_path", "")
        full = self.source_root / path
        if not _is_within(self.source_root, full):
            return {"ok": False, "error": "path outside cwd"}
        content = args.get("content", "")
        # 用户确认
        if not self.confirmer(str(full), "", content):
            return {"ok": False, "error": "user denied"}
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(full), "bytes": len(content)}
```

**confirm.py 设计:**
```python
"""交互式确认入口。agent 改文件前调用,用户 y/n 确认。"""
import sys

def default_confirmer(file_path: str, old: str, new: str) -> bool:
    """默认确认器:打印 diff 概要,stdin 读 y/n。"""
    print(f"\n[CONFIRM] agent wants to edit: {file_path}")
    if old:
        print(f"  replace ({len(old)} chars): {old[:80]!r}...")
        print(f"  with    ({len(new)} chars): {new[:80]!r}...")
    else:
        print(f"  write new file ({len(new)} chars)")
    try:
        ans = input("  allow? (y/N): ").strip().lower()
        return ans == "y"
    except (EOFError, KeyboardInterrupt):
        return False

class AutoApproveConfirmer:
    """测试用:无脑同意所有改动。"""
    def __call__(self, file_path: str, old: str, new: str) -> bool:
        return True

class AutoDenyConfirmer:
    """测试用:无脑拒绝所有改动。"""
    def __call__(self, file_path: str, old: str, new: str) -> bool:
        return False
```

**Steps:**
1. 写 confirm.py
2. 写 EditTool + WriteTool
3. 写测试(test_edit_tool / test_write_tool / test_edit_path_traversal / test_edit_user_denies / test_edit_old_not_unique / test_write_user_denies)
4. Commit: `feat(tools): 加 Edit/Write 工具 + 用户确认机制`

---

### Task 3:加 BashTool

**依赖:** Task 2
**Files:**
- Modify: `src/taisang/agent_core/tools.py`
- Create: `tests/unit/test_tools_bash.py`

**BashTool 设计:**
```python
import subprocess

# 命令白名单:前缀匹配
_BASH_COMMAND_WHITELIST = [
    "git ",
    "python ",
    "python3 ",
    "pytest",
    "pip ",
    "ls",
    "cat ",
    "echo ",
    "grep ",
    "find ",
    "ruff",
    "black",
    "pwd",
    "mkdir ",
    "touch ",
]

class BashTool(_BaseTool):
    name = "Bash"
    
    def __init__(self, source_root: Path, timeout: int = 30):
        self.source_root = source_root
        self.timeout = timeout
    
    def schema(self):
        return {
            "name": "Bash",
            "description": "执行 shell 命令。命令必须在白名单内,且在当前 repo 目录跑。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "shell 命令"},
                },
                "required": ["command"],
            },
        }
    
    def run(self, args):
        command = args.get("command", "").strip()
        if not command:
            return {"ok": False, "error": "empty command"}
        # 白名单检查
        if not any(command.startswith(prefix) or command == prefix.strip() 
                   for prefix in _BASH_COMMAND_WHITELIST):
            return {"ok": False, "error": f"command not in whitelist: {command[:50]}"}
        # 跑命令
        try:
            result = subprocess.run(
                command, shell=True, cwd=str(self.source_root),
                capture_output=True, text=True, timeout=self.timeout,
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout[:5000],   # 截断保护
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {self.timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
```

**Steps:**
1. 写 BashTool
2. 写测试(test_bash_git_status / test_bash_not_in_whitelist_denied / test_bash_timeout / test_bash_cwd_enforced)
3. Commit: `feat(tools): 加 Bash 工具 + 命令白名单 + cwd 限定`

---

### Task 4:改 agent system prompt + 简化 AgentService.run

**依赖:** Task 1, Task 2, Task 3
**Files:**
- Modify: `src/taisang/agent_core/prompts.py`
- Modify: `src/taisang/agent_core/service.py`
- Modify: `src/taisang/agent_core/tools.py`(ToolRegistry)

**新 SYSTEM_PROMPT:**
```python
SYSTEM_PROMPT = """你是一个 coding agent,跟用户对话,帮助用户读写、修改、调试代码。

工作模式:
- 用户说一个目标,你调工具查 / 改 / 跑代码
- 每次工具调用后,告诉用户你做了什么、结果如何
- 信息够了或任务完成,给最终答复

工具:
- Read(path):读文件
- Edit(file_path, old_string, new_string):改文件(用户会确认)
- Write(file_path, content):创建/覆盖文件(用户会确认)
- Grep(pattern, scope):正则搜
- Glob(pattern):文件名匹配
- Bash(command):跑 shell 命令(白名单内,限定 cwd)

约束:
- Edit/Write 会触发用户确认,被拒绝就换方案,不要硬来
- Bash 只能跑白名单命令(git/python/pytest/ls/cat 等),危险命令会被拒
- 改代码前先 Read 确认上下文,不要瞎改
- 用 [file:line] 引用代码位置

语言:跟用户同语言(中文或英文)。
"""
```

**新 AgentService.run:**
```python
class AgentService:
    def __init__(
        self,
        llm,
        source_root: Path,
        confirmer,            # ← 新增:Edit/Write 确认器
        session_memory=None,
        compaction_state=None,
        max_steps: int = 50,
        token_budget: int = 32_000,
    ):
        ...
    
    def run(self, query: str, on_event=None) -> Answer:
        ctx = ContextManager(token_budget=self.token_budget)
        ctx.append_system(SYSTEM_PROMPT)
        ctx.append_user(query)
        
        registry = ToolRegistry(
            source_root=self.source_root,
            confirmer=self.confirmer,
        )
        observations_dir = PathManager.observations_dir(self.source_root)
        transcript_path = PathManager.index_dir(self.source_root) / "sessions" / "current.jsonl"
        
        steps = 0
        tool_calls_since_last_extract = 0
        while steps < self.max_steps:
            steps += 1
            # 阶段 5: apply-tool-result-budget
            new_msgs, _ = enforce_budget(ctx.messages(), self.compaction_state, observations_dir)
            ctx.replace_messages(new_msgs)
            # 阶段 7: autocompact
            if ctx.should_compact():
                if self._try_autocompact(ctx, transcript_path, on_event):
                    tool_calls_since_last_extract = 0
                    continue
            _emit(on_event, AgentEvent(type=LLM_THINKING))
            try:
                resp = self.llm.chat(messages=ctx.messages(), tools=registry.schemas())
            except (LLMProtocolError, LLMTransientError, LLMError) as e:
                return Answer(text=f"(LLM 错误: {e})", citations=[], complete=False, steps_used=steps)
            if not resp.tool_calls:
                _emit(on_event, AgentEvent(type=FINAL_ANSWER, payload={"text": resp.text}))
                return Answer(text=resp.text, citations=self._extract_citations(resp.text),
                              complete=True, steps_used=steps)
            ctx.append_assistant(text=resp.text, tool_calls=resp.tool_calls)
            for i, tc in enumerate(resp.tool_calls):
                name = tc.get("name", "<unknown>")
                args = tc.get("args") or {}
                _emit(on_event, AgentEvent(type=TOOL_CALL, payload={"name": name, "args": args}))
                result = registry.call(name, args)
                observation = json.dumps(result, ensure_ascii=False)
                ctx.append_tool_result(observation, name=name, tool_call_id=f"{name}-{i}")
                tool_calls_since_last_extract += 1
            # session memory post-sampling
            if self.session_memory and self.session_memory.should_extract(
                ctx.total_tokens(), tool_calls_since_last_extract
            ):
                self.session_memory._do_extract(recent_conversation=self._recent_text(ctx))
                # 注入主 prompt(闭环)
                summary = self.session_memory.read_for_compaction()
                if summary:
                    ctx._messages.insert(1, {"role": "user", "content": f"[session memory]\n{summary}"})
                tool_calls_since_last_extract = 0
        return Answer(text="(达到最大步数)", citations=[], complete=False, steps_used=steps)
```

**Steps:**
1. 改 prompts.py
2. 改 service.py(去 doc 分支,加 confirmer 参数,session_memory 注入)
3. 改 tools.py ToolRegistry(接 confirmer,注册新工具)
4. 改测试 test_agent_core.py(用新签名)
5. Commit: `feat(agent_core): 改成通用 coding agent,简化主循环`

---

### Task 5:改 compaction autocompact prompts(从 9 章节模板 → 通用对话摘要)

**依赖:** Task 4
**Files:**
- Modify: `src/taisang/compaction/prompts.py`
- Modify: `src/taisang/session_memory/template.py`
- Modify: `tests/unit/test_compaction_autocompact.py`
- Modify: `tests/unit/test_session_memory.py`

**新 BASE_COMPACT_PROMPT:**
```python
BASE_COMPACT_PROMPT = """你的任务是创建一份到目前为止对话的详细摘要,让 agent 在压缩后能继续帮用户处理代码任务。

摘要应包含:
1. 用户的目标(在做什么)
2. 已经完成的步骤(改了哪些文件、跑了什么命令)
3. 还没完成的步骤
4. 关键文件清单(路径 + 一句话用途)
5. 关键决策点(为什么这么改)
6. 当前状态(下一步该做什么)
7. 注意事项(用户偏好、踩坑点)
"""
```

**新 session_memory DEFAULT_TEMPLATE:**
```python
DEFAULT_TEMPLATE = """# Session Title
*当前在帮用户做什么*

# Current Goal
*用户的目标*

# Completed Steps
*已经完成的步骤(改了哪些文件 / 跑了什么命令)*

# Pending Steps
*还没做的事*

# Files Touched
*改过的关键文件 + 一句话用途*

# Key Decisions
*关键决策点(为什么这么改)*

# Errors & Corrections
*踩过的坑、用户纠正过的事*

# User Preferences
*用户偏好(代码风格、命名习惯等)*

# Learnings
*这个 repo 的特殊性*

# Worklog
*步骤流水(每 3 次工具调用追加一条)*
"""
```

**Steps:**
1. 改 compaction/prompts.py(9 章节模板 → 7 项通用摘要)
2. 改 session_memory/template.py(10 章节 → 10 章节通用 coding 笔记,内容大调)
3. 改相关测试断言
4. Commit: `refactor(compaction+session_memory): 模板改成通用 coding 场景`

---

### Task 6:CLI 改 REPL

**依赖:** Task 4, Task 5
**Files:**
- Modify: `src/taisang/cli/main.py`
- Modify: `src/taisang/__main__.py`
- Modify: `tests/unit/test_cli.py`

**REPL 设计:**
```python
@cli.command()
@click.option("--repo", default=".", help="工作目录(默认当前目录)")
def chat(repo: str):
    """进入交互式 coding agent。"""
    source_root = _normalize_path(repo)
    if not source_root.is_dir():
        click.echo(f"错误:{source_root} 不是目录", err=True)
        sys.exit(1)
    
    llm = _make_llm()
    confirmer = default_confirmer  # 交互式 y/n
    session_mem = SessionMemoryService(
        llm=llm,
        memory_path=PathManager.session_memory_path(source_root, "main"),
    )
    session_mem.ensure_file()
    
    agent = AgentService(
        llm=llm, source_root=source_root,
        confirmer=confirmer,
        session_memory=session_mem,
    )
    
    click.echo(f"taisang agent @ {source_root}")
    click.echo("输入 /exit 退出,/reset 清上下文")
    
    while True:
        try:
            query = click.prompt(">", type=str).strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nbye")
            break
        if not query:
            continue
        if query == "/exit":
            break
        if query == "/reset":
            # TODO: 清 session memory + 重启 agent
            click.echo("(重置)")
            continue
        # 跑 agent
        def _render(evt):
            if evt.type == LLM_THINKING:
                click.echo("  [thinking]")
            elif evt.type == TOOL_CALL:
                click.echo(f"  [tool] {evt.payload['name']} {evt.payload['args']}")
            elif evt.type == TOOL_RESULT:
                p = evt.payload
                click.echo(f"  [result] {p['name']} ({p['total_bytes']} bytes)")
            elif evt.type == FINAL_ANSWER:
                click.echo("")
                click.echo(p["text"])
        answer = agent.run(query, on_event=_render)
        if not answer.complete:
            click.echo(f"(incomplete: {answer.text})")
```

**入口:**
```python
# src/taisang/cli/main.py
@click.group()
def cli():
    """Code Reader Agent - 简化版 coding agent。"""

# 直接 `taisang` 进 REPL(无子命令时进 chat)
# 或者 `taisang chat` 进 REPL
```

**Steps:**
1. 改 cli/main.py(删 cmd_doc/cmd_index,加 chat REPL)
2. 改 __main__.py(不变,仍调 cli)
3. 改 test_cli.py(测 chat 命令能进)
4. 手测:python -m taisang chat --repo D:/Project/rpa-mcp,输入"读 README.md" 看响应
5. Commit: `feat(cli): REPL 交互式 coding agent`

---

### Task 7:types.py 清理 + 整体测试通过

**依赖:** Task 6
**Files:**
- Modify: `src/taisang/types.py`
- Modify: 各测试文件
- Run: `ruff check` / `black --check` / `pytest`

**Steps:**
1. 清 types.py(删 doc 相关类型,确认 RepoMap/RepoIndex/Symbol/CallGraphNode 保留)
2. 清理 import 残留
3. 跑 pytest 全绿
4. 跑 ruff + black 全绿
5. Commit: `chore: 清理 types.py + 测试全绿`

---

### Task 8:更新 README + 最终手测

**依赖:** Task 7
**Files:**
- Modify: `README.md`(如果有)
- Run: 手测 REPL

**手测清单:**
1. `cd D:/Project/rpa-mcp`
2. `python -m taisang chat`
3. 问:"这个项目是干啥的?"
4. 问:"读 README.md 给我总结"
5. 问:"grep 一下 'def main' 找入口"
6. 问:"改 README.md 第一行加个注释"——验证用户确认流程
7. 问:"跑 git status"——验证 Bash 工具
8. 长对话 30+ 轮——验证 autocompact 触发
9. 验证 session memory 笔记有内容

**Steps:**
1. 改 README
2. 手测
3. 修发现的问题
4. Commit: `docs: 更新 README + 手测通过`

---

## 风险点

1. **用户确认 prompt 在 REPL 里需要 stdin 可用**——非交互场景(测试)要注入 mock confirmer。已设计 `AutoApproveConfirmer` / `AutoDenyConfirmer`。
2. **Bash 在 Windows 上的命令差异**——白名单要兼容 Windows(`dir` 而非 `ls`?或者用 git bash)。v0.1 简化:只支持 git/python/pytest/ruff/black/pwd/echo,跨平台都稳。
3. **session_memory 注入主 prompt 的位置**——直接插 ctx._messages[1] 可能干扰 system prompt。改:在 append_user 时合并注入。
4. **autocompact 触发后丢失上下文**——如果用户在问"改 a.py 第 5 行",autocompact 把 a.py 内容压没了,agent 就不知道改哪。解决:autocompact 摘要里保留"用户最近请求 + 待改文件清单"。

---

## 执行方式

按 Subagent-Driven Development,每个 task 一个 subagent 跑完 + commit。8 个 task 预计 6-8 次 subagent 调用。完成后整体手测。

**目标 commit 数:** 8 个(每个 task 一个)。
**目标测试数:** 之前 167 个,删 doc 相关后剩 ~80 个,加新工具测试到 ~100 个。