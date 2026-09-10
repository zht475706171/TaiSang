import { apiGet, apiPost } from './request'
import type { LLMConfig } from '@/types'

export function getConfig(): Promise<LLMConfig> {
  return apiGet<LLMConfig>('/api/config')
}

export function saveConfig(
  model: string,
  api_key: string,
  base_url: string,
  debug: boolean,
): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/config', { model, api_key, base_url, debug })
}

/** 测试连接结果。ok=true 时有 latency_ms + reply,ok=false 时有 error。 */
export interface ConfigTestResult {
  ok: boolean
  latency_ms?: number
  reply?: string
  error?: string
}

/** 用表单传入的 model/api_key/base_url 发最小 hello 请求探测连通性,不持久化。

 * api_key='__unchanged__' 表示用已存的 key(前端 readonly 提交 sentinel)。
 */
export function testConfig(
  model: string,
  api_key: string,
  base_url: string,
): Promise<ConfigTestResult> {
  return apiPost<ConfigTestResult>('/api/config/test', { model, api_key, base_url })
}