# 子 Agent LLM 独立配置 + 设置页改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 主 agent 和子 agent 各配一套 LLM,连接测试分开,子 agent 不配则 fallback 主;设置页改成顶部开关卡 + 主/子/Debug 三卡片 + 分隔线布局;API Key 输入框改成脱敏占位 + 眼睛图标切换明文。

**Architecture:** 后端 `settings.json` 加 `llm_subagent` 字段(`SubAgentLLMConfig`),`_make_child_llm` 改造读盘判断 fallback。`/api/config` GET/POST 改双块嵌套结构,`/api/config/test` 加 `target` 参数。前端 `ConfigModal.vue` 重构成顶部开关卡 + 三 `t-card` + 分隔线,抽出 `ApiKeyInput.vue` 复用组件(脱敏占位 + 眼睛切换 + 修改按钮)。

**Tech Stack:** Python 3.11 + FastAPI + Pydantic + pytest (后端);Vue 3.5 + TypeScript + TDesign Vue Next + Vite (前端)。

**Spec:** `docs/superpowers/specs/2026-09-10-subagent-llm-config-ui-design.md`

---

## File Structure

**后端改动**:
- `src/taisang/config.py` — 新增 `SubAgentLLMConfig` 模型 + `load_subagent_config` / `save_subagent_config` 函数
- `src/taisang/agent_core/agent_tool.py` — 改造 `_make_child_llm` 读盘判断 fallback
- `src/taisang/web/app.py` — `/api/config` GET/POST 改双块嵌套,`/api/config/test` 加 `target` 参数;`ConfigReq` / `ConfigTestReq` 重构嵌套
- `tests/unit/test_config.py` — 新增 subagent 配置测试
- `tests/unit/test_web_app.py` — 更新现有 `/api/config` 测试 + 新增 subagent 相关测试
- `tests/unit/test_agent_tool.py` — 新增 `_make_child_llm` fallback 三种场景测试

**前端改动**:
- `src/taisang/web/frontend/src/components/ApiKeyInput.vue` — 新建,脱敏占位 + 眼睛切换 + 修改按钮复用组件
- `src/taisang/web/frontend/src/components/ConfigModal.vue` — 重构:顶部开关卡 + 主/子/Debug 三卡 + 分隔线
- `src/taisang/web/frontend/src/api/config.ts` — 重构接口签名(getConfig 双块、saveConfig 嵌套、testConfig 加 target)
- `src/taisang/web/frontend/src/types/index.ts` — 加 `LLMConfigSection` / `SubAgentConfigSection` 类型

---

## Task 1: 后端 SubAgentLLMConfig 模型 + 读写函数

**Files:**
- Modify: `src/taisang/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: 写失败测试 — 默认值**

追加到 `tests/unit/test_config.py` 末尾:

```python
def test_load_subagent_config_default(tmp_path, monkeypatch):
    """默认 enabled=false,字段空。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    from taisang.config import load_subagent_config
    cfg = load_subagent_config()
    assert cfg.enabled is False
    assert cfg.base_url == ""
    assert cfg.api_key == ""
    assert cfg.model == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_config.py::test_load_subagent_config_default -v`
Expected: FAIL with `ImportError: cannot import name 'load_subagent_config'`

- [ ] **Step 3: 实现 SubAgentLLMConfig + load_subagent_config**

在 `src/taisang/config.py` 的 `LLMConfig` 类定义之后、`_settings_path` 函数之前,插入:

```python
class SubAgentLLMConfig(BaseModel):
    """子 agent LLM 配置。enabled=false 或 model/base_url 空时 fallback 主 LLMConfig。

    api_key 允许空(本地 endpoint 如 ollama 不需要 key)。
    无 debug 字段(debug 是主 agent 行为,跟 LLM endpoint 无关)。
    """
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
```

在 `save_config` 函数之后(在 `mask_api_key` 之前)插入:

```python
def load_subagent_config() -> SubAgentLLMConfig:
    """加载子 agent LLM 配置。settings.json 的 llm_subagent 字段 > 默认(全空 + enabled=false)。

    损坏文件 fallback 到默认(复用 _load_settings_file 的容错)。
    """
    raw = _load_settings_file().get("llm_subagent", {})
    if not isinstance(raw, dict):
        return SubAgentLLMConfig()
    return SubAgentLLMConfig(
        enabled=bool(raw.get("enabled", False)),
        base_url=str(raw.get("base_url", "")),
        api_key=str(raw.get("api_key", "")),
        model=str(raw.get("model", "")),
    )


def save_subagent_config(cfg: SubAgentLLMConfig) -> None:
    """原子写 settings.json 的 llm_subagent 字段,保留 llm/prompts/skills 等其他字段。权限 600。"""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings_file()
    existing["llm_subagent"] = cfg.model_dump()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod
    os.replace(tmp, p)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_config.py::test_load_subagent_config_default -v`
Expected: PASS

- [ ] **Step 5: 写失败测试 — save 写盘 + 保留其他字段**

追加到 `tests/unit/test_config.py`:

```python
def test_save_subagent_config_writes_field(tmp_path, monkeypatch):
    """save_subagent_config 写 llm_subagent 字段。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    from taisang.config import SubAgentLLMConfig, save_subagent_config
    cfg = SubAgentLLMConfig(enabled=True, base_url="https://api.x.com", api_key="sk-sub", model="glm-4.5")
    save_subagent_config(cfg)
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm_subagent"]["enabled"] is True
    assert data["llm_subagent"]["base_url"] == "https://api.x.com"
    assert data["llm_subagent"]["api_key"] == "sk-sub"
    assert data["llm_subagent"]["model"] == "glm-4.5"


def test_save_subagent_config_preserves_other_fields(tmp_path, monkeypatch):
    """save_subagent_config 保留 llm/prompts 等其他字段。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    p = tmp_path / ".taisang" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "llm": {"base_url": "https://main", "api_key": "sk-main", "model": "m-main"},
        "prompts": {"system_prompt": {"value": "x", "use_default": False}},
    }))
    from taisang.config import SubAgentLLMConfig, save_subagent_config
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="sk-sub", model="m-sub"))
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["base_url"] == "https://main"  # 保留
    assert data["prompts"]["system_prompt"]["value"] == "x"  # 保留
    assert data["llm_subagent"]["enabled"] is True  # 新增
    assert data["llm_subagent"]["base_url"] == "https://sub"
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_config.py::test_save_subagent_config_writes_field tests/unit/test_config.py::test_save_subagent_config_preserves_other_fields -v`
Expected: 2 PASS

- [ ] **Step 7: 提交**

```bash
git add src/taisang/config.py tests/unit/test_config.py
git commit -m "feat(config): add SubAgentLLMConfig model + load/save functions

子 agent LLM 配置存 settings.json 的 llm_subagent 字段,
enabled/model/base_url/api_key 四字段,api_key 允许空。
沿用 LLMConfig 的原子写盘 + 600 权限。"
```

---

## Task 2: 后端 _make_child_llm fallback 改造

**Files:**
- Modify: `src/taisang/agent_core/agent_tool.py:45-47`
- Test: `tests/unit/test_agent_tool.py`

- [ ] **Step 1: 写失败测试 — enabled 用子配置**

追加到 `tests/unit/test_agent_tool.py` 末尾(注意需要 import `LLMConfig`、`LLMClient`、`LLMResponse` 已 import):

```python
def test_make_child_llm_uses_subagent_when_enabled(tmp_path, monkeypatch):
    """enabled=true + model/base_url 填 → 返回独立 LLMClient,与 parent_llm 不同实例。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    # 写子配置到 settings.json
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(
        enabled=True, base_url="https://sub.api", api_key="sk-sub", model="glm-4.5",
    ))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is not parent_llm
    # LLMClient 实例(不是 MockLLM)
    from taisang.llm_client import LLMClient
    assert isinstance(child, LLMClient)
    assert child.model == "glm-4.5"
    assert child.cfg.base_url == "https://sub.api"
    assert child.cfg.api_key == "sk-sub"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_agent_tool.py::test_make_child_llm_uses_subagent_when_enabled -v`
Expected: FAIL (现状 `_make_child_llm` 直接返回 parent_llm,`child is parent_llm` 断言失败)

- [ ] **Step 3: 改造 _make_child_llm**

把 `src/taisang/agent_core/agent_tool.py:45-47` 的:

```python
def _make_child_llm(parent_llm):
    """默认子 agent 用父 LLM(同 client)。测试用 monkeypatch 替换。"""
    return parent_llm
```

改成:

```python
def _make_child_llm(parent_llm):
    """子 agent LLM:启用且 model/base_url 完整 → 独立 LLMClient;否则 fallback parent_llm。

    api_key 允许空(本地 endpoint 如 ollama 不需要 key)。
    每次派子 agent 都读盘一次(派遣频率低,成本可接受;好处是改配置立即生效)。
    测试仍可 monkeypatch 替换本函数,不读盘。
    """
    from ..config import LLMConfig, load_config, load_subagent_config
    sub_cfg = load_subagent_config()
    if not sub_cfg.enabled:
        return parent_llm
    if not (sub_cfg.model and sub_cfg.base_url):
        return parent_llm
    main_cfg = load_config()
    # 子配置不继承 debug(debug 是主 agent 行为)
    child_cfg = LLMConfig(
        base_url=sub_cfg.base_url,
        api_key=sub_cfg.api_key,  # 可空
        model=sub_cfg.model,
        debug=main_cfg.debug,
    )
    return LLMClient(child_cfg)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_agent_tool.py::test_make_child_llm_uses_subagent_when_enabled -v`
Expected: PASS

- [ ] **Step 5: 写失败测试 — disabled fallback**

追加到 `tests/unit/test_agent_tool.py`:

```python
def test_make_child_llm_fallback_parent_when_disabled(tmp_path, monkeypatch):
    """enabled=false → fallback parent_llm。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=False, base_url="https://sub", api_key="k", model="m"))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is parent_llm


def test_make_child_llm_fallback_parent_when_model_empty(tmp_path, monkeypatch):
    """enabled=true 但 model 空 → fallback parent_llm。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="k", model=""))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is parent_llm


def test_make_child_llm_fallback_parent_when_base_url_empty(tmp_path, monkeypatch):
    """enabled=true 但 base_url 空 → fallback parent_llm。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="", api_key="k", model="m"))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    assert child is parent_llm


def test_make_child_llm_allows_empty_api_key(tmp_path, monkeypatch):
    """enabled=true + model/base_url 填 + api_key 空 → 返回独立 LLMClient,api_key 为空字符串。"""
    import taisang.agent_core.agent_tool as at_mod
    from taisang.config import SubAgentLLMConfig, save_subagent_config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="", model="m"))

    parent_llm = MockLLM([LLMResponse(text="parent", tool_calls=[])])
    child = at_mod._make_child_llm(parent_llm)
    from taisang.llm_client import LLMClient
    assert isinstance(child, LLMClient)
    assert child.cfg.api_key == ""  # 允许空
    assert child.cfg.model == "m"
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_agent_tool.py -v -k "make_child_llm"`
Expected: 5 PASS (1 uses_subagent + 4 fallback)

- [ ] **Step 7: 确认现有 agent_tool 测试不被破坏**

Run: `python -m pytest tests/unit/test_agent_tool.py -v`
Expected: 全部 PASS(现有 monkeypatch `_make_child_llm` 的测试不受影响,因为它们直接替换函数,不读盘)

- [ ] **Step 8: 提交**

```bash
git add src/taisang/agent_core/agent_tool.py tests/unit/test_agent_tool.py
git commit -m "feat(agent_tool): _make_child_llm 读 llm_subagent 配置,enabled 且 model/base_url 完整时用独立 LLMClient

api_key 允许空(ollama 等本地 endpoint)。每次派子 agent 读盘一次,
改配置立即生效。现有 monkeypatch 测试不受影响。"
```

---

## Task 3: 后端 /api/config GET/POST 双块嵌套

**Files:**
- Modify: `src/taisang/web/app.py:67-98` (`ConfigReq`/`ConfigTestReq` 模型) + `web/app.py:288-315` (`get_config`/`save_config_route`)
- Test: `tests/unit/test_web_app.py`

- [ ] **Step 1: 写失败测试 — GET 返回双块**

追加到 `tests/unit/test_web_app.py` 末尾:

```python
def test_get_config_returns_main_and_subagent(tmp_path, monkeypatch):
    """GET /api/config 返回 {main: {...}, subagent: {...}} 双块结构。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, SubAgentLLMConfig, save_config, save_subagent_config
    from taisang.web.app import create_app

    save_config(LLMConfig(base_url="https://main", api_key="sk-main1234567890", model="m-main", debug=True))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="sk-sub1234567890", model="m-sub"))

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    # main 块
    assert data["main"]["model"] == "m-main"
    assert data["main"]["base_url"] == "https://main"
    assert data["main"]["api_key"] == "sk-***7890"  # masked
    assert data["main"]["api_key_set"] is True
    assert data["main"]["debug"] is True
    # subagent 块
    assert data["subagent"]["enabled"] is True
    assert data["subagent"]["model"] == "m-sub"
    assert data["subagent"]["base_url"] == "https://sub"
    assert data["subagent"]["api_key"] == "sk-***7890"  # masked
    assert data["subagent"]["api_key_set"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_get_config_returns_main_and_subagent -v`
Expected: FAIL(现状返回扁平 `model`/`base_url`/`api_key`/`api_key_set`/`debug`,断言 `data["main"]` KeyError)

- [ ] **Step 3: 重构 ConfigReq/ConfigTestReq 模型**

把 `src/taisang/web/app.py:67-98` 的:

```python
class ConfigReq(BaseModel):
    model: str
    api_key: str
    base_url: str
    debug: bool = False


class ConfigTestReq(BaseModel):
    """测试连接请求体。

    api_key = "__unchanged__" 表示用已存的 api_key(前端 readonly 提交这个 sentinel),
    否则用表单传入的明文。
    """

    model: str
    api_key: str
    base_url: str
```

改成:

```python
class ConfigSectionReq(BaseModel):
    """单个 LLM 配置块(主或子)的请求体。

    api_key = "__unchanged__" 时保留已存 api_key(前端 readonly 提交 sentinel)。
    """
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class ConfigReq(BaseModel):
    """POST /api/config 请求体:main + subagent 双块。

    subagent 块可省略(等同 enabled=false + 字段空)。
    main.debug 单独放外层(向后兼容旧前端不传 debug 时默认 False)。
    """
    main: ConfigSectionReq
    subagent: ConfigSectionReq | None = None
    debug: bool = False


class ConfigTestReq(BaseModel):
    """POST /api/config/test 请求体。

    target="main" 用 main 块测;target="subagent" 用 subagent 块测。
    api_key = "__unchanged__" 时用已存对应块的 api_key。
    """
    target: str = "main"  # "main" | "subagent"
    model: str
    api_key: str
    base_url: str
```

- [ ] **Step 4: 重构 get_config 路由**

把 `web/app.py` 的 `get_config`(原 288-298 行)改成:

```python
    @app.get("/api/config")
    async def get_config() -> dict:
        """返回 LLM 配置。main + subagent 双块,api_key 打码。"""
        cfg = load_config()
        sub = load_subagent_config()
        return {
            "main": {
                "model": cfg.model,
                "base_url": cfg.base_url,
                "api_key": mask_api_key(cfg.api_key),
                "api_key_set": bool(cfg.api_key),
                "debug": cfg.debug,
            },
            "subagent": {
                "enabled": sub.enabled,
                "model": sub.model,
                "base_url": sub.base_url,
                "api_key": mask_api_key(sub.api_key),
                "api_key_set": bool(sub.api_key),
            },
        }
```

并在 `web/app.py` 顶部的 import 行:

```python
from ..config import LLMConfig, load_config, mask_api_key, save_config
```

改成:

```python
from ..config import (
    LLMConfig,
    SubAgentLLMConfig,
    load_config,
    load_subagent_config,
    mask_api_key,
    save_config,
    save_subagent_config,
)
```

- [ ] **Step 5: 重构 save_config_route 路由**

把 `web/app.py` 的 `save_config_route`(原 300-315 行)改成:

```python
    @app.post("/api/config")
    async def save_config_route(req: ConfigReq) -> dict:
        """保存 LLM 配置(main + subagent)+ 立即应用到所有 session。

        api_key = "__unchanged__" 时保留原 api_key(主/子各自独立 sentinel)。
        """
        # main 块
        if req.main.api_key == "__unchanged__":
            old_main = load_config()
            main_key = old_main.api_key
        else:
            main_key = req.main.api_key
        main_cfg = LLMConfig(
            model=req.main.model,
            api_key=main_key,
            base_url=req.main.base_url,
            debug=req.debug,
        )
        save_config(main_cfg)

        # subagent 块(请求体没传 subagent 时,写空配置 + enabled=false)
        if req.subagent is None:
            save_subagent_config(SubAgentLLMConfig())
        else:
            if req.subagent.api_key == "__unchanged__":
                old_sub = load_subagent_config()
                sub_key = old_sub.api_key
            else:
                sub_key = req.subagent.api_key
            save_subagent_config(SubAgentLLMConfig(
                enabled=req.subagent.enabled if hasattr(req.subagent, "enabled") else False,
                base_url=req.subagent.base_url,
                api_key=sub_key,
                model=req.subagent.model,
            ))

        registry.apply_llm_config(main_cfg)
        return {"ok": True}
```

**注意**:`ConfigSectionReq` 没有 `enabled` 字段(因为主块不需要 enabled,子块的 enabled 是独立标志)。这里 `hasattr` 检查永远 False,需要修正——见 Step 6 修正。

- [ ] **Step 6: 修正 — ConfigSectionReq 加 enabled 可选字段**

把 Step 3 的 `ConfigSectionReq` 改成(加 `enabled` 可选,默认 False,主块传不传都行):

```python
class ConfigSectionReq(BaseModel):
    """单个 LLM 配置块(主或子)的请求体。

    api_key = "__unchanged__" 时保留已存 api_key(前端 readonly 提交 sentinel)。
    enabled 仅子块用(主块始终视为启用),默认 False。
    """
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    enabled: bool = False
```

并把 Step 5 的 `save_config_route` 里子块分支的:

```python
            save_subagent_config(SubAgentLLMConfig(
                enabled=req.subagent.enabled if hasattr(req.subagent, "enabled") else False,
                base_url=req.subagent.base_url,
                api_key=sub_key,
                model=req.subagent.model,
            ))
```

改成(直接用 `req.subagent.enabled`,因为字段已经存在):

```python
            save_subagent_config(SubAgentLLMConfig(
                enabled=req.subagent.enabled,
                base_url=req.subagent.base_url,
                api_key=sub_key,
                model=req.subagent.model,
            ))
```

- [ ] **Step 7: 跑 GET 测试确认通过**

Run: `python -m pytest tests/unit/test_web_app.py::test_get_config_returns_main_and_subagent -v`
Expected: PASS

- [ ] **Step 8: 写失败测试 — POST 保存双块**

追加到 `tests/unit/test_web_app.py`:

```python
def test_post_config_saves_both_sections(tmp_path, monkeypatch):
    """POST /api/config 同时写 main + subagent。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app
    import json

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "main": {"model": "m-main", "api_key": "sk-main1234567890", "base_url": "https://main"},
        "subagent": {"enabled": True, "model": "m-sub", "api_key": "sk-sub1234567890", "base_url": "https://sub"},
        "debug": True,
    })
    assert r.status_code == 200
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["model"] == "m-main"
    assert data["llm"]["base_url"] == "https://main"
    assert data["llm"]["api_key"] == "sk-main1234567890"
    assert data["llm"]["debug"] is True
    assert data["llm_subagent"]["enabled"] is True
    assert data["llm_subagent"]["model"] == "m-sub"
    assert data["llm_subagent"]["base_url"] == "https://sub"
    assert data["llm_subagent"]["api_key"] == "sk-sub1234567890"


def test_post_config_unchanged_sentinel_per_section(tmp_path, monkeypatch):
    """main 的 __unchanged__ 不动 main key,subagent 的 __unchanged__ 不动 sub key。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, SubAgentLLMConfig, save_config, save_subagent_config
    from taisang.web.app import create_app
    import json

    save_config(LLMConfig(base_url="https://main", api_key="sk-main-orig12345", model="m-main"))
    save_subagent_config(SubAgentLLMConfig(enabled=True, base_url="https://sub", api_key="sk-sub-orig12345", model="m-sub"))

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "main": {"model": "m-main-new", "api_key": "__unchanged__", "base_url": "https://main-new"},
        "subagent": {"enabled": True, "model": "m-sub-new", "api_key": "__unchanged__", "base_url": "https://sub-new"},
    })
    assert r.status_code == 200
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    # model/base_url 改了,key 保留
    assert data["llm"]["model"] == "m-main-new"
    assert data["llm"]["api_key"] == "sk-main-orig12345"  # 保留
    assert data["llm_subagent"]["model"] == "m-sub-new"
    assert data["llm_subagent"]["api_key"] == "sk-sub-orig12345"  # 保留


def test_post_config_subagent_none_writes_empty(tmp_path, monkeypatch):
    """POST /api/config 不传 subagent → 写空 subagent 配置(enabled=false)。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app
    import json

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "main": {"model": "m", "api_key": "k", "base_url": "https://x"},
    })
    assert r.status_code == 200
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm_subagent"]["enabled"] is False
    assert data["llm_subagent"]["model"] == ""
```

- [ ] **Step 9: 跑 POST 测试确认通过**

Run: `python -m pytest tests/unit/test_web_app.py::test_post_config_saves_both_sections tests/unit/test_web_app.py::test_post_config_unchanged_sentinel_per_section tests/unit/test_web_app.py::test_post_config_subagent_none_writes_empty -v`
Expected: 3 PASS

- [ ] **Step 10: 更新现有 /api/config 测试**

`tests/unit/test_web_app.py:291-512` 现有测试用扁平请求体,需要更新成嵌套。具体改动:

- `test_get_config_returns_masked_api_key`(291 行):断言从 `data["model"]` 改成 `data["main"]["model"]`,`data["api_key"]` 改成 `data["main"]["api_key"]`,`data["api_key_set"]` 改成 `data["main"]["api_key_set"]`;加 `assert data["subagent"]["enabled"] is False`(默认空)
- `test_post_config_saves_and_applies`(311 行):POST body 从 `{model, api_key, base_url}` 改成 `{main: {model, api_key, base_url}, debug: false}`;断言文件 `data["llm"]` 不变
- `test_post_config_empty_api_key_allowed`(336 行):同上改 body
- `test_post_config_unchanged_api_key`(354 行):同上改 body
- `test_get_config_returns_debug`(378 行):断言 `data["main"]["debug"]` 而不是 `data["debug"]`
- `test_post_config_saves_debug`(394 行):POST body 加 `debug: True` 在顶层
- `test_post_config_default_debug_false`(420 行):同上确认默认 False

逐个改完后跑:

Run: `python -m pytest tests/unit/test_web_app.py -v -k "config"`
Expected: 全部 PASS

- [ ] **Step 11: 提交**

```bash
git add src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): /api/config GET/POST 改 main + subagent 双块嵌套结构

ConfigReq/ConfigSectionReq 嵌套模型,api_key='__unchanged__' sentinel
主/子各自独立。更新现有测试适配新结构。"
```

---

## Task 4: 后端 /api/config/test 加 target 参数

**Files:**
- Modify: `src/taisang/web/app.py` (`test_config_route` 路由)
- Test: `tests/unit/test_web_app.py`

- [ ] **Step 1: 写失败测试 — target=main**

追加到 `tests/unit/test_web_app.py`:

```python
def test_post_config_test_target_main(tmp_path, monkeypatch):
    """POST /api/config/test target=main → 用 main 块探测。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, save_config
    from taisang.web.app import create_app

    save_config(LLMConfig(base_url="https://main", api_key="sk-main1234567890", model="m-main"))
    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config/test", json={
        "target": "main",
        "model": "m-main",
        "api_key": "__unchanged__",
        "base_url": "https://main",
    })
    assert r.status_code == 200
    data = r.json()
    # 没真实 endpoint,预期失败但 error 要有内容
    assert data["ok"] is False
    assert "error" in data
```

- [ ] **Step 2: 跑测试确认现状(可能 PASS 也可能 FAIL,看现有逻辑是否兼容)**

Run: `python -m pytest tests/unit/test_web_app.py::test_post_config_test_target_main -v`
Expected: 现状 `ConfigTestReq` 没有 `target` 字段,Pydantic 会忽略多余字段,测试可能 PASS(因为现有逻辑就是用 main 配置测)。如果 PASS,继续 Step 3 改造让它显式支持 target;如果 FAIL,Step 3 修复。

- [ ] **Step 3: 重构 test_config_route**

把 `web/app.py` 的 `test_config_route`(原 317-346 行)改成:

```python
    @app.post("/api/config/test")
    async def test_config_route(req: ConfigTestReq) -> dict:
        """测试 LLM 连通性。target="main" 用主配置,target="subagent" 用子配置。

        api_key = "__unchanged__" 时用已存对应块的 api_key。
        target="subagent" 但子配置 model/base_url 空 → 返回 {ok: false, error: "子 agent 配置未填写完整"}。
        不持久化任何配置,纯探测。
        """
        import time

        from ..llm_client import LLMClient
        from ..llm_errors import LLMError

        if req.target == "subagent":
            sub = load_subagent_config()
            # 优先用表单传入的值(前端填了但还没保存的场景),__unchanged__ 时用已存
            if req.api_key == "__unchanged__":
                api_key = sub.api_key
            else:
                api_key = req.api_key
            model = req.model
            base_url = req.base_url
            # 防御性校验:model/base_url 空直接报错(前端也应 disabled 按钮)
            if not (model and base_url):
                return {"ok": False, "error": "子 agent 配置未填写完整"}
        else:
            if req.api_key == "__unchanged__":
                old_cfg = load_config()
                api_key = old_cfg.api_key
            else:
                api_key = req.api_key
            model = req.model
            base_url = req.base_url

        probe_cfg = LLMConfig(model=model, api_key=api_key, base_url=base_url, debug=False)
        t0 = time.perf_counter()
        try:
            client = LLMClient(probe_cfg)
            resp = client.chat(messages=[{"role": "user", "content": "hello"}], tools=[])
        except LLMError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms, "reply": (resp.text or "")[:200]}
```

- [ ] **Step 4: 写失败测试 — target=subagent 空配置报错**

追加到 `tests/unit/test_web_app.py`:

```python
def test_post_config_test_target_subagent_empty_returns_error(tmp_path, monkeypatch):
    """target=subagent 但 model/base_url 空 → 返回 {ok: false, error: ...}。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config/test", json={
        "target": "subagent",
        "model": "",
        "api_key": "__unchanged__",
        "base_url": "",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "未填写完整" in data["error"]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_web_app.py::test_post_config_test_target_main tests/unit/test_web_app.py::test_post_config_test_target_subagent_empty_returns_error -v`
Expected: 2 PASS

- [ ] **Step 6: 更新现有 test_config_route 测试**

现有 `test_web_app.py:441-512` 的 `test_post_config_test_*` 测试需要加 `target: "main"` 字段到请求体。逐个改完跑:

Run: `python -m pytest tests/unit/test_web_app.py -v -k "test_config"`
Expected: 全部 PASS

- [ ] **Step 7: 跑全部 web_app 测试确认没破坏**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全部 PASS

- [ ] **Step 8: 提交**

```bash
git add src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): /api/config/test 加 target 参数支持分别测主/子配置

target='subagent' 但 model/base_url 空时返回 '子 agent 配置未填写完整'。
更新现有测试加 target 字段。"
```

---

## Task 5: 前端类型定义 + api/config.ts 重构

**Files:**
- Modify: `src/taisang/web/frontend/src/types/index.ts`
- Modify: `src/taisang/web/frontend/src/api/config.ts`

- [ ] **Step 1: 加类型定义**

在 `src/taisang/web/frontend/src/types/index.ts` 里,把现有的:

```typescript
export interface LLMConfig {
  model: string
  base_url: string
  api_key: string
  api_key_set: boolean
  debug: boolean
}
```

改成:

```typescript
export interface LLMConfigSection {
  model: string
  base_url: string
  api_key: string  // 后端打码返回
  api_key_set: boolean
}

export interface SubAgentConfigSection {
  enabled: boolean
  model: string
  base_url: string
  api_key: string  // 后端打码返回
  api_key_set: boolean
}

export interface LLMConfigResponse {
  main: LLMConfigSection & { debug: boolean }
  subagent: SubAgentConfigSection
}

// 向后兼容:旧代码可能还引用 LLMConfig
export type LLMConfig = LLMConfigResponse
```

- [ ] **Step 2: 重构 api/config.ts**

把 `src/taisang/web/frontend/src/api/config.ts` 全文改成:

```typescript
import { apiGet, apiPost } from './request'
import type { LLMConfigResponse } from '@/types'

export function getConfig(): Promise<LLMConfigResponse> {
  return apiGet<LLMConfigResponse>('/api/config')
}

export interface ConfigSectionPayload {
  model: string
  api_key: string  // '__unchanged__' 或明文
  base_url: string
  enabled?: boolean  // 仅 subagent 块
}

export function saveConfig(payload: {
  main: ConfigSectionPayload
  subagent?: ConfigSectionPayload | null
  debug: boolean
}): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/config', payload)
}

/** 测试连接结果。ok=true 时有 latency_ms + reply,ok=false 时有 error。 */
export interface ConfigTestResult {
  ok: boolean
  latency_ms?: number
  reply?: string
  error?: string
}

/** 用表单传入的 model/api_key/base_url 发最小 hello 请求探测连通性,不持久化。

 * target='main' 用主配置,target='subagent' 用子配置。
 * api_key='__unchanged__' 表示用已存的 key(前端 readonly 提交 sentinel)。
 */
export function testConfig(
  target: 'main' | 'subagent',
  model: string,
  api_key: string,
  base_url: string,
): Promise<ConfigTestResult> {
  return apiPost<ConfigTestResult>('/api/config/test', { target, model, api_key, base_url })
}
```

- [ ] **Step 3: 跑类型检查**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | head -30`
Expected: 无错误(如果 stores/config.ts 引用了旧 `LLMConfig` 类型,会因为 `LLMConfig = LLMConfigResponse` 别名兼容而通过;如果有错,修 stores/config.ts 适配新类型)

- [ ] **Step 4: 修 stores/config.ts 适配新类型(如有需要)**

读 `src/taisang/web/frontend/src/stores/config.ts`,确认 `getConfig()` 调用方式。当前代码:

```typescript
const cfg = await getConfig()
debug.value = cfg.debug ?? false
```

需要改成(因为 debug 现在在 `main` 块下):

```typescript
const cfg = await getConfig()
debug.value = cfg.main.debug ?? false
```

- [ ] **Step 5: 提交**

```bash
git add src/taisang/web/frontend/src/types/index.ts src/taisang/web/frontend/src/api/config.ts src/taisang/web/frontend/src/stores/config.ts
git commit -m "refactor(frontend): api/config.ts 改双块嵌套接口 + types 加 LLMConfigSection/SubAgentConfigSection

getConfig 返回 {main, subagent},saveConfig 接受嵌套 payload,
testConfig 加 target 参数。stores/config 读 main.debug。"
```

---

## Task 6: 前端 ApiKeyInput.vue 复用组件

**Files:**
- Create: `src/taisang/web/frontend/src/components/ApiKeyInput.vue`

- [ ] **Step 1: 创建 ApiKeyInput.vue**

新建 `src/taisang/web/frontend/src/components/ApiKeyInput.vue`:

```vue
<template>
  <div class="api-key-input">
    <t-input
      v-model="modelValue"
      :type="visible ? 'text' : 'password'"
      :readonly="readonly"
      :placeholder="placeholder"
    >
      <template #suffix>
        <t-icon
          :name="visible ? 'browse-off' : 'browse'"
          class="eye-icon"
          @click="toggleVisible"
        />
      </template>
    </t-input>
    <t-button
      v-if="readonly"
      variant="outline"
      size="small"
      @click="$emit('edit')"
    >
      修改
    </t-button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  modelValue: string
  readonly: boolean
  set: boolean  // 是否已配置(决定占位文案)
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'edit': []
}>()

const visible = ref(false)

function toggleVisible() {
  visible.value = !visible.value
}

const placeholder = computed(() => {
  if (props.readonly) {
    return props.set ? '••••••••••••••••' : '(未设置)'
  }
  return '输入新的 api_key'
})

// v-model 透传
const modelValue = computed({
  get: () => props.modelValue,
  set: (v: string) => emit('update:modelValue', v),
})
</script>

<style scoped>
.api-key-input {
  display: flex;
  gap: 8px;
  width: 100%;
}
.api-key-input :deep(.t-input) {
  flex: 1;
}
.eye-icon {
  cursor: pointer;
  color: var(--td-text-color-placeholder);
  font-size: 16px;
  transition: color 0.2s;
}
.eye-icon:hover {
  color: var(--td-text-color-primary);
}
</style>
```

- [ ] **Step 2: 跑类型检查**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | head -30`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add src/taisang/web/frontend/src/components/ApiKeyInput.vue
git commit -m "feat(frontend): 新增 ApiKeyInput 复用组件

脱敏占位(••••••••) + 眼睛图标切换明文 + 修改按钮。
readonly 态显示星号占位,点修改进入编辑态。"
```

---

## Task 7: 前端 ConfigModal.vue 重构

**Files:**
- Modify: `src/taisang/web/frontend/src/components/ConfigModal.vue`

- [ ] **Step 1: 重写 ConfigModal.vue**

把 `src/taisang/web/frontend/src/components/ConfigModal.vue` 全文替换为:

```vue
<template>
  <t-dialog
    v-model:visible="visible"
    header="LLM 配置"
    :footer="false"
    width="520px"
    destroy-on-close
  >
    <!-- 顶部:子 Agent 独立配置开关卡 -->
    <div class="toggle-card" :class="{ active: subForm.enabled }">
      <div class="toggle-left">
        <div class="toggle-icon">
          <t-icon name="user-circle" />
        </div>
        <div>
          <div class="toggle-title-row">
            <span class="toggle-title">子 Agent 独立配置</span>
            <t-tag v-if="subForm.enabled" size="small" class="enabled-pill">已启用</t-tag>
          </div>
          <div class="toggle-desc">开启时,主子 Agent 将分别使用独立的配置</div>
        </div>
      </div>
      <t-switch v-model="subForm.enabled" />
    </div>

    <!-- 主 Agent 卡 -->
    <div class="config-card">
      <div class="card-title-row">
        <span class="card-accent-bar"></span>
        <span class="card-title">主 Agent</span>
        <t-tag v-if="mainKeySet" theme="success" size="small">已配置</t-tag>
      </div>

      <t-form label-align="top">
        <t-form-item label="Model">
          <t-input v-model="mainForm.model" placeholder="gpt-4o / glm-4.5 / Kimi-K2 / ..." />
        </t-form-item>
        <t-form-item label="API Key">
          <ApiKeyInput
            v-model="mainForm.api_key"
            :readonly="mainKeyReadonly"
            :set="mainKeySet"
            @edit="handleEditMainKey"
          />
        </t-form-item>
        <t-form-item label="Base URL">
          <t-input v-model="mainForm.base_url" placeholder="https://api.openai.com/v1" />
        </t-form-item>
      </t-form>

      <div class="card-test-row">
        <t-button
          variant="outline"
          :loading="mainTesting"
          :disabled="!canTestMain"
          @click="handleTestMain"
        >
          测试连接
        </t-button>
        <span v-if="mainTestResult" class="test-result" :class="{ ok: mainTestResult.ok, error: !mainTestResult.ok }">
          <template v-if="mainTestResult.ok">✅ 连接成功!延时 {{ mainTestResult.latency_ms }}ms</template>
          <template v-else>❌ {{ mainTestResult.error }}</template>
        </span>
      </div>
    </div>

    <div class="card-divider"></div>

    <!-- 子 Agent 卡(仅 enabled 时渲染) -->
    <div v-if="subForm.enabled" class="config-card">
      <div class="card-title-row">
        <span class="card-accent-bar"></span>
        <span class="card-title">子 Agent</span>
      </div>

      <t-form label-align="top">
        <t-form-item label="Model">
          <t-input v-model="subForm.model" placeholder="glm-4.5 / deepseek-chat / ..." />
        </t-form-item>
        <t-form-item label="API Key">
          <ApiKeyInput
            v-model="subForm.api_key"
            :readonly="subKeyReadonly"
            :set="subKeySet"
            @edit="handleEditSubKey"
          />
        </t-form-item>
        <t-form-item label="Base URL">
          <t-input v-model="subForm.base_url" placeholder="https://api.openai.com/v1" />
        </t-form-item>
      </t-form>

      <div class="card-test-row">
        <t-button
          variant="outline"
          :loading="subTesting"
          :disabled="!canTestSub"
          @click="handleTestSub"
        >
          测试连接
        </t-button>
        <span v-if="subTestResult" class="test-result" :class="{ ok: subTestResult.ok, error: !subTestResult.ok }">
          <template v-if="subTestResult.ok">✅ 连接成功!延时 {{ subTestResult.latency_ms }}ms</template>
          <template v-else>❌ {{ subTestResult.error }}</template>
        </span>
      </div>
    </div>

    <div v-if="subForm.enabled" class="card-divider"></div>

    <!-- Debug 卡 -->
    <div class="config-card">
      <div class="debug-row">
        <div class="debug-label">
          <div class="debug-title">Debug 模式</div>
          <div class="debug-desc">开启后展示工具调用 + 思考过程 + 完整结果</div>
        </div>
        <t-switch v-model="debugValue" />
      </div>
    </div>

    <!-- 全局错误消息 -->
    <div v-if="msg" class="cfg-msg" :class="{ error: msgError }">{{ msg }}</div>

    <!-- 操作区 -->
    <div class="config-actions">
      <t-button variant="text" @click="visible = false">取消</t-button>
      <t-button theme="primary" :loading="saving" @click="handleSubmit">保存</t-button>
    </div>
  </t-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  getConfig,
  saveConfig,
  testConfig,
  type ConfigTestResult,
  type ConfigSectionPayload,
} from '@/api/config'
import ApiKeyInput from './ApiKeyInput.vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'debug-changed': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

// 主 Agent 表单
const mainForm = ref({ model: '', api_key: '', base_url: '' })
const mainKeyReadonly = ref(true)
const mainKeySet = ref(false)
const mainKeyMasked = ref('')  // 后端打码值,保存成功后恢复
const mainTesting = ref(false)
const mainTestResult = ref<ConfigTestResult | null>(null)

// 子 Agent 表单
const subForm = ref({ enabled: false, model: '', api_key: '', base_url: '' })
const subKeyReadonly = ref(true)
const subKeySet = ref(false)
const subKeyMasked = ref('')
const subTesting = ref(false)
const subTestResult = ref<ConfigTestResult | null>(null)

// Debug
const debugValue = ref(false)
const debugOriginal = ref(false)

// 全局消息
const msg = ref('')
const msgError = ref(false)
const saving = ref(false)

// 测试按钮 disabled 条件:model + base_url 都填
const canTestMain = computed(() =>
  mainForm.value.model.trim() !== '' && mainForm.value.base_url.trim() !== '',
)
const canTestSub = computed(() =>
  subForm.value.model.trim() !== '' && subForm.value.base_url.trim() !== '',
)

async function loadConfig() {
  msg.value = ''
  msgError.value = false
  mainTestResult.value = null
  subTestResult.value = null
  try {
    const cfg = await getConfig()
    // main
    mainForm.value.model = cfg.main.model || ''
    mainForm.value.base_url = cfg.main.base_url || ''
    mainForm.value.api_key = ''  // readonly 态不显示打码值,用占位
    mainKeySet.value = cfg.main.api_key_set
    mainKeyMasked.value = cfg.main.api_key
    mainKeyReadonly.value = true
    // subagent
    subForm.value.enabled = cfg.subagent.enabled
    subForm.value.model = cfg.subagent.model || ''
    subForm.value.base_url = cfg.subagent.base_url || ''
    subForm.value.api_key = ''
    subKeySet.value = cfg.subagent.api_key_set
    subKeyMasked.value = cfg.subagent.api_key
    subKeyReadonly.value = true
    // debug
    debugValue.value = cfg.main.debug ?? false
    debugOriginal.value = cfg.main.debug ?? false
  } catch (e) {
    msg.value = '加载配置失败: ' + (e as Error).message
    msgError.value = true
  }
}

function handleEditMainKey() {
  mainKeyReadonly.value = false
  mainForm.value.api_key = ''
}

function handleEditSubKey() {
  subKeyReadonly.value = false
  subForm.value.api_key = ''
}

async function handleTestMain() {
  mainTestResult.value = null
  const apiKey = mainKeyReadonly.value ? '__unchanged__' : mainForm.value.api_key
  mainTesting.value = true
  try {
    mainTestResult.value = await testConfig('main', mainForm.value.model.trim(), apiKey, mainForm.value.base_url.trim())
  } catch (e) {
    mainTestResult.value = { ok: false, error: (e as Error).message }
  } finally {
    mainTesting.value = false
  }
}

async function handleTestSub() {
  subTestResult.value = null
  const apiKey = subKeyReadonly.value ? '__unchanged__' : subForm.value.api_key
  subTesting.value = true
  try {
    subTestResult.value = await testConfig('subagent', subForm.value.model.trim(), apiKey, subForm.value.base_url.trim())
  } catch (e) {
    subTestResult.value = { ok: false, error: (e as Error).message }
  } finally {
    subTesting.value = false
  }
}

async function handleSubmit() {
  msg.value = ''
  msgError.value = false
  mainTestResult.value = null
  subTestResult.value = null

  // 校验 main
  if (!mainForm.value.model.trim()) {
    msg.value = '主 Agent model 不能为空'
    msgError.value = true
    return
  }
  if (!mainForm.value.base_url.trim()) {
    msg.value = '主 Agent base_url 不能为空'
    msgError.value = true
    return
  }

  // 校验 sub(仅 enabled 时)
  if (subForm.value.enabled) {
    if (!subForm.value.model.trim()) {
      msg.value = '启用独立配置后,子 Agent model 不能为空'
      msgError.value = true
      return
    }
    if (!subForm.value.base_url.trim()) {
      msg.value = '启用独立配置后,子 Agent base_url 不能为空'
      msgError.value = true
      return
    }
  }

  const mainPayload: ConfigSectionPayload = {
    model: mainForm.value.model.trim(),
    api_key: mainKeyReadonly.value ? '__unchanged__' : mainForm.value.api_key,
    base_url: mainForm.value.base_url.trim(),
  }
  const subPayload: ConfigSectionPayload | null = subForm.value.enabled
    ? {
        enabled: true,
        model: subForm.value.model.trim(),
        api_key: subKeyReadonly.value ? '__unchanged__' : subForm.value.api_key,
        base_url: subForm.value.base_url.trim(),
      }
    : null

  saving.value = true
  try {
    await saveConfig({ main: mainPayload, subagent: subPayload, debug: debugValue.value })
    if (debugValue.value !== debugOriginal.value) {
      emit('debug-changed', debugValue.value)
      debugOriginal.value = debugValue.value
    }
    // 保存成功后恢复 readonly
    mainKeyReadonly.value = true
    mainForm.value.api_key = ''
    subKeyReadonly.value = true
    subForm.value.api_key = ''
    visible.value = false
  } catch (e) {
    msg.value = '保存失败: ' + (e as Error).message
    msgError.value = true
  } finally {
    saving.value = false
  }
}

watch(visible, (v) => {
  if (v) {
    loadConfig()
  } else {
    msg.value = ''
    msgError.value = false
    mainTestResult.value = null
    subTestResult.value = null
  }
})
</script>

<style scoped>
.toggle-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);
  border-radius: 8px;
  margin-bottom: 20px;
  transition: all 0.2s;
}
.toggle-card.active {
  border-color: var(--td-brand-color);
  box-shadow: 0 0 0 3px var(--td-brand-color-1);
}
.toggle-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toggle-icon {
  width: 36px;
  height: 36px;
  background: var(--td-brand-color-1);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--td-brand-color);
  font-size: 20px;
  transition: all 0.2s;
}
.toggle-card.active .toggle-icon {
  background: var(--td-brand-color);
  color: #fff;
}
.toggle-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toggle-title {
  font-size: 15px;
  font-weight: 600;
}
.toggle-desc {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin-top: 2px;
}
.enabled-pill {
  background: var(--td-brand-color-1);
  color: var(--td-brand-color);
  border-radius: 10px;
  font-weight: 500;
}

.config-card {
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);
  border-radius: 8px;
  padding: 16px 20px;
}
.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.card-accent-bar {
  width: 6px;
  height: 18px;
  background: var(--td-brand-color);
  border-radius: 2px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
}
.card-test-row {
  display: flex;
  align-items: center;
  gap: 12px;
  border-top: 1px dashed var(--td-component-stroke);
  padding-top: 12px;
}
.test-result {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  line-height: 1.5;
}
.test-result.ok {
  color: var(--td-success-color, #2ba471);
  background: var(--td-success-bg-color, #e8f7ef);
}
.test-result.error {
  color: var(--td-error-color, #d54941);
  background: var(--td-error-bg-color, #fdecee);
}
.card-divider {
  height: 1px;
  background: var(--td-component-stroke);
  margin: 20px 0;
}

.debug-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.debug-label {
  flex: 1;
}
.debug-title {
  font-size: 14px;
  font-weight: 500;
}
.debug-desc {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin-top: 2px;
  line-height: 1.5;
}

.cfg-msg {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin: 12px 0 0;
  min-height: 18px;
}
.cfg-msg.error {
  color: var(--td-error-color, #d54941);
}
.config-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
```

- [ ] **Step 2: 跑类型检查**

Run: `cd src/taisang/web/frontend && npx vue-tsc --noEmit 2>&1 | head -30`
Expected: 无错误

- [ ] **Step 3: 跑前端 build 确认能打包**

Run: `cd src/taisang/web/frontend && npm run build 2>&1 | tail -20`
Expected: build 成功(vue-tsc + vite build 都过)

- [ ] **Step 4: 提交**

```bash
git add src/taisang/web/frontend/src/components/ConfigModal.vue
git commit -m "feat(frontend): ConfigModal 重构为顶部开关卡 + 主/子/Debug 三卡片 + 分隔线布局

顶部开关卡(36x36 图标块 + 标题 + 副标题 + 已启用 pill 标签),
开关关闭时子 Agent 卡不渲染;主/子卡各自独立测试连接按钮 + inline 结果
(✅ 连接成功!延时 Xms);Debug 卡单独分隔。"
```

---

## Task 8: 全量回归测试 + 前端 build 验收

**Files:**
- 无文件改动,纯验证

- [ ] **Step 1: 跑全部后端单测**

Run: `cd D:/GoProject/TaiSang && python -m pytest tests/unit -v 2>&1 | tail -30`
Expected: 全部 PASS(605+ 测试,新增约 15 个)

- [ ] **Step 2: 跑全部后端集成测试**

Run: `cd D:/GoProject/TaiSang && python -m pytest tests/integration -v 2>&1 | tail -20`
Expected: 全部 PASS

- [ ] **Step 3: 跑前端类型检查 + build**

Run: `cd src/taisang/web/frontend && npm run build 2>&1 | tail -20`
Expected: build 成功

- [ ] **Step 4: 跑前端 build 后同步 static 目录**

项目 `src/taisang/web/static/` 是前端 build 产物落盘位置(供 FastAPI 静态服务)。确认 build 产物已同步:

Run: `cd D:/GoProject/TaiSang && ls src/taisang/web/static/assets/ | head -5`
Expected: 有 index-*.js / index-*.css 等文件(如果 build 没自动同步到 static,需要手动 `npm run build` 输出目录配 vite.config.ts 的 `outDir` 指向 static,或手动 cp)

- [ ] **Step 5: 启动 web server 烟测**

Run(后台启动):
```bash
cd D:/GoProject/TaiSang && python -m taisang web --repo D:/GoProject/TaiSang
```
预期:server 起在 http://localhost:8000(或项目配置的端口),不报错

- [ ] **Step 6: 提交最终改动(如果有 build 产物同步)**

```bash
git add src/taisang/web/static/
git commit -m "chore: 同步前端 build 产物到 static 目录"
```

---

## Task 9: Playwright 端到端验收(非截图)

**Files:**
- 无文件改动,纯验证(用 playwright MCP 或临时脚本)

- [ ] **Step 1: 确认 web server 在跑**

确认 Task 8 Step 5 的 server 还在后台跑。如果挂了重启:

Run(后台): `cd D:/GoProject/TaiSang && python -m taisang web --repo D:/GoProject/TaiSang`

- [ ] **Step 2: 用 playwright MCP 打开页面**

调用 `playwright_navigate` 工具打开 `http://localhost:8000`。

**⚠️ 严禁调用任何截图工具**(playwright_screenshot / browser_take_screenshot 等)——会废掉 session。改用:
- `playwright_get_visible_text` 拿页面文本
- `playwright_get_visible_html` 拿 HTML
- `browser_snapshot` 拿无障碍树

- [ ] **Step 3: 打开设置页,验证布局**

调用 `playwright_click` 点 Sidebar 底部的「设置」按钮(或用 `playwright_evaluate` 触发 `document.querySelector('[aria-label*=\"LLM 配置\"]')` 的 click)。

用 `playwright_get_visible_text` 拿 Dialog 文本,验证:
- 有「子 Agent 独立配置」标题
- 有「开启时,主子 Agent 将分别使用独立的配置」副标题
- 有「主 Agent」卡 + Model / API Key / Base URL 字段
- 有「测试连接」按钮
- 有「Debug 模式」
- **没有**「子 Agent」卡的 Model/Key/Base URL 字段(因为开关默认关)

- [ ] **Step 4: 打开开关,验证子 Agent 卡出现**

调用 `playwright_click` 点顶部开关卡的 switch(用 selector 定位)。

用 `playwright_get_visible_text` 验证:
- 出现「子 Agent」卡 + Model / API Key / Base URL 字段
- 出现第二个「测试连接」按钮
- 顶部开关卡显示「已启用」pill 标签

- [ ] **Step 5: 验证 key 控件脱敏**

用 `playwright_get_visible_html` 检查 API Key 输入框:
- readonly 态 `type` 应该是 `password`(眼睛关闭)或显示 `••••••••` 占位
- 点眼睛图标后 `type` 变 `text`(明文显示,但未配置时为空)
- 点「修改」按钮后 readonly 变 false,可输入

- [ ] **Step 6: 关闭开关,验证子 Agent 卡消失**

调用 `playwright_click` 关掉开关。

用 `playwright_get_visible_text` 验证:
- 「子 Agent」卡的 Model/Key/Base URL 字段消失
- 只剩顶部开关卡 + 主 Agent 卡 + Debug 卡

- [ ] **Step 7: 填主配置 + 保存,验证不报错**

用 `playwright_evaluate` 或 `playwright_fill` 填主 Agent 的 model/base_url(用假值如 `test-model` / `https://test.com`),点保存。

用 `playwright_get_visible_text` 验证:
- Dialog 关闭(保存成功)
- 无错误消息

读 `~/.taisang/settings.json` 确认:
```bash
cat ~/.taisang/settings.json
```
Expected: `llm` 字段有 main 配置,`llm_subagent` 字段 `enabled: false`

- [ ] **Step 8: 清理测试数据**

把 `~/.taisang/settings.json` 改回原状(或删掉测试字段),避免污染用户真实配置。

- [ ] **Step 9: 停 web server**

用 TaskStop 工具停掉 Task 8 Step 5 启动的后台 server。

- [ ] **Step 10: 更新 memory 笔记**

在 `C:\Users\50892\.claude\projects\C--Users-50892\memory\` 新建 `2026-09-10-taisang-subagent-llm-config.md`,记录:
- 改动摘要(子 agent 独立 LLM 配置 + 设置页改造)
- commits 列表
- 测试通过数
- 已知 bug / follow-up(如有)

---

## Self-Review Checklist(plan 自审,执行前跑一遍)

- [x] **Spec 覆盖**:
  - 后端 `SubAgentLLMConfig` 模型 → Task 1
  - `_make_child_llm` fallback → Task 2
  - `/api/config` GET/POST 双块 → Task 3
  - `/api/config/test` target 参数 → Task 4
  - 前端类型 + api 重构 → Task 5
  - `ApiKeyInput` 组件 → Task 6
  - `ConfigModal` 重构 → Task 7
  - 测试策略 → Task 1-4 + Task 8
  - 视觉细节(竖条/圆角/分隔线/开关卡) → Task 7 CSS
  - 错误处理(子空 fallback / 校验) → Task 2 + Task 4 + Task 7
  - Playwright 验收 → Task 9

- [x] **占位符扫描**:无 TBD/TODO,每个步骤有具体代码或命令

- [x] **类型一致性**:`SubAgentLLMConfig` / `ConfigSectionReq` / `LLMConfigSection` / `SubAgentConfigSection` / `ConfigSectionPayload` 跨任务命名一致

- [x] **测试覆盖**:每个新增函数都有对应测试;现有测试的更新步骤明确

---

## 执行选择

**Plan complete and saved to `docs/superpowers/plans/2026-09-10-subagent-llm-config-ui.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 每个 task 派一个 fresh subagent,任务间 review,快速迭代

**2. Inline Execution** - 当前 session 按 task 顺序执行,带 checkpoint review

用户已明确要求"写完直接开始,全程不问",采用 **Inline Execution**(subagent-driven 每次都要 review 会打断流程)。继续用 `superpowers:executing-plans` skill。