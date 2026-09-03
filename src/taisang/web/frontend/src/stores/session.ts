import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Session } from '@/types'
import { listSessions, createSession, deleteSession } from '@/api/session'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([])
  const currentId = ref<string | null>(null)
  const loading = ref(false)

  async function fetchSessions() {
    loading.value = true
    try {
      sessions.value = await listSessions()
    } finally {
      loading.value = false
    }
  }

  async function createNew(): Promise<string> {
    const res = await createSession('')
    sessions.value = await listSessions()
    return res.id
  }

  async function remove(id: string) {
    await deleteSession(id)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentId.value === id) {
      currentId.value = null
    }
  }

  function select(id: string | null) {
    currentId.value = id
  }

  return { sessions, currentId, loading, fetchSessions, createNew, remove, select }
})