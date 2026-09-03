import { apiGet, apiPost } from './request'
import type { LLMConfig } from '@/types'

export function getConfig(): Promise<LLMConfig> {
  return apiGet<LLMConfig>('/api/config')
}

export function saveConfig(
  model: string,
  api_key: string,
  base_url: string,
): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/config', { model, api_key, base_url })
}