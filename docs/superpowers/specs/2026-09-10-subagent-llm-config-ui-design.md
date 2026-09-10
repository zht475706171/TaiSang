# TaiSang 子 Agent LLM 独立配置 + 设置页改造 设计文档

> **状态**: 待实施
> **日期**: 2026-09-10
> **参考**: `src/taisang/config.py` / `src/taisang/agent_core/agent_tool.py` / `src/taisang/web/frontend/src/components/ConfigModal.vue`
> **Plan 文档**: 待写(`docs/superpowers/plans/2026-09-10-subagent-llm-config-ui.md`)

## 一句话目标

给 TaiSang 加上"子 agent 独立 LLM 配置"能力：主 agent 和子 agent 各配一套 LLM,连接测试分开,子 agent 不配则 fallback 主;同时把设置页从扁平表单改成双卡片布局,并把 API Key 输入框改造成脱敏占位 + 眼睛图标切换明文。

## 背景与现状

### 现有 LLM 配置(单套)

- `src/taisang/config.py` 的 `LLMConfig(base_url, api_key, model, debug)`,存 `~/.taisang/settings.json` 的 `llm` 字段
- `load_config()` / `save_config()` 单套读写,`mask_api_key()` 前 3 + `***` + 后 4 打码
- `agent_tool.py:45` 的 `_make_child_llm(parent_llm)` 硬复用父 LLM —— 子 agent 模型根本没法单独配
- `web/app.py` 的 `/api/config` GET/POST + `/api/config/test` 单接口
- 前端 `ConfigModal.vue` 是 520px `t-dialog`,4 个表单项挤在一起,无视觉层次

### 现有 key 控件

- `<t-input :readonly="apiKeyReadonly">` + 旁边"修改"按钮
- 后端打码 `sk-***53b6` 格式,前端直接显示打码值
- 无眼睛切换图标,无固定 `********` 占位

### 视觉风格参考

- `McpManage.vue` / `AgentManage.vue` 用 `t-card` + `page-header` + `--td-brand-color` 浅蓝系
- `assets/theme.css` 定义 IBM Plex Sans 字体 + 浅蓝 brand 色(`#3B82F6`)
- 图标库 `tdesign-icons-vue-next` 提供 `browse` / `browse-off` 眼睛图标

## 设计决策(已与用户确认)

| 决策点 | 选择 | 备注 |
|---|---|---|
| 子 agent 配置粒度 | **A. 单套子 agent 配置** | 不按 agent type 拆,所有子 agent 共用一套 |
| Fallback 逻辑 | **A. 子空时整套 fallback 主** | 子配置块整空(或 enabled=false)→ 子 agent 用主 `LLMClient` |
| 设置页形态 | **A. Dialog + 双卡片** | 保持 Sidebar ⚙️ 唤起 Dialog,改造内部布局,不改路由 |
| Key 脱敏占位 | **A. 固定 `••••` + 眼睛切换明文** | 占位不带 `sk-` 前缀,纯星号 |
| 连接测试交互 | **A. 每卡独立测试按钮 + inline 结果** | 主卡 / 子卡各自测试,无全局测试按钮;成功文案 `✅ 连接成功!延时 {ms}ms`(不显示 LLM 回复内容) |
| 子 agent 启用方式 | **顶部全局开关卡 + 条件渲染子 Agent 卡** | 开关关闭时子 Agent 卡完全不渲染;打开时子 Agent 卡出现在主 Agent 和 Debug 之间 |
| Dialog 宽度 | **520px 不变** | 跟现状一致,不扩宽 |
| 卡片竖条装饰 | **保留 6px 蓝色竖条** | 主/子卡左侧视觉标记 |
| 卡片圆角 | **8px** | 比默认 6px 略圆润,统一所有卡 |
| 顶部开关卡视觉 | **36×36 圆角图标块 + 标题 + 副标题 + 开关** | 打开态:brand 色边框 + 浅蓝外发光 + 图标块实蓝 + "已启用" pill 标签;关闭态:默认边框 + 图标块浅蓝底 |
| 开关卡文案 | **「子 Agent 独立配置」+「开启时,主子 Agent 将分别使用独立的配置」** | 正面表述,不写"关闭时..." |

## 架构设计

### 后端数据结构

`settings.json` 新增 `llm_subagent` 字段(与 `llm` 同级):

```json
{
  "llm": { "base_url": "...", "api_key": "...", "model": "...", "debug": false },
  "llm_subagent": {
    "enabled": false,
    "base_url": "",
    "api_key": "",
    "model": ""
  },
  "prompts": { ... },
  "skills": { ... }
}
```

新增 `SubAgentLLMConfig` 模型:

```python
class SubAgentLLMConfig(BaseModel):
    """子 agent LLM 配置。enabled=false 或字段空时 fallback 主 LLMConfig。"""
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
```

新增函数(沿用 `LLMConfig` 的原子写盘 + 600 权限):

- `load_subagent_config() -> SubAgentLLMConfig`
- `save_subagent_config(cfg: SubAgentLLMConfig) -> None`
- 注意:子配置无 `debug` 字段(debug 是主 agent 行为,跟 LLM endpoint 无关)

子 agent LLM 解析逻辑直接内联在 `_make_child_llm` 里(只有一个调用方,不抽 `resolve_subagent_llm` 函数,避免冗余抽象)。

### 后端 API

`web/app.py` 路由改造:

| 路由 | 改造 |
|---|---|
| `GET /api/config` | 返回 `{main: {model, base_url, api_key(masked), api_key_set, debug}, subagent: {enabled, model, base_url, api_key(masked), api_key_set}}` |
| `POST /api/config` | 请求体 `{main: {model, api_key, base_url, debug}, subagent: {enabled, model, api_key, base_url}}`,分别写 `llm` 和 `llm_subagent` 字段;`api_key="__unchanged__"` 保留原值(主/子各自独立 sentinel) |
| `POST /api/config/test` | 请求体加 `target: "main" \| "subagent"`,用对应配置构造 `LLMClient` 发 hello |

`ConfigReq` / `ConfigTestReq` Pydantic 模型重构为嵌套结构。

### 后端运行时

`agent_tool.py:_make_child_llm` 改造:

```python
def _make_child_llm(parent_llm):
    """子 agent LLM:启用且 model/base_url 完整 → 独立 LLMClient;否则 fallback parent_llm。

    api_key 允许空(本地 endpoint 如 ollama 不需要 key)。
    """
    from ..config import load_subagent_config, load_config, LLMConfig
    sub_cfg = load_subagent_config()
    if not sub_cfg.enabled:
        return parent_llm
    # model 和 base_url 必填;api_key 可空(ollama 等本地 endpoint)
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

**注意**:每次派子 agent 都 `load_subagent_config()` 读盘一次。子 agent 派遣频率低(单 session 最多几次),读盘成本可接受;好处是改配置不用重启 session 立即生效。

`session_registry.py:apply_llm_config` 改造:主配置变更时,只更新 `sess.agent.llm`(主 LLM),不动子 agent LLM(子 LLM 在 `_make_child_llm` 里 lazy 读取,下次派子 agent 自然用新配置)。

### 前端 ConfigModal.vue 重构

**结构**:

```
<t-dialog v-model:visible="visible" header="LLM 配置" width="520px">
  <!-- 顶部:子 Agent 独立配置开关卡 -->
  <div class="toggle-card" :class="{ active: subForm.enabled }">
    <div class="toggle-left">
      <div class="toggle-icon">⠿</div>  <!-- 36x36 圆角图标块 -->
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
  <t-card class="config-card" :bordered="true">
    <div class="card-title-row">
      <span class="card-accent-bar"></span>
      <span class="card-title">主 Agent</span>
      <t-tag v-if="mainKeySet" theme="success" size="small">已配置</t-tag>
    </div>
    <t-form-item label="Model">...</t-form-item>
    <t-form-item label="API Key">
      <ApiKeyInput v-model="mainForm.api_key" :set="mainKeySet" @edit="..." />
    </t-form-item>
    <t-form-item label="Base URL">...</t-form-item>
    <div class="card-test-row">
      <t-button @click="testMain">测试连接</t-button>
      <span v-if="mainTestResult" class="test-result">...</span>
    </div>
  </t-card>

  <div class="card-divider"></div>

  <!-- 子 Agent 卡(仅 subForm.enabled 时渲染,否则不出现) -->
  <t-card v-if="subForm.enabled" class="config-card">
    <div class="card-title-row">
      <span class="card-accent-bar"></span>
      <span class="card-title">子 Agent</span>
    </div>
    <t-form-item label="Model">...</t-form-item>
    <t-form-item label="API Key">
      <ApiKeyInput v-model="subForm.api_key" :set="subKeySet" @edit="..." />
    </t-form-item>
    <t-form-item label="Base URL">...</t-form-item>
    <div class="card-test-row">
      <t-button @click="testSub">测试连接</t-button>
      <span v-if="subTestResult" class="test-result">...</span>
    </div>
  </t-card>

  <div class="card-divider" v-if="subForm.enabled"></div>

  <!-- Debug 卡 -->
  <t-card class="config-card">
    <div class="debug-row">...</div>
  </t-card>

  <!-- 操作区 -->
  <div class="config-actions">
    <t-button variant="text" @click="visible = false">取消</t-button>
    <t-button theme="primary" :loading="saving" @click="handleSubmit">保存</t-button>
  </div>
</t-dialog>
```

**新增组件 `ApiKeyInput.vue`**(抽出复用,主/子卡都用):

```
<t-input
  v-model="modelValue"
  :type="visible ? 'text' : 'password'"
  :readonly="readonly"
  :placeholder="readonly ? '••••••••••••••••' : '输入新的 api_key'"
>
  <template #suffix>
    <t-icon
      :name="visible ? 'browse-off' : 'browse'"
      class="eye-icon"
      @click="visible = !visible"
    />
  </template>
</t-input>
<t-button variant="outline" size="small" @click="$emit('edit')" v-if="readonly">修改</t-button>
```

行为:
- `readonly=true` 时(已配置态):输入框显示 `••••••••` 占位(后端返回 masked 值,但前端不显示打码值,直接显示纯星号占位),眼睛图标点击切换明文/密文
- 点"修改"按钮 → `readonly=false`,清空占位,输入新 key
- `readonly=false` 时(编辑态):正常输入,眼睛图标可切换显示
- 提交时:`readonly=true` → 提交 `"__unchanged__"` sentinel;`readonly=false` → 提交明文

**视觉细节**:
- `.card-accent-bar`: `width:6px; height:18px; background:var(--td-brand-color); border-radius:2px;`
- `.card-title`: `font-size:15px; font-weight:600;`
- `.card-subtitle`: `font-size:12px; color:var(--td-text-color-placeholder);`
- 卡片圆角统一 8px(`border-radius:8px`)
- 卡间距: 卡之间用 1px 细灰分隔线(`var(--td-component-stroke)`)+ 上下 `margin:20px 0`,视觉断开;不用 `gap:16px`(那是无分隔线的紧凑排列)
- 卡内 `t-form-item label` 沿用 TDesign 默认 12px
- **顶部开关卡 `.toggle-card`**:
  - 默认态:白底 + 默认边框,`padding:16px 20px`,`border-radius:8px`,`margin-bottom:20px`
  - `.toggle-icon`: `width:36px; height:36px; background:var(--td-brand-color-1); border-radius:8px; color:var(--td-brand-color); font-size:18px;` 居中显示图标
  - `.toggle-title`: `font-size:15px; font-weight:600;`
  - `.toggle-desc`: `font-size:12px; color:var(--td-text-color-placeholder);`
  - `.active`(开关打开):`border:1px solid var(--td-brand-color); box-shadow:0 0 0 3px var(--td-brand-color-1);` 图标块变 `background:var(--td-brand-color); color:#fff;`;显示 `.enabled-pill`(浅蓝底 + 蓝字 + 圆角 10px)「已启用」标签

### 前端 api/config.ts 重构

```typescript
export interface LLMConfigSection {
  model: string
  base_url: string
  api_key: string  // masked
  api_key_set: boolean
  debug?: boolean  // 仅 main
}

export interface SubAgentConfigSection {
  enabled: boolean
  model: string
  base_url: string
  api_key: string  // masked
  api_key_set: boolean
}

export function getConfig(): Promise<{ main: LLMConfigSection; subagent: SubAgentConfigSection }>
export function saveConfig(payload: { main: {...}; subagent: {...} }): Promise<{ ok: boolean }>
export function testConfig(target: 'main' | 'subagent', model: string, api_key: string, base_url: string): Promise<ConfigTestResult>
```

## 错误处理

- 子 agent 配置 `enabled=true` 但 `model` 或 `base_url` 空:`_make_child_llm` 静默 fallback 主 LLM,不报错(用户可能正在填,还没保存就派了子 agent)
- 前端保存时校验:子卡 `enabled=true` 但 `model/base_url` 空 → 报错"启用独立配置后,model 和 base_url 不能为空";`api_key` 空允许(本地 endpoint 如 ollama 不需要 key)
- 连接测试失败:沿用现状 `{ok: false, error: str}`,inline 显示 ❌ + 错误信息
- 连接测试成功:前端 inline 文案 `✅ 连接成功!延时 {latency_ms}ms`,**不显示 LLM 回复内容**(后端 `/api/config/test` 仍返回 `reply` 字段供 debug,但前端不渲染)

## 测试策略

### 后端单元测试(`tests/unit/`)

- `test_config.py` 新增:
  - `test_load_subagent_config_default`(默认 enabled=false,字段空)
  - `test_save_subagent_config_writes_field`(写 `llm_subagent` 字段,保留 `llm` 和其他字段)
  - `test_save_subagent_config_preserves_other_fields`(写 `llm_subagent` 保留 `llm` / `prompts` / `skills` 等)
- `test_web_app.py` 新增:
  - `test_get_config_returns_main_and_subagent`(GET 返回双块结构)
  - `test_post_config_saves_both_sections`(POST 同时写主/子)
  - `test_post_config_unchanged_sentinel_per_section`(主 `__unchanged__` 不动主 key,子 `__unchanged__` 不动子 key)
  - `test_post_config_test_target_main` / `test_post_config_test_target_subagent`
  - `test_post_config_test_target_subagent_fallback_when_empty`(target=subagent 但子配置空 → 用主配置测,或返回错误,二选一,见"歧义问题")
- `test_agent_tool.py` 新增:
  - `test_child_llm_uses_subagent_when_enabled`(_make_child_llm 返回独立 LLMClient,与 parent_llm 不同实例)
  - `test_child_llm_fallback_parent_when_disabled`(enabled=false → parent_llm)
  - `test_child_llm_fallback_parent_when_model_empty`(enabled=true 但 model 空 → parent_llm)
  - `test_child_llm_fallback_parent_when_base_url_empty`(enabled=true 但 base_url 空 → parent_llm)
  - `test_child_llm_allows_empty_api_key`(enabled=true + model/base_url 填 + api_key 空 → 返回独立 LLMClient,api_key 为空字符串)

### 前端

- 不新增端到端测试(`playwright` 跑截图风险高,沿用项目现状只跑 unit + integration)
- `vue-tsc --noEmit` 类型检查必须通过

## 现有测试兼容性

- `test_web_app.py:291-512` 现有 `/api/config` 测试需更新:GET 返回结构从扁平改双块,POST 请求体从扁平改嵌套
- `test_agent_tool.py` 现有 monkeypatch `_make_child_llm` 的测试不受影响(测试里仍直接替换函数,不依赖配置文件)
- `test_config.py` 现有 `LLMConfig` 测试全部保留,不动

## 范围外(YAGNI)

- **按 agent type 各配一套**(B 方案):4 个内置 agent 共用一套子配置,未来有需求再拆
- **Provider preset 下拉**(DeepSeek/Kimi/GLM 预置):用户手填 base_url 即可,不做预设
- **子 agent debug 字段**:debug 是主 agent 行为,子 agent 跟主共用
- **设置页独立路由 `/settings`**:Dialog 形态已够用,不增加路由复杂度
- **全局"测试连接(全部)"按钮**:每卡独立测试已够
- **暗色主题适配**:沿用项目现状(后续计划里有"暗色主题",本设计不动)
- **key 强度校验**:不校验 key 格式,任意非空字符串接受

## 已决歧义

**`POST /api/config/test` target=subagent 但子配置字段空时怎么处理?**

采用 **A + C 组合**:
- 后端(target=subagent 但 model/base_url 空)→ 返回 `{ok: false, error: "子 agent 配置未填写完整"}`
- 前端子卡测试按钮在 `model/base_url` 空时 `disabled`,交互层防呆
- 后端仍校验(防御性,不信任前端)