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

export function interruptSession(id: string): Promise<{ ok: boolean; interrupted: boolean }> {
  return apiPost<{ ok: boolean; interrupted: boolean }>(`/api/sessions/${id}/interrupt`, {})
}

export function getQueue(id: string): Promise<{ queue: string[]; len: number }> {
  return apiGet<{ queue: string[]; len: number }>(`/api/sessions/${id}/queue`)
}

/** 当前阻塞中的 confirm/permission payload(无则 null),切回 session 恢复卡片用。 */
export interface PendingConfirm {
  token: string
  file_path: string
  old: string
  new: string
}
export interface PendingPermission {
  token: string
  path: string
}
export function getPending(id: string): Promise<{ confirm: PendingConfirm | null; permission: PendingPermission | null }> {
  return apiGet<{ confirm: PendingConfirm | null; permission: PendingPermission | null }>(`/api/sessions/${id}/pending`)
}