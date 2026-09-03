<template>
  <div class="chat-view">
    <header v-if="currentSession" class="topbar">
      <span class="label">session</span>
      <h1 class="title">{{ currentSession.title }}</h1>
      <div class="actions">
        <t-button variant="text" size="small" @click="handleReset">/reset</t-button>
        <t-button variant="text" size="small" @click="handleDebug">/debug</t-button>
      </div>
    </header>

    <div class="chat-body">
      <EmptyState v-if="!currentSession" @send="handleSendNew" />
      <div v-else class="messages-placeholder">
        <p>消息列表将在 Plan 3 实现</p>
        <p class="hint">当前会话:{{ currentSession.title }}</p>
      </div>
    </div>

    <MessageInput v-if="currentSession" @send="handleSend" />
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EmptyState from '@/components/EmptyState.vue'
import MessageInput from '@/components/MessageInput.vue'
import { useSessionStore } from '@/stores/session'
import { resetSession, setDebug } from '@/api/session'

const route = useRoute()
const router = useRouter()
const store = useSessionStore()

const currentId = computed(() => (route.params.id as string) ?? null)
const currentSession = computed(() =>
  store.sessions.find((s) => s.id === currentId.value) ?? null,
)

watch(
  currentId,
  (id) => {
    store.select(id)
  },
  { immediate: true },
)

async function handleSendNew(query: string) {
  const id = await store.createNew()
  store.select(id)
  router.push(`/chat/${id}`)
  // Plan 3 才真正发消息,这里先跳转
  void query
}

async function handleSend(_query: string) {
  // Plan 3 实现:POST /api/sessions/:id/messages + SSE
}

async function handleReset() {
  if (!currentId.value) return
  await resetSession(currentId.value)
}

async function handleDebug() {
  if (!currentId.value) return
  await setDebug(currentId.value, true)
}
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  flex: 1;
  min-width: 0;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--td-component-stroke);
  background: var(--td-bg-color-container);
}
.topbar .label {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  font-family: var(--app-font-mono);
}
.topbar .title {
  font-size: 16px;
  font-weight: 500;
  color: var(--td-text-color-primary);
  margin: 0;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.topbar .actions {
  display: flex;
  gap: 4px;
}
.chat-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.messages-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--td-text-color-placeholder);
  font-size: 14px;
  gap: 8px;
}
.messages-placeholder .hint {
  font-size: 12px;
}
</style>