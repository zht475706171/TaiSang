# MCP 三种快速添加方式 设计

> **Date:** 2026-09-07
> **Status:** Approved → 待实施
> **Goal:** 给 McpManage 页加三种快速添加 MCP server 的方式(CLI / 粘贴 JSON / 上传文件),保留现有表单,每种方式展示使用示例。

---

## 1. 范围

### 包含
- **CLI 一行式添加**(单条):claude-code CLI 风格语法,前端单行 textarea
- **粘贴 JSON 配置**(批量):claude-code `.mcp.json` 格式 + TaiSang 扩展格式
- **上传 `.mcp.json` 文件**(批量):file picker 选文件,后端解析
- 同名 server 覆盖语义(批量逐个独立)
- Dialog 内 Tab 切换四种方式(三种快路 + 现有表单)
- 每种快路 Tab 顶部展示只读使用示例

### 不做
- `--env KEY=VALUE` CLI flag(v2)
- CLI 里指定 `headers`(JSON 格式可写,CLI 不行)
- 拖拽上传文件(只用 file picker)
- 导入预览(直接覆盖,不先展示 diff)
- CLI 批量(单条;批量走 JSON / 文件)

---

## 2. CLI 语法(纯 claude-code 风格)

### stdio
```
filesystem npx -y @modelcontextprotocol/server-filesystem /tmp
```
解析:
- `name = filesystem`
- `command = npx`
- `args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]`
- `transport = stdio`(默认)

### SSE
```
search --transport sse https://example.com/sse
```
解析:
- `name = search`
- `transport = sse`
- `url = https://example.com/sse`

### 解析规则
1. 第一 token = `name`(必须,非空,符合 `^[A-Za-z0-9][A-Za-z0-9_-]*$`)
2. 扫描 `--transport <value>` flag:`value` 只接受 `stdio`/`sse`,其他 → `McpParseError`
   - 未指定 `--transport` → 默认 `stdio`
3. stdio:剩余 token 第一个是 `command`(必须),其余是 `args`
4. sse:剩余 token 必须恰好一个 → `url`;零个或多个 → `McpParseError`
5. 空行 / 只有空白 → `McpParseError`
6. 不支持 `--env`、不支持 `--header`(v2 再说)

### 异常
- `McpParseError`:语法层(name 缺失、transport 非法、token 数不对)
- `McpValidationError`:字段层(name 不符合字符集、url 不是 URL 形态)

---

## 3. JSON 格式(双格式兼容)

### claude-code 格式(顶层 `mcpServers`,默认 stdio)
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {"NODE_ENV": "production"}
    },
    "search": {
      "url": "https://example.com/sse"
    }
  }
}
```
- 顶层 `mcpServers` 是 object,key 作 `name`
- 值对象没 `transport` 字段:
  - 有 `url` → 自动判 `sse`
  - 没 `url` → 默认 `stdio`
- `command`/`args`/`env` 透传

### TaiSang 扩展格式
**单对象**:
```json
{
  "name": "search",
  "transport": "sse",
  "url": "https://example.com/sse",
  "headers": {"Authorization": "Bearer xxx"}
}
```

**数组(包 `servers` key)**:
```json
{
  "servers": [
    {"name": "fs", "transport": "stdio", "command": "npx", "args": ["-y", "srv"]},
    {"name": "search", "transport": "sse", "url": "https://example.com/sse"}
  ]
}
```

**裸数组**:
```json
[
  {"name": "fs", "transport": "stdio", "command": "npx"}
]
```

### 解析规则
1. 顶层是 dict 且含 `mcpServers` → claude-code 格式
2. 顶层是 dict 且含 `servers` → TaiSang 数组,取 `servers` 的 list
3. 顶层是 list → TaiSang 裸数组
4. 顶层是 dict 且含 `name` → TaiSang 单对象,包成 `[obj]`
5. 其他 → `McpParseError`

每个 `McpServerConfig` 走 `McpServerConfig(**data)` 校验(复用现有 pydantic model),失败 → `McpValidationError`。

---

## 4. 上传文件

- 前端 `<input type="file" accept=".json,.mcp.json">`
- 读文件为 text,走和"粘贴 JSON"完全相同的后端解析路径
- 文件大小上限 1MB(防误传大文件,超限 → 413)
- 文件名不强制要求 `.mcp.json`,`.json` 也接受
- 上传后不持久化原文件,只解析后入 `mcp_servers.json` 状态文件(已有机制)

---

## 5. 同名冲突处理

泰哥定:**覆盖重名**。

### 单条(CLI)
- 已存在 → `update_server`(断开旧连接 + 写新配置 + 重连)
- 不存在 → `add_server` + 连接

### 批量(JSON / 文件)
逐个执行,每个独立 try/except:
- 已存在 → `update_server` + reconnect
- 不存在 → `add_server` + connect
- 失败 → 记入 `failed`,继续下一个

返回:
```json
{
  "added": ["fs", "github"],
  "updated": ["search"],
  "failed": [
    {"name": "bad", "error": "invalid transport: foo"}
  ]
}
```

前端展示汇总(成功多少 / 失败哪些)。

---

## 6. 后端设计

### 新文件 `src/taisang/mcp/importer.py`

纯解析层,无副作用,纯函数。

```python
class McpImportError(Exception): ...
class McpParseError(McpImportError): ...   # 语法层
class McpValidationError(McpImportError): ...  # 字段层

def parse_cli(line: str) -> McpServerConfig:
    """解析单行 CLI 语法 → 一个 config。"""

def parse_json(text: str) -> list[McpServerConfig]:
    """解析 JSON 文本 → config 列表(支持四种格式)。"""

def parse_mcp_json_file(content: bytes, max_size: int = 1_000_000) -> list[McpServerConfig]:
    """解析上传文件 → config 列表(超限抛 McpImportError)。"""
```

### `src/taisang/web/mcp_api.py` 加两个路由

**决策:前端传 raw text,后端统一解析。** 理由:
- CLI 语法解析放后端,前端只传原始字符串
- JSON 也传原始 text,后端 `parse_json` 处理
- 上传文件:前端读文件为 text,POST 同 `import` 路由

拆两个路由(REST 语义清晰):

**`POST /api/mcp/servers/import-cli`**(单条)
- Body: `{"line": "filesystem npx -y @mcp/fs /tmp"}`
- 流程:`parse_cli(line)` → 同名覆盖(add 或 update) → connect → 返回 `McpServerInfo`
- 异常映射:
  - `McpParseError` / `McpValidationError` → 422
  - 其他 → 500

**`POST /api/mcp/servers/import`**(批量,JSON 粘贴 + 文件上传共用)
- Body: `{"text": "<JSON 文本>"}`
- 流程:
  1. `parse_json(text)` → `list[McpServerConfig]`(语法错误直接 422)
  2. 逐个处理:
     - 已存在 → `update_server` + `reconnect_server`
     - 不存在 → `add_server` + `connect_server`
     - 失败记入 `failed`,继续下一个
  3. 返回 `{added, updated, failed}`
- 文件上传场景:前端读文件为 text → POST 同一路由

### 现有路由不动
- `POST /api/mcp/servers`(表单单条)保留
- `PUT /api/mcp/servers/{name}` 保留

---

## 7. 前端设计

### McpManage.vue Dialog 改 4 Tab

```
┌─添加服务器──────────────────────┐
│ [手动填写] [CLI] [粘贴JSON] [上传文件] │
│──────────────────────────────────│
│ (Tab 内容)                       │
│                                  │
│ [添加]   [取消]                   │
└──────────────────────────────────┘
```

**Tab 1 手动填写**(现有表单,不动):
- 名称 / 传输方式 / command / args / url

**Tab 2 CLI**(新增):
- 顶部只读示例代码块:
  ```
  # stdio
  filesystem npx -y @modelcontextprotocol/server-filesystem /tmp

  # sse
  search --transport sse https://example.com/sse
  ```
- 单行 textarea(实际用 textarea 便于复制)
- 提交 → `POST /api/mcp/servers/import-cli`

**Tab 3 粘贴 JSON**(新增):
- 顶部只读示例代码块:
  ```json
  // claude-code 格式
  {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
      }
    }
  }

  // TaiSang 扩展(可含 SSE)
  {
    "servers": [
      {"name": "search", "transport": "sse", "url": "https://example.com/sse"}
    ]
  }
  ```
- JSON textarea
- 提交 → `POST /api/mcp/servers/import` body `{text}`

**Tab 4 上传文件**(新增):
- 顶部只读示例代码块(说明 + 一个 `.mcp.json` 样例)
- `<input type="file" accept=".json,.mcp.json">`
- 选完文件 → 读为 text 存进 reactive state → 用户点 Dialog 底部"添加"才提交(和其他 Tab 一致)

### 前端 API 层(`api/mcp.ts`)
新增:
```typescript
export function importCli(line: string): Promise<McpServerInfo>
export function importBatch(text: string): Promise<{added: string[], updated: string[], failed: {name: string, error: string}[]}>
```

### Pinia store
`stores/mcp.ts` 新增:
- `importCli(line)` → 调 API + `fetchServers()`
- `importBatch(text)` → 调 API + `fetchServers()` + 返回汇总

---

## 8. 测试

### `tests/unit/test_mcp_importer.py`(新)
- CLI 解析:
  - stdio 标准
  - sse 标准
  - 缺 name → `McpParseError`
  - `--transport foo` 非法 → `McpParseError`
  - sse 多 token → `McpParseError`
  - stdio 无 command → `McpParseError`
  - 空 line → `McpParseError`
  - name 含非法字符 → `McpValidationError`
- JSON 解析:
  - claude-code 格式 stdio
  - claude-code 格式 有 url 自动判 sse
  - TaiSang 单对象
  - TaiSang `{servers: [...]}` 数组
  - TaiSang 裸数组
  - 混合格式不认 → `McpParseError`
  - 缺 name 字段 → `McpValidationError`
  - 非法 JSON → `McpParseError`
- 文件解析:
  - 超限 → `McpImportError`
  - 非 UTF-8 → `McpParseError`

### `tests/unit/test_mcp_api.py` 扩展
- `import-cli` 路由:
  - stdio 成功 → 返回 `McpServerInfo`
  - sse 成功
  - 同名覆盖(已有 fs,新配置覆盖,status 仍 connected)
  - 解析失败 → 422
- `import` 路由:
  - 批量新增(全部新)→ `added=[...]`, `updated=[]`, `failed=[]`
  - 批量覆盖(部分已有)→ `updated` 有名字
  - 部分失败(其中一个 config 字段非法)→ `failed` 有,其他成功的不受影响
  - 语法错误(整个 JSON parse 失败)→ 422

### e2e
不动(可选,如果加,验证:粘贴 JSON → 列表刷新 + 汇总 toast)。

---

## 9. 实施顺序

1. **Task 1**: `mcp/importer.py` + `test_mcp_importer.py`(纯解析层,TDD)
2. **Task 2**: `mcp_api.py` 加 `import-cli` 路由 + 测试
3. **Task 3**: `mcp_api.py` 加 `import` 批量路由 + 测试
4. **Task 4**: 前端 `api/mcp.ts` + `stores/mcp.ts` 加 importCli / importBatch
5. **Task 5**: `McpManage.vue` 改 4 Tab Dialog,加三种快路 UI + 示例展示
6. **Task 6**: 前端构建 + 端到端验证

每个 Task TDD(先红后绿)+ 单独 commit。

---

## 10. 决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| CLI 语法 | 纯 claude-code CLI 风格 | 用户熟悉,迁移成本低 |
| UI 布局 | Dialog 内 Tab | 和现有 Dialog 风格一致,改动小 |
| JSON 格式 | claude-code + TaiSang 扩展兼容 | 兼容性最好 |
| 批量 | CLI 单个,JSON/上传批量 | CLI 定位"最快加一个",JSON/上传为"批量导入" |
| 同名冲突 | 覆盖重名 | 用户定 |
| SSE 语法 | 照搬 `--transport sse URL` | 和 claude-code 一致 |
| 解析层位置 | 后端 | 逻辑集中,测试好写,前后端共享 |
| 上传文件大小 | 1MB | 防误传大文件 |

---

## 11. 风险与边界

- **CLI 解析器和 claude-code 真实 CLI 不完全一致**:claude-code 还支持 `--scope`、`--env` 等 flag,我们只认 `--transport`。文档里标注"简化版"。
- **claude-code 格式里的 `env` 字段**:透传,不校验 key/value 格式。
- **覆盖重名会断开旧连接**:可能正在被 agent 使用的 server 断开会有副作用,但这是用户主动操作,可接受。
- **JSON 批量部分失败不回滚**:已成功的 stays,失败的进 `failed`。用户看汇总决定是否重试。