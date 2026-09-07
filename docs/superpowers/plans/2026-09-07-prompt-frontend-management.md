# Prompt 前端管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 TaiSang 的核心 prompt（主 System Prompt / Autocompact 摘要 Prompt / Session Memory 模板 + 更新指令）暴露到前端 `/prompts` 页面，用户可查看、编辑、保存、恢复默认，修改后全局持久化到 `~/.taisang/settings.json` 并对所有活跃 session 立即生效。

**Architecture:** 后端在 `config.py` 新增 `PromptsConfig` 持久化层，三个 prompt 源文件（`agent_core/prompts.py` / `compaction/prompts.py` / `session_memory/template.py`）改造为"读 config 优先，fallback 代码常量"；`SessionRegistry.apply_prompts_config` 仿 `apply_llm_config` 广播 system prompt 替换到所有活跃 session；新增 `web/prompts_api.py` 提供 GET/PUT/RESET 三个 endpoint；前端新增 `/prompts` 路由 + `PromptManage.vue` 四折叠面板页面 + `api/prompts.ts`。

**Tech Stack:** Python 3 + FastAPI + Pydantic（后端），Vue 3.5 + Vite + TDesign（前端），pytest（测试），`~/.taisang/settings.json`（持久化）。

**Spec:** `docs/superpowers/specs/2026-09-07-prompt-frontend-management-design.md`

---

## 文件结构

### 新建
- `tests/unit/test_prompts_config.py` —— PromptsConfig 加载/保存/重置单测
- `tests/unit/test_prompts_api.py` —— prompts API + apply_prompts_config 广播单测
- `tests/unit/test_prompt_runtime.py` —— `get_system_prompt()` / `get_autocompact_prompt()` / `get_template()` / `get_update_prompt()` 运行时读取单测
- `src/taisang/web/prompts_api.py` —— GET/PUT/RESET 三个 endpoint
- `src/taisang/web/frontend/src/api/prompts.ts` —— 前端 API client
- `src/taisang/web/frontend/src/views/PromptManage.vue` —— 四折叠面板管理页

### 修改
- `src/taisang/config.py` —— 新增 `PromptsConfig` / `PromptOverride` / `load_prompts` / `save_prompt_override` / `reset_prompt_override`
- `src/taisang/agent_core/prompts.py` —— 新增 `get_system_prompt()`，`build_system_prompt` 改用之
- `src/taisang/compaction/prompts.py` —— 新增 `DEFAULT_AUTOCOMPACT_PROMPT` 常量 + `get_autocompact_prompt(conversation_text)`
- `src/taisang/compaction/autocompact.py` —— 改用 `get_autocompact_prompt(conversation_text)`
- `src/taisang/session_memory/template.py` —— `get_template()` / `get_update_prompt()` 读 config 优先
- `src/taisang/agent_core/context.py` —— 新增 `replace_system_prompt(text)` 方法
- `src/taisang/web/session_registry.py` —— 新增 `apply_prompts_config(key)`
- `src/taisang/web/app.py` —— 注册 prompts 路由
- `src/taisang/web/frontend/src/router/index.ts` —— 加 `/prompts` 路由
- `src/taisang/web/frontend/src/components/Sidebar.vue` —— 加 "Prompt 管理" 入口

---

## Task 1: PromptsConfig 持久化层

**Files:**
- Modify: `src/taisang/config.py`（追加在文件末尾）
- Test: `tests/unit/test_prompts_config.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_prompts_config.py`：

```python
"""PromptsConfig 持久化层单测:load/save/reset,use_default 切换,损坏文件 fallback。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taisang.config import (
    PromptOverride,
    PromptsConfig,
    load_prompts,
    reset_prompt_override,
    save_prompt_override,
)


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """把 ~/.taisang/settings.json 重定向到 tmp_path。"""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home / ".taisang" / "settings.json"


def test_load_prompts_no_file_all_default(tmp_settings):
    """无 settings.json → 全 use_default=true。"""
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is True
    assert cfg.autocompact_prompt.use_default is True
    assert cfg.session_memory_template.use_default is True
    assert cfg.session_memory_update_prompt.use_default is True


def test_save_prompt_override_sets_use_default_false(tmp_settings):
    """save 后 use_default=false,value 写入。"""
    save_prompt_override("system_prompt", "你是自定义 agent。")
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is False
    assert cfg.system_prompt.value == "你是自定义 agent。"


def test_reset_prompt_override_sets_use_default_true(tmp_settings):
    """reset 后 use_default=true,value 清空。"""
    save_prompt_override("system_prompt", "自定义")
    reset_prompt_override("system_prompt")
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is True
    assert cfg.system_prompt.value == ""


def test_save_preserves_other_keys(tmp_settings):
    """保存 prompts 不丢 llm / skills 字段。"""
    # 先写一个含 llm 的 settings.json
    tmp_settings.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.write_text(
        json.dumps({"llm": {"model": "gpt-4o", "api_key": "k", "base_url": "u"}}),
        encoding="utf-8",
    )
    save_prompt_override("autocompact_prompt", "自定义摘要")
    raw = json.loads(tmp_settings.read_text(encoding="utf-8"))
    assert raw["llm"]["model"] == "gpt-4o"
    assert raw["prompts"]["autocompact_prompt"]["value"] == "自定义摘要"


def test_corrupted_settings_falls_back_to_default(tmp_settings):
    """损坏 settings.json → fallback 默认。"""
    tmp_settings.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.write_text("not json {{{", encoding="utf-8")
    cfg = load_prompts()
    assert cfg.system_prompt.use_default is True


def test_save_empty_value_raises(tmp_settings):
    """空 value → ValueError。"""
    with pytest.raises(ValueError, match="不能为空"):
        save_prompt_override("system_prompt", "")


def test_save_too_long_value_raises(tmp_settings):
    """超 50KB → ValueError。"""
    with pytest.raises(ValueError, match="过长"):
        save_prompt_override("system_prompt", "x" * (50 * 1024 + 1))


def test_save_invalid_key_raises(tmp_settings):
    """非法 key → ValueError。"""
    with pytest.raises(ValueError, match="非法 key"):
        save_prompt_override("nonexistent_key", "xxx")


def test_reset_invalid_key_raises(tmp_settings):
    with pytest.raises(ValueError, match="非法 key"):
        reset_prompt_override("nonexistent_key")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_prompts_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'PromptOverride'` 或类似

- [ ] **Step 3: 实现 PromptsConfig**

在 `src/taisang/config.py` 末尾追加：

```python
# === Prompts 配置 ===

PROMPT_KEYS = frozenset(
    {
        "system_prompt",
        "autocompact_prompt",
        "session_memory_template",
        "session_memory_update_prompt",
    }
)

_PROMPT_MAX_BYTES = 50 * 1024


class PromptOverride(BaseModel):
    """单个 prompt 的覆盖配置。

    use_default=true 时运行时读代码常量,value 忽略;
    use_default=false 时运行时读 value。
    """

    value: str = ""
    use_default: bool = True


class PromptsConfig(BaseModel):
    """四份 prompt 的覆盖配置。"""

    system_prompt: PromptOverride = PromptOverride()
    autocompact_prompt: PromptOverride = PromptOverride()
    session_memory_template: PromptOverride = PromptOverride()
    session_memory_update_prompt: PromptOverride = PromptOverride()


def load_prompts() -> PromptsConfig:
    """加载 prompts 配置。settings.json 的 prompts 字段 > 默认(全 use_default=true)。

    损坏文件 fallback 到默认(复用 _load_settings_file 的容错)。
    """
    raw = _load_settings_file().get("prompts", {})
    if not isinstance(raw, dict):
        return PromptsConfig()
    # 逐字段构造,容忍部分缺失
    data = {}
    for key in PROMPT_KEYS:
        item = raw.get(key)
        if isinstance(item, dict):
            data[key] = PromptOverride(
                value=str(item.get("value", "")),
                use_default=bool(item.get("use_default", True)),
            )
        # 缺失的 key 用默认 PromptOverride(不写进 data,让 Pydantic 填默认)
    return PromptsConfig(**data)


def _save_prompts_section(prompts_dict: dict) -> None:
    """原子写 settings.json 的 prompts 字段,保留 llm/skills 等其他字段。权限 600。"""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings_file()
    existing["prompts"] = prompts_dict
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, p)


def _validate_prompt_value(value: str) -> None:
    if not value:
        raise ValueError("prompt 不能为空")
    if len(value.encode("utf-8")) > _PROMPT_MAX_BYTES:
        raise ValueError(f"prompt 过长(>{_PROMPT_MAX_BYTES // 1024}KB)")


def save_prompt_override(key: str, value: str) -> PromptsConfig:
    """保存单个 prompt 覆盖:use_default=false + 写 value。返回最新完整 config。

    校验:key 合法、value 非空且 ≤ 50KB。
    """
    if key not in PROMPT_KEYS:
        raise ValueError(f"非法 key: {key}")
    _validate_prompt_value(value)
    cfg = load_prompts()
    override = PromptOverride(value=value, use_default=False)
    setattr(cfg, key, override)
    raw = {
        k: getattr(cfg, k).model_dump() for k in PROMPT_KEYS
    }
    _save_prompts_section(raw)
    return cfg


def reset_prompt_override(key: str) -> PromptsConfig:
    """恢复单个 prompt 为默认:use_default=true + 清空 value。返回最新完整 config。"""
    if key not in PROMPT_KEYS:
        raise ValueError(f"非法 key: {key}")
    cfg = load_prompts()
    setattr(cfg, key, PromptOverride())
    raw = {
        k: getattr(cfg, k).model_dump() for k in PROMPT_KEYS
    }
    _save_prompts_section(raw)
    return cfg
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_prompts_config.py -v`
Expected: 9 passed

- [ ] **Step 5: 跑现有 config 测试确保没回归**

Run: `pytest tests/unit/test_config.py -v`
Expected: 全部 pass（prompts 改动是追加，不动现有 LLMConfig 逻辑）

- [ ] **Step 6: 提交**

```bash
git add src/taisang/config.py tests/unit/test_prompts_config.py
git commit -m "feat(config): add PromptsConfig persistence layer for prompt overrides"
```

---

## Task 2: agent_core/prompts.py 运行时读取

**Files:**
- Modify: `src/taisang/agent_core/prompts.py:44-51`（`build_system_prompt` 函数）
- Test: `tests/unit/test_prompt_runtime.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_prompt_runtime.py`：

```python
"""prompt 运行时读取单测:get_system_prompt / get_autocompact_prompt / get_template / get_update_prompt。"""

from __future__ import annotations

from pathlib import Path

import pytest

from taisang.config import reset_prompt_override, save_prompt_override
from taisang.agent_core.prompts import SYSTEM_PROMPT, build_system_prompt, get_system_prompt
from taisang.compaction.prompts import (
    BASE_COMPACT_PROMPT,
    DEFAULT_AUTOCOMPACT_PROMPT,
    NO_TOOLS_PREAMBLE,
    NO_TOOLS_TRAILER,
    get_autocompact_prompt,
)
from taisang.session_memory.template import DEFAULT_TEMPLATE, DEFAULT_UPDATE_PROMPT, get_template, get_update_prompt


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    yield
    # 每个测试后清理:把所有 key 重置回默认(防测试间污染)
    for key in ["system_prompt", "autocompact_prompt", "session_memory_template", "session_memory_update_prompt"]:
        try:
            reset_prompt_override(key)
        except Exception:
            pass


def test_get_system_prompt_default_returns_constant(tmp_settings):
    """use_default 时返回代码常量 SYSTEM_PROMPT。"""
    assert get_system_prompt() == SYSTEM_PROMPT


def test_get_system_prompt_custom_returns_value(tmp_settings):
    """自定义时返回 value。"""
    save_prompt_override("system_prompt", "你是自定义 agent。")
    assert get_system_prompt() == "你是自定义 agent。"


def test_build_system_prompt_uses_custom_system(tmp_settings):
    """build_system_prompt 用自定义 system prompt + 拼 skills 段。"""
    save_prompt_override("system_prompt", "自定义基座。")
    result = build_system_prompt(skills_section="## Skills\n- skill1", mcp_section="")
    assert result.startswith("自定义基座。")
    assert "## Skills\n- skill1" in result


def test_build_system_prompt_default(tmp_settings):
    """默认时 build_system_prompt 用 SYSTEM_PROMPT + 拼段。"""
    result = build_system_prompt(skills_section="X", mcp_section="Y")
    assert result.startswith(SYSTEM_PROMPT)
    assert "X" in result and "Y" in result


def test_get_autocompact_prompt_default(tmp_settings):
    """默认时返回三段 + {conversation} 替换后的文本。"""
    result = get_autocompact_prompt("你好世界")
    assert NO_TOOLS_PREAMBLE in result
    assert BASE_COMPACT_PROMPT in result
    assert NO_TOOLS_TRAILER in result
    assert "你好世界" in result
    # 确认默认值里 {conversation} 被替换
    assert "{conversation}" not in result


def test_get_autocompact_prompt_custom(tmp_settings):
    """自定义时用 value,替换 {conversation}。"""
    save_prompt_override("autocompact_prompt", "前缀\n{conversation}\n后缀")
    result = get_autocompact_prompt("对话内容")
    assert result == "前缀\n对话内容\n后缀"


def test_get_template_default(tmp_settings):
    assert get_template() == DEFAULT_TEMPLATE


def test_get_template_custom(tmp_settings):
    save_prompt_override("session_memory_template", "自定义模板")
    assert get_template() == "自定义模板"


def test_get_update_prompt_default(tmp_settings):
    result = get_update_prompt(current_notes="现有笔记", memory_path="/tmp/notes.md")
    assert "{current_notes}" not in result
    assert "现有笔记" in result
    assert "/tmp/notes.md" in result


def test_get_update_prompt_custom(tmp_settings):
    save_prompt_override(
        "session_memory_update_prompt",
        "更新笔记 {memory_path}\n当前:\n{current_notes}",
    )
    result = get_update_prompt(current_notes="N", memory_path="/p.md")
    assert result == "更新笔记 /p.md\n当前:\nN"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_prompt_runtime.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_system_prompt'` / `DEFAULT_AUTOCOMPACT_PROMPT` 等

- [ ] **Step 3: 改造 `agent_core/prompts.py`**

把 `build_system_prompt` 函数（44-51 行）替换为：

```python
def get_system_prompt() -> str:
    """返回当前生效的主 system prompt:config 自定义 > 代码常量 SYSTEM_PROMPT。"""
    from ..config import load_prompts

    override = load_prompts().system_prompt
    if override.use_default or not override.value:
        return SYSTEM_PROMPT
    return override.value


def build_system_prompt(skills_section: str = "", mcp_section: str = "") -> str:
    """组装完整 system prompt:基础 prompt(读 config)+ (可选)skills 清单段 + (可选)MCP 能力段。"""
    prompt = get_system_prompt()
    if skills_section:
        prompt += SKILLS_SECTION_HEADER + "\n" + skills_section + "\n"
    if mcp_section:
        prompt += MCP_SECTION_HEADER + "\n" + mcp_section + "\n"
    return prompt
```

（`from ..config import load_prompts` 放函数内是避免循环 import：config.py 不应被 prompts.py 顶层依赖。）

- [ ] **Step 4: 改造 `compaction/prompts.py`**

在 `compaction/prompts.py` 末尾追加：

```python
DEFAULT_AUTOCOMPACT_PROMPT = (
    NO_TOOLS_PREAMBLE
    + "\n\n"
    + BASE_COMPACT_PROMPT
    + "\n\n对话内容:\n{conversation}\n\n"
    + NO_TOOLS_TRAILER
)


def get_autocompact_prompt(conversation_text: str) -> str:
    """返回 autocompact 完整 prompt:config 自定义 > 默认三段拼接。

    用户自定义文本必须含 {conversation} 占位符(保存时已校验)。
    运行时把 {conversation} 替换为对话文本。
    """
    from ..config import load_prompts

    override = load_prompts().autocompact_prompt
    template = DEFAULT_AUTOCOMPACT_PROMPT if override.use_default or not override.value else override.value
    return template.format(conversation=conversation_text)
```

- [ ] **Step 5: 改造 `compaction/autocompact.py`**

把 `autocompact.py` 第 13 行的 import 和 36-44 行的拼接逻辑替换。

原 import（13 行）：
```python
from .prompts import BASE_COMPACT_PROMPT, NO_TOOLS_PREAMBLE, NO_TOOLS_TRAILER
```
改为：
```python
from .prompts import get_autocompact_prompt
```

原拼接（36-44 行附近）：
```python
    # 1. 拼 prompt
    conversation_text = _messages_to_text(messages)
    full_prompt = "\n\n".join(
        [
            NO_TOOLS_PREAMBLE,
            BASE_COMPACT_PROMPT,
            "对话内容:",
            conversation_text,
            NO_TOOLS_TRAILER,
        ]
    )
```
改为：
```python
    # 1. 拼 prompt(读 config,支持用户自定义)
    conversation_text = _messages_to_text(messages)
    full_prompt = get_autocompact_prompt(conversation_text)
```

- [ ] **Step 6: 改造 `session_memory/template.py`**

把 `get_template()` 和 `get_update_prompt()` 函数（79-94 行）替换为：

```python
def get_template() -> str:
    """返回当前生效的 session memory 模板:config 自定义 > DEFAULT_TEMPLATE。"""
    from ..config import load_prompts

    override = load_prompts().session_memory_template
    if override.use_default or not override.value:
        return DEFAULT_TEMPLATE
    return override.value


def get_update_prompt(current_notes: str, memory_path: str) -> str:
    """根据当前笔记 + 笔记路径,组装更新 prompt。

    自定义文本支持 {current_notes} / {memory_path} 占位符(缺占位符不报错,
    用户自行负责)。
    """
    from ..config import load_prompts

    override = load_prompts().session_memory_update_prompt
    template = DEFAULT_UPDATE_PROMPT if override.use_default or not override.value else override.value
    return template.format(current_notes=current_notes, memory_path=str(memory_path))
```

- [ ] **Step 7: 运行新测试确认通过**

Run: `pytest tests/unit/test_prompt_runtime.py -v`
Expected: 全部 pass

- [ ] **Step 8: 跑现有相关测试确保没回归**

Run: `pytest tests/unit/test_compaction_autocompact.py tests/unit/test_session_memory.py -v`
Expected: 全部 pass（autocompact 行为零变化：默认 prompt 拼出来等价于原来的拼接顺序）

- [ ] **Step 9: 提交**

```bash
git add src/taisang/agent_core/prompts.py src/taisang/compaction/prompts.py src/taisang/compaction/autocompact.py src/taisang/session_memory/template.py tests/unit/test_prompt_runtime.py
git commit -m "feat(prompts): prompts read from config with fallback to code constants"
```

---

## Task 3: AgentContext.replace_system_prompt

**Files:**
- Modify: `src/taisang/agent_core/context.py`（在 `append_system` 后追加方法）
- Test: `tests/unit/test_context.py`（追加测试）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_context.py` 末尾追加：

```python
def test_replace_system_prompt_updates_messages_zero():
    """replace_system_prompt 原地替换 messages[0] 的 content(若存在 system 消息)。"""
    ctx = AgentContext()
    ctx.append_system("原 system")
    ctx.append_user("hi")
    ctx.replace_system_prompt("新 system")
    msgs = ctx.messages()
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "新 system"
    assert msgs[1]["content"] == "hi"  # 其他消息不变


def test_replace_system_prompt_no_system_does_nothing():
    """没有 system 消息时 no-op(不插入)。"""
    ctx = AgentContext()
    ctx.append_user("hi")
    ctx.replace_system_prompt("新 system")
    msgs = ctx.messages()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_replace_system_prompt_replaces_only_first():
    """只替换第一个 system 消息(去重后通常只有一个)。"""
    ctx = AgentContext()
    ctx.append_system("原 system 1")
    ctx.append_system("原 system 2")  # 罕见,但测一下只换第一个
    ctx.replace_system_prompt("新 system")
    msgs = ctx.messages()
    assert msgs[0]["content"] == "新 system"
    assert msgs[1]["content"] == "原 system 2"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_context.py::test_replace_system_prompt_updates_messages_zero -v`
Expected: FAIL with `AttributeError: 'AgentContext' object has no attribute 'replace_system_prompt'`

- [ ] **Step 3: 实现 replace_system_prompt**

在 `src/taisang/agent_core/context.py` 的 `append_system` 方法后追加：

```python
    def replace_system_prompt(self, text: str) -> None:
        """原地替换第一个 system 消息的 content。

        无 system 消息时 no-op(不主动插入)。
        用于 prompt 配置变更后广播到活跃 session。
        """
        for msg in self._messages:
            if msg["role"] == "system":
                msg["content"] = text
                break
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_context.py -v -k replace_system_prompt`
Expected: 3 passed

- [ ] **Step 5: 跑全部 context 测试确保没回归**

Run: `pytest tests/unit/test_context.py -v`
Expected: 全部 pass

- [ ] **Step 6: 提交**

```bash
git add src/taisang/agent_core/context.py tests/unit/test_context.py
git commit -m "feat(context): add replace_system_prompt for in-place system message update"
```

---

## Task 4: SessionRegistry.apply_prompts_config

**Files:**
- Modify: `src/taisang/web/session_registry.py`（在 `apply_llm_config` 后追加方法）
- Test: `tests/unit/test_prompts_api.py`（在 Task 5 一起写，这里先手动验证）

- [ ] **Step 1: 实现 apply_prompts_config**

在 `src/taisang/web/session_registry.py` 的 `apply_llm_config` 方法后（311 行附近）追加：

```python
    def apply_prompts_config(self, key: str) -> None:
        """改 prompt 后广播到所有内存 session。

        - key == "system_prompt":
            重新调 build_system_prompt(skills_section, mcp_section),
            替换每个 session 的 ctx.messages[0](system 消息)。
            skills/mcp 段从该 session 现有 agent 取,不丢。
        - 其他 key(autocompact / session_memory_*):
            触发时才读 config,不需要 broadcast,直接返回。
        - 正在跑的 run 持有 sess.lock,等它跑完下一次 LLM 调用自然用新 system
          —— 与 apply_llm_config 同语义。
        - MockLLM session 也替换 messages[0](system prompt 与 llm 类型无关)。
        """
        if key != "system_prompt":
            return
        with self._lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            agent = sess.agent
            # 重新组装 system prompt,保留 skills/mcp 段(与 service.__init__/reset 同逻辑)
            from ..skills.listing import format_skill_listing
            from ..agent_core.prompts import build_system_prompt, format_mcp_section
            skills_section = format_skill_listing(agent.skills)
            mcp_section = format_mcp_section(agent._mcp_manager) if getattr(agent, "_mcp_manager", None) else ""
            new_system = build_system_prompt(skills_section, mcp_section)
            agent.ctx.replace_system_prompt(new_system)
```

- [ ] **Step 2: 确认导入无误**

Run: `python -c "from taisang.web.session_registry import SessionRegistry; print('ok')"`
Expected: 输出 `ok`（无 ImportError）

- [ ] **Step 3: 跑现有 registry 相关测试确保没回归**

Run: `pytest tests/unit/test_web_app.py -v`
Expected: 全部 pass（apply_prompts_config 是新增方法，不改现有）

- [ ] **Step 4: 提交**

```bash
git add src/taisang/web/session_registry.py
git commit -m "feat(registry): add apply_prompts_config to broadcast system prompt changes"
```

---

## Task 5: prompts_api.py 路由

**Files:**
- Create: `src/taisang/web/prompts_api.py`
- Modify: `src/taisang/web/app.py`（注册路由）
- Test: `tests/unit/test_prompts_api.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_prompts_api.py`：

```python
"""prompts API 单测:GET/PUT/RESET + apply_prompts_config 广播。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from taisang.config import reset_prompt_override
from taisang.web.app import create_app
from taisang.web.session_registry import SessionRegistry


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    yield fake_home / ".taisang" / "settings.json"
    # 清理
    for key in ["system_prompt", "autocompact_prompt", "session_memory_template", "session_memory_update_prompt"]:
        try:
            reset_prompt_override(key)
        except Exception:
            pass


@pytest.fixture
def app(tmp_settings, tmp_path):
    """创建 app,source_root 指向 tmp_path。"""
    return create_app(source_root=tmp_path, allow_dirs=[tmp_path])


@pytest.fixture
def client(app):
    return TestClient(app)


def test_get_prompts_returns_four_keys_with_defaults(client):
    """GET 返回四个 key,每个有 current/default/use_default。"""
    r = client.get("/api/prompts")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {
        "system_prompt",
        "autocompact_prompt",
        "session_memory_template",
        "session_memory_update_prompt",
    }
    for key, item in data.items():
        assert "current" in item and "default" in item and "use_default" in item
        assert item["use_default"] is True
        assert item["current"] == item["default"]  # 默认时 current=default


def test_put_prompt_saves_value(client, tmp_settings):
    """PUT 保存 value,use_default=false。"""
    r = client.put("/api/prompts", json={"key": "system_prompt", "value": "自定义 system"})
    assert r.status_code == 200
    body = r.json()
    assert body["system_prompt"]["use_default"] is False
    assert body["system_prompt"]["value"] == "自定义 system"
    # GET 反映新值
    r2 = client.get("/api/prompts")
    assert r2.json()["system_prompt"]["current"] == "自定义 system"


def test_reset_prompt_restores_default(client, tmp_settings):
    """POST reset 后 use_default=true,current=default。"""
    client.put("/api/prompts", json={"key": "system_prompt", "value": "自定义"})
    r = client.post("/api/prompts/reset", json={"key": "system_prompt"})
    assert r.status_code == 200
    body = r.json()
    assert body["system_prompt"]["use_default"] is True
    assert body["system_prompt"]["current"] == body["system_prompt"]["default"]


def test_put_invalid_key_returns_400(client):
    r = client.put("/api/prompts", json={"key": "nonexistent", "value": "x"})
    assert r.status_code == 400


def test_put_empty_value_returns_400(client):
    r = client.put("/api/prompts", json={"key": "system_prompt", "value": ""})
    assert r.status_code == 400


def test_put_autocompact_missing_conversation_placeholder_returns_400(client):
    """autocompact_prompt 自定义文本缺 {conversation} → 400。"""
    r = client.put("/api/prompts", json={"key": "autocompact_prompt", "value": "没有占位符的文本"})
    assert r.status_code == 400
    assert "{conversation}" in r.json()["detail"]


def test_put_autocompact_with_placeholder_succeeds(client, tmp_settings):
    """autocompact_prompt 含 {conversation} → 保存成功。"""
    r = client.put("/api/prompts", json={"key": "autocompact_prompt", "value": "前缀\n{conversation}\n后缀"})
    assert r.status_code == 200


def test_reset_invalid_key_returns_400(client):
    r = client.post("/api/prompts/reset", json={"key": "nonexistent"})
    assert r.status_code == 400


def test_put_system_prompt_broadcasts_to_active_session(client, app, tmp_path):
    """PUT system_prompt 后,活跃 session 的 messages[0] 被替换为新 system(含 skills/mcp 段)。"""
    registry: SessionRegistry = app.state.registry
    sid = registry.create(title="test")
    sess = registry.get_or_load(sid)
    original_system = sess.agent.ctx.messages()[0]["content"]

    # 保存自定义 system prompt
    client.put("/api/prompts", json={"key": "system_prompt", "value": "全新 system prompt"})

    # 验证 messages[0] 被替换
    new_system = sess.agent.ctx.messages()[0]["content"]
    assert new_system != original_system
    assert new_system.startswith("全新 system prompt")


def test_put_autocompact_does_not_broadcast(client, app, tmp_path):
    """PUT autocompact_prompt 不触发 broadcast(不需要,触发时才读 config)。"""
    registry: SessionRegistry = app.state.registry
    sid = registry.create(title="test")
    sess = registry.get_or_load(sid)
    original_system = sess.agent.ctx.messages()[0]["content"]

    client.put("/api/prompts", json={"key": "autocompact_prompt", "value": "前缀\n{conversation}\n后缀"})

    # messages[0] 不变
    assert sess.agent.ctx.messages()[0]["content"] == original_system


def test_reset_system_prompt_broadcasts_default(client, app, tmp_path):
    """RESET system_prompt 后,活跃 session 的 messages[0] 恢复为默认 system。"""
    registry: SessionRegistry = app.state.registry
    sid = registry.create(title="test")
    sess = registry.get_or_load(sid)

    # 先自定义,再 reset
    client.put("/api/prompts", json={"key": "system_prompt", "value": "临时 system"})
    assert sess.agent.ctx.messages()[0]["content"].startswith("临时 system")

    client.post("/api/prompts/reset", json={"key": "system_prompt"})
    # 恢复为默认 SYSTEM_PROMPT
    from taisang.agent_core.prompts import SYSTEM_PROMPT
    assert sess.agent.ctx.messages()[0]["content"].startswith(SYSTEM_PROMPT)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_prompts_api.py -v`
Expected: FAIL with 404（路由不存在）或 ImportError

- [ ] **Step 3: 实现 prompts_api.py**

新建 `src/taisang/web/prompts_api.py`：

```python
"""Prompt 管理 API 路由:GET / PUT / RESET。

四份 prompt(system_prompt / autocompact_prompt / session_memory_template /
session_memory_update_prompt)持久化到 ~/.taisang/settings.json。
PUT/RESET system_prompt 时调 registry.apply_prompts_config 广播到所有活跃 session。
"""

from __future__ import annotations

from fastapi import HTTPException

from ..agent_core.prompts import SYSTEM_PROMPT, get_system_prompt
from ..compaction.prompts import DEFAULT_AUTOCOMPACT_PROMPT
from ..config import (
    PROMPT_KEYS,
    load_prompts,
    reset_prompt_override,
    save_prompt_override,
)
from ..session_memory.template import DEFAULT_TEMPLATE, DEFAULT_UPDATE_PROMPT


# 默认值查表:GET 时返回每个 key 的 default(代码常量)
_DEFAULT_VALUES = {
    "system_prompt": SYSTEM_PROMPT,
    "autocompact_prompt": DEFAULT_AUTOCOMPACT_PROMPT,
    "session_memory_template": DEFAULT_TEMPLATE,
    "session_memory_update_prompt": DEFAULT_UPDATE_PROMPT,
}


def _build_response() -> dict:
    """组装 GET 响应:{ key: { current, default, use_default } }。"""
    cfg = load_prompts()
    result = {}
    for key in PROMPT_KEYS:
        override = getattr(cfg, key)
        default = _DEFAULT_VALUES[key]
        current = default if override.use_default or not override.value else override.value
        result[key] = {
            "current": current,
            "default": default,
            "use_default": override.use_default,
        }
    return result


def register_prompts_routes(app, registry) -> None:
    """注册 /api/prompts 路由。registry 用于 broadcast system prompt 变更。"""

    @app.get("/api/prompts")
    async def get_prompts() -> dict:
        return _build_response()

    @app.put("/api/prompts")
    async def save_prompt(req: dict) -> dict:
        key = req.get("key")
        value = req.get("value")
        if key not in PROMPT_KEYS:
            raise HTTPException(400, f"非法 key: {key}")
        if not value or not isinstance(value, str):
            raise HTTPException(400, "value 不能为空")
        # autocompact_prompt 自定义文本必须含 {conversation} 占位符
        if key == "autocompact_prompt" and "{conversation}" not in value:
            raise HTTPException(400, "autocompact prompt 必须包含 {conversation} 占位符")
        try:
            save_prompt_override(key, value)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        # broadcast(只对 system_prompt 生效,其他 key no-op)
        registry.apply_prompts_config(key)
        return _build_response()

    @app.post("/api/prompts/reset")
    async def reset_prompt(req: dict) -> dict:
        key = req.get("key")
        if key not in PROMPT_KEYS:
            raise HTTPException(400, f"非法 key: {key}")
        try:
            reset_prompt_override(key)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        registry.apply_prompts_config(key)
        return _build_response()
```

- [ ] **Step 4: 在 app.py 注册路由**

在 `src/taisang/web/app.py` 第 239 行 `register_skills_routes(app, source_root)` 后追加：

```python
    from .prompts_api import register_prompts_routes
    register_prompts_routes(app, registry)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/unit/test_prompts_api.py -v`
Expected: 全部 pass（11 passed）

- [ ] **Step 6: 跑全部 web 测试确保没回归**

Run: `pytest tests/unit/test_web_app.py tests/unit/test_skills_api.py tests/unit/test_mcp_api.py -v`
Expected: 全部 pass

- [ ] **Step 7: 提交**

```bash
git add src/taisang/web/prompts_api.py src/taisang/web/app.py tests/unit/test_prompts_api.py
git commit -m "feat(web): add /api/prompts GET/PUT/RESET endpoints with broadcast"
```

---

## Task 6: 前端 API client

**Files:**
- Create: `src/taisang/web/frontend/src/api/prompts.ts`

- [ ] **Step 1: 新建 prompts.ts**

```typescript
import { apiGet, apiPost, apiPut } from './request'

export type PromptKey =
  | 'system_prompt'
  | 'autocompact_prompt'
  | 'session_memory_template'
  | 'session_memory_update_prompt'

export interface PromptItem {
  current: string
  default: string
  use_default: boolean
}

export type PromptsMap = Record<PromptKey, PromptItem>

export function fetchPrompts(): Promise<PromptsMap> {
  return apiGet<PromptsMap>('/api/prompts')
}

export function savePrompt(key: PromptKey, value: string): Promise<PromptsMap> {
  return apiPut<PromptsMap>('/api/prompts', { key, value })
}

export function resetPrompt(key: PromptKey): Promise<PromptsMap> {
  return apiPost<PromptsMap>('/api/prompts/reset', { key })
}
```

- [ ] **Step 2: 验证 TS 编译**

Run: `cd src/taisang/web/frontend && npx tsc --noEmit`
Expected: 无错误（如 tsconfig 配置允许；如该命令不可用，跳过，留到 Task 8 整体构建验证）

- [ ] **Step 3: 提交**

```bash
git add src/taisang/web/frontend/src/api/prompts.ts
git commit -m "feat(frontend): add prompts API client"
```

---

## Task 7: 前端 PromptManage.vue 页面

**Files:**
- Create: `src/taisang/web/frontend/src/views/PromptManage.vue`
- Modify: `src/taisang/web/frontend/src/router/index.ts`
- Modify: `src/taisang/web/frontend/src/components/Sidebar.vue`

- [ ] **Step 1: 新建 PromptManage.vue**

```vue
<template>
  <div class="prompt-manage">
    <div class="page-header">
      <h2 class="page-title">Prompt 管理</h2>
      <div class="page-hint">Prompt 修改全局生效,对所有会话立即应用。</div>
    </div>

    <t-collapse :default-expand-all="true">
      <t-collapse-panel
        v-for="p in panels"
        :key="p.key"
        :header="p.title"
      >
        <template #default>
          <div class="panel-body">
            <div class="panel-toolbar">
              <t-tag
                :theme="state[p.key].useDefault ? 'default' : 'primary'"
                size="small"
              >
                {{ state[p.key].useDefault ? '使用默认' : '自定义' }}
              </t-tag>
              <span class="status-line" :class="statusClass(p.key)">
                {{ statusText(p.key) }}
              </span>
              <div class="toolbar-spacer" />
              <t-button
                variant="outline"
                size="small"
                :disabled="state[p.key].useDefault && !dirty(p.key)"
                @click="onReset(p.key)"
              >
                恢复默认
              </t-button>
              <t-button
                theme="primary"
                size="small"
                :disabled="!dirty(p.key) || !state[p.key].draft"
                :loading="state[p.key].saving"
                @click="onSave(p.key)"
              >
                保存
              </t-button>
            </div>
            <textarea
              v-model="state[p.key].draft"
              class="prompt-textarea"
              :rows="20"
              spellcheck="false"
            />
          </div>
        </template>
      </t-collapse-panel>
    </t-collapse>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  fetchPrompts,
  savePrompt,
  resetPrompt,
  type PromptKey,
  type PromptsMap,
} from '@/api/prompts'

interface PanelState {
  original: string
  draft: string
  useDefault: boolean
  saving: boolean
  justSaved: boolean
}

interface PanelMeta {
  key: PromptKey
  title: string
  confirmText: string
}

const panels: PanelMeta[] = [
  {
    key: 'system_prompt',
    title: '主 System Prompt',
    confirmText:
      '⚠️ 修改主 System Prompt 将立即应用到所有活跃会话。\n' +
      '- 当前进行中的对话,agent 行为指令会中途切换,可能导致前后风格/约束不一致;\n' +
      '- API 的 prompt cache 会失效,下一次响应稍慢、多消耗一次前缀 token,之后自动重建。\n\n' +
      '建议在新会话开始前修改。是否继续?',
  },
  {
    key: 'autocompact_prompt',
    title: 'Autocompact 摘要 Prompt',
    confirmText:
      '⚠️ 修改后将立即保存。下次触发上下文压缩时使用新 prompt。\n' +
      '当前进行中的对话不受影响(只有触发 compaction 时才用到)。\n\n' +
      '是否继续?\n\n' +
      '注意:自定义文本必须包含 {conversation} 占位符,否则保存会失败。',
  },
  {
    key: 'session_memory_template',
    title: 'Session Memory 模板',
    confirmText:
      '⚠️ 修改后将立即保存。下次触发笔记更新时使用新模板。\n' +
      '当前进行中的对话不受影响(只有触发 compaction 时才用到)。\n\n是否继续?',
  },
  {
    key: 'session_memory_update_prompt',
    title: 'Session Memory 更新指令',
    confirmText:
      '⚠️ 修改后将立即保存。下次触发笔记更新时使用新指令。\n' +
      '当前进行中的对话不受影响(只有触发 compaction 时才用到)。\n\n' +
      '注意:自定义文本支持 {current_notes} 和 {memory_path} 占位符(缺了不报错)。\n\n是否继续?',
  },
]

const state = reactive<Record<PromptKey, PanelState>>({
  system_prompt: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
  autocompact_prompt: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
  session_memory_template: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
  session_memory_update_prompt: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
})

function dirty(key: PromptKey): boolean {
  return state[key].draft !== state[key].original
}

function statusClass(key: PromptKey): string {
  if (state[key].justSaved) return 'status-saved'
  if (dirty(key)) return 'status-dirty'
  if (state[key].useDefault) return 'status-default'
  return 'status-clean'
}

function statusText(key: PromptKey): string {
  if (state[key].justSaved) return '已保存'
  if (dirty(key)) return '未保存改动'
  if (state[key].useDefault) return '使用默认值'
  return '已保存'
}

function applyResponse(data: PromptsMap) {
  for (const p of panels) {
    const item = data[p.key]
    state[p.key].original = item.current
    state[p.key].draft = item.current
    state[p.key].useDefault = item.use_default
  }
}

async function load() {
  try {
    const data = await fetchPrompts()
    applyResponse(data)
  } catch (e) {
    MessagePlugin.error('加载 prompt 配置失败')
  }
}

async function onSave(key: PromptKey) {
  const meta = panels.find((p) => p.key === key)!
  if (!confirm(meta.confirmText)) return
  state[key].saving = true
  try {
    const data = await savePrompt(key, state[key].draft)
    applyResponse(data)
    state[key].justSaved = true
    MessagePlugin.success('保存成功')
    setTimeout(() => {
      state[key].justSaved = false
    }, 2000)
  } catch (e: any) {
    const msg = e?.message || '保存失败'
    MessagePlugin.error(msg)
  } finally {
    state[key].saving = false
  }
}

async function onReset(key: PromptKey) {
  if (!confirm('将恢复为内置默认值,自定义内容会被覆盖。是否继续?')) return
  state[key].saving = true
  try {
    const data = await resetPrompt(key)
    applyResponse(data)
    MessagePlugin.success('已恢复默认')
  } catch (e: any) {
    MessagePlugin.error(e?.message || '恢复失败')
  } finally {
    state[key].saving = false
  }
}

function anyDirty(): boolean {
  return panels.some((p) => dirty(p.key))
}

onMounted(() => {
  load()
  window.addEventListener('beforeunload', onBeforeUnload)
})

onBeforeRouteLeave(() => {
  if (anyDirty() && !confirm('有未保存的 prompt 修改,确定离开?')) {
    return false
  }
  return true
})

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (anyDirty()) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<style scoped>
.prompt-manage {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.page-header {
  margin-bottom: 16px;
}
.page-title {
  margin: 0 0 4px 0;
}
.page-hint {
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.panel-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toolbar-spacer {
  flex: 1;
}
.status-line {
  font-size: 13px;
  color: var(--td-text-color-placeholder);
}
.status-dirty {
  color: var(--td-warning-color);
}
.status-saved {
  color: var(--td-success-color);
}
.status-default {
  color: var(--td-text-color-placeholder);
}
.status-clean {
  color: var(--td-success-color);
}
.prompt-textarea {
  width: 100%;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  line-height: 1.5;
  padding: 12px;
  border: 1px solid var(--td-border-level-2-color);
  border-radius: 4px;
  resize: vertical;
  min-height: 300px;
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
}
</style>
```

- [ ] **Step 2: 加路由**

修改 `src/taisang/web/frontend/src/router/index.ts`，在 `const McpManage = ...` 后加：

```typescript
const PromptManage = () => import('@/views/PromptManage.vue')
```

在 `routes` 数组里 `/mcp` 路由后加：

```typescript
    { path: '/prompts', name: 'prompts', component: PromptManage },
```

完整修改后文件：

```typescript
import { createRouter, createWebHistory } from 'vue-router'

const ChatView = () => import('@/views/ChatView.vue')
const SkillManage = () => import('@/views/SkillManage.vue')
const McpManage = () => import('@/views/McpManage.vue')
const PromptManage = () => import('@/views/PromptManage.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: ChatView },
    { path: '/chat/:id', name: 'chat', component: ChatView },
    { path: '/skills', name: 'skills', component: SkillManage },
    { path: '/mcp', name: 'mcp', component: McpManage },
    { path: '/prompts', name: 'prompts', component: PromptManage },
  ],
})

export default router
```

- [ ] **Step 3: 加 Sidebar 入口**

修改 `src/taisang/web/frontend/src/components/Sidebar.vue` 的 `<nav class="nav-menu">` 块，在 MCP 管理后加 Prompt 管理：

```html
    <nav class="nav-menu" aria-label="管理入口">
      <div class="menu-item" @click="router.push('/skills')">
        <t-icon name="code" class="menu-icon" />
        <span class="menu-title">Skill 管理</span>
      </div>
      <div class="menu-item" @click="router.push('/mcp')">
        <t-icon name="server" class="menu-icon" />
        <span class="menu-title">MCP 管理</span>
      </div>
      <div class="menu-item" @click="router.push('/prompts')">
        <t-icon name="edit-1" class="menu-icon" />
        <span class="menu-title">Prompt 管理</span>
      </div>
    </nav>
```

- [ ] **Step 4: 构建前端验证无错**

Run: `cd src/taisang/web/frontend && npm run build`
Expected: 构建成功，无 TS 错误

- [ ] **Step 5: 启动后端 + 前端 dev server 手动验证**

启动后端：`cd D:/GoProject/TaiSang && python -m taisang web --source-root .`
启动前端：`cd src/taisang/web/frontend && npm run dev`
浏览器打开前端地址，手动验证清单：
- [ ] 点击 Sidebar "Prompt 管理"，进入 `/prompts`
- [ ] 四个折叠面板默认展开，每个显示当前 prompt 文本
- [ ] 标签显示"使用默认"
- [ ] 编辑主 System Prompt，状态行变"未保存改动"（橙色）
- [ ] 点保存，弹确认框（含 cache 失效提示），确认后状态行变"已保存"（绿色，2 秒后恢复）
- [ ] 标签变"自定义"
- [ ] 点"恢复默认"，弹确认，确认后 textarea 替换为默认值，标签变"使用默认"
- [ ] 编辑 Autocompact prompt，故意删掉 `{conversation}` 占位符，保存应失败并提示
- [ ] 编辑有未保存改动时尝试离开页面，应弹"有未保存的 prompt 修改,确定离开?"
- [ ] 改主 system prompt 后，开一个活跃 session，发消息，开 `/debug` 验证 messages[0] 是新 system prompt

- [ ] **Step 6: 提交**

```bash
git add src/taisang/web/frontend/src/views/PromptManage.vue src/taisang/web/frontend/src/router/index.ts src/taisang/web/frontend/src/components/Sidebar.vue
git commit -m "feat(frontend): add /prompts page with 4 panels for prompt management"
```

---

## Task 8: 最终全量验证

- [ ] **Step 1: 跑全部后端单测**

Run: `cd D:/GoProject/TaiSang && pytest tests/unit/ -v`
Expected: 全部 pass（含新增的 test_prompts_config / test_prompts_api / test_prompt_runtime，现有测试无回归）

- [ ] **Step 2: 跑集成测试(若有)**

Run: `cd D:/GoProject/TaiSang && pytest tests/integration/ -v 2>&1 | tail -20`
Expected: 全部 pass

- [ ] **Step 3: 跑前端构建**

Run: `cd src/taisang/web/frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 手动端到端验证(完整流程)**

1. 启动后端 + 前端 dev server
2. 新建一个 session，发条消息，确认 agent 正常工作（用默认 prompt）
3. 进 `/prompts`，改主 system prompt（加一句"回复末尾必须加 [TESTED]"），保存
4. 回到刚才的 session，发新消息，确认 agent 回复末尾有 `[TESTED]`（验证 broadcast 生效）
5. 进 `/prompts`，改 autocompact prompt（保留 `{conversation}`），保存
6. 在 session 里持续发消息直到触发 autocompact，确认压缩成功（debug 模式看日志）
7. 进 `/prompts`，把主 system prompt "恢复默认"
8. 回 session 发消息，确认 `[TESTED]` 消失（验证 reset broadcast 生效）
9. 重启 TaiSang 进程，进 `/prompts`，确认自定义配置持久化（autocompact 还是自定义）

- [ ] **Step 5: 提交(若有遗漏的改动)**

```bash
git status
# 若有遗漏改动:
git add <files>
git commit -m "test: e2e verification passed for prompt management"
```

---

## 实施顺序总结

1. Task 1: PromptsConfig 持久化层（后端基础）
2. Task 2: 三个 prompt 源文件改造为读 config（后端运行时）
3. Task 3: AgentContext.replace_system_prompt（后端 broadcast 基础）
4. Task 4: SessionRegistry.apply_prompts_config（后端 broadcast）
5. Task 5: prompts_api.py 路由（后端 API）
6. Task 6: 前端 API client（前端基础）
7. Task 7: PromptManage.vue + 路由 + Sidebar（前端页面）
8. Task 8: 最终全量验证

每个 Task 独立可测、可提交。Task 1-5 后端，Task 6-7 前端，Task 8 整体验证。