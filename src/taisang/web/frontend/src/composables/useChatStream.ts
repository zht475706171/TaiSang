import { ref, type Ref } from 'vue'
import type { ChatMessage, HistoryRecord, UsageData } from '@/types'
import { getHistory, sendMessage, respondConfirm, respondPermission } from '@/api/chat'

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
  const connectionState = ref<'connected' | 'reconnecting' | 'failed'>('connected')
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

    eventSource.addEventListener('llm_thinking', () => {
      thinking.value = true
    })
    eventSource.addEventListener('tool_call', (e: MessageEvent) => {
      const d = safeParse<{ name: string; args: Record<string, unknown> }>(e.data)
      if (!d) return
      clearThinking()
      pushToolCall(d.name, JSON.stringify(d.args))
    })
    eventSource.addEventListener('tool_result', (e: MessageEvent) => {
      const d = safeParse<{ name: string; preview: string; total_bytes: number }>(e.data)
      if (!d) return
      fillToolResult(d.name, d.preview, d.total_bytes)
    })
    eventSource.addEventListener('final_answer', (e: MessageEvent) => {
      const d = safeParse<{ text: string }>(e.data)
      if (!d) return
      clearThinking()
      pushAssistant(d.text || '')
    })
    eventSource.addEventListener('compacted', (e: MessageEvent) => {
      const d = safeParse<{ via: string }>(e.data)
      if (!d) return
      pushCompacted(d.via)
    })
    eventSource.addEventListener('usage_report', (e: MessageEvent) => {
      const d = safeParse<UsageData>(e.data)
      if (!d) return
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
      pushRunError(d.error || '未知错误')
    })
    eventSource.addEventListener('run_end', () => {
      clearThinking()
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
    connectionState.value = 'connected'
    reconnectCount = 0
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
    connectionState,
    send,
    loadHistory,
    openEventStream,
    closeEventStream,
    answerConfirm,
  }
}