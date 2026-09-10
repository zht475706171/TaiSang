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

/** 会话元信息(GET /info)。当前仅含 source_root(当前工作目录)。 */
export interface SessionInfo {
  id: string
  source_root: string | null
}

/** 目录选择器返回:取消时 cancelled=true;选定时 path=绝对路径。 */
export interface PickDirectoryResult {
  path?: string
  cancelled?: boolean
}

/** 切换目录返回:ok + 新的 source_root 绝对路径。 */
export interface SwitchDirectoryResult {
  ok: boolean
  source_root: string
}

/** 取会话元信息(当前工作目录)。打开会话时调一次。 */
export function getSessionInfo(id: string): Promise<SessionInfo> {
  return apiGet<SessionInfo>(`/api/sessions/${id}/info`)
}

/** 弹系统目录选择器(Windows tkinter)。用户取消返回 {cancelled: true}。 */
export function pickDirectory(id: string): Promise<PickDirectoryResult> {
  return apiPost<PickDirectoryResult>(`/api/sessions/${id}/pick-directory`, {})
}

/** 切换会话当前工作目录到 path。后端更新 agent.source_root + permission + shell cwd。 */
export function switchDirectory(id: string, path: string): Promise<SwitchDirectoryResult> {
  return apiPost<SwitchDirectoryResult>(`/api/sessions/${id}/switch-directory`, { path })
}