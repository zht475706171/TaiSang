import { apiGet, apiPost, apiPut } from './request'

export type ProfileFieldKey =
  | 'tech_stack'
  | 'code_style'
  | 'communication'
  | 'environment'
  | 'taboos'

export interface UserProfile {
  tech_stack: string
  code_style: string
  communication: string
  environment: string
  taboos: string
  total_chars: number
}

export interface ProfileHistoryEntry {
  ts: string
  source: 'user' | 'agent' | 'rollback'
  field: string
  old: string
  new: string
  session_id: string | null
  snapshot_before: Record<string, string>
}

export function fetchProfile(): Promise<UserProfile> {
  return apiGet<UserProfile>('/api/profile')
}

export function saveProfileField(field: ProfileFieldKey, content: string): Promise<UserProfile> {
  return apiPut<UserProfile>('/api/profile', { field, content })
}

export function resetProfileField(field: ProfileFieldKey): Promise<UserProfile> {
  return apiPost<UserProfile>('/api/profile/reset', { field })
}

export function rollbackProfile(): Promise<UserProfile> {
  return apiPost<UserProfile>('/api/profile/rollback', {})
}

export function fetchProfileHistory(): Promise<ProfileHistoryEntry[]> {
  return apiGet<ProfileHistoryEntry[]>('/api/profile/history')
}