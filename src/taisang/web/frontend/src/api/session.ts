import { apiGet, apiPost, apiDelete } from './request'
import type { Session } from '@/types'

export function listSessions(): Promise<Session[]> {
  return apiGet<Session[]>('/api/sessions')
}

export function createSession(title = ''): Promise<{ id: string; title: string }> {
  return apiPost<{ id: string; title: string }>('/api/sessions', { title })
}

export function deleteSession(id: string): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`/api/sessions/${id}`)
}

export function resetSession(id: string): Promise<{ reset: boolean }> {
  return apiPost<{ reset: boolean }>(`/api/sessions/${id}/reset`, {})
}

export function setDebug(id: string, on: boolean): Promise<{ debug: boolean }> {
  return apiPost<{ debug: boolean }>(`/api/sessions/${id}/debug`, { on })
}