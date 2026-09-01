# Lessons Learned — Code Reader Agent

> 跨 session 的教训累积。遇到错误/坑/设计决策立即记录,下次 session 读这份避免重犯。

## 工程化教训

### Windows 平台测试隔离

**问题**:Python `Path.home()` 在 Windows 读 `USERPROFILE`,Linux/Mac 读 `HOME`。测试只 patch `HOME` 会让 Windows 测试失败。

**解法**:测试文件统一加 `_isolate_home(tmp_path, monkeypatch)` helper,同时 patch 两个 env:
```python
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
```

适用 Task:Task 3 (paths)、Task 4 (config) — 所有涉及 `Path.home()` 的测试都要用。

### Spec 测试代码可能含 lint/平台 bug

**问题**:Plan 里的测试代码不是 lint-clean 的,会有:
- 未使用的 import (F401) — 删除或加测试用上
- 文件末尾无换行 (W292) — ruff --fix 自动补
- import 顺序乱 (I001) — ruff 自动排序
- Windows 不兼容 — 见上一条

**解法**:implementer 主动修这些小瑕疵,在 DONE_WITH_CONCERNS 里记录偏离原因。生产代码不动,只改测试。

### Black 与 Ruff 的 `extend-exclude` 类型陷阱

**问题**:在 `pyproject.toml` 里给 black 和 ruff 同时配置 `extend-exclude` 排除 `tests/fixtures` 时:
- ruff 接受 list: `extend-exclude = ["tests/fixtures"]`
- black 只接受字符串(regex),传 list 会报 `Config key extend-exclude must be a string` 退出码 2

**解法**:同一文件里两段写法不同 — ruff 用 list,black 用字符串:
```toml
[tool.ruff]
extend-exclude = ["tests/fixtures"]

[tool.black]
extend-exclude = "tests/fixtures"
```

适用 Task:Task 7 及以后所有需要排除 fixture/生成文件的 task。

### Fixture 文件含语法错误时不进 ruff/black 扫描路径

**问题**:`tests/fixtures/python/sample_with_syntax_error.py` 故意写畸形(`def x(` 缺 `:`),ruff 会报 E999(语法错),black 直接报错退出。如果显式把 fixture 路径传给 `ruff check` / `black --check`,extend-exclude 不会生效(只在隐式目录扫描时生效)。

**解法**:
1. 在 `pyproject.toml` 里 `extend-exclude tests/fixtures`(如上条)
2. 跑 lint 时只传生产 + 测试代码路径,**不要** 传 `tests/fixtures`
3. fixture 文件本身允许含语法错误、未使用 import、缺尾换行等(用于解析器容错测试)

## 待办技术债(按 task 累积)

### Task 5 遗留 — ✅ 已修复(2026-08-21)

1. **`json.loads(tc.function.arguments)` 无错误处理** ✅ 已修
   - 真实 LLM 偶尔返回畸形 JSON,会抛 `JSONDecodeError`,agent_core 循环会崩
   - 解法:try/except 包装,JSONDecodeError/AttributeError → 抛 `LLMProtocolError`
2. **openai SDK 异常未包装** ✅ 已修
   - 解法:加 `LLMError` 基类 + `LLMProtocolError`(不可重试) + `LLMTransientError`(可重试)层级,`chat.completions.create` 抛任何 Exception → `LLMTransientError`
3. **MockLLM.calls 存原始引用** ✅ 已修
   - 解法:`copy.deepcopy(messages)` + `copy.deepcopy(tools)` 防 caller mutate 污染

### Task 7 遗留 — Task 8 / Task 11 处理

1. **`_extract_imports` 漏抓 `import a, b` 多模块语法**(parser_python.py:51-57)
   - tree-sitter `name` 字段只返回第一个;相对导入 `from . import x` 的 module_name 为 None 被跳过
   - Task 8 linker 解析标准库调用时可能受影响
   - 解法:遍历 `names` 字段(多模块)而非只取 `name`;相对导入特殊处理
2. **嵌套函数 id 不唯一风险**(parser_python.py:66-68, 96-98)
   - `_make_symbol_id` 只用 `parent_class` 限定,函数内嵌套函数(`def outer(): def inner():`)id 会冲突
   - Linker 按 id 索引,冲突会静默覆盖
   - 解法:要么限定 path 用完整 qualified name(含外层函数),要么测试断言当前 fixture 不触发
3. **静默吞异常无日志**(parser_python.py:139, 143) — **关键**
   - `except OSError` / `except Exception` 直接 `return []`,Task 11 `index_errors` 收集需要可见性
   - 解法:Task 11 集成时加 `logging.getLogger(__name__).warning(...)`,让上层感知哪些文件解析失败
4. **测试缺边缘场景**:空文件、async 函数、装饰器、嵌套 class 未测
   - 解法:polish 阶段补 fixture(至少 1-2 个)
5. **`_extract_calls` 可能重复**:同一函数体内对同一函数多次调用会产生重复 call 名
   - 解法:加注释说明"允许重复,由 linker 去重"或直接 dedupe(preserve_order=True)
6. **`test_parse_simple_file_function_kind` 断言过松**:`>= 5` 应改 `== 6` 更精确
7. **模块级 `_PARSER` 非线程安全**:Task 11 若用 ThreadPoolExecutor 并发解析会撞
   - 解法:Task 11 集成时改成函数内 `Parser(_LANGUAGE)` 或加 `threading.Lock`

### Task 10 遗留 — Task 11 indexer service 集成时必须处理

1. **docstring 假承诺 "pull 最新"**(fetcher.py:26):reuse 分支只调 `_current_commit`,**没有 pull**。GitHub HTTPS repo cache 会永久 stale
   - 解法:要么改成 `git -C target pull --depth 1`,要么删掉"pull 最新"措辞 + docstring 注明"v1 不做更新,需手动清 cache"
2. **`_url_hash` 与 `PathManager._repo_hash` 重复**(fetcher.py:20, paths.py:28):都是 `sha1(url)[:16]`。URL 规范化(尾斜杠、`.git` 后缀)不一致会导致 fetcher clone 目录与 PathManager indices 目录错位
   - 解法:hash 函数提到 `storage/paths.py` 或 `utils.py`,Fetcher 接收 `PathManager` 或 hash callable
3. **`_current_commit` 返回 "unknown" 哨兵**(fetcher.py:63):调用方难区分"真的 unknown commit"和"取不到"
   - 解法:至少 `logging.warning` 一次,或直接 raise
4. **`import shutil` 在循环内 lazy import**(fetcher.py:40):应提到模块顶部
5. **无 logging**:retry 失败、rmtree 异常都不留痕。Task 11 接入后排障缺信息
   - 解法:加 `logging.getLogger(__name__)` 至少 warning 级别
6. **`shutil.rmtree` Windows 文件锁**:未捕获 OSError,残留目录有被占用文件会抛非 RuntimeError
7. **缺 retry/stale target/timeout 测试**:Task 11 补
8. **test 中 `import pytest` 在函数内**(test_fetcher.py:58):应放模块顶部

### Task 9 遗留 — Task 11 indexer service 集成时处理

1. **DELETE+INSERT vs INSERT OR REPLACE 风格不一致**(storage.py:56, 58):`save_symbols` 用 DELETE+INSERT(因 symbol_id 跨 commit 可能消失,DELETE 必要),但 commits 表用 `INSERT OR REPLACE`。同一函数两种 upsert 写法易让读者困惑
   - 解法:统一为 DELETE+INSERT 或在注释里说明"DELETE 是为了清掉已删除的 symbol_id"
2. **`_conn()` 每次新建连接**(storage.py:26-27):Task 11 indexer service 频繁调用时会放大开销
   - 解法:复用一个长连接(成员变量 `self._conn`),在 `__init__` 中打开,配合 `check_same_thread=False` 或显式 `close()`
3. **`index_errors` 表无 PK**(storage.py:44-47):MVP 可接受,未来按错误顺序回放时可加 `id INTEGER PRIMARY KEY AUTOINCREMENT`
4. **`load_index_errors` 返回类型应为 `list[dict[str, Any]]`**(storage.py:100):更精确
5. **测试缺大列表性能边界用例**:MVP 阶段非必须

### Task 8 遗留 — 后续 polish / Task 14 处理

1. **`_method_class` 嵌套类限制**(linker.py:30-35):`file::Outer.Inner.method` 按 "." split 取 [0] 得 "Outer",不同嵌套层级的同名 method 会被错误关联。MVP 无嵌套类 fixture,docstring 注明限制即可
2. **same-class 优先于全局唯一无 fallback**(linker.py:62-73):策略 1 命中后不再 fallback 到策略 2。Task 14 trace 工具暴露给 agent 时可能引起误解,docstring 补一句
3. **测试缺 self-call + depth=0 边缘场景**:Task 14 trace 工具很可能传 depth=0 当 "只看自己" 用,高曝光路径。补 2 条测试
4. **`resolve_call_chain` depth 语义是"边数"不是"节点数"**:docstring "N 跳调用链" 容易被读成 "N 个节点"。Task 14 tool 包装时要把语义传清楚
5. **`CallGraphNode.line_range` 当前是 dead field**:为 Task 14 trace 工具展示保留,加注释说明用途

### Task 11 遗留 — 后续 task 顺手补

1. **`test_index_persists_to_storage` 名实不符**(test_indexer_service.py:87):注释写"第二次 build 应该走增量路径",但实际调 `build()`(全量)非 `update()`。既未验证 storage 持久化,也未验证增量
   - 解法:改名 `test_index_rebuild_idempotent`,或真正调用 `service.update()` 并断言只重解析变动文件
2. **build/update 解析循环 DRY 违反**(service.py:34 & 84):两段几乎完全重复(~20 行)
   - 解法:抽 `_parse_files(py_files, local_path, only: set|None) -> tuple[list[Symbol], list[dict]]`
3. **update 的 old_errors + errors 无限累积**(service.py:109):deleted/modified 文件的旧 error 不会被清理,errors 跨多次 update 永久增长
   - 解法:根据 to_drop 清理旧 errors 里同文件的记录,或在注释里明确"v1 简化不清理"
4. **update 增量路径无测试覆盖**:只有 build 被测,update() 的 added/modified/deleted 分支无闭环用例
   - 解法:Task 18 端到端集成测试补一个 modify-one-file-then-update 用例
5. **`kept = [s for s in old_symbols if s.file not in to_drop]` O(n*m)**(service.py:91):MVP 规模可接受,大 repo 上万符号时需优化
   - 解法:把 to_drop 改 set 查询(O(1)),n*m → n — 其实 `to_drop` 已是 set,问题在 `s.file not in to_drop` 是 O(1),实际是 O(n) — 审阅者误判,忽略
6. **update 返回 `files=list(new_fps.keys())` 而 build 用 `list(fingerprints.keys())`**(service.py:111 vs 56):命名不对称,fingerprints vs new_fps
   - 解法:统一命名(都叫 fingerprints 或都叫 new_fps),可读性微瑕
7. **`self.fetcher = Fetcher(pm.cache_dir)` 假定 Fetcher 构造签名稳定**(service.py:18):若后续 Task 调整 Fetcher 构造签名需同步
   - 解法:加类型注解或工厂,非阻塞
8. **`py_files = sorted(...)` 后再 list-comprehension 过滤 .git 两步**(service.py:23-24):可合并,非阻断

### Task 12 遗留 — 后续 task 顺手补

1. **`_chat` 截断注释与实现不符**(service.py:50):注释写"超了截断"但 `_chat` 没截断,截断在调用处 `summary[:FILE_BUDGET]`
   - 解法:删 `_chat` 里那条注释,或把截断挪到 `_chat` 统一处理
2. **模块路径处理混合 Path + 字符串替换**(service.py:96):`str(Path(fp).parent).replace("\\", "/")` 脆弱,Windows 上其实 `Path.parent` 已是 PosixPath
   - 解法:统一用 `Path(fp).parent.as_posix()` 或 `PurePosixPath`
3. **`entry_candidates` 跨符号全局匹配可能重复**(service.py:112):同名符号在不同文件会产生重复 entry_points,截断 `[:10]` 不去重
   - 解法:用 dict.fromkeys 去重保序,或改 set
4. **模块路径 "" 根目录约定隐式**(prompts.py:54 + service.py):空字符串触发 `(根目录)` 兜底,无类型注释或常量声明
   - 解法:定义 `ROOT_MODULE = ""` 常量,或 docstring 标注约定
5. **`FailingLLM.chat` 签名缺返回类型**(test_summarizer.py:65):`(self, messages, tools)` 无 `-> LLMResponse`
   - 解法:加返回类型注解,与 LLMClient 协议对齐
6. **全局摘要"半成品"不记 errors**(service.py:120):LLM 全失败时 `dependency_summary=""` 但 `entry_points`/`core_modules` 仍填充,未记入 errors
   - 解法:`global_text is None` 时 append 一条 error 让上层感知
7. **`by_file: dict[str, list]` 缺类型参数**(service.py:约 78 行):应为 `dict[str, list[Symbol]]`
   - 解法:补类型参数
8. **测试未覆盖 error 路径**:源文件不存在、文件读取异常、模块级 LLM 失败跳过 — 有代码无测试
   - 解法:Task 18 端到端集成测试补 1-2 个,或 polish 阶段补单测
9. **FILE_BUDGET=200 vs prompt 要求 100 字**:预算比 prompt 宽,合理但值得文档化

### Task 13 遗留 — 后续 task 顺手补

1. **`[一-龥]` 正则只覆盖 CJK BMP**(bm25.py:8-12):缺 CJK Extension B+ 和部分标点,MVP 可接受
   - 解法:加注释说明"仅 ASCII + CJK-BMP,扩展 B+ 留给后续",或换 `regex` 库支持 Unicode property
2. **`sorted` 负/零分数 ties 按插入序**(bm25.py:37):BM25 有零分时排序不稳定
   - 解法:加 secondary key(如 key 名)保证确定性
3. **`search_modules` 死代码返回 `[]`**(service.py:40-42):既已实现签名又永远返回空,要么删要么 `NotImplementedError`
   - 解法:v2 真正实现模块索引,或暂改 `raise NotImplementedError("v1 uses search_files only")` 让失败可见
4. **`line_range=(1,1)` 占位语义不清**(service.py:30):文件级检索无行号,占位 (1,1) 易被 caller 误读为"第 1 行"
   - 解法:docstring 注明"文件级,行号占位不代表实际行",或 Snippet 允许 None
5. **`VectorStore` Protocol + `BM25OnlyStore` 未被 service.py 使用**(vectorstore.py:18-20):premature abstraction,service 直接用 `BM25Index`
   - 解法:v2 真正接 Chroma 时再激活,或删掉直到需要
6. **测试未覆盖 `_normalize` 退化分支**(hybrid.py:12):all-equal 分支无测试
   - 解法:补一个 `test_normalize_single_value_returns_uniform_1`
7. **`test_hybrid_rank_combines_vector_and_bm25` 只断言 top-1**(test_retriever.py:43):未验证剩余排序和归一化生效
   - 解法:补 2nd-place 断言
8. **`test_bm25_basic_search` 未断言 a vs c 排序**(test_retriever.py:25):只查集合,未查 order
   - 解法:补 `results[0][0] == "a"`(a 含"支付"+"模块"双命中,c 只"支付")— 但这依赖分词细节,可能脆弱,可选
9. **hybrid.py 是 v1 死代码**(service.py 用 BM25-only):可接受作 scaffold,但应加 TODO 注释
   - 解法:v2 接 Chroma 后激活,或 docstring 标 "v2 reserved"
10. **目录级 `git add` 误带入 `__pycache__/*.pyc`**:Task 13 首次 commit 中招,amend 清理
    - 解法:**后续 task 一律用显式文件列表 `git add`,或尽快建 `.gitignore`** 排除 `__pycache__/`、`*.pyc`、`.pytest_cache/` 等

### Task 14 遗留 — 安全加固部分已修(2026-08-21)

1. **Path traversal — ReadFileTool** ✅ 已修
   - 解法:加 `_is_within(source_root, target)` helper 用 `target.resolve().is_relative_to(source_root.resolve())`,ReadFileTool.run 调它先校验
2. **Path traversal — GrepTool fallback** ✅ 已修
   - 解法:scope 作为 glob 无命中时,fallback 单文件分支也用 `_is_within` 校验
3. **Regex DoS — GrepTool** ✅ 已修(部分)
   - 解法:加 `_search_with_timeout(regex, line)` helper,Linux/Mac 用 `signal.SIGALRM` + `setitimer` 5 秒超时;Windows 无 SIGALRM 跳过超时(仅保留 re.error 捕获 + warning log)。注:compile 本身通常不 DoS,DoS 在 search
4. **`GlobTool` 用 `fnmatch.fnmatch`** ⏳ 未修(minor,不阻塞)
   - 解法:换 `Path.match` 或手写 glob walk
5. **`LookupMapTool` global 层忽略 query** ⏳ 未修(minor)
   - 解法:对 entry_points/core_modules 也做 query 过滤,或 docstring 注明
6. **DRY:`str(f.relative_to(self.source_root)).replace("\\","/")` 重复** ✅ 已修
   - 解法:抽模块级 `_rel(source_root, path) -> str` helper,GrepTool + GlobTool 共用
7. **测试缺失** ✅ 已补
   - 解法:本轮补 `test_read_file_tool_rejects_path_traversal`、`test_grep_tool_rejects_path_traversal_scope`、`test_grep_tool_bad_regex_returns_error`

### Task 15 spec test bug(已修)

**问题**:`test_compact_keeps_system_and_recent` 参数与断言矛盾。
- 测试用 `token_budget=1000`, `keep_recent=4`(默认),只加 2 个 tool msg
- `compact()`: `len(tool_idx)=2 <= keep_recent=4` → 早退,什么都不压
- 断言 `"old result" not in text or "[compacted" in text` → `False or False` → FAIL
- 总 tokens ≈ 671 < budget 1000,`while` 循环也不触发

**根因**:spec 测试参数(2 个 tool msg + keep_recent=4)与断言期望(旧 tool 被压缩)矛盾。

**解法**:改测试参数 `keep_recent=1`,让 old tool 超出保护范围被压缩,new 保留。实现逻辑不变(实现是对的)。

**教训**:spec 测试代码可能有参数-断言矛盾。implementer 应先分析能否通过,如不能,报告 DONE_WITH_CONCERNS,由 controller 决定修测试还是修实现。修测试参数(保留 spec 意图)通常比改实现更安全。

### Task 15 遗留 — 后续 polish

1. **`compact()` 开头的 `if not self.should_compact()...pass` 是空操作**(context.py:75-77):spec 原文这段 `pass` 块无实际效果,逻辑混乱的遗迹
   - 解法:删除这个 if 块,或改成有意义的守卫
2. **`compact()` 用 while + for 双重循环找"最旧未压缩"**(context.py:90-104):O(n²),MVP 可接受
   - 解法:用指针记录下次压缩位置,或预排序
3. **`_messages` 直接 mutate content**(context.py:88, 101):原地修改 dict,caller 持有的 messages() 返回的是浅拷贝列表但 dict 是同一引用
   - 解法:docstring 注明"compact 原地修改",或返回新列表
4. **token 估算 `len(text)//3` 过于粗糙**(context.py:34):中文实际 ~1.5 char/token,英文 ~4 char/token,混合取 3 偏差大
   - 解法:v2 换 tiktoken,或按字符类型加权
5. **测试未覆盖**:append_assistant with tool_calls、empty compact(无 tool msg)、已压缩后再 compact
   - 解法:polish 阶段补

### Task 16 遗留 — 健壮性部分已修(2026-08-21)

1. **Tool dispatch loop 无异常守卫** ✅ 已修
   - 解法:dispatch 循环体包 try/except,`registry.call` 抛异常时 result 改为 `{"error": "tool X failed: ..."}` 继续;`tc["name"]` 改 `tc.get("name", "<unknown>")` 防 KeyError
   - 触发场景:Task 5 遗留 `json.loads(tc.function.arguments)` 无错误处理,真实 LLM 返回畸形 JSON 时 LLMClient 会崩,或 tool_calls 结构异常时 `tc["name"]` KeyError
2. **observation 无大小限制** ✅ 已修
   - 解法:加常量 `_MAX_OBSERVATION_BYTES = 32_000`,`json.dumps` 后超长截断 + 加 `...{"_truncated": true}` 后缀
3. **`tool_call_id=name` 复用工具名作 ID** ✅ 已修
   - 解法:改 `f"{name}-{i}"` 用 enumerate 索引唯一化
4. **`tc.get("args", {})` 不处理 `args=None`** ✅ 已修
   - 解法:`args = tc.get("args") or {}`
5. **测试未覆盖 LLM 异常路径** ✅ 已补
   - 解法:本轮补 `test_agent_llm_protocol_error_terminates` + service.py 把 LLM 异常细分为 `LLMProtocolError` / `LLMTransientError` / `LLMError` 三类捕获
6. **测试未覆盖 `tool_calls=None`** ⏳ 未补(minor)
   - 解法:polish 阶段补一个 MockLLM 返回 `tool_calls=None` 的测试
7. **额外补:`test_agent_malformed_tool_call_does_not_crash`** ✅ 已补
   - 验证 LLM 返回缺 name 键的 tool_call,Agent 不崩继续到下一步回答
8. **额外补:`test_agent_observation_truncation`** ✅ 已补
   - 验证 read_file 返回 40K 内容时,tool_result 被截断到 ≤33K

### Task 17 遗留 — 后续 task 顺手补

1. **source_root 查找重复**(main.py:53-55 vs 95-97):`repo_hash = pm._repo_hash(repo_url); source_root = pm.cache_dir / repo_hash` 两处重复,且访问 PathManager 的私有 `_repo_hash`
   - 解法:PathManager 加公开 `source_root(repo_url) -> Path` property/method,CLI 调它
2. **缺 exit-2 no-api-key 测试**:main.py:27-32 的 `not cfg.api_key` 分支无覆盖,易回归
   - 解法:补 `test_cli_ask_without_api_key_exits_2`(不设 mock、不设 key,断言 exit_code==2 + stderr 含提示)
3. **缺 ask-before-index 测试**:main.py:84-87 的 "repo 未索引过" exit-1 路径无覆盖
   - 解法:补 `test_cli_ask_without_index_exits_1`
4. **`idx.index_errors`/`summarizer.errors` 访问假设公开属性**(main.py:45,69):属性改名则静默破坏
   - 解法:docstring 标注 public API,或测试覆盖错误输出分支
5. **summarize 长时无进度反馈**(main.py:60):只 echo 一次 "生成三层摘要...",大 repo 多次 LLM 调用无 streaming
   - 解法:v2 加进度回调或 tqdm
6. **`import os` 在 test 函数内**(test_cli.py:27):应提模块顶部
   - 解法:移到顶部
7. **cmd_ask 每次 update(repo) 静默重索引**(main.py:92):无 `--no-refresh` 选项
   - 解法:加 `--no-refresh` flag 或 docstring 注明 "ask 会自动增量更新索引"

### Task 2/3/4/6 遗留 — 后续 task 顺手补

- Task 2: `RepoIndex.files`/`symbols` 一致性 docstring 标注 — Task 11 indexer 用到时补
- Task 3: `cache_dir` property 有副作用(mkdir)— Task 9 实际用 cache 时统一处理
- Task 3: 空 repo_url 校验、权限失败 docstring — Task 9/11 入口层处理
- Task 4: malformed `settings.json` 处理(目前 json.loads 裸抛)— 加 try/except 返回 {}
- Task 4: `os.environ.get` 重复 6 行 — 可抽 `_pick(env_key, file_key)` helper(9+ 字段时再说)
- Task 4: `summ_base`/`summ_key`/`summ_model` 缩写命名不一致 — 改 `summarizer_*` 全名
- Task 6: `file_hash` FileNotFoundError docstring 标注 Raises — Task 11 用到时补
- Task 6: hash 契约测试(长度 16 + hex 格式)— polish 阶段补
- Task 6: `diff_files` 边缘测试(空 dict、完全相同、完全不相交)— polish 阶段补
- Task 6: `diff_files` 双遍迭代 common 改单遍 — 不阻塞,风格 nit

## 工作流教训

### Subagent-driven-development 连续执行

用户明确说"不需要每个 task 都问,直接做"。所以:
- 每个 task:implementer → spec compliance → code quality → 修补(只修阻塞性 Important)→ 下一个 task
- 不阻塞的 Important issue 记到本文件,后续 task 顺手补
- 只在 BLOCKED 或所有 task 完成才停下问用户

### SendMessage 工具不可用

派 subagent 后无法用 SendMessage 继续对话(工具不在我的列表)。如果 subagent 中途停下问问题,必须派新 agent 并把完整 context 写进 prompt。不要依赖 SendMessage。

### Task 2/3/9 遗留 — ✅ 已修(2026-08-21,本地 repo 改造)

1. **Fetcher `git clone` 过度设计** ✅ 已修
   - 解法:砍 `fetch` + `_url_hash`,退化成 `current_commit(path)` 静态方法薄壳。用户先 `git clone` 到本地再 `taisang index <path>`
2. **PathManager 集中落盘不可读** ✅ 已修
   - 解法:砍 `cache_dir`/`indices_dir`/`_repo_hash`,新增 `index_dir(source_root)` 等 classmethod,落 `<repo>/.taisang/`。删 repo 时索引自动清,team 共享连 repo 一起 copy
3. **`Fetcher._current_commit` 未捕获 OSError** ✅ 已修
   - 解法:`current_commit` 加 `try/except (TimeoutExpired, OSError, FileNotFoundError)`,Windows git 未装时返回 "unknown" 不崩
4. **IndexerService 扫源码未排除 `.taisang/`** ✅ 已修
   - 解法:`py_files` 过滤条件加 `".taisang" not in f.parts`,防止索引产物被当源码解析
5. **`RepoIndex.repo_url` 字段名误导** ✅ 已修
   - 解法:改名 `source_root: str`,语义清晰

### 三合一改造 — tool_calls OpenAI 标准 schema + ctx 提实例 + reset(2026-08-31)

1. **tool_calls 简化结构 `{"name":..., "args":{...}}` 不兼容 OpenAI API**
   - 解法:LLMClient.chat 透传标准结构 `{"id":..., "type":"function", "function":{"name":..., "arguments":"<JSON 字符串>"}}`,arguments 保持字符串不在 client 解析;service.py 用时 `json.loads`,畸形 JSON 降级为 malformed error observation 但仍 append tool_result(否则 OpenAI API 因缺 tool result 报错);tool_call_id 用 `tc["id"]` 不再自拼 `f"{name}-{i}"`
   - 教训:LLM client 层只透传不解析,解析责任在 service 层(可降级),client 层抛错会直接终止 agent
2. **ContextManager 在 run() 内部新建导致 REPL 多轮无短期记忆**
   - 解法:ctx 提到 `AgentService.__init__` 实例属性,跨 run() 保留;reset() 重建 ctx+compaction_state 但**不重置 session_memory**(长期笔记跨 session 保留)
   - 教训:实例属性 vs 局部变量的边界——跨方法调用需要保留的状态必须放实例属性;reset 要分清"短期对话"和"长期笔记"两层记忆
3. **`_try_autocompact`/`_recent_text` 参数从 `ctx` 改 `self.ctx`**
   - 判断:无测试直接调这两个私有方法(grep 确认),直接删参数用 self.ctx 更简洁;若测试需 mock ctx 再考虑保留参数