<template>
  <div class="app-layout">
    <Sidebar @open-config="configOpen = true" @new-session="handleNewSession" />
    <main class="app-main">
      <router-view />
    </main>
    <ConfigModal v-model="configOpen" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Sidebar from '@/components/Sidebar.vue'
import ConfigModal from '@/components/ConfigModal.vue'
import { useSessionStore } from '@/stores/session'

const configOpen = ref(false)
const store = useSessionStore()
const router = useRouter()

async function handleNewSession() {
  const id = await store.createNew()
  store.select(id)
  router.push(`/chat/${id}`)
}

function handleGlobalKeydown(e: KeyboardEvent) {
  // Cmd/Ctrl+K → 新对话
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    handleNewSession()
  }
  // Cmd/Ctrl+, → 打开配置
  if ((e.metaKey || e.ctrlKey) && e.key === ',') {
    e.preventDefault()
    configOpen.value = true
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
  store.fetchSessions()
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<style>
.app-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--td-bg-color-page);
}
</style>