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