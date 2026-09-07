import { apiGet, apiPost, apiPut, apiDelete } from './request'

export interface McpServer {
  name: string
  transport: 'stdio' | 'sse'
  enabled: boolean
  command: string | null
  args: string[]
  env: Record<string, string>
  url: string | null
  headers: Record<string, string>
}

export interface McpToolInfo {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface McpResourceInfo {
  uri: string
  name: string
  description: string
  mime_type: string | null
}

export interface McpPromptInfo {
  name: string
  description: string
  arguments: Record<string, unknown>[]
}

export interface McpServerInfo {
  name: string
  status: 'connected' | 'disconnected' | 'failed' | 'disabled'
  error: string | null
  tools: McpToolInfo[]
  resources: McpResourceInfo[]
  prompts: McpPromptInfo[]
}

export function listMcpServers(): Promise<McpServer[]> {
  return apiGet<McpServer[]>('/api/mcp/servers')
}

export function addMcpServer(cfg: Partial<McpServer>): Promise<McpServerInfo> {
  return apiPost<McpServerInfo>('/api/mcp/servers', cfg)
}

export function updateMcpServer(name: string, cfg: Partial<McpServer>): Promise<McpServerInfo> {
  return apiPut<McpServerInfo>(`/api/mcp/servers/${name}`, cfg)
}

export function deleteMcpServer(name: string): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`/api/mcp/servers/${name}`)
}

// toggle returns merged {**config, **info} — has both `enabled` (from config) and `status` (from info)
export function toggleMcpServer(name: string, enabled: boolean): Promise<McpServer & McpServerInfo> {
  return apiPost<McpServer & McpServerInfo>(`/api/mcp/servers/${name}/toggle`, { enabled })
}

export function reconnectMcpServer(name: string): Promise<McpServerInfo> {
  return apiPost<McpServerInfo>(`/api/mcp/servers/${name}/reconnect`, {})
}

export function getMcpServerInfo(name: string): Promise<McpServerInfo> {
  return apiGet<McpServerInfo>(`/api/mcp/servers/${name}/info`)
}

export interface ImportBatchResult {
  added: string[]
  updated: string[]
  failed: { name: string; error: string }[]
}

export function importCliMcp(line: string): Promise<McpServerInfo> {
  return apiPost<McpServerInfo>('/api/mcp/servers/import-cli', { line })
}

export function importBatchMcp(text: string): Promise<ImportBatchResult> {
  return apiPost<ImportBatchResult>('/api/mcp/servers/import', { text })
}