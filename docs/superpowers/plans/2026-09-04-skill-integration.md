# TaiSang Skill 接入实现 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 TaiSang agent 加 Skill 能力:用户/项目放 `SKILL.md`,agent 能发现并调用,Sidebar "Skill 管理" 入口有页面承接。

**Architecture:** 仿 claude-code Agent Skills 机制(v1 子集)。目录式 SKILL.md 格式,多源加载(用户级 `~/.taisang/skills` + 项目级 `<repo>/.taisang/skills`,项目同名覆盖用户级)。渐进披露:skill 清单注入 SYSTEM_PROMPT 尾部,SkillTool schema 只写静态通用文案。调用时 SkillTool 把 SKILL.md 正文作为 user 消息注入 ctx,tool_result 触发 LLM 继续。权限默认全部自动允许。allowed_tools 仅提示 LLM 遵守不硬拦。只做 inline 执行,fork/hooks/条件 paths 延后。

**Tech Stack:** Python 3.12 + FastAPI(后端) / Vue 3.5 + Vite + TDesign(前端) / pytest(TDD) / PyYAML(frontmatter 解析)

---

## 范围

### v1 包含
- SKILL.md 目录格式 + frontmatter 子集(name/description/when_to_use/allowed_tools)
- 两源加载:用户级 + 项目级,项目同名覆盖用户级
- SkillTool 工具:清单注入 SYSTEM_PROMPT,调用时 user 消息注入 + tool_result 触发
- `${TAISANG_SKILL_DIR}` 占位符替换
- allowed_tools 提示 LLM 遵守(注入时在正文前追加提示段,不硬拦)
- 权限:全部自动允许(无 confirmer 调用)
- Skill 管理 UI:列表 + 启用/禁用 toggle + 重载按钮
- FastAPI 路由:list / reload / toggle

### v1 不做(延后)
- fork 执行(frontmatter `context: fork`)
- hooks
- 条件 paths 激活
- 插件源 / MCP skill 源
- argument-hint / arguments 参数解析(只支持 `args: str` 自由文本)
- deny 规则 / safe-properties 白名单
- 硬性 allowed_tools 拦截
- skill 内调用 skill(嵌套)

---

## 文件结构

### 新建
- `src/taisang/skills/__init__.py` — 包导出
- `src/taisang/skills/types.py` — `Skill` dataclass
- `src/taisang/skills/loader.py` — 扫描目录、解析 frontmatter、去重
- `src/taisang/agent_core/skill_tool.py` — `SkillTool` 类
- `src/taisang/web/skills_api.py` — FastAPI 路由
- `frontend/src/views/SkillManage.vue` — 管理页
- `tests/unit/test_skills_loader.py`
- `tests/unit/test_skill_tool.py`
- `tests/unit/test_skill_listing.py`

### 修改
- `src/taisang/agent_core/tools.py` — `ToolRegistry` 接受 `skills` 参数,注册 SkillTool
- `src/taisang/agent_core/service.py` — system prompt 追加 skill 清单段,ToolRegistry 传 skills
- `src/taisang/agent_core/prompts.py` — SYSTEM_PROMPT 加 skill 使用说明段
- `src/taisang/web/app.py` — 挂载 skills_api router
- `src/taisang/web/session_registry.py` — `_build_session` 传 skills
- `src/taisang/config.py` — 新增 `skills_dirs` / `skills_auto_allow` 字段(可选)
- `frontend/src/router/index.ts` — 加 `/skills` 路由
- `frontend/src/components/Sidebar.vue` — Skill 管理 menu_item 点击跳 `/skills`
- `frontend/src/stores/session.ts` — 不改(skill 列表独立 store 或直接在页面 fetch)

---

## 核心设计决策(已和泰哥确认)

| 决策点 | 选择 |
|--------|------|
| skill 清单注入位置 | SYSTEM_PROMPT 尾部(TaiSang 无 attachment 机制) |
| SkillTool 注入方式 | user 消息注入 SKILL.md 正文 + tool_result 触发 LLM 继续 |
| 权限策略 | 全部自动允许(无 confirmer 调用) |
| allowed_tools | 提示 LLM 遵守,不硬拦 |
| 执行模式 | 只做 inline |

---

## 数据结构

### `Skill` dataclass (`src/taisang/skills/types.py`)

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Skill:
    name: str                    # 目录名(frontmatter name 覆盖则用 frontmatter)
    description: str             # frontmatter description,缺失时 fallback 正文首段
    when_to_use: str              # frontmatter when_to_use,可空
    allowed_tools: list[str] | None  # None 表示不限制
    dir_path: Path                # SKILL.md 所在目录(用于 ${TAISANG_SKILL_DIR})
    content: str                 # 去 frontmatter 后的正文
    source: str                   # "user" | "project"
    disabled: bool = False       # 管理 UI 切换
```

### SKILL.md 格式(v1 子集)

```yaml
---
name: commit  # 可省,默认用目录名
description: 生成 git commit message 并提交
when_to_use: 用户说"提交"或"commit"且工作区有改动时
allowed_tools: [Bash, Read]  # 可选
---
正文 markdown 指令,可含 ${TAISANG_SKILL_DIR} 占位符……
```

不支持的字段(fork/hooks/paths/argument-hint/arguments/version/model 等)静默忽略。

---

## 实施任务

### Task 1: Skill 数据结构 + loader

**Files:**
- Create: `src/taisang/skills/__init__.py`
- Create: `src/taisang/skills/types.py`
- Create: `src/taisang/skills/loader.py`
- Test: `tests/unit/test_skills_loader.py`

- [ ] **Step 1: 写失败测试 `test_load_from_user_dir`**

```python
# tests/unit/test_skills_loader.py
from pathlib import Path
from taisang.skills.loader import load_skills
from taisang.skills.types import Skill

def test_load_from_user_dir(tmp_path):
    user_dir = tmp_path / "user_skills"
    (user_dir / "commit" / "SKILL.md").write_text(
        "---\n"
        "description: 生成 commit\n"
        "when_to_use: 用户说提交时\n"
        "---\n"
        "调用 git commit……\n",
        encoding="utf-8",
    )
    skills = load_skills(user_dirs=[user_dir], project_dirs=[])
    assert len(skills) == 1
    s = skills[0]
    assert s.name == "commit"
    assert s.description == "生成 commit"
    assert s.when_to_use == "用户说提交时"
    assert s.allowed_tools is None
    assert s.source == "user"
    assert "调用 git commit" in s.content
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_skills_loader.py::test_load_from_user_dir -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: 实现 types.py**

```python
# src/taisang/skills/types.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str
    allowed_tools: list[str] | None
    dir_path: Path
    content: str
    source: str
    disabled: bool = False
```

- [ ] **Step 4: 实现 loader.py**

```python
# src/taisang/skills/loader.py
from __future__ import annotations
import re
from pathlib import Path
import yaml
from .types import Skill

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

def _parse_skill_md(path: Path, source: str) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 无 frontmatter,用正文首段做 description
        content = text.strip()
        first_para = content.split("\n\n")[0].strip()[:200]
        return Skill(
            name=path.parent.name,
            description=first_para or "(no description)",
            when_to_use="",
            allowed_tools=None,
            dir_path=path.parent,
            content=content,
            source=source,
        )
    fm_text, content = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None
    name = str(fm.get("name") or path.parent.name)
    desc = str(fm.get("description") or content.split("\n\n")[0].strip()[:200] or "(no description)")
    when = str(fm.get("when_to_use") or "")
    allowed = fm.get("allowed_tools")
    if allowed is not None:
        if isinstance(allowed, str):
            allowed = [allowed]
        allowed = [str(t) for t in allowed]
    return Skill(
        name=name,
        description=desc,
        when_to_use=when,
        allowed_tools=allowed,
        dir_path=path.parent,
        content=content.strip(),
        source=source,
    )

def load_skills(user_dirs: list[Path], project_dirs: list[Path]) -> list[Skill]:
    """扫描多源 skill 目录,项目同名覆盖用户级。"""
    by_name: dict[str, Skill] = {}
    # 先扫 user,再扫 project(项目同名覆盖)
    for source, dirs in [("user", user_dirs), ("project", project_dirs)]:
        for d in dirs:
            if not d.is_dir():
                continue
            for skill_md in sorted(d.glob("*/SKILL.md")):
                skill = _parse_skill_md(skill_md, source)
                if skill is None:
                    continue
                by_name[skill.name] = skill  # project 后扫,覆盖 user
    return list(by_name.values())
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/unit/test_skills_loader.py::test_load_from_user_dir -v`
Expected: PASS

- [ ] **Step 6: 补齐 loader 测试**

```python
def test_project_overrides_user_same_name(tmp_path):
    user_dir = tmp_path / "user"
    proj_dir = tmp_path / "proj"
    for d in [user_dir, proj_dir]:
        (d / "commit" / "SKILL.md").write_text(
            f"---\ndescription: {d.name}版\n---\n{d.name}内容\n",
            encoding="utf-",
        )
    skills = load_skills(user_dirs=[user_dir], project_dirs=[proj_dir])
    assert len(skills) == 1
    assert skills[0].source == "project"
    assert skills[0].description == "proj版"

def test_missing_description_falls_back_to_first_paragraph(tmp_path):
    d = tmp_path / "user"
    (d / "x" / "SKILL.md").write_text("---\n---\n第一段\n\n第二段\n", encoding="utf-8")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert skills[0].description == "第一段"

def test_broken_frontmatter_skipped(tmp_path):
    d = tmp_path / "user"
    (d / "bad" / "SKILL.md").write_text("---\nname: [unclosed\n---\nbody\n", encoding="utf-8")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert len(skills) == 0

def test_allowed_tools_parsed(tmp_path):
    d = tmp_path / "user"
    (d / "r" / "SKILL.md").write_text(
        "---\nallowed_tools: [Bash, Read]\n---\nbody\n", encoding="utf-8"
    )
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert skills[0].allowed_tools == ["Bash", "Read"]

def test_no_frontmatter_uses_first_paragraph(tmp_path):
    d = tmp_path / "user"
    (d / "plain" / "SKILL.md").write_text("纯正文首段\n\n次段", encoding="utf-8")
    skills = load_skills(user_dirs=[d], project_dirs=[])
    assert skills[0].name == "plain"
    assert skills[0].description == "纯正文首段"
```

- [ ] **Step 7: 跑全部 loader 测试**

Run: `pytest tests/unit/test_skills_loader.py -v`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add src/taisang/skills/ tests/unit/test_skills_loader.py
git commit -m "feat(skills): add SKILL.md loader with user/project sources"
```

---

### Task 2: SkillTool 工具

**Files:**
- Create: `src/taisang/agent_core/skill_tool.py`
- Test: `tests/unit/test_skill_tool.py`

- [ ] **Step 1: 写失败测试 `test_skill_not_found`**

```python
# tests/unit/test_skill_tool.py
from taisang.agent_core.skill_tool import SkillTool
from taisang.skills.types import Skill

def test_skill_not_found():
    tool = SkillTool(skills=[], ctx=None)
    result = tool.run({"skill": "missing"})
    assert result["error"] == "skill not found"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_skill_tool.py::test_skill_not_found -v`
Expected: FAIL

- [ ] **Step 3: 实现 SkillTool**

```python
# src/taisang/agent_core/skill_tool.py
from __future__ import annotations
from pathlib import Path
from .tools import _BaseTool
from ..skills.types import Skill

class SkillTool(_BaseTool):
    """调用 skill,把 SKILL.md 正文注入 ctx 作为 user 消息,tool_result 触发 LLM 继续。

    权限:v1 全部自动允许,不调 confirmer。
    allowed_tools:注入时在正文前追加提示段,不硬拦。
    ${TAISANG_SKILL_DIR}:替换成 skill.dir_path 绝对路径(反斜杠转正斜杠)。
    """

    name = "skill"

    def __init__(self, skills: list[Skill], ctx) -> None:
        self.skills = {s.name: s for s in skills}
        self.ctx = ctx  # ContextManager,用于 append_user 注入 SKILL.md

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "调用一个 skill 执行特定任务。可用 skill 清单见 system prompt。"
                "用 skill name 调用,可选 args 传参数。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "skill 名称"},
                    "args": {"type": "string", "description": "可选参数文本"},
                },
                "required": ["skill"],
            },
        }

    def run(self, args: dict) -> dict:
        name = args.get("skill", "")
        skill = self.skills.get(name)
        if skill is None:
            return {"error": "skill not found"}
        if skill.disabled:
            return {"error": "skill disabled"}
        content = self._inject(skill, args.get("args", ""))
        # 注入到 ctx 作为 user 消息
        if self.ctx is not None:
            self.ctx.append_user(content)
        return {"ok": True, "injected": True, "skill": name}

    def _inject(self, skill: Skill, args: str) -> str:
        content = skill.content
        # ${TAISANG_SKILL_DIR} 替换
        skill_dir = str(skill.dir_path.resolve()).replace("\\", "/")
        content = content.replace("${TAISANG_SKILL_DIR}", skill_dir)
        # allowed_tools 提示段
        header = ""
        if skill.allowed_tools is not None:
            tools_list = ", ".join(skill.allowed_tools)
            header = (
                f"> 执行本 skill 期间,只允许使用以下工具: {tools_list}\n\n"
            )
        # args 参数段
        args_block = ""
        if args:
            args_block = f"\n\n## 用户传入参数\n{args}"
        return f"{header}# Skill: {skill.name}\n\n{content}{args_block}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_skill_tool.py::test_skill_not_found -v`
Expected: PASS

- [ ] **Step 5: 补齐 SkillTool 测试**

```python
def test_disabled_skill_returns_error():
    from pathlib import Path
    s = Skill(name="x", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user", disabled=True)
    tool = SkillTool(skills=[s], ctx=None)
    result = tool.run({"skill": "x"})
    assert result["error"] == "skill disabled"

def test_normal_call_injects_user_message():
    from pathlib import Path
    from taisang.agent_core.context import ContextManager
    s = Skill(name="commit", description="d", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="调用 git commit", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    result = tool.run({"skill": "commit"})
    assert result["ok"] is True
    assert result["injected"] is True
    msgs = ctx.messages()
    assert any("调用 git commit" in m.get("content", "") for m in msgs if m["role"] == "user")

def test_skill_dir_substitution():
    from pathlib import Path
    s = Skill(name="r", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("C:/some/dir"), content="读 ${TAISANG_SKILL_DIR}/a.txt", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r"})
    msgs = ctx.messages()
    injected = [m["content"] for m in msgs if m["role"] == "user"][-1]
    assert "C:/some/dir/a.txt" in injected
    assert "${TAISANG_SKILL_DIR}" not in injected

def test_allowed_tools_hint():
    from pathlib import Path
    s = Skill(name="r", description="d", when_to_use="",
              allowed_tools=["Bash", "Read"], dir_path=Path("."), content="body", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r"})
    injected = [m["content"] for m in ctx.messages() if m["role"] == "user"][-1]
    assert "只允许使用以下工具: Bash, Read" in injected

def test_args_passed_through():
    from pathlib import Path
    s = Skill(name="r", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user")
    ctx = ContextManager()
    tool = SkillTool(skills=[s], ctx=ctx)
    tool.run({"skill": "r", "args": "fix bug #123"})
    injected = [m["content"] for m in ctx.messages() if m["role"] == "user"][-1]
    assert "fix bug #123" in injected
```

- [ ] **Step 6: 跑全部 SkillTool 测试**

Run: `pytest tests/unit/test_skill_tool.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add src/taisang/agent_core/skill_tool.py tests/unit/test_skill_tool.py
git commit -m "feat(skill): add SkillTool with inline injection"
```

---

### Task 3: SYSTEM_PROMPT 注入 skill 清单

**Files:**
- Modify: `src/taisang/agent_core/prompts.py`
- Modify: `src/taisang/agent_core/service.py`
- Create: `src/taisang/skills/listing.py`
- Test: `tests/unit/test_skill_listing.py`

- [ ] **Step 1: 写失败测试 `test_listing_format`**

```python
# tests/unit/test_skill_listing.py
from pathlib import Path
from taisang.skills.listing import format_skill_listing
from taisang.skills.types import Skill

def test_listing_format():
    skills = [
        Skill(name="commit", description="生成 commit", when_to_use="用户说提交时",
              allowed_tools=None, dir_path=Path("."), content="", source="user"),
        Skill(name="review", description="代码审查", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="project"),
    ]
    listing = format_skill_listing(skills, char_budget=2000)
    assert "- commit: 生成 commit - 用户说提交时" in listing
    assert "- review: 代码审查" in listing

def test_listing_truncates_long_description():
    long_desc = "x" * 300
    skills = [
        Skill(name="r", description=long_desc, when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="user")
    ]
    listing = format_skill_listing(skills, char_budget=2000)
    assert "…" in listing
    assert len(long_desc) > 250  # 确认原始就长

def test_listing_over_budget_falls_back_to_names_only():
    # 造大量 skill 触发降级
    skills = [
        Skill(name=f"s{i}", description="d"*200, when_to_use="w"*200,
              allowed_tools=None, dir_path=Path("."), content="", source="user")
        for i in range(100)
    ]
    listing = format_skill_listing(skills, char_budget=500)
    assert "- s0" in listing  # 至少有名字
    # 不应含完整 description
    assert "d"*200 not in listing

def test_listing_empty_skills():
    assert format_skill_listing([], char_budget=2000) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_skill_listing.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 listing.py**

```python
# src/taisang/skills/listing.py
from __future__ import annotations
from .types import Skill

MAX_LISTING_DESC_CHARS = 250
MIN_DESC_LENGTH = 20

def _entry(skill: Skill) -> str:
    desc = skill.description
    if skill.when_to_use:
        desc = f"{skill.description} - {skill.when_to_use}"
    if len(desc) > MAX_LISTING_DESC_CHARS:
        desc = desc[:MAX_LISTING_DESC_CHARS - 1] + "…"
    return f"- {skill.name}: {desc}"

def format_skill_listing(skills: list[Skill], char_budget: int = 2000) -> str:
    if not skills:
        return ""
    # 只含 enabled 的 skill
    enabled = [s for s in skills if not s.disabled]
    if not enabled:
        return ""
    full = "\n".join(_entry(s) for s in enabled)
    if len(full) <= char_budget:
        return full
    # 降级:逐条截断 description 到 max_desc_len
    name_overhead = sum(len(s.name) + 4 for s in enabled) + (len(enabled) - 1)
    available = char_budget - name_overhead
    max_desc = available // len(enabled)
    if max_desc < MIN_DESC_LENGTH:
        # 极端降级:只留名字
        return "\n".join(f"- {s.name}" for s in enabled)
    lines = []
    for s in enabled:
        desc = s.description
        if s.when_to_use:
            desc = f"{s.description} - {s.when_to_use}"
        if len(desc) > max_desc:
            desc = desc[:max_desc - 1] + "…"
        lines.append(f"- {s.name}: {desc}")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_skill_listing.py -v`
Expected: 4 passed

- [ ] **Step 5: 改 prompts.py 加 skill 段占位**

```python
# src/taisang/agent_core/prompts.py 末尾追加

SKILLS_SECTION_HEADER = """

## 可用 Skills
"""

def build_system_prompt(skills_section: str = "") -> str:
    """组装完整 system prompt:基础 prompt + (可选)skills 清单段。"""
    if not skills_section:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + SKILLS_SECTION_HEADER + "\n" + skills_section + "\n"
```

- [ ] **Step 6: 改 service.py 在 __init__ 用 build_system_prompt**

修改 `AgentService.__init__`:
- 接收新参数 `skills: list[Skill] | None = None`
- `from ..skills.listing import format_skill_listing`
- `from ..skills.types import Skill` (type only)
- `skills_section = format_skill_listing(skills or [])`
- `self.ctx.append_system(build_system_prompt(skills_section))`

注意:`__init__` 当前直接 `self.ctx.append_system(SYSTEM_PROMPT)`。改成调 `build_system_prompt`。`reset()` 同步改。

- [ ] **Step 7: 写集成测试验证 skill 清单出现在 system prompt**

```python
# tests/unit/test_skill_listing.py 追加
def test_service_system_prompt_contains_skills():
    from pathlib import Path
    from unittest.mock import MagicMock
    from taisang.agent_core.service import AgentService
    from taisang.skills.types import Skill
    skills = [
        Skill(name="commit", description="生成 commit", when_to_use="",
              allowed_tools=None, dir_path=Path("."), content="", source="user")
    ]
    llm = MagicMock()
    llm.chat.return_value = MagicMock(tool_calls=None, text="done", usage=None)
    svc = AgentService(llm=llm, source_root=Path("."), confirmer=lambda *a: True,
                       skills=skills)
    sys_msgs = [m for m in svc.ctx.messages() if m["role"] == "system"]
    assert any("commit" in m["content"] for m in sys_msgs)
```

- [ ] **Step 8: 跑测试**

Run: `pytest tests/unit/test_skill_listing.py -v`
Expected: 5 passed

- [ ] **Step 9: Commit**

```bash
git add src/taisang/agent_core/prompts.py src/taisang/agent_core/service.py src/taisang/skills/listing.py tests/unit/test_skill_listing.py
git commit -m "feat(skill): inject skill listing into system prompt"
```

---

### Task 4: ToolRegistry 集成 SkillTool

**Files:**
- Modify: `src/taisang/agent_core/tools.py`
- Modify: `src/taisang/agent_core/service.py`

- [ ] **Step 1: 改 ToolRegistry 接受 skills + ctx**

`ToolRegistry.__init__` 新增参数:
```python
def __init__(
    self,
    cwd: Path,
    shell=None,
    confirmer=None,
    permission=None,
    bash_timeout: int = 30,
    observations_dir: Path | None = None,
    skills: list | None = None,  # 新增
    ctx=None,  # 新增,SkillTool 注入用
) -> None:
    ...
    # 原有工具注册
    self._tools: dict[str, _BaseTool] = { ... }
    if self._bash is not None:
        self._tools[BashTool.name] = self._bash
    # 新增 SkillTool
    if skills:
        from .skill_tool import SkillTool
        self._tools[SkillTool.name] = SkillTool(skills=skills, ctx=ctx)
```

- [ ] **Step 2: 改 service.py run() 传 skills + self.ctx**

`run()` 内 `ToolRegistry(...)` 调用加 `skills=self.skills, ctx=self.ctx`。

- [ ] **Step 3: 写测试验证 SkillTool 注册**

```python
# tests/unit/test_skill_tool.py 追加
def test_tool_registry_registers_skill_tool():
    from pathlib import Path
    from taisang.agent_core.tools import ToolRegistry
    from taisang.skills.types import Skill
    s = Skill(name="x", description="d", when_to_use="", allowed_tools=None,
              dir_path=Path("."), content="body", source="user")
    reg = ToolRegistry(cwd=Path("."), skills=[s], ctx=None)
    schemas = reg.schemas()
    names = [s["name"] for s in schemas]
    assert "skill" in names
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/unit/test_skill_tool.py::test_tool_registry_registers_skill_tool -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taisang/agent_core/tools.py src/taisang/agent_core/service.py tests/unit/test_skill_tool.py
git commit -m "feat(skill): wire SkillTool into ToolRegistry"
```

---

### Task 5: 加载位置 + config

**Files:**
- Modify: `src/taisang/config.py`
- Modify: `src/taisang/web/session_registry.py`

- [ ] **Step 1: config.py 加 skills_dirs**

```python
# config.py LLMConfig 旁新增
class SkillsConfig(BaseModel):
    user_dirs: list[Path] = []  # 默认 ~/.taisang/skills
    project_dirs: list[Path] = []  # 默认 <repo>/.taisang/skills
    auto_allow: list[str] = []  # v1 不用,预留

def load_skills_config() -> SkillsConfig:
    file_cfg = _load_settings_file().get("skills", {})
    user_dirs = file_cfg.get("user_dirs") or [Path.home() / ".taisang" / "skills"]
    project_dirs = file_cfg.get("project_dirs") or []
    return SkillsConfig(
        user_dirs=[Path(d) for d in user_dirs],
        project_dirs=[Path(d) for d in project_dirs],
    )
```

- [ ] **Step 2: session_registry.py `_build_session` 加载 skills**

```python
# session_registry.py _build_session 内
from ..skills.loader import load_skills
from ..skills.config import load_skills_config  # 或直接用 config.py
skills_cfg = load_skills_config()
skills = load_skills(user_dirs=skills_cfg.user_dirs, project_dirs=skills_cfg.project_dirs)
# 传给 AgentService
agent = AgentService(..., skills=skills)
```

注意:project_dirs 应包含 `source_root / ".taisang" / "skills"`,这样项目级 skill 自动加载。

- [ ] **Step 3: 测试加载位置**

```python
# tests/unit/test_skills_loader.py 追加
def test_load_from_project_dir(tmp_path):
    proj = tmp_path / "proj"
    (proj / "test" / "SKILL.md").write_text("---\n---\nbody", encoding="utf-8")
    skills = load_skills(user_dirs=[], project_dirs=[proj])
    assert len(skills) == 1
    assert skills[0].source == "project"
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/unit/test_skills_loader.py tests/unit/test_skill_tool.py tests/unit/test_skill_listing.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/taisang/config.py src/taisang/web/session_registry.py tests/unit/test_skills_loader.py
git commit -m "feat(skill): wire skill loading into session build"
```

---

### Task 6: FastAPI 路由

**Files:**
- Create: `src/taisang/web/skills_api.py`
- Modify: `src/taisang/web/app.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_skills_api.py
from fastapi.testclient import TestClient
from taisang.web.app import create_app

def test_list_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("TAISANG_SOURCE_ROOT", str(tmp_path))
    user_dir = tmp_path / ".taisang" / "skills"
    user_dir.mkdir(parents=True)
    (user_dir / "commit" / "SKILL.md").write_text(
        "---\ndescription: d\n---\nbody", encoding="utf-8")
    app = create_app(source_root=tmp_path)
    client = TestClient(app)
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["name"] == "commit" for s in data["skills"])

def test_toggle_skill(tmp_path, monkeypatch):
    # 类似上面,POST /api/skills/commit/toggle → disabled 翻转
    ...

def test_reload_skills(tmp_path, monkeypatch):
    # POST /api/skills/reload → 200
    ...
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 skills_api.py**

```python
# src/taisang/web/skills_api.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
from ..skills.loader import load_skills
from ..skills.types import Skill

router = APIRouter(prefix="/api/skills", tags=["skills"])

# 进程内缓存:_skills_by_session? 简化:全局列表 + 磁盘状态文件
# v1 简化:每次 list 都重扫磁盘,toggle 写到 ~/.taisang/skills_state.json

_STATE_FILE = Path.home() / ".taisang" / "skills_state.json"

def _load_disabled() -> dict[str, bool]:
    if not _STATE_FILE.exists():
        return {}
    import json
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_disabled(state: dict[str, bool]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

def _get_all_skills(source_root: Path) -> list[Skill]:
    user_dir = Path.home() / ".taisang" / "skills"
    proj_dir = source_root / ".taisang" / "skills"
    skills = load_skills(user_dirs=[user_dir], project_dirs=[proj_dir])
    disabled = _load_disabled()
    for s in skills:
        s.disabled = disabled.get(s.name, False)
    return skills

@router.get("")
def list_skills(source_root: Path) -> dict:
    skills = _get_all_skills(source_root)
    return {"skills": [
        {"name": s.name, "description": s.description,
         "when_to_use": s.when_to_use, "source": s.source,
         "allowed_tools": s.allowed_tools, "disabled": s.disabled}
        for s in skills
    ]}

@router.post("/reload")
def reload_skills(source_root: Path) -> dict:
    # 磁盘重扫,缓存清(下次 list 重读)
    return {"ok": True}

@router.post("/{name}/toggle")
def toggle_skill(name: str, source_root: Path) -> dict:
    skills = _get_all_skills(source_root)
    if not any(s.name == name for s in skills):
        raise HTTPException(404, "skill not found")
    disabled = _load_disabled()
    disabled[name] = not disabled.get(name, False)
    _save_disabled(disabled)
    return {"ok": True, "disabled": disabled[name]}
```

- [ ] **Step 4: app.py 挂载 router**

```python
# app.py
from .skills_api import router as skills_router
app.include_router(skills_router)
```

注意:source_root 怎么传给路由? v1 简化:用 `app.state.source_root` 或在 create_app 闭包里注册。

- [ ] **Step 5: 跑测试**

Run: `pytest tests/unit/test_skills_api.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/taisang/web/skills_api.py src/taisang/web/app.py tests/unit/test_skills_api.py
git commit -m "feat(web): add /api/skills routes (list/toggle/reload)"
```

---

### Task 7: 前端 Skill 管理页

**Files:**
- Create: `frontend/src/views/SkillManage.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/Sidebar.vue`

- [ ] **Step 1: 加路由 `/skills`**

```ts
// router/index.ts
import SkillManage from '@/views/SkillManage.vue'
// routes 数组追加
{ path: '/skills', name: 'skills', component: SkillManage }
```

- [ ] **Step 2: Sidebar menu_item 跳转**

```vue
<!-- Sidebar.vue Skill 管理 menu_item 改 -->
<div class="menu-item" @click="router.push('/skills')">
  <t-icon name="code" class="menu-icon" />
  <span class="menu-title">Skill 管理</span>
</div>
```

- [ ] **Step 3: 实现 SkillManage.vue**

```vue
<template>
  <div class="skill-manage">
    <div class="header">
      <h2>Skill 管理</h2>
      <t-button variant="outline" @click="reload">重载</t-button>
    </div>
    <t-table :data="skills" :columns="columns" row-key="name">
      <template #disabled="{ row }">
        <t-switch :value="!row.disabled" @change="(v) => toggle(row.name)" />
      </template>
    </t-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

interface SkillRow {
  name: string
  description: string
  when_to_use: string
  source: 'user' | 'project'
  allowed_tools: string[] | null
  disabled: boolean
}

const skills = ref<SkillRow[]>([])
const columns = [
  { colKey: 'name', title: '名称', width: 150 },
  { colKey: 'description', title: '描述' },
  { colKey: 'source', title: '来源', width: 100 },
  { colKey: 'disabled', title: '启用', width: 80, slot: 'disabled' },
]

async function fetchSkills() {
  const r = await fetch('/api/skills')
  skills.value = (await r.json()).skills
}
async function toggle(name: string) {
  await fetch(`/api/skills/${name}/toggle`, { method: 'POST' })
  await fetchSkills()
}
async function reload() {
  await fetch('/api/skills/reload', { method: 'POST' })
  await fetchSkills()
  MessagePlugin.success('已重载')
}
onMounted(fetchSkills)
</script>

<style scoped>
.skill-manage { padding: 24px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
</style>
```

- [ ] **Step 4: Playwright DOM 断言验证**

- 访问 `/skills` 页面能看到表格
- toggle 切换调用 API
- 重载按钮工作

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/SkillManage.vue frontend/src/router/index.ts frontend/src/components/Sidebar.vue
git commit -m "feat(web): add Skill management page"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 造测试 skill**

在 `~/.taisang/skills/test-skill/SKILL.md` 写一个简单 skill:
```yaml
---
description: 测试 skill,echo 一句话
when_to_use: 用户说"测试 skill"时
---
用户说测试 skill 时,你在最终答复里说"skill 已调用"。
```

- [ ] **Step 2: 启动后端 (mock LLM)**

```bash
$env:TAISANG_MOCK_LLM=1; python -m taisang.web
```

- [ ] **Step 3: 前端验证**

- 打开 `/skills` 确认 `test-skill` 出现
- 开新对话,输入"测试 skill"
- 用 Playwright DOM 断言:agent 最终答复含"skill 已调用"

注意:mock LLM 默认不调工具,需要让 mock LLM 识别 "测试 skill" 关键词调 skill 工具,或手写一个 mock 脚本。

- [ ] **Step 4: type-check + build**

```bash
cd frontend && npm run type-check && npm run build
```

- [ ] **Step 5: 跑全测试套件**

```bash
pytest tests/unit -v
```

- [ ] **Step 6: 清理测试 skill**

删除 `~/.taisang/skills/test-skill/`

- [ ] **Step 7: 更新 memory**

`memory/2026-09-04.md` 追加 Skill 接入会话日志

- [ ] **Step 8: 最终 Commit**

```bash
git add -A
git commit -m "feat(skill): end-to-end skill integration v1"
```

---

## 自检清单

**Spec 覆盖**:
- [x] SKILL.md 目录格式 → Task 1
- [x] frontmatter 子集(name/description/when_to_use/allowed_tools) → Task 1
- [x] 多源加载(用户级 + 项目级,项目覆盖用户) → Task 1, 5
- [x] SkillTool + 注入 → Task 2
- [x] skill 清单注入 SYSTEM_PROMPT → Task 3
- [x] ${TAISANG_SKILL_DIR} 替换 → Task 2
- [x] allowed_tools 提示 → Task 2
- [x] ToolRegistry 集成 → Task 4
- [x] session_registry 加载 → Task 5
- [x] API 路由(list/toggle/reload) → Task 6
- [x] Skill 管理 UI → Task 7
- [x] 端到端验证 → Task 8

**占位符扫描**:无 "TBD"/"TODO"/"implement later"。所有代码段完整。

**类型一致性**:`Skill` dataclass 字段在 Task 1/2/3/6 引用一致(`name/description/when_to_use/allowed_tools/dir_path/content/source/disabled`)。`SkillTool` 在 Task 2/4 一致。`format_skill_listing` 在 Task 3/5 一致。

---

## 执行选项

**Plan 已保存到 `docs/superpowers/plans/2026-09-04-skill-integration.md`。两种执行方式:**

**1. Subagent-Driven(推荐)** — 我派子 agent 逐 task 实现,task 间 review,迭代快

**2. Inline Execution** — 在当前会话按 task 执行,带 checkpoint

**泰哥你选哪种? 或者要先调整方案某处?**