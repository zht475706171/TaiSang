# 用户画像（User Profile）设计

> 日期：2026-09-09
> 状态：已批准，待实现
> 对标：Claude Code 的 memory + 用户偏好注入

## 1. 目标

让 agent 认识用户——把用户的技术栈、代码风格、沟通偏好、环境、禁忌作为 system prompt 的一部分注入，使 agent 从通用工具变成私人助手。

**核心约束**：画像更新不能额外废 prompt cache。

## 2. 关键决策

| # | 维度 | 决策 |
|---|------|------|
| 1 | 数据来源 | 混合：用户手写种子 + agent 增量补充 |
| 2 | agent 触发 | LLM 主动调 `update_profile` 工具 |
| 3 | 数据结构 | 分栏 5 栏：技术栈 / 代码风格 / 沟通 / 环境 / 禁忌 |
| 4 | 注入格式 | `## 用户画像` + 每栏 `### 小标题`，空栏跳过 |
| 5 | 工具粒度 | 整栏覆盖 `update_profile({field, content})` |
| 6 | 生效时机 | 不广播；autocompact 两路径都重注入；新 session 启动注入 |
| 7 | 变更历史 | 保留，前端可回溯 |
| 8 | cache 策略 | 搭 autocompact 便车，零额外废 cache |
| 9 | 画像位置 | 基础 prompt 后、skills/mcp/agents 前 |
| 10 | 日志存储 | 单独 `~/.taisang/profile_history.jsonl` |
| 11 | 总长上限 | 5 栏总和 ≤ 500 字符，注入时静默截断尾部 |
| 12 | 截断策略 | 按栏顺序截断尾部 |
| 13 | 历史上限 | 最近 5 条，带 `snapshot_before` 完整快照 |
| 14 | 回滚 | 整体回滚到上一版本，从最后往前找可解析条 |
| 15 | 竞态 | `threading.Lock` 串行化 `save_profile_field` |
| 16 | 通知 | agent 改 → SSE `PROFILE_UPDATE` 事件 → toast；用户改 → 前端直接 toast |
| 17 | 子 agent | 也能调 `update_profile`，toast 统一「agent」不区分主子 |

## 3. 架构

### 3.1 新增包：`src/taisang/user_profile/`

```
src/taisang/user_profile/
  __init__.py       # 导出公共 API
  types.py          # UserProfile + ProfileFieldKey + PROFILE_FIELD_LABELS
  store.py          # load_profile / save_profile_field / reset_profile_field
  history.py        # append_profile_change / read_profile_history / rollback_profile
  format.py         # format_profile_section()
  tool.py           # UpdateProfileTool(_BaseTool)
```

### 3.2 新增 Web 后端：`src/taisang/web/profile_api.py`

对标 `prompts_api.py`：
- `GET /api/profile` → 当前画像 + 总字数
- `PUT /api/profile` → 单栏更新（`{field, content}`）
- `POST /api/profile/reset` → 单栏清空
- `POST /api/profile/rollback` → 回滚到上一版本
- `GET /api/profile/history` → 变更历史（≤5 条带 snapshot_before）

### 3.3 新增前端

- `views/ProfileManage.vue`：5 个 textarea + 每栏保存/重置 + 总字数 + 超限红字 + 恢复按钮 + 历史列表
- `stores/profile.ts` + `api/profile.ts`
- `router/index.ts` 加 `/profile` 路由
- `components/Sidebar.vue` 加「用户画像」入口
- SSE 监听 `profile_update` 事件 → toast「画像【label】已更新」

### 3.4 改动点（现有文件）

| 文件 | 改动 |
|------|------|
| `agent_core/prompts.py` | `build_system_prompt` 加 `profile_section` 参数（最前）；新增 `PROFILE_SECTION_HEADER` |
| `agent_core/events.py` | 新增 `PROFILE_UPDATE` 事件类型 |
| `agent_core/service.py` | `__init__` 两处 `append_system` 传 `profile_section`；`_try_autocompact` 两路径成功后 `replace_system_prompt`；新增 `_emit_profile_update` 方法 |
| `agent_core/tools.py` 或注册处 | `UpdateProfileTool` 注册 |
| `agent_core/prompts.py` `SYSTEM_PROMPT` | 加「用户画像」说明段 |
| `web/app.py` | `register_profile_routes(app)` |
| `web/session_registry.py` | `apply_prompts_config` 不改（画像不广播） |

## 4. 数据模型与存储

### 4.1 `types.py`

```python
from typing import Literal
from pydantic import BaseModel

ProfileFieldKey = Literal["tech_stack", "code_style", "communication", "environment", "taboos"]

PROFILE_FIELD_LABELS: dict[ProfileFieldKey, str] = {
    "tech_stack": "技术栈",
    "code_style": "代码风格",
    "communication": "沟通",
    "environment": "环境",
    "taboos": "禁忌",
}

class UserProfile(BaseModel):
    tech_stack: str = ""
    code_style: str = ""
    communication: str = ""
    environment: str = ""
    taboos: str = ""
```

### 4.2 settings.json `user_profile` 段

存原始完整内容，不截断。原子写（tmp + `os.replace` + chmod 0o600 best-effort），保留其它段。

### 4.3 profile_history.jsonl

路径：`~/.taisang/profile_history.jsonl`

每条带 `snapshot_before`（变更前完整 5 栏快照）：
```json
{"ts":"2026-09-09T14:30:00+08:00","source":"user","field":"tech_stack","old":"","new":"Python/Go","session_id":null,
 "snapshot_before":{"tech_stack":"","code_style":"","communication":"","environment":"","taboos":""}}
```

- `source`: `"user"` / `"agent"` / `"rollback"`
- 上限：最近 5 条，追加时超过则删最老的
- 损坏处理：追加时发现非合法 jsonl → 重建空文件；回滚时从最后往前找第一条可解析的 `snapshot_before`

### 4.4 format_profile_section()

```python
def format_profile_section(profile: UserProfile) -> str:
    """格式化画像段。5 栏按顺序拼接,总长超 500 按栏顺序截断尾部。全空返回空串。"""
```

输出格式（5 栏都有内容时）：
```
## 用户画像

### 技术栈
Python/Go，偏好 pnpm

### 代码风格
4 空格缩进，snake_case

### 沟通
中文，简洁

### 环境
Windows

### 禁忌
别动 main 分支
```

- 空栏跳过
- 全空返回空串 → `build_system_prompt` 不加 `## 用户画像` 段
- 截断：5 栏拼接后总长 >500 → 截断到 500，尾部丢弃

### 4.5 build_system_prompt 改动

```python
PROFILE_SECTION_HEADER = """

## 用户画像
"""

def build_system_prompt(
    skills_section: str = "",
    mcp_section: str = "",
    agents_section: str = "",
    profile_section: str = "",
) -> str:
    prompt = get_system_prompt()
    if profile_section:
        prompt += PROFILE_SECTION_HEADER + "\n" + profile_section + "\n"
    if skills_section:
        prompt += SKILLS_SECTION_HEADER + "\n" + skills_section + "\n"
    if mcp_section:
        prompt += MCP_SECTION_HEADER + "\n" + mcp_section + "\n"
    if agents_section:
        prompt += AGENTS_SECTION_HEADER + "\n" + agents_section + "\n"
    return prompt
```

## 5. 工具 schema 与 system prompt 说明

### 5.1 UpdateProfileTool schema

```python
{
    "name": "update_profile",
    "description": "更新用户画像的某一栏。当从对话中发现用户的明确偏好/习惯/禁忌时调用...",
    "parameters": {
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "enum": ["tech_stack", "code_style", "communication", "environment", "taboos"],
            },
            "content": {"type": "string", "description": "该栏完整新内容(整栏覆盖)..."},
        },
        "required": ["field", "content"],
    },
}
```

### 5.2 run() 行为

- 合法 field → `save_profile_field` + `append_profile_change` + emit `PROFILE_UPDATE` + 返回生效文案
- 非法 field → 返回 error，不写盘
- 空 content → 允许（等于清空该栏）

### 5.3 SYSTEM_PROMPT 加说明段

```
用户画像(认识用户):
- 你的 system prompt 里有"## 用户画像"段,记录用户的技术栈/代码风格/沟通偏好/环境/禁忌
- 对话中发现用户的明确偏好或禁忌时,调 update_profile({field, content}) 更新对应栏
  - field: tech_stack / code_style / communication / environment / taboos
  - content: 该栏完整新内容(整栏覆盖)
- 何时该调:用户明确表达"我用 X"/"别做 Y"/"我喜欢 Z 风格"等偏好时
- 何时别调:你推测但用户没明说时(别过度推断)、用户临时性表述时
- 更新在下次上下文压缩或新会话时生效,当前会话不立即生效(不废 prompt cache)
```

## 6. 数据流与生效时机

### 6.1 五条路径

**路径 1：新 session 启动**
- `AgentService.__init__` → `load_profile()` → `format_profile_section()` → `build_system_prompt(profile, skills, mcp, agents)` → `ctx.append_system()`
- 生效：立即；cache：不涉及

**路径 2：agent 调 update_profile**
- `UpdateProfileTool.run` → `save_profile_field` + `append_profile_change` + emit `PROFILE_UPDATE`
- 不碰 ctx → 当前 session system prompt 没变 → cache 持续命中
- tool_result 文案：「画像【label】已更新，将在下次上下文压缩或新会话时生效，当前会话仍用旧画像」
- 生效：当前 session 不生效；cache：零

**路径 3：autocompact**
- 两条路径（session_memory / LLM 摘要）成功 `replace_messages` 后：
  - `load_profile()` → `format_profile_section()` → `build_system_prompt(profile, skills, mcp, agents)` → `ctx.replace_system_prompt()`
- 生效：立即（下轮 LLM 调用）；cache：零额外成本（cache 在 replace_messages 时已全废）

**路径 4：用户前端手改**
- `PUT /api/profile` → `save_profile_field(source="user")` → 不广播
- 前端 toast「已保存，当前会话下次压缩时生效；新会话立即生效」
- 生效：活跃 session 等各自下次 autocompact；新 session 立即；cache：零

**路径 5：用户前端回滚**
- `POST /api/profile/rollback` → 读最后一条 `snapshot_before` → 写回 settings.json → 追加 `source="rollback"` history
- 不广播，生效时机同路径 4

### 6.2 不变式

1. 画像更新永远不碰活跃 session 的 ctx → cache 零额外失效
2. 画像只在两个点注入：新 session `__init__` + autocompact 后 `replace_system_prompt`
3. autocompact 是画像更新的唯一「搭便车」点
4. tool_result 诚实告知生效时机

### 6.3 竞态处理

`save_profile_field` 用模块级 `threading.Lock` 包住「读-改-写」：
```python
_profile_lock = threading.Lock()

def save_profile_field(field, content, source, session_id):
    with _profile_lock:
        cfg = _load_settings_file()
        profile = UserProfile(**cfg.get("user_profile", {}))
        old = getattr(profile, field)
        snapshot_before = profile.model_dump()
        setattr(profile, field, content)
        cfg["user_profile"] = profile.model_dump()
        _atomic_write(cfg)
    append_profile_change(field, old, content, source, session_id, snapshot_before)
```

锁范围小（几毫秒），不阻塞 LLM 流式输出。消除 web 线程 + agent 线程并发写竞态。

## 7. 事件机制

### 7.1 新增 PROFILE_UPDATE 事件

`agent_core/events.py`：
```python
PROFILE_UPDATE = "profile_update"
```

payload：`{"field": str, "label": str, "content": str, "source": "agent"}`

### 7.2 AgentService._emit_profile_update

对标 `_emit_todo_update`：
```python
def _emit_profile_update(self, field, label, content, agent_id=""):
    from .events import AgentEvent, PROFILE_UPDATE
    on_event = getattr(self, "_last_on_event", None)
    if on_event is not None:
        on_event(AgentEvent(
            type=PROFILE_UPDATE,
            payload={"field": field, "label": label, "content": content, "source": "agent"},
            agent_id=agent_id,
        ))
```

### 7.3 UpdateProfileTool 持有 parent_service

和 `TodoWriteTool` 一样，构造时传 `parent_service`，run() 后调 `_emit_profile_update`。

### 7.4 前端监听

SSE handler 加 case `profile_update` → toast「画像【label】已更新」（不跳转）。

## 8. 错误处理矩阵

| 场景 | 处理 |
|------|------|
| settings.json 不存在/损坏/段类型错 | `load_profile` fallback 空 UserProfile |
| 5 栏总长超 500 | 存原始，注入时截断；前端红字提示 |
| update_profile 非法 field | schema 层挡 + run() 兜底 error |
| update_profile 空 content | 允许（清空该栏） |
| save_profile_field 写盘失败 | 异常上抛 → API 500 / 工具 error |
| web + agent 并发写 | threading.Lock 串行化 |
| profile_history.jsonl 损坏 | 追加时重建空；回滚时跳过损坏条 |
| 无历史可回滚 | API 409「无可用历史版本」 |
| autocompact 时 load_profile 失败 | 用空画像注入，不阻塞压缩 |

## 9. 测试策略

### 9.1 单元测试

- `test_profile_types.py`：UserProfile 默认值 + 容错
- `test_profile_store.py`：load/save + 原子写 + 并发安全 + 别栏不动
- `test_profile_history.py`：追加 + 滚动 5 条 + 损坏重建 + 回滚
- `test_profile_format.py`：空画像/部分空/截断/截断点
- `test_profile_tool.py`：schema + 合法/非法 field + 空 content + emit 事件
- `test_web_profile_api.py`：5 个路由全覆盖

### 9.2 集成测试

- `test_profile_injection_e2e.py`：新 session 注入 + agent 调工具 cache 不废 + autocompact 后生效
- `test_profile_event_e2e.py`：SSE 收到 PROFILE_UPDATE + 子 agent 调也触发

### 9.3 不测

- 前端 Vue 组件渲染（对齐项目现状）
- 真实 LLM 决策（用 MockLLM）
- 跨进程竞态（v1 单进程）

## 10. 范围

### v1 包含
- 5 栏画像存储 + 注入 + 截断
- agent `update_profile` 工具 + PROFILE_UPDATE 事件
- autocompact 两路径重注入
- 前端 /profile 管理页 + 5 栏编辑 + 历史 + 回滚
- Sidebar 入口 + SSE toast
- 变更历史 5 条 + snapshot_before + 回滚
- threading.Lock 并发安全
- 单元 + 集成测试

### v2 留作
- 回滚到任意历史版本（v1 只回滚上一版）
- agent 改画像的实时前端高亮（v1 只 toast）
- 画像多用户/多 profile 切换