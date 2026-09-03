# 前端 LLM 配置页设计

**日期**: 2026-09-03
**状态**: 已实施(2026-09-03) — Playwright e2e 验证通过
**作者**: 泰哥 + Claude

## 背景

当前 LLM 配置只能通过 `~/.taisang/settings.json` 文件或环境变量改,前端无法配置。用户每次换 model/api_key/base_url 要手改文件 + 重启服务,体验差。

**现状**:
- `config.py` `load_config()` 优先级:env > `~/.taisang/settings.json` > 默认
- `LLMClient` 构造时拿 `LLMConfig` 建 `OpenAI` SDK client,model 固定在实例
- `SessionRegistry._make_llm()` 每次 build session 调 `load_config()`,每个 session 有独立 LLMClient 实例
- CLI 也用同一套 config

## 目标

- 前端 sidebar 底部"设置"按钮 → 独立设置页,三个字段(model / api_key / base_url)
- 保存后立即生效(所有 session 的 LLMClient 重建)
- api_key 打码显示,防截图泄露
- CLI 不动,共享同一份 `~/.taisang/settings.json`
- 零新依赖

## 决策汇总

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | 配置作用域 | 全局唯一(所有 session 共享) | 对齐 Claude Code / ChatGPT,简单 |
| 2 | 生效方式 | 立即重建所有 session 的 LLMClient | 用户期望改完立刻生效 |
| 3 | 配置存储 | 复用 `~/.taisang/settings.json` | 零迁移成本,跟 CLI 共享 |
| 4 | UI 入口 | sidebar 底部"设置"按钮 → 独立页 | 表单空间大,不挤占顶栏 |
| 5 | api_key 显示 | GET 打码(`sk-***4321`),POST 存真 | 防截图泄露 |
| 6 | CLI 兼容 | CLI 不动,共享同一份文件 | 零改动 |
| 7 | env 优先级 | 前端写入后完全以文件为准 | 前端是真相源,env 仅首次 fallback |

## 持久化范围

**存**(`~/.taisang/settings.json` 的 `llm` 字段,跟现有格式一致):
- `base_url`: string
- `api_key`: string(完整明文,文件权限 600)
- `model`: string

**不存**:env 变量(env 仅在文件不存在/字段缺失时作 fallback,一旦前端写过文件就以文件为准)。

## 组件架构

### 现有组件改造

**`config.py`**

改造点:
1. `load_config()` 改优先级:**文件 > env > 默认**(原 env > 文件 > 默认)。env 仅在文件字段缺失时 fallback。理由:前端写入后文件是真相源,env 不该 override 前端改的值。
2. 新增 `save_config(cfg: LLMConfig) -> None`:原子写 `~/.taisang/settings.json`。读现有文件(若有)→ 合并 `llm` 字段(保留其它字段)→ tmp 文件 + `os.replace` 原子替换。文件权限 600(`os.chmod`)。

```python
def save_config(cfg: LLMConfig) -> None:
    """原子写 ~/.taisang/settings.json 的 llm 字段。保留其它字段。"""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings_file()
    existing["llm"] = cfg.model_dump()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def mask_api_key(key: str) -> str:
    """api_key 打码:前 3 + *** + 后 4,短于 8 字符全 ***。"""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"
```

**`SessionRegistry`**

改造点:加 `apply_llm_config(cfg: LLMConfig) -> None`。

```python
def apply_llm_config(self, cfg: LLMConfig) -> None:
    """所有内存 session 的 LLMClient 用新 cfg 重建。立即生效。
    
    遍历 _sessions,每个 sess.agent.llm 替换成新 LLMClient。
    加 self._lock 防跟 _build_session / list_all race。
    正在跑的 run 持有 sess.lock,run 内部用旧 llm 跑完当前 LLM 调用;
    下一次 LLM 调用(同 run 循环里)用新 llm —— 这是可接受的边界(model 中途切换)。
    """
    with self._lock:
        sessions = list(self._sessions.values())
    for sess in sessions:
        # 保留 MockLLM 场景(env TAISANG_MOCK_LLM=1):不替换
        if isinstance(sess.agent.llm, MockLLM):
            continue
        sess.agent.llm = LLMClient(cfg)
```

**注意**:
- MockLLM 不替换(测试场景)
- 不给每个 session 加锁等当前 run 结束(会让 API 调用阻塞,且用户期望立即生效)。接受"正在跑的对话下一步 LLM 调用切 model"的边界。
- `_make_llm` 逻辑不变(仍 `load_config()` 读文件),新建 session 自动用新配置。

**`app.py`**

新增 2 个路由:

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

**前端 `index.html`**

改造点:
1. sidebar 底部加"⚙ 设置"按钮(在 `#session-list` 下面,sidebar flex 底部)
2. 新增设置页 `<div id="config-page" class="hidden">`,覆盖 `#main` 区或独立 overlay
   - 三个输入框:model / api_key / base_url
   - api_key 旁有"修改"按钮(点击才可编辑,默认 readonly 显示打码值)
   - 保存 / 取消按钮
3. JS:
   - `openConfigPage()`:GET /api/config → 填表单 → 显示设置页
   - `saveConfig()`:POST /api/config → 成功后隐藏设置页
   - `cancelConfig()`:隐藏设置页
   - api_key "修改"按钮:点 `#api-key-input` removeAttribute('readonly')

### 配置页 UI 草图

```
┌──────────────────────────────────────┐
│  ⚙ LLM 配置                          │
├──────────────────────────────────────┤
│  Model                               │
│  [gpt-4o                    ]        │
│                                      │
│  API Key                             │
│  [sk-***4321          ] [修改]       │
│                                      │
│  Base URL                            │
│  [https://api.openai.com/v1]         │
│                                      │
│         [取消]  [保存]               │
└──────────────────────────────────────┘
```

## 数据流

### 读(打开配置页)

```
用户点"设置" → openConfigPage()
  → GET /api/config
    → load_config() 读 ~/.taisang/settings.json
    → 返回 {model, base_url, api_key: 打码, api_key_set}
  → 填表单(api_key readonly 显示打码值)
  → 显示设置页
```

### 写(保存配置)

```
用户改字段 → 点"保存"
  → POST /api/config {model, api_key, base_url}
    → save_config(LLMConfig(...))
      → 读现有 settings.json(若有)
      → 合并 llm 字段
      → tmp + os.replace 原子写(权限 600)
    → registry.apply_llm_config(cfg)
      → 遍历 _sessions,替换每个 agent.llm(MockLLM 跳过)
  → 返回 {ok: true}
  → 前端隐藏设置页 + 顶栏闪"配置已生效"
```

## 错误处理 + 边界

1. **settings.json 损坏**:`load_config` try/except,损坏时当文件不存在,用 env/默认。
2. **save_config 写失败**(磁盘满/权限):抛异常,API 返回 500,前端显示错误。
3. **api_key 为空**:允许保存(有些本地 endpoint 如 ollama 不需要 key)。
4. **apply_llm_config 时 session 正在跑**:不阻塞,替换 `sess.agent.llm` 引用。当前 LLM 调用已进 SDK 用旧 client,下次调用用新。可接受。
5. **MockLLM 场景**:`apply_llm_config` 跳过 MockLLM 实例(测试场景)。
6. **并发写**:只有一个 web 进程,`save_config` 原子替换,无并发写。多进程部署不在本次范围。

## 测试策略

### 单元测试

**`test_config.py`**(新建或补):
- `save_config` 原子写 + 权限 600
- `save_config` 保留其它字段(只改 llm)
- `load_config` 文件 > env > 默认(改后的优先级)
- `mask_api_key` 短于 8 字符全 ***,正常情况前3+***+后4

**`test_web_app.py`**(补):
- GET /api/config 返回打码 api_key
- POST /api/config 写文件 + apply 到所有 session
- POST /api/config 空 api_key 允许保存
- apply_llm_config 替换所有非 MockLLM 的 agent.llm

### 集成测试

- 改配置 → 新建 session 用新 model
- 改配置 → 已存在 session 的 agent.llm 被替换

## 实施顺序

1. `config.py` 加 `save_config` + `mask_api_key` + 改 `load_config` 优先级 + 单测
2. `SessionRegistry.apply_llm_config` + 单测
3. `app.py` 加 GET/POST /api/config 路由 + 测试
4. 前端 sidebar 设置按钮 + 设置页 + JS 逻辑
5. 端到端验证(Playwright)

## 不做(YAGNI)

- **多 profile**:不支持保存多套配置切换。一个全局配置够用。
- **配置导入导出**:YAGNI。
- **连接测试按钮**:配置页加"测试连接"按钮调一次 LLM 验证。可做但非必需,留扩展点。
- **加密存储 api_key**:文件权限 600 + 打码显示已够。企业级加密不在范围。
- **per-session 配置**:决策 1 已选全局唯一。

## 未来扩展点

- "测试连接"按钮
- 多 profile(本地/远程/不同 model)
- 配置变更历史