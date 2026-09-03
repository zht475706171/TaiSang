import { apiPost, apiGet } from './request'
import type { HistoryRecord } from '@/types'

export function sendMessage(id: string, query: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(`/api/sessions/${id}/messages`, { query })
}

export function getHistory(id: string): Promise<HistoryRecord[]> {
  return apiGet<HistoryRecord[]>(`/api/sessions/${id}/messages`)
}

export function respondConfirm(id: string, token: string, approve: boolean): Promise<{ resolved: boolean }> {
  return apiPost<{ resolved: boolean }>(`/api/sessions/${id}/confirm/${token}`, { approve })
}

export function respondPermission(id: string, token: string, approve: boolean): Promise<{ resolved: boolean }> {
  return apiPost<{ resolved: boolean }>(`/api/sessions/${id}/permission/${token}`, { approve })
}