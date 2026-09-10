import { apiGet, apiPost } from './request'
import type { LLMConfig, SaveConfigReq } from '@/types'

export function getConfig(): Promise<LLMConfig> {
  return apiGet<LLMConfig>('/api/config')
}

export function saveConfig(req: SaveConfigReq): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/config', req)
}

/** 测试连接结果。ok=true 时有 latency_ms + reply,ok=false 时有 error。 */
export interface ConfigTestResult {
  ok: boolean
  latency_ms?: number
  reply?: string
  error?: string
}

/** 用表单传入的 model/api_key/base_url 发最小 hello 请求探测连通性,不持久化。

 * api_key='__unchanged__' 表示用已存 key(前端 readonly 提交 sentinel)。
 * target='main'(默认)用 main 段已存 key fallback;'subagent' 用 subagent 段。
 */
export function testConfig(
  model: string,
  api_key: string,
  base_url: string,
  target: 'main' | 'subagent' = 'main',
): Promise<ConfigTestResult> {
  return apiPost<ConfigTestResult>('/api/config/test', { model, api_key, base_url, target })
}