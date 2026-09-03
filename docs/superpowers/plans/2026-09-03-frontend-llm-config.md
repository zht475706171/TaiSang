# 前端 LLM 配置页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端 sidebar 底部加"设置"按钮 → 独立配置页,可改 model / api_key / base_url,保存后立即生效(重建所有 session 的 LLMClient)。

**Architecture:** `config.py` 加 `save_config` + `mask_api_key` + 改 `load_config` 优先级(文件 > env > 默认);`SessionRegistry.apply_llm_config` 重建所有 session 的 LLMClient;`app.py` 加 GET/POST /api/config 路由;前端 sidebar 设置按钮 + 设置页 + JS。

**Tech Stack:** Python 3.12 + fastapi + pytest(已有),前端纯 JS(无框架),零新依赖。

**Spec:** `docs/superpowers/specs/2026-09-03-frontend-llm-config-design.md`

---

## 文件结构

**修改**:
- `src/taisang/config.py` — 加 `save_config` + `mask_api_key`,`load_config` 改优先级
- `src/taisang/web/session_registry.py` — 加 `apply_llm_config`
- `src/taisang/web/app.py` — 加 GET/POST /api/config 路由 + 文件头注释
- `src/taisang/web/static/index.html` — sidebar 设置按钮 + 设置页 + JS
- `tests/unit/test_config.py` — 改 `test_env_overrides_file` 为文件 > env + 加 save_config / mask_api_key 测试
- `tests/unit/test_web_app.py` — 加配置路由 + apply_llm_config 测试

---

## Task 1: config.py 加 save_config + mask_api_key + 改 load_config 优先级

**Files:**
- Modify: `src/taisang/config.py`
- Modify: `tests/unit/test_config.py:57-69`(`test_env_overrides_file` 改成文件 > env)
- Test: `tests/unit/test_config.py`(加 3 个新测试)

- [ ] **Step 1: 改 test_env_overrides_file + 加新失败测试**

替换 `tests/unit/test_config.py:57-69` 的 `test_env_overrides_file`:

```python
def test_file_overrides_env(tmp_path, monkeypatch):
    """决策 7:文件 > env > 默认。前端写入后文件是真相源,env 不 override。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    settings = tmp_path / ".taisang" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"llm": {"base_url": "https://from-file", "api_key": "k-file", "model": "m-file"}})
    )
    monkeypatch.setenv("TAISANG_LLM_MODEL", "from-env")
    cfg = load_config()
    # 文件优先,env 被 override
    assert cfg.model == "m-file"
    assert cfg.base_url == "https://from-file"
    assert cfg.api_key == "k-file"
```

在文件末尾追加 3 个新测试:

```python
from taisang.config import save_config, mask_api_key, LLMConfig


def test_save_config_writes_llm_field(tmp_path, monkeypatch):
    """save_config 原子写 settings.json 的 llm 字段。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    cfg = LLMConfig(base_url="https://api.test.com", api_key="sk-abc12345", model="test-model")
    save_config(cfg)
    import json
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["base_url"] == "https://api.test.com"
    assert data["llm"]["api_key"] == "sk-abc12345"
    assert data["llm"]["model"] == "test-model"


def test_save_config_preserves_other_fields(tmp_path, monkeypatch):
    """save_config 保留 settings.json 的其它字段(只改 llm)。"""
    _isolate_home(tmp_path, monkeypatch)
    _clear_llm_env(monkeypatch)
    p = tmp_path / ".taisang" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"other_field": "keep_me", "llm": {"base_url": "old", "api_key": "old", "model": "old"}}))
    cfg = LLMConfig(base_url="new", api_key="new-k", model="new-m")
    save_config(cfg)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["other_field"] == "keep_me"  # 保留
    assert data["llm"]["base_url"] == "new"  # 覆盖


def test_mask_api_key():
    """api_key 打码:前3+***+后4,短于8字符全 ***。"""
    assert mask_api_key("sk-f1575dabc663ec6df17433c4b8396ed2fd8fc17cf9f97a09454b37db38db53b6") == "sk-***3b6"
    assert mask_api_key("short") == "***"
    assert mask_api_key("") == "***"
    assert mask_api_key("12345678") == "***"  # 正好 8 字符,全 ***
    assert mask_api_key("123456789") == "123***6789"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: `test_save_config_*` 和 `test_mask_api_key` FAIL(函数不存在),`test_file_overrides_env` FAIL(env 还优先)

- [ ] **Step 3: 改 config.py**

替换 `src/taisang/config.py` 全文:

```python
"""LLM endpoint 配置加载 + 保存。

优先级: 文件(~/.taisang/settings.json) > env > 默认值。
前端写入后文件是真相源,env 仅在文件字段缺失时 fallback。
单一 LLM 配置(summarizer / agent 全用同一个模型)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


class LLMConfig(BaseModel):
    """LLM 接入配置。"""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"


def _settings_path() -> Path:
    return Path.home() / ".taisang" / "settings.json"


def _load_settings_file() -> dict:
    p = _settings_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 损坏文件当空处理,fallback 到 env/默认
        return {}


def load_config() -> LLMConfig:
    """加载 LLM 配置。文件 > env > 默认。env 仅在文件字段缺失时 fallback。"""
    file_cfg = _load_settings_file().get("llm", {})
    # 文件优先,文件没的字段才看 env
    base_url = file_cfg.get("base_url") or os.environ.get("TAISANG_LLM_BASE_URL")
    api_key = file_cfg.get("api_key") or os.environ.get("TAISANG_LLM_API_KEY")
    model = file_cfg.get("model") or os.environ.get("TAISANG_LLM_MODEL")
    config_data = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }
    # Drop None values so Pydantic field defaults apply
    config_data = {k: v for k, v in config_data.items() if v is not None}
    return LLMConfig(**config_data)


def save_config(cfg: LLMConfig) -> None:
    """原子写 ~/.taisang/settings.json 的 llm 字段。保留其它字段。权限 600。"""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings_file()
    existing["llm"] = cfg.model_dump()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows 无 chmod,跳过
    os.replace(tmp, p)


def mask_api_key(key: str) -> str:
    """api_key 打码:前 3 + *** + 后 4,短于 8 字符全 ***。"""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: 全 PASS

- [ ] **Step 5: 跑全套确保无回归**

Run: `python -m pytest`
Expected: 179/179 PASS(若 test_env_overrides_file 被改名,总数不变:删 1 加 4)

- [ ] **Step 6: 提交**

```bash
git add src/taisang/config.py tests/unit/test_config.py
git commit -m "feat(config): 加 save_config + mask_api_key,load_config 优先级改文件>env>默认"
```

---

## Task 2: SessionRegistry.apply_llm_config

**Files:**
- Modify: `src/taisang/web/session_registry.py`(加 `apply_llm_config` 方法)
- Test: `tests/unit/test_web_app.py`(加测试)

- [ ] **Step 1: 加失败测试**

追加到 `tests/unit/test_web_app.py`:

```python
def test_apply_llm_config_replaces_all_non_mock_sessions(tmp_path, monkeypatch):
    """apply_llm_config 重建所有非 MockLLM session 的 LLMClient。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    from taisang.web.session_registry import SessionRegistry
    from taisang.config import LLMConfig
    from taisang.llm_client import LLMClient

    reg = SessionRegistry(tmp_path)
    sid1 = reg.create(title="")
    sid2 = reg.create(title="")
    sess1 = reg.get_or_load(sid1)
    sess2 = reg.get_or_load(sid2)
    # 构造时是 MockLLM(没设真 env),先手动换成真 LLMClient 模拟生产
    old_cfg = LLMConfig(base_url="https://old", api_key="sk-old1234567890", model="old-m")
    sess1.agent.llm = LLMClient(old_cfg)
    sess2.agent.llm = LLMClient(old_cfg)

    new_cfg = LLMConfig(base_url="https://new", api_key="sk-new1234567890", model="new-m")
    reg.apply_llm_config(new_cfg)

    for sess in [sess1, sess2]:
        assert isinstance(sess.agent.llm, LLMClient)
        assert sess.agent.llm.model == "new-m"
        assert sess.agent.llm.cfg.base_url == "https://new"


def test_apply_llm_config_skips_mock_sessions(tmp_path, monkeypatch):
    """apply_llm_config 跳过 MockLLM 实例(测试场景不替换)。"""
    monkeypatch.setenv("TAISANG_MOCK_LLM", "1")
    from taisang.web.session_registry import SessionRegistry
    from taisang.config import LLMConfig
    from taisang.llm_client import MockLLM

    reg = SessionRegistry(tmp_path)
    sid = reg.create(title="")
    sess = reg.get_or_load(sid)
    assert isinstance(sess.agent.llm, MockLLM)
    reg.apply_llm_config(LLMConfig(base_url="x", api_key="y", model="z"))
    # 还是 MockLLM,没被替换
    assert isinstance(sess.agent.llm, MockLLM)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_apply_llm_config_replaces_all_non_mock_sessions -v`
Expected: FAIL — `apply_llm_config` 方法不存在(AttributeError)

- [ ] **Step 3: 加 apply_llm_config 方法**

在 `src/taisang/web/session_registry.py` 的 `SessionRegistry` 类里,`delete` 方法前(或 `set_debug` 后)加:

```python
    def apply_llm_config(self, cfg: "LLMConfig") -> None:
        """所有内存 session 的 LLMClient 用新 cfg 重建。立即生效。

        MockLLM 实例跳过(测试场景)。
        正在跑的 run 持有 sess.lock,run 内部用旧 llm 跑完当前 LLM 调用;
        下一次 LLM 调用用新 llm —— 这是可接受的边界(model 中途切换)。
        """
        with self._lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            if isinstance(sess.agent.llm, MockLLM):
                continue
            sess.agent.llm = LLMClient(cfg)
```

同时在文件头 import 区加:
```python
from ..config import LLMConfig, load_config
from ..llm_client import LLMClient, MockLLM
```
(已有 `load_config` 和 `LLMClient, MockLLM`,只需加 `LLMConfig`)

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全 PASS

- [ ] **Step 5: 跑全套**

Run: `python -m pytest`
Expected: 全 PASS

- [ ] **Step 6: 提交**

```bash
git add src/taisang/web/session_registry.py tests/unit/test_web_app.py
git commit -m "feat(web): SessionRegistry.apply_llm_config 重建所有 session 的 LLMClient"
```

---

## Task 3: app.py 加 GET/POST /api/config 路由

**Files:**
- Modify: `src/taisang/web/app.py`(加 2 个路由 + 文件头注释 + ConfigReq model)
- Test: `tests/unit/test_web_app.py`

- [ ] **Step 1: 加失败测试**

追加到 `tests/unit/test_web_app.py`:

```python
def test_get_config_returns_masked_api_key(tmp_path, monkeypatch):
    """GET /api/config 返回 model/base_url + api_key 打码。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, save_config
    from taisang.web.app import create_app

    save_config(LLMConfig(base_url="https://api.x.com", api_key="sk-abcdefghij1234567", model="m"))
    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "m"
    assert data["base_url"] == "https://api.x.com"
    assert data["api_key"] == "sk-***4567"  # 打码
    assert data["api_key_set"] is True


def test_post_config_saves_and_applies(tmp_path, monkeypatch):
    """POST /api/config 写文件 + apply 到所有 session。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "model": "new-model",
        "api_key": "sk-newkey1234567890",
        "base_url": "https://api.new.com",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # 文件被写
    import json
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["model"] == "new-model"
    assert data["llm"]["base_url"] == "https://api.new.com"
    assert data["llm"]["api_key"] == "sk-newkey1234567890"


def test_post_config_empty_api_key_allowed(tmp_path, monkeypatch):
    """POST /api/config 空 api_key 允许保存(本地 endpoint 如 ollama 不需要 key)。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.web.app import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "model": "m",
        "api_key": "",
        "base_url": "http://localhost:11434/v1",
    })
    assert r.status_code == 200
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/unit/test_web_app.py::test_get_config_returns_masked_api_key -v`
Expected: FAIL — 路由不存在(404)

- [ ] **Step 3: 加路由**

在 `src/taisang/web/app.py` 文件头路由注释区加:

```python
- GET  /api/config           → 取 LLM 配置(api_key 打码)
- POST /api/config           → 保存 LLM 配置 + 立即应用到所有 session
```

在 import 区加(`load_config` 已有,补 `LLMConfig, save_config, mask_api_key`):
```python
from ..config import LLMConfig, load_config, mask_api_key, save_config
```

在路由区(看现有 model 定义位置,加 ConfigReq;在 `get_messages` 路由后面加 2 个路由):

```python
class ConfigReq(BaseModel):
    model: str
    api_key: str
    base_url: str


@app.get("/api/config")
async def get_config() -> dict:
    """返回当前 LLM 配置。api_key 打码。"""
    cfg = load_config()
    return {
        "model": cfg.model,
        "base_url": cfg.base_url,
        "api_key": mask_api_key(cfg.api_key),
        "api_key_set": bool(cfg.api_key),
    }


@app.post("/api/config")
async def save_config_route(req: ConfigReq) -> dict:
    """保存 LLM 配置 + 立即应用到所有 session。"""
    cfg = LLMConfig(model=req.model, api_key=req.api_key, base_url=req.base_url)
    save_config(cfg)
    registry.apply_llm_config(cfg)
    return {"ok": True}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/unit/test_web_app.py -v`
Expected: 全 PASS

- [ ] **Step 5: 跑全套**

Run: `python -m pytest`
Expected: 全 PASS

- [ ] **Step 6: 提交**

```bash
git add src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): 加 GET/POST /api/config 路由(配置页后端)"
```

---

## Task 4: 前端 sidebar 设置按钮 + 设置页 + JS

**Files:**
- Modify: `src/taisang/web/static/index.html`(sidebar 加按钮 + 设置页 div + JS)

- [ ] **Step 1: sidebar 底部加设置按钮**

在 `src/taisang/web/static/index.html` 的 `<div id="sidebar">` 里,`<div id="session-list"></div>` 后加:

```html
    <div id="config-btn-wrap">
      <button id="config-btn"><span class="gear">⚙</span>设置</button>
    </div>
```

- [ ] **Step 2: 加设置页 HTML**

在 `<div id="main">` 后加独立设置页(默认 hidden):

```html
<div id="config-page" class="hidden">
  <div class="config-header">
    <h2>⚙ LLM 配置</h2>
    <button id="config-close-btn" title="关闭">×</button>
  </div>
  <div class="config-form">
    <label>
      <span class="field-label">Model</span>
      <input id="cfg-model" type="text" placeholder="gpt-4o / glm-5.2 / ...">
    </label>
    <label>
      <span class="field-label">API Key</span>
      <div class="api-key-row">
        <input id="cfg-api-key" type="text" readonly placeholder="(未设置)">
        <button id="cfg-api-key-edit" type="button">修改</button>
      </div>
    </label>
    <label>
      <span class="field-label">Base URL</span>
      <input id="cfg-base-url" type="text" placeholder="https://api.openai.com/v1">
    </label>
    <div class="config-actions">
      <button id="cfg-cancel">取消</button>
      <button id="cfg-save" class="primary">保存</button>
    </div>
    <div id="cfg-msg" class="cfg-msg"></div>
  </div>
</div>
```

- [ ] **Step 3: 加 CSS**

在 `src/taisang/web/static/index.html` 的 `<style>` 区末尾加:

```css
/* ===== 配置页 ===== */
#config-btn-wrap {
  padding: 12px 20px;
  border-top: 1px solid var(--rule-soft);
  flex-shrink: 0;
}
#config-btn {
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: 1px solid var(--rule);
  color: var(--ink-2);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  border-radius: 4px;
  text-align: left;
}
#config-btn:hover { background: var(--paper-3); color: var(--ink); }
#config-btn .gear { margin-right: 8px; }

#config-page {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: var(--paper);
  z-index: 100;
  padding: 40px 20% 20px;
  overflow-y: auto;
}
#config-page.hidden { display: none; }
.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--rule);
}
.config-header h2 {
  font-family: "IBM Plex Mono", monospace;
  font-size: 18px;
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}
#config-close-btn {
  background: transparent;
  border: none;
  font-size: 24px;
  color: var(--ink-3);
  cursor: pointer;
  padding: 0 8px;
}
#config-close-btn:hover { color: var(--ink); }
.config-form label {
  display: block;
  margin-bottom: 20px;
}
.field-label {
  display: block;
  font-size: 12px;
  color: var(--ink-3);
  margin-bottom: 6px;
  font-family: "IBM Plex Mono", monospace;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.config-form input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: var(--paper-2);
  font-family: "IBM Plex Mono", monospace;
  font-size: 14px;
  color: var(--ink);
}
.config-form input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.config-form input[readonly] { background: var(--paper-3); color: var(--ink-3); }
.api-key-row { display: flex; gap: 8px; }
.api-key-row input { flex: 1; }
.api-key-row button {
  padding: 10px 16px;
  border: 1px solid var(--rule);
  background: transparent;
  color: var(--ink-2);
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
}
.api-key-row button:hover { background: var(--paper-3); }
.config-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 32px;
}
.config-actions button {
  padding: 10px 24px;
  border: 1px solid var(--rule);
  background: transparent;
  color: var(--ink-2);
  cursor: pointer;
  border-radius: 4px;
  font-size: 14px;
}
.config-actions button.primary {
  background: var(--accent);
  color: var(--paper);
  border-color: var(--accent);
}
.config-actions button:hover { background: var(--paper-3); }
.config-actions button.primary:hover { background: var(--accent-strong, var(--accent)); }
.cfg-msg {
  margin-top: 16px;
  font-size: 13px;
  color: var(--accent);
  min-height: 18px;
}
.cfg-msg.error { color: #c0392b; }
```

- [ ] **Step 4: 加 JS 逻辑**

在 `src/taisang/web/static/index.html` 的 `<script>` 区末尾(`loadSessions();` 之前)加:

```javascript
// ========== 配置页 ==========
const configPage = document.getElementById('config-page');
const cfgModel = document.getElementById('cfg-model');
const cfgApiKey = document.getElementById('cfg-api-key');
const cfgBaseUrl = document.getElementById('cfg-base-url');
const cfgMsg = document.getElementById('cfg-msg');

async function openConfigPage() {
  cfgMsg.textContent = '';
  cfgMsg.classList.remove('error');
  try {
    const r = await fetch('/api/config');
    if (!r.ok) throw new Error('GET /api/config failed');
    const data = await r.json();
    cfgModel.value = data.model || '';
    cfgBaseUrl.value = data.base_url || '';
    cfgApiKey.value = data.api_key || '';
    cfgApiKey.setAttribute('readonly', '');
    cfgApiKey.dataset.original = data.api_key || '';
    cfgApiKey.placeholder = data.api_key_set ? data.api_key : '(未设置)';
    configPage.classList.remove('hidden');
  } catch (e) {
    cfgMsg.textContent = '加载配置失败: ' + e.message;
    cfgMsg.classList.add('error');
    configPage.classList.remove('hidden');
  }
}

function closeConfigPage() {
  configPage.classList.add('hidden');
}

async function saveConfig() {
  cfgMsg.textContent = '';
  cfgMsg.classList.remove('error');
  // api_key 若 readonly(未点修改),用原打码值?不行 —— 打码值不能存。
  // 逻辑:readonly 时保留原值,后端 GET 返回的是打码,不能直接存打码。
  // 解决:readonly 时提交空字符串,后端识别"空 = 不改"?
  // 但 POST /api/config 的 schema 要求 api_key: str,空就是空(清空 key)。
  // 更好:readonly 时提交原打码值,后端检测到打码格式(sk-***xxxx)就跳过不改 api_key。
  // 这里取简单方案:readonly 时把 input 切回真值?不,前端没有真值。
  // 最终方案:readonly 时提交空,后端遇到空 + api_key_set=True 就保留原 key。
  // 但 test_post_config_empty_api_key_allowed 允许真清空。
  // 折中:加个 flag,read-only 时提交特殊值 "__unchanged__",后端识别跳过。
  // 这里先实现:read-only 时提交 "__unchanged__",后端遇到这个值就保留原 api_key。
  let apiKeyToSend = cfgApiKey.value;
  if (cfgApiKey.hasAttribute('readonly')) {
    apiKeyToSend = '__unchanged__';
  }
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        model: cfgModel.value,
        api_key: apiKeyToSend,
        base_url: cfgBaseUrl.value,
      }),
    });
    if (!r.ok) throw new Error('POST /api/config failed: ' + r.status);
    cfgMsg.textContent = '配置已生效';
    closeConfigPage();
  } catch (e) {
    cfgMsg.textContent = '保存失败: ' + e.message;
    cfgMsg.classList.add('error');
  }
}

document.getElementById('config-btn').addEventListener('click', openConfigPage);
document.getElementById('config-close-btn').addEventListener('click', closeConfigPage);
document.getElementById('cfg-cancel').addEventListener('click', closeConfigPage);
document.getElementById('cfg-save').addEventListener('click', saveConfig);
document.getElementById('cfg-api-key-edit').addEventListener('click', () => {
  cfgApiKey.removeAttribute('readonly');
  cfgApiKey.value = '';
  cfgApiKey.focus();
  cfgApiKey.placeholder = '输入新 API Key';
});
```

- [ ] **Step 5: 后端处理 "__unchanged__" sentinel**

Task 3 的 `save_config_route` 需要改:api_key 为 `"__unchanged__"` 时保留原值。

修改 `src/taisang/web/app.py` 的 `save_config_route`:

```python
@app.post("/api/config")
async def save_config_route(req: ConfigReq) -> dict:
    """保存 LLM 配置 + 立即应用到所有 session。

    api_key = "__unchanged__" 时保留原 api_key(前端 readonly 提交这个 sentinel)。
    """
    if req.api_key == "__unchanged__":
        old_cfg = load_config()
        api_key = old_cfg.api_key
    else:
        api_key = req.api_key
    cfg = LLMConfig(model=req.model, api_key=api_key, base_url=req.base_url)
    save_config(cfg)
    registry.apply_llm_config(cfg)
    return {"ok": True}
```

补测试到 `tests/unit/test_web_app.py`:

```python
def test_post_config_unchanged_api_key_keeps_old(tmp_path, monkeypatch):
    """POST /api/config api_key='__unchanged__' 时保留原 api_key。"""
    monkeypatch.delenv("TAISANG_MOCK_LLM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from taisang.config import LLMConfig, save_config
    from taisang.web.app import create_app

    save_config(LLMConfig(base_url="https://api.x.com", api_key="sk-original123456789", model="m"))
    app = create_app(tmp_path)
    client = TestClient(app)
    r = client.post("/api/config", json={
        "model": "new-m",
        "api_key": "__unchanged__",
        "base_url": "https://api.new.com",
    })
    assert r.status_code == 200
    import json
    p = tmp_path / ".taisang" / "settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "sk-original123456789"  # 保留
    assert data["llm"]["model"] == "new-m"  # 改了
```

- [ ] **Step 6: 手动验证(Playwright 或浏览器)**

启动服务,打开 Web UI:
1. 点左侧"⚙ 设置"按钮 → 设置页弹出,显示当前 model/base_url + api_key 打码
2. 改 model → 保存 → 设置页关闭 → 新建会话发消息 → 用新 model
3. 重启服务 → 打开配置页 → api_key 还是原值(保留)

- [ ] **Step 7: 跑全套测试**

Run: `python -m pytest`
Expected: 全 PASS

- [ ] **Step 8: 提交**

```bash
git add src/taisang/web/static/index.html src/taisang/web/app.py tests/unit/test_web_app.py
git commit -m "feat(web): 前端配置页 — sidebar 设置按钮 + model/api_key/base_url 表单"
```

---

## Task 5: 端到端验证 + 更新 spec 状态

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-frontend-llm-config-design.md`(状态改已实施)

- [ ] **Step 1: Playwright 端到端验证**

启动服务 → Playwright 走一遍:
1. 打开配置页 → 字段正确填入
2. 改 model → 保存 → 新建会话发消息 → 确认生效
3. api_key readonly 时保存 → 原值保留
4. 点"修改"api_key → 输入新值 → 保存 → 重启验证

- [ ] **Step 2: 更新 spec 状态**

`docs/superpowers/specs/2026-09-03-frontend-llm-config-design.md` 第 3 行改:
```
**状态**: 已实施(2026-09-03)
```

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/specs/2026-09-03-frontend-llm-config-design.md
git commit -m "docs: 前端 LLM 配置页 spec 状态改已实施"
```

---

## 完工验证清单

- [ ] `python -m pytest` 全 PASS
- [ ] Playwright: 打开配置页 → 字段正确
- [ ] Playwright: 改 model 保存 → 新会话用新 model
- [ ] Playwright: api_key readonly 保存 → 原值保留
- [ ] Playwright: 重启服务 → 配置页显示文件里的值