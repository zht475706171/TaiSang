# Session 对话持久化 + Resume 设计

**日期**: 2026-09-02
**状态**: 已实施(2026-09-02)
**作者**: 泰哥 + Claude

## 背景

当前 `AgentService.ctx`(`ContextManager`)只持有内存态 messages,进程重启或切换会话后历史丢失。`.taisang/sessions/<id>/` 目录只有 `session-memory/`(LLM 抽取笔记),没有对话 transcript。

**现状问题**:
1. Web UI 点击左侧历史会话,消息区空白(切不过去),因为前端只开 SSE 听新事件,不加载历史
2. 进程重启后所有对话彻底丢失,ctx 是空的
3. `SessionRegistry.list_all` 用目录 mtime 当 updated_at,不准(子目录文件变动不更新父目录 mtime)
4. title 首条 query 定死,不随对话演进

## 目标

- 对话内容持久化到磁盘,进程重启后能完整 resume
- Web UI 点击历史会话能看到完整对话 + 继续对话
- title 跟着最后 user query 动态更新(对齐 Claude Code 主路径)
- 零外部依赖(纯 Python 标准库 + 现有 fastapi)

## 参考标杆

Claude Code 源码 `D:/GoProject/claude-code/src/utils/sessionStorage.ts`(5105 行) + `sessionRestore.ts`(551 行)。本设计对齐其主路径,简化非必要特性。

## 决策汇总

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | 持久化范围 | user / assistant / tool_result(嵌 content)/ compacted boundary / session 元数据 | 对齐 Claude Code,不存 thinking/usage/confirm 瞬态 |
| 2 | 存储方案 | 纯 JSONL | 零依赖、append 顺序写最快、人类可读、崩溃容忍好、易升级 |
| 3 | resume 灌回 | 全量灌回(压缩后快照) | 对齐 Claude Code,简单,token 量可控 |
| 4 | 写盘时机 | 每条 message 立即 append | 崩溃丢数据最少,Claude Code 验证过 |
| 5 | 元数据存储 | 单独 `meta.json` 文件,turn 结束整体重写 | list_all 读定长小文件干净,不用倒扫 jsonl |
| 6 | title 策略 | 跟着最后 user query 前 40 字,零 LLM 调用 | 对齐 Claude Code 主路径,YAGNI 豆包式 AI 总结 |
| 7 | 整体架构 | 方案 1 — ContextManager 加 `on_append` 回调 | 内存磁盘原子同步,改动小,可测试 |

## 持久化范围(详)

**持久化**:
- `user` message(含 tool_result 嵌在 content blocks 里,对齐 OpenAI message 格式)
- `assistant` message(含 tool_calls 嵌在 content blocks 里)
- `system` message(compacted boundary 标记)
- session 元数据(title / last_prompt / created_at / updated_at)→ 单独 meta.json

**不持久化**:
- thinking / loading 瞬态(Claude Code 也不存)
- usage token 数字(每轮重新算)
- confirm / permission 卡片状态(瞬时 UI 元素)
- file-history-snapshot(留给未来 undo 扩展点,这次不做)

## 存储格式

### conversation.jsonl

每行一条 record,append-only。格式:

```json
{"type":"user","role":"user","content":"...","uuid":"...","timestamp":1693622400.123}
{"type":"assistant","role":"assistant","content":"...","tool_calls":[...],"uuid":"...","timestamp":...}
{"type":"tool","role":"tool","name":"read_file","content":"...","tool_call_id":"...","uuid":"...","timestamp":...}
{"type":"system","role":"system","content":"[compacted via llm]","timestamp":...}
```

**字段规则**:
- `type`: `user` / `assistant` / `tool` / `system`(对齐 OpenAI message role,灌回 ctx 直接用)
- `role` + `content` + `tool_calls` + `tool_call_id` + `name`: 跟 `ctx.messages()` dict 字段一致
- `uuid`: uuid4 hex,每条唯一(未来 fork/undo 用,这次只用 uuid,不建 parentUuid 链)
- `timestamp`: `time.time()` float 秒

**compacted boundary record**:
- `{type: "system", role: "system", content: "[compacted via llm]"}` 或 `[compacted via session_memory]`
- 灌回 ctx 时**跳过这条不灌**(UI 标记,不是真 message)
- UI 渲染时显示"上下文已压缩"分隔符

**不存** `cwd` / `gitBranch` / `version` / `sessionId`(Claude Code 存是跨项目 resume,我们单项目不需要)

### meta.json

```json
{
  "id": "83302207",
  "title": "帮我看看这个文件",
  "last_prompt": "帮我看看这个文件",
  "created_at": 1693622400.0,
  "updated_at": 1693622400.123
}
```

- `title`: 动态更新,取最后一条 user query 前 40 字(对齐 Claude Code + 现有 `set_title_from_query` 逻辑)
- `last_prompt`: 最后一条 user query 全文(截 200 字,给 list_all 显示用)
- 每次 turn 结束 `write_meta` 整体重写(tmp + os.replace 原子替换)

### session 目录结构

```
.taisang/sessions/<id>/
├── conversation.jsonl   # 新增:对话 transcript
├── meta.json            # 新增:session 元数据
└── session-memory/      # 已有:LLM 抽取笔记(autocompact 用)
    └── summary.md
```

## 组件架构

### 新增组件

**`ConversationStore`** — 新文件 `src/taisang/storage/conversation_store.py`

职责:单个 session 的 jsonl + meta.json 读写。

接口:
```python
class ConversationStore:
    def __init__(self, session_id: str, sessions_dir: Path) -> None: ...

    def append(self, record: dict) -> None:
        """追加一行到 conversation.jsonl。append 模式,单行 write 原子。"""

    def load_all(self) -> list[dict]:
        """读 conversation.jsonl 全文,逐行 json.loads。
        损坏行跳过 + log warning,不抛异常。文件不存在返回 []。"""

    def load_meta(self) -> dict | None:
        """读 meta.json。损坏/不存在返回 None。"""

    def write_meta(self, meta: dict) -> None:
        """整体重写 meta.json。tmp 文件 + os.replace 原子替换。"""
```

纯文件 IO,无状态。线程安全靠 append 模式原子性 + meta.json 原子替换。

### 现有组件改造

**`ContextManager`** — `src/taisang/agent_core/context.py`

改造点:
1. 构造加 `on_append: Callable[[dict], None] | None = None` 参数
2. 4 个 append 方法(`append_system` / `append_user` / `append_assistant` / `append_tool_result`)各加:
   ```python
   if self.on_append:
       self.on_append(msg)
   ```
3. `replace_messages` 加 compaction boundary 逻辑:
   ```python
   def replace_messages(self, new_messages, compaction_via: str | None = None):
       if self.on_append and compaction_via:
           self.on_append({"type":"system","role":"system","content":f"[compacted via {compaction_via}]"})
           for msg in new_messages:
               self.on_append(msg)
       self._messages = list(new_messages)
   ```
   **调用点改造**:`AgentService` 现有两处 `ctx.replace_messages(...)` 调用要加 `compaction_via` 参数:
   - `service.py:169`(`_try_autocompact` 内的 autocompact 路径)→ `compaction_via="llm"`
   - `service.py:343`(`do_autocompact` 调用后)→ `compaction_via="llm"`
   - session_memory 触发的压缩(若有)→ `compaction_via="session_memory"`
   - resume 灌回时的 `load_from_records` 不走 `replace_messages`,直接赋值,不会误写 boundary
4. 新增 `load_from_records(records: list[dict])`:
   ```python
   def load_from_records(self, records: list[dict]) -> None:
       """resume 灌回专用,直接赋值 _messages,不走 on_append(避免重复写盘)。
       过滤掉 compacted boundary record(type=system 且 content 以 [compacted 开头)。"""
       self._messages = [r for r in records if not _is_boundary(r)]
   ```

**`SessionRegistry`** — `src/taisang/web/session_registry.py`

改造点:
1. `_build_session` 构造 `ConversationStore`,注入 `ContextManager.on_append`:
   ```python
   store = ConversationStore(session_id, self.source_root / ".taisang" / "sessions")
   agent = AgentService(..., ctx=ContextManager(on_append=store.append))
   # 或 AgentService 内部构造 ctx 时注入,取决于现有构造方式
   ```
2. `get_or_load` lazy 重建时灌回:
   ```python
   sess = self._build_session(session_id)
   records = sess.store.load_all()
   sess.agent.ctx.load_from_records(records)
   ```
3. `list_all` 改读 `meta.json`(替代扫目录 mtime):
   - 扫 `.taisang/sessions/*/` 目录拿 session id 列表(不变)
   - 每个 session 读 `meta.json` 拿 title / updated_at / last_prompt
   - meta.json 损坏/不存在 fallback 用目录 mtime + id 当 title
4. turn 结束写 meta.json(在 `AgentService.run` 结束处或 `SessionRegistry` 包一层):
   ```python
   meta = {
       "id": session_id,
       "title": _derive_title(last_user_query),  # 前 40 字
       "last_prompt": last_user_query[:200],
       "created_at": sess.created_at,
       "updated_at": time.time(),
   }
   store.write_meta(meta)
   ```

**`app.py`** — 新增 `GET /api/sessions/{id}/messages`

```python
@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str) -> list[dict]:
    sess = registry.get_or_load(session_id)
    if sess is None:
        raise HTTPException(404, f"session not found: {session_id}")
    return sess.store.load_all()
```

**前端 `index.html`**

改造点:
1. `switchSession` 里 `openEventStream` 前先拉历史:
   ```javascript
   async function switchSession(id, title) {
     if (eventSource) eventSource.close();
     currentSessionId = id;
     // ... title 更新逻辑不变 ...
     document.getElementById('messages').innerHTML = '';
     const r = await fetch(`/api/sessions/${id}/messages`);
     const history = await r.json();
     renderHistory(history);          // 新增
     openEventStream(id);
   }
   ```
2. 新增 `renderHistory(messages)`:
   - 遍历 records,按 type 分发到现有 render 函数
   - `user` → 渲染用户气泡(复用现有 user 气泡渲染)
   - `assistant` → `renderFinalAnswer({text: msg.content})`(复用)
   - `tool` → `renderToolResult({name, preview, total_bytes})`(复用,从 content 算 preview)
   - `system` 且 content 以 `[compacted` 开头 → 渲染"上下文已压缩"分隔符(复用 `renderCompacted`)

## 数据流

### 写(对话进行时)

```
user query → AgentService.run()
  → ctx.append_user(query)
     → 内存 _messages += [user msg]
     → on_append(user msg) → ConversationStore.append → conversation.jsonl += 1 行
  → LLM 返回 → ctx.append_assistant(text, tool_calls)
     → 内存 += [assistant msg]
     → on_append(assistant msg) → jsonl += 1 行
  → 工具执行 → ctx.append_tool_result(...)
     → 内存 += [tool msg]
     → on_append(tool msg) → jsonl += 1 行
  → autocompact 触发 → ctx.replace_messages(new_msgs, compaction_via="llm")
     → on_append(system "[compacted via llm]") → jsonl += 1 行(boundary)
     → for msg in new_msgs: on_append(msg) → jsonl += N 行
     → 内存 = new_msgs
  → run() 结束 → SessionRegistry 更新 meta.json(title=最后 user query 前40字, updated_at=now)
```

### 读(resume 时)

```
用户点会话 → SessionRegistry.get_or_load(id)
  → _build_session() 造 AgentService + ConversationStore
  → store.load_all() 读 conversation.jsonl 全文 → list[dict]
  → ctx.load_from_records(records)  过滤 boundary,直接赋值 _messages(不触发 on_append)
  → 前端 GET /api/sessions/{id}/messages
    → store.load_all() → 返回 JSON
    → 前端 renderHistory() 渲染气泡 + 工具卡片 + 压缩分隔符
    → openEventStream(id) 开 SSE 接新事件
```

## 错误处理 + 边界情况

1. **jsonl 解析失败**(文件损坏/截断):`load_all` 逐行 `json.loads`,失败的行跳过 + log warning,不抛异常。读完能拿多少拿多少
2. **meta.json 损坏**:`load_meta` try/except,损坏返回 None,`list_all` fallback 用目录 mtime + id 当 title
3. **jsonl 不存在**(新建会话):`load_all` 返回 `[]`,正常走空会话路径
4. **resume 灌回不触发 on_append**:用 `load_from_records` 方法,直接赋值 `self._messages`,绕过 on_append
5. **并发写**:同一 session 的 AgentService 有 per-session Lock(已有),append 串行化,无并发写。不同 session 不同文件,无竞争
6. **大 tool_result**:service.py 已截断到 30KB(`_MAX_OBSERVATION_BYTES`),inline 存 jsonl 无压力
7. **删除会话**:`SessionRegistry.delete` 已有 `shutil.rmtree` 删整个 session 目录,jsonl + meta.json 一起删,不用改

## 测试策略

### 单元测试

**`test_conversation_store.py`**(新增):
- append + load_all 往返一致
- 损坏行跳过不抛异常
- meta.json 原子写(tmp + replace)
- 文件不存在时 load_all 返回 []、load_meta 返回 None

**`test_context_manager.py`**(补充):
- `on_append` 回调被调用,传入完整 record dict
- `replace_messages(new_msgs, compaction_via="llm")` 先写 boundary 再写新 messages
- `load_from_records` 过滤 boundary,直接赋值不触发 on_append

**`test_session_registry.py`**(补充):
- `get_or_load` lazy 重建时灌回历史(模拟重启)
- `list_all` 读 meta.json 拿 title/updated_at
- meta.json 损坏时 fallback 到目录 mtime

### 集成测试

- 跑一轮对话 → 新建 registry(模拟进程重启)→ `get_or_load` 灌回 → 验证 ctx 跟重启前一致
- autocompact 触发 → jsonl 有 boundary record + 新 messages → resume 灌回是压缩后的
- 前端 `switchSession` 拉历史 → 渲染完整对话

## 实施顺序

1. `ConversationStore` 类 + 单元测试
2. `ContextManager` 加 `on_append` + `load_from_records` + 单元测试
3. `SessionRegistry._build_session` 注入 store + `get_or_load` 灌回 + `list_all` 读 meta + 集成测试
4. `app.py` 加 `GET /api/sessions/{id}/messages`
5. 前端 `switchSession` 拉历史 + `renderHistory`
6. title 动态更新逻辑(turn 结束写 meta.json)

## 不做(YAGNI)

- **ai-title(LLM 总结)**:留扩展点,等基础持久化稳了再考虑。Claude Code 也没把 ai-title 当默认
- **file-history-snapshot + undo**:复杂度高,ROI 不明,留扩展点
- **parentUuid 链 + fork session**:这次只用 uuid,不建链。未来 fork 再加
- **跨项目 resume**(存 cwd/gitBranch/version):我们单项目不需要
- **content-replacement 外存**(大 tool_result 单独存):service.py 已截断到 30KB,inline 够用
- **sqlite 存储**:YAGNI,jsonl 够用且易升级

## 未来扩展点(不在这次范围)

- `ai-title` record 类型 + LLM 总结 title
- `file-history-snapshot` record + /undo 命令
- `parentUuid` 链 + `--fork-session` 分叉
- 全文搜索(从 jsonl 灌 sqlite 建 FTS 索引)