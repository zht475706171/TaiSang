export interface Session {
  id: string
  title: string
  active: boolean
  updated_at: number
  relative_time: string
}

export interface LLMConfigSection {
  model: string
  base_url: string
  api_key: string
  api_key_set: boolean
  /** 仅 subagent 段有;main 段忽略 */
  enabled?: boolean
}

export interface LLMConfig {
  main: LLMConfigSection & { debug: boolean }
  subagent: LLMConfigSection
}

/** POST /api/config 请求体:main + subagent + debug。每段 api_key='__unchanged__' 表示保留已存 key。 */
export interface SaveConfigReq {
  main: {
    model: string
    api_key: string
    base_url: string
  }
  subagent?: {
    enabled: boolean
    model: string
    api_key: string
    base_url: string
  }
  debug: boolean
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
  | 'llm_chunk'

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
  toolFullContent?: string  // debug 模式下完整 observation(debug_tool_result 事件覆盖)
  toolFilled?: boolean     // tool_result 是否已填充
  // compacted
  via?: string
  stage?: number           // 1=enforce_budget, 2=autocompact/llm, 3=session_memory
  // compacted 统计字段(按 stage 不同):
  //   stage 1: replaced?: Array<{tool_call_id: string; path: string}>
  //   stage 2: before_tokens?: number; after_tokens?: number; summary_messages?: number
  //   stage 3: trigger?: string; current_tokens?: number; delta_tokens?: number
  replaced?: Array<{ tool_call_id: string; path: string }>
  beforeTokens?: number
  afterTokens?: number
  summaryMessages?: number
  trigger?: string
  currentTokens?: number
  deltaTokens?: number
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
  // 流式相关
  streaming?: boolean       // True = 正在流式累积(llm_chunk 来了,final_answer 未到)
  interrupted?: boolean     // True = 用户主动中断(FINAL_ANSWER interrupted 标记)
  // llm_chunk(subagent 嵌套用,主 agent 的 chunk 不存 message list)
  textDelta?: string
  reasoningDelta?: string
  // Task 14: subagent 事件嵌套渲染
  agentId?: string               // 非空 → 该消息来自子 agent
  subAgentEvents?: ChatMessage[] // 嵌套子事件,挂在 Agent 工具卡片内
  // TodoWrite:子 agent todo 嵌套到 Agent 卡片(主 agent 的 todos 在 useChatStream.todos 顶层)
  subAgentTodos?: Todo[]
}

export interface UsageData {
  turn: { prompt: number; completion: number; total: number } | null
  session: { prompt: number; completion: number; total: number }
  cache: { available: boolean; cached_tokens: number | null }
}

// TodoWrite 任务项(LLM 调 TodoWriteTool 后从 todo_update SSE 事件推来)
export interface Todo {
  content: string
  status: 'pending' | 'in_progress' | 'completed'
  activeForm?: string
}

// 后端 history record(GET /api/sessions/:id/messages 返回)
export interface HistoryRecord {
  role: string
  content: string
  tool_calls?: Array<{ function: { name: string; arguments: string } }>
  name?: string
}