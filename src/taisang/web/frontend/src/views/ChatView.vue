<template>
  <div class="chat-view">
    <header v-if="currentSession" class="topbar">
      <span class="label">session</span>
      <h1 class="title">{{ currentSession.title || currentSession.id }}</h1>
      <div class="actions">
        <t-button variant="text" size="small" @click="handleReset">/reset</t-button>
        <t-button variant="text" size="small" @click="handleDebug">/debug</t-button>
      </div>
    </header>

    <div class="chat-body">
      <EmptyState v-if="!messages.length" @send="handleEmptySend" />
      <MessageList
        v-else
        :messages="messages"
        :thinking="thinking"
        @answer="handleAnswer"
      />
    </div>

    <MessageInput v-if="currentSession && messages.length" @send="handleSend" />
  </div>
</template>

<script setup lang="ts">
import { computed, watch, toRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EmptyState from '@/components/EmptyState.vue'
import MessageList from '@/components/MessageList.vue'
import MessageInput from '@/components/MessageInput.vue'
import { useSessionStore } from '@/stores/session'
import { resetSession, setDebug } from '@/api/session'
import { useChatStream } from '@/composables/useChatStream'

const route = useRoute()
const router = useRouter()
const store = useSessionStore()

const currentId = computed(() => (route.params.id as string) ?? null)
const currentSession = computed(
  () => store.sessions.find((s) => s.id === currentId.value) ?? null,
)

// useChatStream 需要一个 ref,用 toRef 把 computed 转 ref
const sessionIdRef = toRef(currentId)
const { messages, thinking, send, loadHistory, openEventStream, closeEventStream, answerConfirm } =
  useChatStream(sessionIdRef, () => store.fetchSessions())

watch(
  currentId,
  async (id) => {
    store.select(id)
    if (id) {
      await loadHistory(id)
      openEventStream(id)
    } else {
      closeEventStream()
      messages.value = []
    }
  },
  { immediate: true },
)

async function handleSendNew(query: string) {
  const id = await store.createNew()
  store.select(id)
  router.push(`/chat/${id}`)
  // 跳转后 watch 会自动 loadHistory + openEventStream
  // 等流接上再发消息
  setTimeout(() => send(query), 100)
}

// EmptyState 发送:有会话直接发,无会话先创建再发
async function handleEmptySend(query: string) {
  if (currentId.value) {
    await send(query)
    store.fetchSessions()
  } else {
    await handleSendNew(query)
  }
}

async function handleSend(query: string) {
  // 斜杠命令
  if (query.startsWith('/')) {
    await handleSlash(query)
    return
  }
  await send(query)
  store.fetchSessions()  // 刷新列表(title 可能变了)
}

async function handleSlash(cmd: string) {
  const parts = cmd.slice(1).split(/\s+/)
  const name = parts[0]
  if (name === 'reset' && currentId.value) {
    await resetSession(currentId.value)
    messages.value = []
  } else if (name === 'debug' && currentId.value) {
    await setDebug(currentId.value, true)
  } else if (name === 'clear') {
    messages.value = []
  } else {
    // 未知命令当普通消息发
    await send(cmd)
  }
}

async function handleAnswer(token: string, approve: boolean) {
  await answerConfirm(token, approve)
}

async function handleReset() {
  if (!currentId.value) return
  await resetSession(currentId.value)
  messages.value = []
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
</style>