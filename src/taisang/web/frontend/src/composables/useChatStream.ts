import { ref, type Ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import type { ChatMessage, HistoryRecord, Todo, UsageData } from '@/types'
import { getHistory, sendMessage, respondConfirm, respondPermission, interruptSession } from '@/api/chat'

let _idCounter = 0
function nextId(): string {
  _idCounter += 1
  return `m${_idCounter}`
}

export function useChatStream(
  sessionId: Ref<string | null>,
  onTitleUpdated?: () => void,
) {
  const messages = ref<ChatMessage[]>([])
  const thinking = ref(false)
  // LLM 重试状态:call_with_retry 重试前 emit llm_retry,前端在 ThinkingIndicator 旁显示
  // "第 N 次重试中(Xs 后)"。新事件(tool_call/final_answer/run_end)到来时清掉。
  const retryInfo = ref<{ attempt: number; delaySec: number } | null>(null)
  // 流式状态:正在累积的 assistant 消息 + reasoning 文本
  const streamingMessage = ref<ChatMessage | null>(null)
  const reasoningText = ref('')
  // stopping:用户点了 stop,后台还在收尾(等 final_answer/run_end)。
  // 立刻切回发送按钮(thinking=false),但显示"停止中…"提示,final_answer 来了再清。
  // 对标 Claude Code:前端翻 flag 立刻反馈,不等后端真的停。
  const stopping = ref(false)
  const connectionState = ref<'connected' | 'reconnecting' | 'failed'>('connected')
  // TodoWrite:LLM 调 TodoWriteTool 后,顶部 sticky 区渲染 todo 列表。
  // 主 agent 的 todos 在顶层;子 agent 的 todos 嵌套到 Agent 工具卡片(不冒泡顶部)。
  const todos = ref<Todo[]>([])
  let eventSource: EventSource | null = null
  let reconnectCount = 0
  const MAX_RECONNECT = 5

  function safeParse<T>(data: string): T | null {
    try {
      return JSON.parse(data) as T
    } catch (e) {
      console.error('SSE event parse failed:', e, data)
      return null
    }
  }

  function clearThinking() {
    thinking.value = false
    retryInfo.value = null
    reasoningText.value = ''
  }

  function clearStreaming() {
    if (streamingMessage.value && streamingMessage.value.streaming) {
      streamingMessage.value.streaming = false
    }
    streamingMessage.value = null
  }

  function pushUser(text: string) {
    messages.value.push({ id: nextId(), kind: 'user', text })
  }

  function pushAssistant(text: string) {
    messages.value.push({ id: nextId(), kind: 'assistant', text })
  }

  function pushToolCall(name: string, args: string) {
    messages.value.push({
      id: nextId(),
      kind: 'tool_call',
      toolName: name,
      toolArgs: args,
      toolFilled: false,
    })
  }

  function fillToolResult(name: string, preview: string, totalBytes: number) {
    // 找最后一个同名未填充的 tool_call
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m.kind === 'tool_call' && m.toolName === name && !m.toolFilled) {
        m.toolPreview = preview || '(无输出)'
        m.toolBytes = totalBytes
        m.toolFilled = true
        return
      }
    }
    // 没找到,单独 push 一个 result
    messages.value.push({
      id: nextId(),
      kind: 'tool_result',
      toolName: name,
      toolPreview: preview || '(无输出)',
      toolBytes: totalBytes,
      toolFilled: true,
    })
  }

  function pushCompacted(via: string) {
    messages.value.push({ id: nextId(), kind: 'compacted', via })
  }

  function pushConfirm(token: string, filePath: string, old: string, newContent: string) {
    messages.value.push({
      id: nextId(),
      kind: 'confirm',
      token,
      filePath,
      oldContent: old,
      newContent,
      answered: false,
    })
  }

  function pushPermission(token: string, path: string) {
    messages.value.push({
      id: nextId(),
      kind: 'permission',
      token,
      path,
      answered: false,
    })
  }

  function pushUsage(usage: UsageData) {
    messages.value.push({ id: nextId(), kind: 'usage', usage })
  }

  function pushRunError(error: string) {
    messages.value.push({ id: nextId(), kind: 'run_error', error })
  }

  // Task 14: 子 agent 事件嵌套渲染辅助函数
  // 找最后一个 Agent 工具卡片,作为子事件的父容器
  function findLastAgentToolCall(): ChatMessage | null {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m.kind === 'tool_call' && m.toolName === 'Agent') {
        if (!m.subAgentEvents) m.subAgentEvents = []
        return m
      }
    }
    return null
  }

  // 把子事件 push 到父卡片的嵌套数组
  function pushSubEvent(parent: ChatMessage, sub: ChatMessage) {
    if (!parent.subAgentEvents) parent.subAgentEvents = []
    parent.subAgentEvents.push(sub)
  }

  // 子 agent tool_result 填充:在父卡片的嵌套数组里找最后一个同名未填的 tool_call
  function fillSubToolResult(parent: ChatMessage, name: string, preview: string, totalBytes: number) {
    if (!parent.subAgentEvents) return
    for (let i = parent.subAgentEvents.length - 1; i >= 0; i--) {
      const m = parent.subAgentEvents[i]
      if (m.kind === 'tool_call' && m.toolName === name && !m.toolFilled) {
        m.toolPreview = preview || '(无输出)'
        m.toolBytes = totalBytes
        m.toolFilled = true
        return
      }
    }
    // 没找到匹配的 tool_call,单独 push 一个 result
    parent.subAgentEvents.push({
      id: nextId(),
      kind: 'tool_result',
      toolName: name,
      toolPreview: preview || '(无输出)',
      toolBytes: totalBytes,
      toolFilled: true,
    })
  }

  async function answerConfirm(token: string, approve: boolean) {
    if (!sessionId.value) return
    const m = messages.value.find((x) => x.token === token && (x.kind === 'confirm' || x.kind === 'permission'))
    if (m) {
      m.answered = true
      m.approved = approve
    }
    if (m?.kind === 'confirm') {
      await respondConfirm(sessionId.value, token, approve)
    } else if (m?.kind === 'permission') {
      await respondPermission(sessionId.value, token, approve)
    }
  }

  // stop:用户点停止按钮,立刻 thinking=false(按钮切回发送态)+stopping=true(显示停止中)。
  // POST /interrupt fire-and-forget,不等返回。后台收到 cancel_event 真关 LLM 流,
  // final_answer(interrupted=true) 来了再 stopping=false。
  // 对标 Claude Code:前端同步翻 flag 立刻反馈,后台异步收尾。
  function stop() {
    if (!sessionId.value) return
    if (!thinking.value && !stopping.value) return  // 没在跑,忽略
    thinking.value = false
    stopping.value = true
    interruptSession(sessionId.value).catch((e) => console.error('interrupt failed:', e))
  }

  function renderHistory(records: HistoryRecord[]) {
    messages.value = []
    for (const r of records) {
      if (r.role === 'user') {
        pushUser(r.content || '')
      } else if (r.role === 'assistant') {
        pushAssistant(r.content || '')
        if (r.tool_calls && r.tool_calls.length) {
          for (const tc of r.tool_calls) {
            const fn = tc.function || {}
            let args = '{}'
            try {
              args = fn.arguments || '{}'
            } catch {
              args = '{}'
            }
            pushToolCall(fn.name || '', args)
          }
        }
      } else if (r.role === 'tool') {
        const preview = (r.content || '').slice(0, 200)
        const bytes = (r.content || '').length
        fillToolResult(r.name || '', preview, bytes)
      } else if (r.role === 'system' && typeof r.content === 'string' && r.content.startsWith('[compacted')) {
        const via = r.content.includes('session_memory') ? 'session_memory' : 'llm'
        pushCompacted(via)
      }
      // system role 的 SYSTEM_PROMPT 不渲染
    }
  }

  function openEventStream(id: string) {
    closeEventStream()
    eventSource = new EventSource(`/api/sessions/${id}/events`)

    eventSource.onopen = () => {
      connectionState.value = 'connected'
      reconnectCount = 0
    }
    eventSource.onerror = () => {
      if (!eventSource) return
      if (eventSource.readyState === EventSource.CLOSED) {
        connectionState.value = 'failed'
        eventSource.close()
        eventSource = null
      } else {
        // CONNECTING,浏览器在重连
        reconnectCount += 1
        if (reconnectCount > MAX_RECONNECT) {
          connectionState.value = 'failed'
          eventSource.close()
          eventSource = null
        } else {
          connectionState.value = 'reconnecting'
        }
      }
    }

    eventSource.addEventListener('llm_thinking', (e: MessageEvent) => {
      const d = safeParse<{ agent_id?: string }>(e.data)
      // 子 agent thinking:嵌套到父卡片(降级处理:无父则忽略,避免主流闪烁)
      if (d?.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, { id: nextId(), kind: 'thinking', agentId: d.agent_id })
        }
        return
      }
      thinking.value = true
    })
    eventSource.addEventListener('llm_retry', (e: MessageEvent) => {
      const d = safeParse<{ attempt: number; error: string; delay_sec: number; agent_id?: string }>(e.data)
      if (!d) return
      // 子 agent 重试:嵌套到父卡片(降级:无父则忽略)
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'llm_retry',
            retryAttempt: d.attempt,
            delaySec: d.delay_sec,
            agentId: d.agent_id,
          })
        }
        return
      }
      // 主 agent 重试:更新 retryInfo,ThinkingIndicator 显示"第 N 次重试中"
      retryInfo.value = { attempt: d.attempt, delaySec: d.delay_sec }
    })
    eventSource.addEventListener('llm_chunk', (e: MessageEvent) => {
      const d = safeParse<{ text_delta: string; reasoning_delta: string; agent_id?: string }>(e.data)
      if (!d) return
      // 子 agent chunk:嵌套到父卡片(降级:无父则忽略)
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'llm_chunk',
            textDelta: d.text_delta,
            reasoningDelta: d.reasoning_delta,
            agentId: d.agent_id,
          })
        }
        return
      }
      // 主 agent chunk
      if (d.text_delta) {
        if (!streamingMessage.value || !streamingMessage.value.streaming) {
          streamingMessage.value = {
            id: nextId(),
            kind: 'assistant',
            text: '',
            streaming: true,
          }
          messages.value.push(streamingMessage.value)
        }
        streamingMessage.value.text = (streamingMessage.value.text || '') + d.text_delta
      }
      if (d.reasoning_delta) {
        reasoningText.value = (reasoningText.value || '') + d.reasoning_delta
      }
    })
    eventSource.addEventListener('todo_update', (e: MessageEvent) => {
      const d = safeParse<{ todos: Todo[]; agent_id?: string }>(e.data)
      if (!d) return
      // 子 agent todo:嵌套到父 Agent 卡片(降级:无父则忽略,不冒泡顶部)
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          parent.subAgentTodos = d.todos
        }
        return
      }
      // 主 agent:覆盖式更新顶部 todos
      todos.value = d.todos
    })
    eventSource.addEventListener('profile_update', (e: MessageEvent) => {
      // agent 改了画像,toast 提示(不跳转,不区分主/子 agent)
      const d = safeParse<{ field?: string; label?: string; content?: string; source?: string }>(e.data)
      if (!d) return
      const label = d.label || '画像'
      MessagePlugin.info(`画像【${label}】已更新`)
    })
    eventSource.addEventListener('tool_call', (e: MessageEvent) => {
      const d = safeParse<{ name: string; args: Record<string, unknown>; agent_id?: string }>(e.data)
      if (!d) return
      clearThinking()
      clearStreaming()
      if (d.agent_id) {
        // 子 agent 事件:嵌套到最近的 Agent 工具卡片
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'tool_call',
            toolName: d.name,
            toolArgs: JSON.stringify(d.args),
            toolFilled: false,
            agentId: d.agent_id,
          })
          return
        }
        // 父卡片缺失(异常),降级到主流
      }
      pushToolCall(d.name, JSON.stringify(d.args))
    })
    eventSource.addEventListener('tool_result', (e: MessageEvent) => {
      const d = safeParse<{ name: string; preview: string; total_bytes: number; agent_id?: string }>(e.data)
      if (!d) return
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          fillSubToolResult(parent, d.name, d.preview, d.total_bytes)
          return
        }
      }
      fillToolResult(d.name, d.preview, d.total_bytes)
    })
    eventSource.addEventListener('final_answer', (e: MessageEvent) => {
      const d = safeParse<{ text: string; interrupted?: boolean; agent_id?: string }>(e.data)
      if (!d) return
      clearThinking()
      stopping.value = false  // 后台收尾结束,清停止中状态
      if (d.agent_id) {
        // 子 agent 最终答案:嵌套到父卡片
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, {
            id: nextId(),
            kind: 'assistant',
            text: d.text || '',
            interrupted: d.interrupted || false,
            agentId: d.agent_id,
          })
          return
        }
      }
      // 主 agent:流式模式下 FINAL_ANSWER 不重复 push(已在 llm_chunk 累积)
      if (streamingMessage.value && streamingMessage.value.streaming) {
        streamingMessage.value.streaming = false
        streamingMessage.value.interrupted = d.interrupted || false
        // 如果中断且 text 为空,用 d.text(含 [interrupted] 标记)
        if (!streamingMessage.value.text) {
          streamingMessage.value.text = d.text
        } else if (d.interrupted) {
          streamingMessage.value.text = (streamingMessage.value.text || '') + ' [interrupted]'
        }
        streamingMessage.value = null
      } else {
        // 非流式回退(autocompact LLM 摘要等内部调用仍用 chat 非流式)
        pushAssistant(d.text || '')
      }
    })
    eventSource.addEventListener('compacted', (e: MessageEvent) => {
      const d = safeParse<{ via: string; agent_id?: string }>(e.data)
      if (!d) return
      if (d.agent_id) {
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, { id: nextId(), kind: 'compacted', via: d.via, agentId: d.agent_id })
          return
        }
      }
      pushCompacted(d.via)
    })
    eventSource.addEventListener('usage_report', (e: MessageEvent) => {
      const d = safeParse<UsageData & { agent_id?: string }>(e.data)
      if (!d) return
      if (d.agent_id) {
        // 子 agent 用量:嵌套到父卡片,ToolCard 渲染为 "子 agent 用了 N token" 小标注
        const parent = findLastAgentToolCall()
        if (parent) {
          pushSubEvent(parent, { id: nextId(), kind: 'usage', usage: d, agentId: d.agent_id })
          return
        }
      }
      pushUsage(d)
    })
    eventSource.addEventListener('confirm_request', (e: MessageEvent) => {
      const d = safeParse<{ token: string; file_path: string; old: string; new: string }>(e.data)
      if (!d) return
      clearThinking()
      pushConfirm(d.token, d.file_path, d.old, d.new)
    })
    eventSource.addEventListener('permission_request', (e: MessageEvent) => {
      const d = safeParse<{ token: string; path: string }>(e.data)
      if (!d) return
      clearThinking()
      pushPermission(d.token, d.path)
    })
    eventSource.addEventListener('run_error', (e: MessageEvent) => {
      const d = safeParse<{ error: string }>(e.data)
      if (!d) return
      clearThinking()
      clearStreaming()
      stopping.value = false
      pushRunError(d.error || '未知错误')
    })
    eventSource.addEventListener('run_end', () => {
      clearThinking()
      clearStreaming()
      stopping.value = false
    })
    eventSource.addEventListener('session_title_updated', () => {
      if (onTitleUpdated) onTitleUpdated()
    })
  }

  function closeEventStream() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    clearThinking()
    clearStreaming()
    stopping.value = false
    connectionState.value = 'connected'
    reconnectCount = 0
    todos.value = []
  }

  async function loadHistory(id: string) {
    try {
      const records = await getHistory(id)
      renderHistory(records)
    } catch (e) {
      pushRunError(`加载历史失败: ${(e as Error).message}`)
    }
  }

  async function send(query: string) {
    if (!sessionId.value) return
    pushUser(query)
    try {
      await sendMessage(sessionId.value, query)
      // SSE 流会自动推事件
    } catch (e) {
      pushRunError(`发送失败: ${(e as Error).message}`)
    }
  }

  return {
    messages,
    thinking,
    stopping,
    retryInfo,
    reasoningText,
    streamingMessage,
    connectionState,
    todos,
    send,
    stop,
    loadHistory,
    openEventStream,
    closeEventStream,
    answerConfirm,
  }
}