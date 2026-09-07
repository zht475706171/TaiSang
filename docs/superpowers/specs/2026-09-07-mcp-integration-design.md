# TaiSang MCP 接入设计文档

> **状态**: 待实施
> **日期**: 2026-09-07
> **参考**: claude-code MCP 实现 (`D:/GoProject/claude-code/src/services/mcp/`)

## 一句话目标

给 TaiSang agent 加上 MCP 客户端能力：通过 UI 配置任意 MCP server（stdio/SSE），连接后自动拉取 server 暴露的 Tools/Resources/Prompts，动态注入 agent 工具列表，LLM 像调本地工具一样调远程能力。

## 背景知识

### MCP 协议简述

MCP（Model Context Protocol）是 LLM agent 调用外部服务的标准协议。一个 MCP server 暴露三类能力：

| 类型 | 说明 | 示例 |
|------|------|------|
| **Tools** | LLM 可调用的函数 | `search_web(query)`, `execute_sql(query)` |
| **Resources** | LLM 可读取的数据源 | `file:///docs/api.md`, `db://schema` |
| **Prompts** | 预设 prompt 模板 | `review_code`, `generate_tests` |

### 连接流程

```
1. 启动连接（stdio 子进程 / SSE HTTP）
2. 握手 + 能力协商（initialize → capabilities）
3. 拉取能力列表（tools/list, resources/list, prompts/list）
4. 动态注入 agent 工具列表
5. LLM 通过 registry.call() 统一分发，不区分本地/MCP
```

### 传输方式

| 传输 | 说明 | 适用场景 |
|------|------|----------|
| **stdio** | 子进程 stdio 通信 | 本地 MCP server（文件系统、git、数据库 CLI） |
| **SSE** | HTTP Server-Sent Events | 远程 MCP server（搜索 API、翻译服务） |

## 范围

### v1 包含

- **传输**: stdio + SSE
- **能力**: Tools + Resources + Prompts 全支持
- **工具注入**: MCP 工具注册到 ToolRegistry，名称格式 `mcp__<server>__<tool>`
- **Resources**: 通过 `mcp_resource(server, uri)` 伪工具读取
- **Prompts**: 通过 `mcp_prompt(server, name)` 伪工具注入 prompt 到对话
- **UI 管理**: 增删查改 + 启用/禁用 + 重连 + 连接状态显示
- **持久化**: 配置保存到 `~/.taisang/mcp_servers.json`
- **连接生命周期**: 启动时自动连接、断线标记失败、手动重连

### v1 不做（延后）

- OAuth 认证流（needs-auth 状态）
- WebSocket 传输
- HTTP Streamable 传输
- MCP server 发现/市场
- 企业策略/插件源
- 并发连接池（串行连接即可）

## 架构

### 模块划分

```
src/taisang/mcp/
├── __init__.py        # 包导出
├── types.py           # 数据模型（McpServerConfig, McpToolInfo, McpResourceInfo, McpPromptInfo）
├── client.py          # MCP 客户端核心（连接管理、传输层、能力拉取、tool_call）
├── tool.py            # MCPTool 类（注册到 ToolRegistry）
├── manager.py         # MCPManager（配置 CRUD、连接生命周期、状态管理）
└── errors.py          # 异常体系

src/taisang/web/
├── mcp_api.py         # FastAPI 路由（增删查改、启用/禁用、重连）
└── (session_registry.py 修改)  # _build_session 时传 MCP tools

frontend/src/
├── views/McpManage.vue    # MCP 管理页
├── stores/mcp.ts          # MCP 状态 store
└── components/Sidebar.vue # 修改 MCP 管理入口点击逻辑
```

### 数据流

```
┌─────────────────────────────────────────────┐
│  McpManage.vue (UI)                          │
│  增删查改 + 启用/禁用 + 重连 + 状态显示          │
└──────────────┬──────────────────────────────┘
               │ REST API
┌──────────────▼──────────────────────────────┐
│  MCPManager (核心)                            │
│  - 管理 server 配置 (内存 + mcp_servers.json)  │
│  - 维护 server 连接 (stdio/SSE)               │
│  - 拉取 tools/resources/prompts              │
│  - 提供 call_tool 接口                        │
└──────────────┬──────────────────────────────┘
               │ 注册动态工具
┌──────────────▼──────────────────────────────┐
│  ToolRegistry                                │
│  mcp__<server>__<tool> → MCPTool 实例        │
│  mcp_resource → McpResourceTool              │
│  mcp_prompt → McpPromptTool                  │
└──────────────┬──────────────────────────────┘
               │ agent 主循环
┌──────────────▼──────────────────────────────┐
│  AgentService                                │
│  LLM 调 tool → registry.call() → MCP 执行    │
└─────────────────────────────────────────────┘
```

## 数据模型

### `McpServerConfig` — server 配置

```python
class McpServerConfig(BaseModel):
    name: str                                    # 唯一标识
    transport: Literal["stdio", "sse"]           # 传输方式
    enabled: bool = True                         # 是否启用
    # stdio 配置
    command: str | None = None                   # 可执行文件路径
    args: list[str] = []                         # 命令行参数
    env: dict[str, str] = {}                     # 环境变量
    # sse 配置
    url: str | None = None                       # SSE 端点 URL
    headers: dict[str, str] = {}                 # 自定义请求头
```

### `McpServerInfo` — server 运行时信息

```python
class McpToolInfo(BaseModel):
    name: str                # 原始工具名（不带 mcp__ 前缀）
    description: str
    input_schema: dict       # JSON Schema

class McpResourceInfo(BaseModel):
    uri: str                 # 资源 URI
    name: str                # 资源名称
    description: str
    mime_type: str | None

class McpPromptInfo(BaseModel):
    name: str                # prompt 名称
    description: str
    arguments: list[dict]    # 参数 schema

class McpServerInfo(BaseModel):
    name: str
    status: Literal["connected", "disconnected", "failed", "disabled"]
    error: str | None = None
    tools: list[McpToolInfo] = []
    resources: list[McpResourceInfo] = []
    prompts: list[McpPromptInfo] = []
```

### 持久化格式 (`~/.taisang/mcp_servers.json`)

```json
{
  "servers": {
    "filesystem": {
      "name": "filesystem",
      "transport": "stdio",
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/root"],
      "env": {},
      "url": null,
      "headers": {}
    },
    "search": {
      "name": "search",
      "transport": "sse",
      "enabled": true,
      "command": null,
      "args": [],
      "env": {},
      "url": "https://api.example.com/sse",
      "headers": {}
    }
  }
}
```

## 核心组件设计

### 1. `MCPClient` — 连接与能力拉取 (`mcp/client.py`)

职责：
- 根据配置创建对应传输（`StdioClientTransport` / `SSEClientTransport`）
- 执行 `client.connect(transport)` 握手
- 提供 `list_tools()` / `list_resources()` / `list_prompts()` 拉取能力
- 提供 `call_tool(name, args)` 调用远程工具
- 提供 `read_resource(uri)` 读取资源
- 提供 `get_prompt(name, args)` 获取 prompt 内容

```python
class MCPClient:
    """单个 MCP server 的客户端封装。"""

    def __init__(self, config: McpServerConfig): ...

    async def connect(self) -> None:
        """建立连接，握手协商能力。"""

    async def disconnect(self) -> None:
        """关闭连接。"""

    async def list_tools(self) -> list[McpToolInfo]: ...

    async def list_resources(self) -> list[McpResourceInfo]: ...

    async def list_prompts(self) -> list[McpPromptInfo]: ...

    async def call_tool(self, name: str, args: dict) -> str:
        """调用工具，返回结果文本。"""

    async def read_resource(self, uri: str) -> str:
        """读取资源内容。"""

    async def get_prompt(self, name: str, args: dict | None = None) -> str:
        """获取 prompt 模板内容。"""

    @property
    def is_connected(self) -> bool: ...
```

### 2. `MCPManager` — 管理器 (`mcp/manager.py`)

职责：
- 管理所有 server 配置（CRUD）
- 维护所有 server 连接（`dict[str, MCPClient]`）
- 启动时自动连接所有 enabled 的 server
- 提供统一的 tool/resource/prompt 查询接口
- 持久化配置到 `~/.taisang/mcp_servers.json`
- 汇总所有 server 状态

```python
class MCPManager:
    """MCP 服务器管理器（单例）。"""

    def __init__(self, state_path: Path | None = None): ...

    # 配置 CRUD
    def add_server(self, config: McpServerConfig) -> None: ...
    def remove_server(self, name: str) -> None: ...
    def update_server(self, name: str, config: McpServerConfig) -> None: ...
    def get_server(self, name: str) -> McpServerConfig | None: ...
    def list_servers(self) -> list[McpServerConfig]: ...

    # 连接管理
    async def connect_server(self, name: str) -> None: ...
    async def disconnect_server(self, name: str) -> None: ...
    async def reconnect_server(self, name: str) -> None: ...
    async def connect_all(self) -> None: ...

    # 状态查询
    def get_server_info(self, name: str) -> McpServerInfo: ...
    def list_server_info(self) -> list[McpServerInfo]: ...

    # 工具/资源/ prompt 操作
    async def call_tool(self, server_name: str, tool_name: str, args: dict) -> str: ...
    async def read_resource(self, server_name: str, uri: str) -> str: ...
    async def get_prompt(self, server_name: str, prompt_name: str, args: dict | None = None) -> str: ...

    # 启用/禁用
    def set_enabled(self, name: str, enabled: bool) -> None: ...

    # 汇总（给 ToolRegistry 用）
    def get_all_mcp_tools(self) -> list[dict]: ...  # [{server, tool, client}, ...]
    def get_all_mcp_resources(self) -> list[dict]: ...
    def get_all_mcp_prompts(self) -> list[dict]: ...
```

### 3. `MCPTool` — 动态工具 (`mcp/tool.py`)

职责：
- 每个 MCP 工具对应一个 `MCPTool` 实例
- 注册到 ToolRegistry，名称 `mcp__<server>__<tool>`
- `run()` 调用 `MCPManager.call_tool()` 执行

```python
class MCPTool(_BaseTool):
    """单个 MCP 工具的封装。"""

    def __init__(self, server_name: str, tool_info: McpToolInfo, manager: MCPManager): ...

    @property
    def name(self) -> str:
        return f"mcp__{self.server_name}__{self.tool_info.name}"

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.tool_info.description,
            "parameters": self.tool_info.input_schema,
        }

    def run(self, args: dict) -> dict:
        # 同步包装异步调用
        result = asyncio.run(self.manager.call_tool(self.server_name, self.tool_info.name, args))
        return {"content": result, "error": None}
```

### 4. `McpResourceTool` / `McpPromptTool` — 伪工具

不注册为独立工具，而是在 SYSTEM_PROMPT 里注入可用资源/prompt 列表，LLM 通过特殊工具调用：

```python
class McpResourceTool(_BaseTool):
    """读取 MCP 资源。LLM 调 mcp_resource(server, uri) 读取。"""
    name = "mcp_resource"

    def schema(self) -> dict:
        return {
            "name": "mcp_resource",
            "description": "读取 MCP server 暴露的资源。参数: server(服务器名), uri(资源URI)",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务器名"},
                    "uri": {"type": "string", "description": "资源 URI"},
                },
                "required": ["server", "uri"],
            },
        }

    def run(self, args: dict) -> dict:
        server = args.get("server", "")
        uri = args.get("uri", "")
        result = asyncio.run(self.manager.read_resource(server, uri))
        return {"content": result, "error": None}


class McpPromptTool(_BaseTool):
    """获取 MCP prompt 模板。LLM 调 mcp_prompt(server, name) 获取。"""
    name = "mcp_prompt"

    def schema(self) -> dict:
        return {
            "name": "mcp_prompt",
            "description": "获取 MCP server 的 prompt 模板。参数: server(服务器名), name(prompt名), args(可选参数)",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务器名"},
                    "name": {"type": "string", "description": "prompt 名称"},
                    "args": {"type": "object", "description": "prompt 参数(可选)"},
                },
                "required": ["server", "name"],
            },
        }

    def run(self, args: dict) -> dict:
        server = args.get("server", "")
        name = args.get("name", "")
        prompt_args = args.get("args")
        result = asyncio.run(self.manager.get_prompt(server, name, prompt_args))
        return {"content": result, "error": None}
```

## ToolRegistry 集成

修改 `ToolRegistry.__init__()`，新增 `mcp_manager` 参数：

```python
def __init__(self, ..., mcp_manager: MCPManager | None = None):
    # ... 原有工具注册 ...

    # 注册 MCP 工具
    if mcp_manager:
        for mcp_tool in mcp_manager.get_all_mcp_tools():
            self._tools[mcp_tool["name"]] = MCPTool(
                server_name=mcp_tool["server"],
                tool_info=mcp_tool["tool_info"],
                manager=mcp_manager,
            )
        # 注册伪工具（仅当有 MCP server 时）
        self._tools["mcp_resource"] = McpResourceTool(mcp_manager)
        self._tools["mcp_prompt"] = McpPromptTool(mcp_manager)
```

修改 `AgentService.__init__()` 和 `SessionRegistry._build_session()`，传入 `mcp_manager`。

## SYSTEM_PROMPT 注入

在 system prompt 里追加 MCP 能力说明：

```
## MCP 服务器

已连接的 MCP 服务器提供了额外的工具和资源：

### 可用 MCP 工具
- mcp__filesystem__read_file: 读取文件系统
- mcp__filesystem__write_file: 写入文件
- mcp__search__search_web: 网络搜索

### 可用 MCP 资源
- filesystem: file:///project/docs/api.md - API 文档
- filesystem: file:///project/schema.sql - 数据库 schema

### 可用 MCP 提示
- filesystem: code_review - 代码审查提示模板

调 MCP 工具: 直接用 mcp__<server>__<tool> 工具名
读 MCP 资源: 调 mcp_resource(server, uri)
用 MCP 提示: 调 mcp_prompt(server, name)
```

## API 路由 (`web/mcp_api.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mcp/servers` | 列出所有 server 状态（含 tools/resources/prompts） |
| POST | `/api/mcp/servers` | 添加 server 配置 |
| PUT | `/api/mcp/servers/{name}` | 更新 server 配置 |
| DELETE | `/api/mcp/servers/{name}` | 删除 server |
| POST | `/api/mcp/servers/{name}/toggle` | 启用/禁用 |
| POST | `/api/mcp/servers/{name}/reconnect` | 重连 |
| GET | `/api/mcp/servers/{name}/info` | 获取单个 server 详情 |

## 前端设计

### `McpManage.vue` — MCP 管理页

布局：
- 顶部："添加服务器"按钮
- 主体：卡片列表，每个 server 一张卡片
  - 卡片头：server 名称 + 状态标签（connected/disconnected/failed/disabled）+ 传输标签（stdio/SSE）
  - 卡片体：
    - 连接配置摘要（command + args / url）
    - 能力列表（tools 数量、resources 数量、prompts 数量，可展开查看）
    - 错误信息（失败时显示）
  - 卡片底：启用/禁用开关 + 重连按钮 + 编辑按钮 + 删除按钮

### 添加/编辑表单（Dialog）

字段：
- 名称（text input）
- 传输方式（select: stdio / SSE）
- stdio 模式：command（text input）、args（动态列表）、env（key-value 列表）
- SSE 模式：URL（text input）、headers（key-value 列表）

### Sidebar 修改

MCP 管理入口点击后跳转 `/mcp`，和 Skill 管理一样。

## 连接生命周期

### 启动时

```
1. MCPManager 从 ~/.taisang/mcp_servers.json 加载配置
2. 对每个 enabled 的 server 异步调用 connect_server()
3. 连接成功 → 拉取 tools/resources/prompts → 注册到 ToolRegistry
4. 连接失败 → 标记 status=failed，记录 error，不阻塞其他 server
```

### 运行时

- 连接断开 → 标记 status=failed，LLM 调 MCP 工具时返回错误 observation
- 用户点重连 → 重新 connect_server()
- 用户禁用 → disconnect_server()，从 ToolRegistry 移除该 server 的工具

### 添删改

- 添加 → 写配置 → connect_server() → 注册工具
- 删除 → disconnect_server() → 移除工具 → 删配置
- 修改 → disconnect_server() → 更新配置 → connect_server() → 重新注册工具

## 错误处理

| 场景 | 处理 |
|------|------|
| 连接超时 | 标记 failed，error="connection timeout" |
| 命令不存在（stdio） | 标记 failed，error="command not found" |
| URL 不可达（SSE） | 标记 failed，error="connection refused" |
| 工具调用失败 | 返回 error observation，不中断 agent 循环 |
| 资源不存在 | 返回 error observation |
| prompt 不存在 | 返回 error observation |

## 依赖

需要安装 MCP SDK：

```
pip install "mcp[cli]"
```

`mcp` 包提供了：
- `mcp.client.stdio.StdioClientTransport`
- `mcp.client.sse.SSEClientTransport`
- `mcp.server.Server`（测试用）
- 协议类型定义

## 测试策略

### 单元测试

- `test_mcp_types.py` — 数据模型序列化/反序列化
- `test_mcp_client.py` — MCPClient 连接/能力拉取/工具调用（用 mock server）
- `test_mcp_manager.py` — 配置 CRUD、连接生命周期、状态汇总
- `test_mcp_tool.py` — MCPTool schema/run
- `test_mcp_api.py` — API 路由

### 集成测试

- 启动一个真实的 MCP server（如 `@modelcontextprotocol/server-filesystem`）
- 通过 API 添加 → 连接 → 验证工具注册 → 调工具 → 验证结果

### 前端测试

- Playwright: 渲染 McpManage 页、添加 server、toggle 开关、删除

## 文件清单

### 新建

- `src/taisang/mcp/__init__.py`
- `src/taisang/mcp/types.py`
- `src/taisang/mcp/client.py`
- `src/taisang/mcp/tool.py`
- `src/taisang/mcp/manager.py`
- `src/taisang/mcp/errors.py`
- `src/taisang/web/mcp_api.py`
- `frontend/src/views/McpManage.vue`
- `frontend/src/stores/mcp.ts`
- `tests/unit/test_mcp_types.py`
- `tests/unit/test_mcp_client.py`
- `tests/unit/test_mcp_manager.py`
- `tests/unit/test_mcp_tool.py`
- `tests/unit/test_mcp_api.py`

### 修改

- `src/taisang/agent_core/tools.py` — ToolRegistry 接受 mcp_manager 参数
- `src/taisang/agent_core/service.py` — AgentService 传 mcp_manager
- `src/taisang/agent_core/prompts.py` — SYSTEM_PROMPT 追加 MCP 能力段
- `src/taisang/web/app.py` — 挂载 mcp_api router
- `src/taisang/web/session_registry.py` — _build_session 传 mcp_manager
- `frontend/src/router/index.ts` — 加 `/mcp` 路由
- `frontend/src/components/Sidebar.vue` — MCP 管理点击跳 `/mcp`
- `pyproject.toml` — 加 `mcp` 依赖
