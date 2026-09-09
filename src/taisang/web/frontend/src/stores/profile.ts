import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  fetchProfile,
  fetchProfileHistory,
  resetProfileField,
  rollbackProfile,
  saveProfileField,
  type ProfileFieldKey,
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

  async function saveField(field: ProfileFieldKey, content: string) {
    profile.value = await saveProfileField(field, content)
    history.value = await fetchProfileHistory()
  }

  async function resetField(field: ProfileFieldKey) {
    profile.value = await resetProfileField(field)
    history.value = await fetchProfileHistory()
  }

  async function rollback() {
    profile.value = await rollbackProfile()
    history.value = await fetchProfileHistory()
  }

  return { profile, history, loading, load, saveField, resetField, rollback }
})