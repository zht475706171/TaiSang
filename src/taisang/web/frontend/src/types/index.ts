export interface Session {
  id: string
  title: string
  active: boolean
  updated_at: number
  relative_time: string
}

export interface LLMConfig {
  model: string
  base_url: string
  api_key: string
  api_key_set: boolean
}

// 消息列表项(前端渲染用,从 SSE 事件 + history records 合并)
export type MessageKind =
  | 'user'
  | 'assistant'
  | 'tool_call'
  | 'tool_result'
  | 'thinking'
  | 'compacted'
  | 'confirm'
  | 'permission'
  | 'run_error'
  | 'usage'
  | 'llm_retry'

export interface ChatMessage {
  id: string               // 前端生成 uuid,用于 v-for key
  kind: MessageKind
  // user / assistant
  text?: string
  // tool_call / tool_result
  toolName?: string
  toolArgs?: string        // JSON.stringify(args)
  toolPreview?: string
  toolBytes?: number
  toolFilled?: boolean     // tool_result 是否已填充
  // compacted
  via?: string
  // confirm / permission
  token?: string
  filePath?: string
  oldContent?: string
  newContent?: string
  path?: string
  answered?: boolean
  approved?: boolean
  // usage
  usage?: UsageData
  // run_error
  error?: string
  // llm_retry
  retryAttempt?: number    // 第几次重试(1-based)
  delaySec?: number        // 几秒后重试
  // Task 14: subagent 事件嵌套渲染
  agentId?: string               // 非空 → 该消息来自子 agent
  subAgentEvents?: ChatMessage[] // 嵌套子事件,挂在 Agent 工具卡片内
}

export interface UsageData {
  turn: { prompt: number; completion: number; total: number } | null
  session: { prompt: number; completion: number; total: number }
  cache: { available: boolean; cached_tokens: number | null }
}

// 后端 history record(GET /api/sessions/:id/messages 返回)
export interface HistoryRecord {
  role: string
  content: string
  tool_calls?: Array<{ function: { name: string; arguments: string } }>
  name?: string
}