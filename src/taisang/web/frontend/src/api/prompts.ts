import { apiGet, apiPost, apiPut } from './request'

export type PromptKey =
  | 'system_prompt'
  | 'autocompact_prompt'
  | 'session_memory_template'
  | 'session_memory_update_prompt'

export interface PromptItem {
  current: string
  default: string
  use_default: boolean
  value: string | null  // use_default 时为 null,自定义时为保存的 value
}

export type PromptsMap = Record<PromptKey, PromptItem>

export function fetchPrompts(): Promise<PromptsMap> {
  return apiGet<PromptsMap>('/api/prompts')
}

export function savePrompt(key: PromptKey, value: string): Promise<PromptsMap> {
  return apiPut<PromptsMap>('/api/prompts', { key, value })
}

export function resetPrompt(key: PromptKey): Promise<PromptsMap> {
  return apiPost<PromptsMap>('/api/prompts/reset', { key })
}