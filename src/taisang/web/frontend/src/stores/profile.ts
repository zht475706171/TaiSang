import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  clearProfile,
  fetchProfile,
  fetchProfileHistory,
  resetProfileToDefault,
  rollbackProfile,
  saveProfileContent,
  type ProfileHistoryEntry,
  type UserProfile,
} from '@/api/profile'

export const useProfileStore = defineStore('profile', () => {
  const profile = ref<UserProfile | null>(null)
  const history = ref<ProfileHistoryEntry[]>([])
  const loading = ref(false)

  async function load() {
    loading.value = true
    try {
      profile.value = await fetchProfile()
      history.value = await fetchProfileHistory()
    } finally {
      loading.value = false
    }
  }

  async function save(content: string) {
    profile.value = await saveProfileContent(content)
    history.value = await fetchProfileHistory()
  }

  async function resetDefault() {
    profile.value = await resetProfileToDefault()
    history.value = await fetchProfileHistory()
  }

  async function clear() {
    profile.value = await clearProfile()
    history.value = await fetchProfileHistory()
  }

  async function rollback() {
    profile.value = await rollbackProfile()
    history.value = await fetchProfileHistory()
  }

  return { profile, history, loading, load, save, resetDefault, clear, rollback }
})