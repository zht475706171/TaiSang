import { apiGet, apiPost, apiPut } from './request'

export interface UserProfile {
  content: string
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

export function saveProfileContent(content: string): Promise<UserProfile> {
  return apiPut<UserProfile>('/api/profile', { content })
}

export function resetProfileToDefault(): Promise<UserProfile> {
  return apiPost<UserProfile>('/api/profile/reset-default', {})
}

export function clearProfile(): Promise<UserProfile> {
  return apiPost<UserProfile>('/api/profile/clear', {})
}

export function rollbackProfile(): Promise<UserProfile> {
  return apiPost<UserProfile>('/api/profile/rollback', {})
}

export function fetchProfileHistory(): Promise<ProfileHistoryEntry[]> {
  return apiGet<ProfileHistoryEntry[]>('/api/profile/history')
}