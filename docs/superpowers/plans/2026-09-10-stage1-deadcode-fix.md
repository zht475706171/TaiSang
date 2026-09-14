# Stage-1 enforce_budget 死代码修复（Plan D-full 对齐 claude-code）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 stage-1 enforce_budget 持久化在生产是死代码的问题（`_MAX_OBSERVATION_BYTES=32K < DEFAULT_PERSIST_THRESHOLD=50K`），通过对齐 claude-code 的截断架构：移除 service.py 硬截断、ReadFileTool 抛 FileTooLargeError 而非截断、ReadFileTool opt-out 持久化、observation 进 ctx 后由 enforce_budget 50K 阈值自然触发持久化。

**Architecture:** 三层独立闸门：(1) 每个工具自己的 `maxResultSizeChars` 属性决定是否截断/抛错/落盘，ReadFileTool=Infinity（永不持久化，256KB 抛 FileTooLargeError），BashTool 保持 30KB 落盘不变；(2) service.py 移除 `_MAX_OBSERVATION_BYTES` 硬截断，observation 原样进 ctx；(3) enforce_budget 在每轮 LLM 调用前检查 ctx 里所有 tool_result，单条 > 50K 且总轮超 200K 预算时持久化到磁盘 + 占位符替换。ReadFileTool 因 maxResultSizeChars=Infinity 被 enforce_budget 跳过（读回文件是循环，永不持久化）。

**Tech Stack:** Python 3.11+、pytest、pytest-asyncio、dataclass。无新依赖。

---

## 背景与问题诊断

### 当前架构问题

`src/taisang/agent_core/service.py:53` 定义 `_MAX_OBSERVATION_BYTES = 32_000`，在 `service.py:587-588` 把任何超过 32KB 的 observation 硬截断：

```python
observation = json.dumps(result, ensure_ascii=False)
total_bytes = len(observation.encode("utf-8"))
if total_bytes > _MAX_OBSERVATION_BYTES:
    observation = observation[:_MAX_OBSERVATION_BYTES] + '...{"_truncated": true}'
```

而 `src/taisang/compaction/tool_result_budget.py:28` 定义 `DEFAULT_PERSIST_THRESHOLD = 50_000`，enforce_budget 只持久化 > 50KB 的 tool_result。

**32KB < 50KB → 单条 observation 进 ctx 前就被截到 32KB，永远达不到 50KB 持久化阈值，stage-1 enforce_budget 持久化在生产是死代码。** 现有 Task 3 测试用 `monkeypatch _MAX_OBSERVATION_BYTES=200_000` 绕过验证。

### claude-code 的架构（参考）

- `D:\GoProject\claude-code\src\constants\toolLimits.ts`: `DEFAULT_MAX_RESULT_SIZE_CHARS=50_000`、`MAX_TOOL_RESULT_BYTES=400KB`、`MAX_TOOL_RESULTS_PER_MESSAGE_CHARS=200_000`
- `src/tools/FileReadTool/FileReadTool.ts:342`: `maxResultSizeChars: Infinity`（opt-out 持久化）
- `src/utils/readFileInRange.ts:95-102`: `!truncateOnByteLimit && stats.size > maxBytes` → 抛 `FileTooLargeError`（不截断）
- `src/utils/toolResultStorage.ts:59-64`: Read tool 通过 Infinity 检查 opt-out，理由"Read self-bounds via maxTokens; persisting its output to a file the model reads back with Read is circular"
- `src/utils/toolResultStorage.ts:309`: `const threshold = persistenceThreshold ?? MAX_TOOL_RESULT_BYTES`

### 目标架构（Plan D-full）

1. **ReadFileTool**: 默认读（不传 limit）时文件 > 256KB 抛 `FileTooLargeError`（不截断），observation 是 JSON `{"error": "file too large: 300KB > 256KB, use offset+limit"}`；传了 limit 时按行读，不受字节闸门，由 maxTokens 兜底（本 plan 暂不实现 token 兜底，保留按行读行为）。`maxResultSizeChars = Infinity`，enforce_budget 跳过持久化。
2. **BashTool**: 保持 `BASH_MAX_OUTPUT=30_000` 落盘 + `<persisted-output>` 包装不变。`maxResultSizeChars = 30_000`（对齐 claude-code BashTool），但 BashTool 自己已落盘，enforce_budget 见到的是 < 30KB 的包装结果，不会重复持久化。
3. **GrepTool / GlobTool / EditTool / WriteTool / TodoWriteTool**: 加 `maxResultSizeChars` 属性（Grep=20K、Glob=100K、Edit/Write/Todo=100K），enforce_budget 按此判断是否跳过。
4. **service.py**: 删除 `_MAX_OBSERVATION_BYTES` 常量 + 删除 `service.py:587-588` 的硬截断逻辑。observation 原样进 ctx。
5. **enforce_budget**: 检查 tool message 的 `name` 字段对应工具的 `maxResultSizeChars`，如果是 `Infinity` 则跳过（永不持久化）。持久化阈值保持 `DEFAULT_PERSIST_THRESHOLD=50_000` 不变。

### 文件结构

- **Modify** `src/taisang/agent_core/tools.py` — ReadFileTool 抛 FileTooLargeError + 所有 _BaseTool 加 maxResultSizeChars 类属性
- **Modify** `src/taisang/agent_core/service.py` — 删除 _MAX_OBSERVATION_BYTES 常量 + 删除硬截断逻辑
- **Modify** `src/taisang/compaction/tool_result_budget.py` — enforce_budget 按 tool name 查 maxResultSizeChars 跳过 Infinity 工具
- **Modify** `tests/unit/agent_core/test_tools.py` — ReadFileTool 256KB 抛错测试 + 其他工具 maxResultSizeChars 属性测试
- **Modify** `tests/unit/agent_core/test_service.py` — 移除 _MAX_OBSERVATION_BYTES 截断测试，加 observation 原样进 ctx 测试
- **Modify** `tests/unit/compaction/test_tool_result_budget.py` — enforce_budget 跳过 Read 工具测试 + 50K 阈值在生产能触发测试

---

### Task 1: _BaseTool 加 maxResultSizeChars 类属性 + 各工具设值

**Files:**
- Modify: `src/taisang/agent_core/tools.py:90-100`（_BaseTool）+ 各 Tool 子类
- Test: `tests/unit/agent_core/test_tools.py`

- [ ] **Step 1: 写失败测试 — _BaseTool 有 maxResultSizeChars 属性，默认 100_000**

```python
# tests/unit/agent_core/test_tools.py 末尾追加
def test_base_tool_default_max_result_size_chars():
    """_BaseTool 子类默认 maxResultSizeChars=100_000，可被覆写。"""
    # 用一个最小子类测试
    class _DummyTool(_BaseTool):
        name = "dummy"
    t = _DummyTool()
    assert t.max_result_size_chars == 100_000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/agent_core/test_tools.py::test_base_tool_default_max_result_size_chars -v`
Expected: FAIL with `AttributeError: '_DummyTool' object has no attribute 'max_result_size_chars'`

- [ ] **Step 3: 实现 — _BaseTool 加类属性 + 各子类覆写**

在 `src/taisang/agent_core/tools.py:90` `_BaseTool` 类里加：

```python
class _BaseTool:
    """工具基类。"""

    name: str = ""
    # 单条 observation 持久化阈值(字符数)。对齐 claude-code maxResultSizeChars。
    # - 默认 100_000:小结果工具(Edit/Write/Todo/Glob)
    # - Infinity:ReadFileTool(opt-out 永不持久化,读回文件是循环)
    # - 30_000:BashTool(自己已落盘,enforce_budget 见到的是包装结果)
    # - 20_000:GrepTool(对齐 claude-code GrepTool)
    max_result_size_chars: float = 100_000

    def schema(self) -> dict:
        raise NotImplementedError

    def run(self, args: dict) -> dict:
        raise NotImplementedError
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/agent_core/test_tools.py::test_base_tool_default_max_result_size_chars -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agent_core/tools.py tests/unit/agent_core/test_tools.py
git commit -m "refactor(tools): _BaseTool 加 max_result_size_chars 类属性默认 100K"
```

---

### Task 2: 各工具覆写 maxResultSizeChars（Read=Infinity, Bash=30K, Grep=20K）

**Files:**
- Modify: `src/taisang/agent_core/tools.py` — ReadFileTool/GrepTool/BashTool 类体
- Test: `tests/unit/agent_core/test_tools.py`

- [ ] **Step 1: 写失败测试 — 各工具 maxResultSizeChars 值正确**

```python
# tests/unit/agent_core/test_tools.py 追加
def test_read_file_tool_max_result_size_chars_infinity(tmp_path):
    from taisang.agent_core.permission import AutoApprovePermissionManager
    t = ReadFileTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    assert t.max_result_size_chars == float("inf")

def test_grep_tool_max_result_size_chars_20k(tmp_path):
    from taisang.agent_core.permission import AutoApprovePermissionManager
    t = GrepTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    assert t.max_result_size_chars == 20_000

def test_bash_tool_max_result_size_chars_30k(tmp_path):
    """BashTool 的 max_result_size_chars=30_000(自己已落盘,enforce_budget 见包装结果)。"""
    from taisang.agent_core.tools import BashTool
    # 用 None shell 构造会失败,改用 mock
    class _StubShell:
        def cwd(self): return tmp_path
        def run(self, cmd, timeout=None, cancel_event=None):
            return {"output": "", "ok": True, "returncode": 0}
    t = BashTool(_StubShell(), tmp_path / "obs")
    assert t.max_result_size_chars == 30_000

def test_glob_tool_max_result_size_chars_100k(tmp_path):
    from taisang.agent_core.permission import AutoApprovePermissionManager
    t = GlobTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    assert t.max_result_size_chars == 100_000

def test_edit_tool_max_result_size_chars_100k(tmp_path):
    from taisang.agent_core.permission import AutoApprovePermissionManager
    from taisang.agent_core.confirm import AutoDenyConfirmer
    t = EditTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]), AutoDenyConfirmer())
    assert t.max_result_size_chars == 100_000

def test_write_tool_max_result_size_chars_100k(tmp_path):
    from taisang.agent_core.permission import AutoApprovePermissionManager
    from taisang.agent_core.confirm import AutoDenyConfirmer
    t = WriteTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]), AutoDenyConfirmer())
    assert t.max_result_size_chars == 100_000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/agent_core/test_tools.py -k "max_result_size_chars" -v`
Expected: 6 个 FAIL（ReadFileTool 不是 inf、GrepTool 不是 20K、BashTool 不是 30K 等）

- [ ] **Step 3: 实现 — 各子类覆写 max_result_size_chars**

在 `src/taisang/agent_core/tools.py` 各子类的 `name = "..."` 下面加 `max_result_size_chars = ...`：

```python
class ReadFileTool(_BaseTool):
    name = "read_file"
    # Infinity:opt-out 持久化。Read 自管 256KB 抛错 + 按行读,
    # 持久化 Read 结果到文件再被 LLM 读回是循环,永不持久化。
    # 对齐 claude-code FileReadTool.ts:342 maxResultSizeChars: Infinity。
    max_result_size_chars = float("inf")
```

```python
class GrepTool(_BaseTool):
    name = "grep"
    # 对齐 claude-code GrepTool maxResultSizeChars=20_000。
    max_result_size_chars = 20_000
```

```python
class GlobTool(_BaseTool):
    name = "glob"
    max_result_size_chars = 100_000
```

```python
class EditTool(_BaseTool):
    name = "Edit"
    max_result_size_chars = 100_000
```

```python
class WriteTool(_BaseTool):
    name = "Write"
    max_result_size_chars = 100_000
```

```python
class BashTool(_BaseTool):
    name = "Bash"
    # 30_000:BashTool 自己已落盘超长输出到 .taisang/observations/,
    # enforce_budget 见到的是 < 30KB 的 <persisted-output> 包装结果,不会重复持久化。
    # 对齐 claude-code BashTool maxResultSizeChars=30_000。
    max_result_size_chars = 30_000
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/agent_core/test_tools.py -k "max_result_size_chars" -v`
Expected: 7 PASS（含 Task 1 的 default 测试）

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agent_core/tools.py tests/unit/agent_core/test_tools.py
git commit -m "refactor(tools): 各工具覆写 max_result_size_chars (Read=inf, Bash=30K, Grep=20K)"
```

---

### Task 3: ReadFileTool 默认读 > 256KB 抛 FileTooLargeError（不截断）

**Files:**
- Modify: `src/taisang/agent_core/tools.py:102-177`（ReadFileTool.run）
- Test: `tests/unit/agent_core/test_tools.py`

- [ ] **Step 1: 写失败测试 — 文件 > 256KB 抛错，observation 带 error 提示**

```python
# tests/unit/agent_core/test_tools.py 追加
def test_read_file_tool_throws_file_too_large_over_256kb(tmp_path):
    """文件 > 256KB 默认读(不传 limit)时,不截断,返回 error 提示用 offset+limit。
    
    对齐 claude-code readFileInRange.ts:95-102 抛 FileTooLargeError 行为。
    TaiSang 不抛 Python 异常(会破坏 tool dispatch),改返回 dict observation
    带 error 字段,LLM 见到 error 会下一轮用 offset+limit 重读。
    """
    from taisang.agent_core.permission import AutoApprovePermissionManager
    big_file = tmp_path / "big.txt"
    # 300KB 内容
    big_file.write_text("x" * (300 * 1024), encoding="utf-8")
    t = ReadFileTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    result = t.run({"path": "big.txt"})
    assert result["content"] == ""
    assert "file too large" in result["error"].lower()
    assert "offset" in result["error"].lower() or "limit" in result["error"].lower()
    assert result.get("truncated") is False  # 没截断,是 error

def test_read_file_tool_under_256kb_reads_full(tmp_path):
    """文件 < 256KB 默认读时,原样读全文(不截断)。"""
    from taisang.agent_core.permission import AutoApprovePermissionManager
    small_file = tmp_path / "small.txt"
    small_file.write_text("x" * (200 * 1024), encoding="utf-8")  # 200KB
    t = ReadFileTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    result = t.run({"path": "small.txt"})
    assert result["error"] is None
    assert result["truncated"] is False
    assert len(result["content"]) == 200 * 1024

def test_read_file_tool_256kb_boundary_passes(tmp_path):
    """文件正好 256KB 边界(< 256KB + 1 byte)应该能读。"""
    from taisang.agent_core.permission import AutoApprovePermissionManager
    boundary_file = tmp_path / "boundary.txt"
    boundary_file.write_text("x" * (256 * 1024), encoding="utf-8")  # 正好 256KB
    t = ReadFileTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    result = t.run({"path": "boundary.txt"})
    assert result["error"] is None
    assert result["truncated"] is False

def test_read_file_tool_with_limit_bypasses_256kb_gate(tmp_path):
    """传了 limit 时,不受 256KB 闸门,按行读(对齐 claude-code limit===undefined ? maxSizeBytes : undefined)。"""
    from taisang.agent_core.permission import AutoApprovePermissionManager
    big_file = tmp_path / "big.txt"
    # 300KB,10000 行(每行 30 字节)
    big_file.write_text("\n".join("x" * 29 for _ in range(10000)), encoding="utf-8")
    t = ReadFileTool(tmp_path, AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    result = t.run({"path": "big.txt", "offset": 100, "limit": 50})
    assert result["error"] is None
    assert result["limit"] == 50
    assert result["offset"] == 100
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/agent_core/test_tools.py -k "read_file_tool" -v`
Expected: 4 个 FAIL（`test_read_file_tool_throws_file_too_large_over_256kb` 期望 error 但当前是 truncated=True；其他 3 个可能因 32KB 截断失败）

- [ ] **Step 3: 实现 — ReadFileTool.run 改用 256KB 闸门 + 抛错不截断**

在 `src/taisang/agent_core/tools.py:102` ReadFileTool 类体里，类属性区加常量：

```python
class ReadFileTool(_BaseTool):
    name = "read_file"
    max_result_size_chars = float("inf")
    # 默认读(不传 limit)时的字节闸门。文件 > 256KB 返回 error 提示用 offset+limit,
    # 不截断(对齐 claude-code readFileInRange.ts:95-102 抛 FileTooLargeError)。
    # 传了 limit 时不受此闸门,按行读(由 LLM 自己控制读取范围)。
    _DEFAULT_READ_MAX_BYTES = 256 * 1024
```

把 `__init__` 的 `max_bytes` 参数默认值从 `32_000` 改成 `_DEFAULT_READ_MAX_BYTES`：

```python
    def __init__(
        self,
        cwd: Path,
        permission: PermissionManager,
        max_bytes: int = _DEFAULT_READ_MAX_BYTES,
    ) -> None:
        self.cwd = cwd
        self.permission = permission
        self.max_bytes = max_bytes
```

把 `run` 方法里"没传 limit 走字节闸门"分支（原 `tools.py:163-175`）改成抛错不截断：

```python
            # 没传 limit,走字节闸门
            data = text.encode("utf-8", errors="replace")
            if len(data) > self.max_bytes:
                # 文件太大,不截断,返回 error 让 LLM 下一轮用 offset+limit 重读。
                # 对齐 claude-code FileTooLargeError(不截断,直接拒绝)。
                return {
                    "content": "",
                    "truncated": False,
                    "total_lines": total_lines,
                    "offset": offset,
                    "error": (
                        f"file too large: {len(data):,} bytes > {self.max_bytes:,} bytes. "
                        f"use offset + limit to read a specific range."
                    ),
                }
            return {
                "content": data.decode("utf-8", errors="replace"),
                "truncated": False,
                "total_lines": total_lines,
                "offset": offset,
                "error": None,
            }
```

同步更新 schema description（`tools.py:127-132`）让 LLM 知道 limit 的语义：

```python
                    "limit": {
                        "type": "integer",
                        "description": (
                            "读多少行。不传则读全部(文件 > 256KB 时返回 error 提示用 offset+limit);"
                            "传了则按行读,不受 256KB 字节闸门"
                        ),
                    },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/agent_core/test_tools.py -k "read_file_tool" -v`
Expected: 全部 ReadFileTool 测试 PASS

- [ ] **Step 5: 跑全量测试确认没破坏其他**

Run: `pytest tests/unit/agent_core/test_tools.py -v`
Expected: 全 PASS（如有 BashTool 测试因 stub shell 调整，修测试）

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/tools.py tests/unit/agent_core/test_tools.py
git commit -m "feat(read_file): 默认读 > 256KB 抛 error 不截断,对齐 claude-code FileTooLargeError"
```

---

### Task 4: service.py 移除 _MAX_OBSERVATION_BYTES 硬截断

**Files:**
- Modify: `src/taisang/agent_core/service.py:53`（删常量）+ `service.py:585-588`（删截断逻辑）
- Test: `tests/unit/agent_core/test_service.py`

- [ ] **Step 1: 写失败测试 — observation 原样进 ctx 不截断**

```python
# tests/unit/agent_core/test_service.py 追加
def test_observation_not_truncated_by_service(monkeypatch, tmp_path):
    """service.py 不再硬截断 observation 到 32KB,observation 原样进 ctx。
    
    大 observation 由工具自己管(ReadFileTool 256KB 抛错,BashTool 30KB 落盘),
    以及 enforce_budget 50K 阈值持久化。service.py 不再加第二道 32KB 截断。
    """
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.context import ContextManager
    from taisang.agent_core.tools import ToolRegistry
    from taisang.agent_core.permission import AutoApprovePermissionManager
    
    # mock LLM:第一轮调 big_tool,第二轮给最终答案
    big_observation = "x" * 60_000  # 60KB,超过原 32KB 截断阈值
    class _MockLLM:
        def __init__(self):
            self.calls = 0
        def chat_stream(self, messages, tools, on_chunk=None):
            self.calls += 1
            if self.calls == 1:
                # 第一轮:调一个返回大 observation 的工具
                yield {"type": "tool_call", "tool_call": {"id": "tc1", "name": "big_tool", "arguments": {}}}
            else:
                yield {"type": "text", "text": "done"}
                yield {"type": "done"}
    
    class _BigTool:
        name = "big_tool"
        max_result_size_chars = 100_000
        def schema(self): return {"name": "big_tool", "description": "test", "parameters": {"type": "object", "properties": {}}}
        def run(self, args): return {"data": big_observation}
    
    # 构造最小 AgentService
    ctx = ContextManager(token_budget=200_000)
    registry = ToolRegistry(cwd=tmp_path, permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]))
    registry._tools["big_tool"] = _BigTool()
    # ... (用最小构造跑 run,断言 ctx 里 tool message content 长度 == 60_000 + JSON 包装,
    #      不再被截到 32KB)
    # 具体构造见现有 test_service.py 里的 mock 模式
    pass  # TODO: 实现时按现有 test_service.py mock 模式补全
```

> **注：** Step 1 的测试骨架需要在实现时按 `test_service.py` 现有 mock 模式补全 AgentService 构造。实现 subagent 应先读 `tests/unit/agent_core/test_service.py` 找到现有的 mock 构造模式（FakeLLM / FakeShell 等），照搬补全。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/agent_core/test_service.py::test_observation_not_truncated_by_service -v`
Expected: FAIL（当前 service.py:587-588 硬截断到 32KB，60KB observation 会变 32KB）

- [ ] **Step 3: 实现 — 删 service.py 常量 + 截断逻辑**

在 `src/taisang/agent_core/service.py:52-53` 删除：

```python
# observation 单条上限(字节)。超长截断以保护上下文预算。
_MAX_OBSERVATION_BYTES = 32_000
```

在 `service.py:585-588` 把截断逻辑删掉，observation 原样使用：

```python
                observation = json.dumps(result, ensure_ascii=False)
                total_bytes = len(observation.encode("utf-8"))
                # 移除 _MAX_OBSERVATION_BYTES 硬截断:
                # 工具自己管截断/抛错(ReadFileTool 256KB, BashTool 30KB 落盘),
                # enforce_budget 50K 阈值在每轮 LLM 调用前持久化大 observation。
                # service.py 不再加第二道 32KB 截断(会让 enforce_budget 50K 阈值永远触发不到)。
                _emit(
                    AgentEvent(
                        type=TOOL_RESULT,
                        payload={
                            "name": name,
                            "preview": observation[:30],
                            "total_bytes": total_bytes,
                        },
                    )
                )
```

- [ ] **Step 4: 跑 Step 1 测试确认通过**

Run: `pytest tests/unit/agent_core/test_service.py::test_observation_not_truncated_by_service -v`
Expected: PASS

- [ ] **Step 5: 跑全量 test_service.py 确认没破坏其他**

Run: `pytest tests/unit/agent_core/test_service.py -v`
Expected: 全 PASS（如有原 _MAX_OBSERVATION_BYTES 截断测试失败，删掉或改成测 observation 原样进 ctx）

- [ ] **Step 6: 跑全量测试套件确认没破坏其他**

Run: `pytest tests/unit -v`
Expected: 全 PASS 或仅有已知的 non-related 失败

- [ ] **Step 7: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/agent_core/test_service.py
git commit -m "refactor(service): 移除 _MAX_OBSERVATION_BYTES 硬截断,observation 原样进 ctx"
```

---

### Task 5: enforce_budget 按 tool name 查 maxResultSizeChars 跳过 Infinity 工具

**Files:**
- Modify: `src/taisang/compaction/tool_result_budget.py:43-126`（enforce_budget）
- Test: `tests/unit/compaction/test_tool_result_budget.py`

**背景：** 当前 enforce_budget 只按 `SKIP_TOOL_NAMES = {"write_doc", "list_pending_sections", "finalize_doc", "glob"}` 跳过工具。这是旧 doc 时代的白名单，新架构改成按工具的 `max_result_size_chars` 属性判断：Infinity 就跳过（Read 永不持久化）。但 enforce_budget 签名只收 `messages: list[dict]`，不持有工具实例，需要新增一个 `tool_size_limits: dict[str, float]` 参数（tool_name → maxResultSizeChars），由 service.py 调用时传入。

- [ ] **Step 1: 写失败测试 — Read 工具的 tool_result 永不持久化**

```python
# tests/unit/compaction/test_tool_result_budget.py 追加
def test_enforce_budget_skips_infinity_tools(tmp_path):
    """max_result_size_chars=Infinity 的工具(如 read_file)永不持久化,即使 > 50K 阈值。
    
    对齐 claude-code toolResultStorage.ts:59-64: Read opt-out 持久化,
    理由"Read self-bounds via maxTokens; persisting its output to a file
    the model reads back with Read is circular"。
    """
    from taisang.compaction.tool_result_budget import (
        ContentReplacementState, enforce_budget,
    )
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "x" * 60_000},
        {"role": "tool", "tool_call_id": "tc2", "name": "Bash", "content": "y" * 60_000},
    ]
    state = ContentReplacementState()
    # read_file=Infinity(跳过), Bash=30_000(参与持久化)
    tool_size_limits = {"read_file": float("inf"), "Bash": 30_000}
    new_msgs, replaced = enforce_budget(
        messages, state, tmp_path,
        budget_bytes=50_000,
        tool_size_limits=tool_size_limits,
    )
    # read_file(tc1) 不被持久化,content 原样
    assert new_msgs[0]["content"] == "x" * 60_000
    # Bash(tc2) > 30K + 总超 50K 预算,被持久化
    assert new_msgs[1]["content"] != "y" * 60_000
    assert any(r["tool_call_id"] == "tc2" for r in replaced)
    assert not any(r["tool_call_id"] == "tc1" for r in replaced)

def test_enforce_budget_default_tool_size_limits_100k(tmp_path):
    """没传 tool_size_limits 时,默认所有工具 max_result_size_chars=100_000(参与持久化)。"""
    from taisang.compaction.tool_result_budget import (
        ContentReplacementState, enforce_budget,
    )
    messages = [
        {"role": "tool", "tool_call_id": "tc1", "name": "unknown_tool", "content": "x" * 60_000},
    ]
    state = ContentReplacementState()
    new_msgs, replaced = enforce_budget(
        messages, state, tmp_path, budget_bytes=50_000,
    )
    # unknown_tool 默认 100K,60K < 100K 但总 60K > 50K 预算...
    # 实际:60K < persist_threshold 50K? 不,60K > 50K,所以持久化
    assert len(replaced) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/compaction/test_tool_result_budget.py::test_enforce_budget_skips_infinity_tools -v`
Expected: FAIL with `TypeError: enforce_budget() got an unexpected keyword argument 'tool_size_limits'`

- [ ] **Step 3: 实现 — enforce_budget 加 tool_size_limits 参数 + 跳过 Infinity**

在 `src/taisang/compaction/tool_result_budget.py:43` 修改签名：

```python
def enforce_budget(
    messages: list[dict],
    state: ContentReplacementState,
    persist_dir: Path,
    budget_bytes: int = PER_MESSAGE_BUDGET_BYTES,
    persist_threshold: int = DEFAULT_PERSIST_THRESHOLD,
    tool_size_limits: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """对 messages 跑 apply-tool-result-budget。

    返回 (新 messages, 本次新做的替换决策列表)。

    三分区:
    - mustReapply:已在 seen_ids,套已存的 preview(若有)即可,无 I/O
    - frozen/skip:在 SKIP_TOOL_NAMES 或 max_result_size_chars=Infinity(Read opt-out),标记 seen 不替换
    - fresh:累加字节;若超预算,按"最大优先"持久化直到降到预算内

    tool_size_limits: tool_name → max_result_size_chars 映射。
        - None 或未列出的 tool:默认 100_000(参与持久化)
        - float("inf"):opt-out 永不持久化(Read 工具,读回文件是循环)
    """
    new_messages = list(messages)
    newly_replaced: list[dict] = []
    limits = tool_size_limits or {}
    # 找所有 tool message
    tool_indices = [i for i, m in enumerate(new_messages) if m["role"] == "tool"]
    fresh_to_check: list[int] = []
    total_bytes = 0
    for i in tool_indices:
        tcid = new_messages[i].get("tool_call_id", "")
        content = new_messages[i].get("content", "")
        if not isinstance(content, str):
            continue
        if tcid in state.seen_ids:
            # mustReapply:套已存的 preview
            if tcid in state.replacements:
                new_messages[i] = {**new_messages[i], "content": state.replacements[tcid]}
            continue
        # fresh
        name = new_messages[i].get("name", "")
        # 跳过条件:SKIP_TOOL_NAMES 白名单 OR max_result_size_chars=Infinity(Read opt-out)
        tool_limit = limits.get(name, 100_000)
        if name in SKIP_TOOL_NAMES or tool_limit == float("inf"):
            state.seen_ids.add(tcid)
            continue
        fresh_to_check.append(i)
        total_bytes += len(content.encode("utf-8"))
    if total_bytes <= budget_bytes:
        for i in fresh_to_check:
            state.seen_ids.add(new_messages[i].get("tool_call_id", ""))
        return new_messages, []
    # 超预算:fresh 里按"最大优先"持久化
    fresh_to_check.sort(
        key=lambda i: len(new_messages[i].get("content", "").encode("utf-8")),
        reverse=True,
    )
    bytes_to_free = total_bytes - budget_bytes
    for i in fresh_to_check:
        if bytes_to_free <= 0:
            break
        content = new_messages[i].get("content", "")
        content_bytes = len(content.encode("utf-8"))
        if content_bytes < persist_threshold:
            state.seen_ids.add(new_messages[i].get("tool_call_id", ""))
            continue
        tcid = new_messages[i].get("tool_call_id", "")
        persist_file = persist_dir / f"{tcid}.txt"
        persist_file.write_text(content, encoding="utf-8")
        preview = content[:PREVIEW_BYTES]
        omitted = content_bytes - PREVIEW_BYTES
        placeholder = CLEARED_PLACEHOLDER.format(
            path=str(persist_file),
            size=f"{content_bytes:,}",
            preview=preview,
            omitted=f"{omitted:,}",
        )
        state.replacements[tcid] = placeholder
        state.seen_ids.add(tcid)
        new_messages[i] = {**new_messages[i], "content": placeholder}
        newly_replaced.append({"tool_call_id": tcid, "path": str(persist_file)})
        bytes_to_free -= content_bytes
    for i in fresh_to_check:
        tcid = new_messages[i].get("tool_call_id", "")
        if tcid not in state.seen_ids:
            state.seen_ids.add(tcid)
    return new_messages, newly_replaced
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/compaction/test_tool_result_budget.py -k "infinity_tools or default_tool_size_limits" -v`
Expected: 2 PASS

- [ ] **Step 5: 跑全量 test_tool_result_budget.py 确认没破坏现有测试**

Run: `pytest tests/unit/compaction/test_tool_result_budget.py -v`
Expected: 全 PASS（`tool_size_limits` 默认 None，向后兼容）

- [ ] **Step 6: Commit**

```bash
git add src/taisang/compaction/tool_result_budget.py tests/unit/compaction/test_tool_result_budget.py
git commit -m "feat(enforce_budget): 按 tool max_result_size_chars 跳过 Infinity 工具 (Read opt-out)"
```

---

### Task 6: service.py 调 enforce_budget 时传 tool_size_limits

**Files:**
- Modify: `src/taisang/agent_core/service.py:370-373`（enforce_budget 调用点）
- Test: `tests/unit/agent_core/test_service.py`

**背景：** service.py 调 enforce_budget 时需要把 ToolRegistry 里所有工具的 `max_result_size_chars` 属性收集成一个 dict 传过去。这样 enforce_budget 才能知道 read_file=Infinity 跳过、Bash=30K 等。

- [ ] **Step 1: 写失败测试 — service 传 tool_size_limits 给 enforce_budget**

```python
# tests/unit/agent_core/test_service.py 追加
def test_service_passes_tool_size_limits_to_enforce_budget(monkeypatch, tmp_path):
    """service.py 调 enforce_budget 时传 tool_size_limits={tool_name: max_result_size_chars}。
    
    read_file=Infinity 应被 enforce_budget 跳过。
    """
    # monkeypatch enforce_budget 捕获调用参数
    captured = {}
    def _fake_enforce_budget(messages, state, persist_dir, **kwargs):
        captured.update(kwargs)
        captured["messages_len"] = len(messages)
        return messages, []
    monkeypatch.setattr("taisang.agent_core.service.enforce_budget", _fake_enforce_budget)
    
    # 构造最小 AgentService 跑一轮(调一个 read_file tool_call)
    # ... 照现有 test_service.py mock 模式补全
    # 断言 captured["tool_size_limits"]["read_file"] == float("inf")
    # 断言 captured["tool_size_limits"]["Bash"] == 30_000
    pass  # TODO: 实现时按现有 mock 模式补全
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/agent_core/test_service.py::test_service_passes_tool_size_limits_to_enforce_budget -v`
Expected: FAIL（当前 service.py 调 enforce_budget 不传 tool_size_limits，captured 里没这个 key）

- [ ] **Step 3: 实现 — service.py 收集 tool_size_limits 并传入**

在 `src/taisang/agent_core/service.py` enforce_budget 调用点（`service.py:370` 附近）改成：

```python
            # 阶段 5: apply-tool-result-budget
            # 收集 ToolRegistry 里所有工具的 max_result_size_chars,传给 enforce_budget
            # 让 Read(Infinity) opt-out 持久化,Bash(30K) 等按各自阈值判断。
            tool_size_limits = {
                name: getattr(tool, "max_result_size_chars", 100_000)
                for name, tool in registry._tools.items()
            }
            new_msgs, newly_replaced = enforce_budget(
                self.ctx.messages(),
                self.compaction_state,
                observations_dir,
                tool_size_limits=tool_size_limits,
            )
            self.ctx.replace_messages(new_msgs)
```

> **注：** `registry._tools` 是私有属性，service.py 已在同一进程内访问可接受。如果 ToolRegistry 有公共 `schemas()` 或可加 `get_tool_size_limits()` 方法更干净。实现 subagent 可酌情加一个 `ToolRegistry.get_tool_size_limits() -> dict[str, float]` 公共方法，避免访问私有属性。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/agent_core/test_service.py::test_service_passes_tool_size_limits_to_enforce_budget -v`
Expected: PASS

- [ ] **Step 5: 跑全量 test_service.py 确认没破坏**

Run: `pytest tests/unit/agent_core/test_service.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add src/taisang/agent_core/service.py tests/unit/agent_core/test_service.py
git commit -m "feat(service): 调 enforce_budget 传 tool_size_limits (Read opt-out 持久化生效)"
```

---

### Task 7: 端到端集成测试 — 大 observation 在生产能触发 enforce_budget 持久化

**Files:**
- Test: `tests/unit/agent_core/test_service_compaction_integration.py`（新建或追加到现有 integration 测试）

**背景：** 这是验证死代码已复活的关键测试。构造一个返回 60KB observation 的工具，跑一轮 AgentService.run()，断言：
1. observation 原样进 ctx（不被 32KB 截断）
2. 下一轮 enforce_budget 检测到 60KB > 50K 阈值 + 总超 200K 预算时持久化到磁盘
3. ctx 里 tool message content 被替换成 `<persisted-output>` 占位符
4. 磁盘上有 `{tcid}.txt` 文件

- [ ] **Step 1: 写集成测试 — 60KB observation 触发 enforce_budget 持久化**

```python
# tests/unit/agent_core/test_service_compaction_integration.py
"""stage-1 enforce_budget 持久化在生产能触发的端到端集成测试。

验证死代码修复:移除 service.py 32K 硬截断后,60KB observation 能进 ctx,
enforce_budget 50K 阈值能触发持久化。
"""
import json
from pathlib import Path


def test_60kb_observation_triggers_enforce_budget_persist(tmp_path):
    """60KB observation(超 50K persist_threshold)在生产能触发 enforce_budget 持久化。"""
    from taisang.agent_core.service import AgentService
    from taisang.agent_core.context import ContextManager
    from taisang.agent_core.tools import ToolRegistry, _BaseTool
    from taisang.agent_core.permission import AutoApprovePermissionManager
    from taisang.agent_core.confirm import AutoDenyConfirmer
    from taisang.compaction.tool_result_budget import ContentReplacementState
    from taisang.llm_client import MockLLM
    
    # 构造一个返回 60KB observation 的工具
    class _BigTool(_BaseTool):
        name = "big_tool"
        max_result_size_chars = 100_000  # 非 Infinity,参与持久化
        def schema(self):
            return {"name": "big_tool", "description": "test", "parameters": {"type": "object", "properties": {}}}
        def run(self, args):
            return {"data": "x" * 60_000}  # 60KB observation
    
    # mock LLM:第一轮调 big_tool,第二轮给最终答案
    mock_llm = MockLLM(responses=[
        # 第一轮:tool_call
        [{"type": "tool_call", "tool_call": {"id": "tc1", "name": "big_tool", "arguments": {}}}],
        # 第二轮:最终答案
        [{"type": "text", "text": "done"}, {"type": "done"}],
    ])
    
    ctx = ContextManager(token_budget=200_000)
    compaction_state = ContentReplacementState()
    observations_dir = tmp_path / "obs"
    observations_dir.mkdir()
    
    registry = ToolRegistry(
        cwd=tmp_path,
        permission=AutoApprovePermissionManager(initial_dirs=[tmp_path]),
        confirmer=AutoDenyConfirmer(),
    )
    registry._tools["big_tool"] = _BigTool()
    
    service = AgentService(
        llm=mock_llm,
        ctx=ctx,
        registry=registry,
        compaction_state=compaction_state,
        observations_dir=observations_dir,
        # ... 其他必要参数照现有 test_service.py 补全
    )
    
    # 跑一轮
    answer = service.run(prompt="test")
    
    # 断言 1:磁盘上有持久化文件
    persist_files = list(observations_dir.glob("tc1.txt"))
    assert len(persist_files) == 1, f"expected tc1.txt persisted, got {list(observations_dir.glob('*'))}"
    
    # 断言 2:ctx 里 tool message content 被替换成 <persisted-output> 占位符
    tool_msgs = [m for m in ctx.messages() if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "[persisted-output]" in tool_msgs[0]["content"]
    assert "tc1.txt" in tool_msgs[0]["content"]
    
    # 断言 3:持久化文件内容是原 60KB observation
    persisted = persist_files[0].read_text(encoding="utf-8")
    assert len(persisted) > 50_000  # 原 observation 全量
    assert "x" * 100 in persisted  # 内容正确
```

> **注：** 上述测试骨架的 AgentService 构造参数需要按 `tests/unit/agent_core/test_service.py` 现有 mock 模式补全（session_memory、transcript_path 等）。实现 subagent 应先读现有 test_service.py 找到正确的构造模式。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/agent_core/test_service_compaction_integration.py::test_60kb_observation_triggers_enforce_budget_persist -v`
Expected: FAIL（死代码状态下，60KB observation 被截到 32KB，enforce_budget 50K 阈值触发不到，磁盘无 tc1.txt）

> **注：** 如果 Task 1-6 已正确实现，这个测试应该在 Task 6 之后就 PASS。此 Task 7 是验证性测试。如果 Task 6 后已 PASS，Step 2 可跳过。

- [ ] **Step 3: 跑测试确认通过**

Run: `pytest tests/unit/agent_core/test_service_compaction_integration.py::test_60kb_observation_triggers_enforce_budget_persist -v`
Expected: PASS

- [ ] **Step 4: 跑全量测试套件确认整体没破坏**

Run: `pytest tests/unit -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/agent_core/test_service_compaction_integration.py
git commit -m "test(integration): 60KB observation 端到端触发 enforce_budget 持久化(死代码复活验证)"
```

---

### Task 8: 更新 memory 笔记 + 验证 playwright 端到端

**Files:**
- Modify: `C:\Users\50892\.claude\projects\C--Users-50892\memory\2026-09-10-taisang-debug-observability.md`
- Verify: playwright 文本验证（非截图）

- [ ] **Step 1: 跑全量测试套件最终确认**

Run: `pytest tests/unit -v`
Expected: 全 PASS，测试数 ≥ 590（原基线）+ 新增测试

- [ ] **Step 2: 跑 vue-tsc + 前端 build（如果前端无改动可跳过）**

Run: `cd src/taisang/web/frontend && npm run build`
Expected: 成功（本 plan 不改前端，应无影响）

- [ ] **Step 3: playwright 文本验证 — 大文件读返回 error 不截断**

```bash
# 启动服务（如未运行）
python -m taisang web
```

用 playwright 文本方式（**不要截图**）验证：
1. 打开 http://localhost:8765
2. 开启 debug 模式
3. 让 LLM 读一个 > 256KB 的文件（如 `D:\GoProject\TaiSang\src\taisang\agent_core\service.py` 如果 > 256KB，否则构造一个临时大文件）
4. 用 `playwright_get_visible_text` 看工具卡片内容
5. 断言：ToolCard 显示 `error: file too large: ... > 256KB, use offset + limit`（不是截断后的内容）

- [ ] **Step 4: playwright 文本验证 — Bash 大输出落盘 + enforce_budget 持久化**

1. 让 LLM 跑一个输出 > 50KB 的 Bash 命令（如 `python -c "print('x'*60000)"`）
2. 第一轮：ToolCard 显示 `<persisted-output>` 包装 + 2KB 预览（BashTool 自己落盘）
3. 继续对话直到触发 enforce_budget（总 observation > 200K 预算时）
4. 用 `playwright_get_visible_text` 看 compacted 区域
5. 断言：stage-1 ① 压缩标记出现，显示 `tool_result_budget 压缩:N 个大结果持久化到磁盘`

- [ ] **Step 5: 更新 memory 笔记**

修改 `C:\Users\50892\.claude\projects\C--Users-50892\memory\2026-09-10-taisang-debug-observability.md` 的"⚠️ 架构问题（待 follow-up）"section，改成"已修复（Plan D-full）"+ 简述修复内容：

```markdown
## ✅ 架构问题（已修复 Plan D-full，2026-09-10）
**stage-1 enforce_budget 持久化在生产是死代码** — 已修复：
- 移除 service.py `_MAX_OBSERVATION_BYTES=32K` 硬截断
- ReadFileTool 默认读 > 256KB 抛 error 不截断（对齐 claude-code FileTooLargeError）
- ReadFileTool maxResultSizeChars=Infinity opt-out 持久化（对齐 claude-code）
- enforce_budget 按 tool max_result_size_chars 跳过 Infinity 工具
- 各工具 maxResultSizeChars: Read=∞, Bash=30K, Grep=20K, Glob/Edit/Write/Todo=100K
- 50K persist_threshold 不变，移除 32K 截断后自然能触发
```

- [ ] **Step 6: Commit memory + 整体收尾**

```bash
# memory 文件在 ~/.claude 下,不在项目仓库,不用 git commit
# 项目仓库的 commits 已在 Task 1-7 分别提交
# 此步仅做最终 git log 确认
git log --oneline -10
```

Expected: 看到 7 个新 commit（Task 1-7 各一个），消息清晰。

---

## Self-Review 清单

- [ ] **Spec coverage:** 
  - 移除 service.py 32K 截断 → Task 4 ✓
  - ReadFileTool 256KB 抛错不截断 → Task 3 ✓
  - ReadFileTool opt-out 持久化 → Task 2 (max=∞) + Task 5 (enforce_budget 跳过 ∞) + Task 6 (service 传 limits) ✓
  - 各工具 maxResultSizeChars 属性 → Task 1 + Task 2 ✓
  - enforce_budget 50K 阈值能触发 → Task 4 (移除截断) + Task 7 (端到端验证) ✓
  - 不破坏现有测试 → 每个 Task 都有"跑全量测试"步骤 ✓

- [ ] **Placeholder scan:** Task 4 Step 1 和 Task 6 Step 1 和 Task 7 Step 1 有 `# TODO: 实现时按现有 mock 模式补全` 注释。这是合理的——实现 subagent 需要先读现有 test_service.py 找到 mock 构造模式，plan 里无法预先写死（不同项目 mock 模式不同）。但 subagent 必须补全，不能跳过。已用 `> **注：**` 明确标注。

- [ ] **Type consistency:**
  - `max_result_size_chars` 全程用 `float`（`float("inf")` 或 int），一致 ✓
  - `tool_size_limits: dict[str, float]` 在 enforce_budget 签名 + service.py 调用点一致 ✓
  - `ContentReplacementState` 不变 ✓
  - `_DEFAULT_READ_MAX_BYTES = 256 * 1024` 命名一致 ✓