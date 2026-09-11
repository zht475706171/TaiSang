<template>
  <div class="chat-view">
    <header v-if="currentSession" class="topbar">
      <span class="label">session</span>
      <h1 class="title">{{ currentSession.title || currentSession.id }}</h1>
    </header>

    <div
      v-if="currentSession && connectionState !== 'connected'"
      class="connection-bar"
      :class="connectionState"
    >
      <span v-if="connectionState === 'reconnecting'">连接断开,正在重连...</span>
      <span v-else-if="connectionState === 'failed'">连接失败,请刷新页面</span>
    </div>

    <div class="chat-body">
      <TodoList :todos="todos" />
      <EmptyState
        v-if="!messages.length"
        :source-root="currentSourceRoot"
        @send="handleEmptySend"
        @import-project="handleImportProject"
      />
      <MessageList
        v-else
        :messages="messages"
        :thinking="thinking"
        :stopping="stopping"
        :retry-info="retryInfo"
        :reasoning-text="reasoningText"
        @answer="handleAnswer"
      />
    </div>

    <MessageInput
      v-if="currentSession && messages.length"
      autofocus
      :streaming="thinking"
      :source-root="currentSourceRoot"
      @send="handleSend"
      @stop="stop"
      @import-project="handleImportProject"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, toRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import EmptyState from '@/components/EmptyState.vue'
import MessageList from '@/components/MessageList.vue'
import MessageInput from '@/components/MessageInput.vue'
import TodoList from '@/components/TodoList.vue'
import { useSessionStore } from '@/stores/session'
import { resetSession, getSessionInfo, pickDirectory, switchDirectory } from '@/api/session'
import { useChatStream } from '@/composables/useChatStream'

const route = useRoute()
const router = useRouter()
const store = useSessionStore()

const currentId = computed(() => (route.params.id as string) ?? null)
const currentSession = computed(
  () => store.sessions.find((s) => s.id === currentId.value) ?? null,
)

// 当前会话工作目录:打开会话时从 /info 读;用户导入项目后切换并更新。
// null = 未加载或无会话;空串 = 显式无 source_root(fallback 默认)。
const currentSourceRoot = ref<string | null>(null)

// useChatStream 需要一个 ref,用 toRef 把 computed 转 ref
const sessionIdRef = toRef(currentId)
const { messages, thinking, stopping, retryInfo, reasoningText, connectionState, todos, send, stop, loadHistory, openEventStream, closeEventStream, answerConfirm } =
  useChatStream(sessionIdRef, () => store.fetchSessions())

watch(
  currentId,
  async (id) => {
    store.select(id)
    if (id) {
      await loadHistory(id)
      openEventStream(id)
      // 拉当前工作目录展示在输入栏上方
      try {
        const info = await getSessionInfo(id)
        currentSourceRoot.value = info.source_root
      } catch (e) {
        currentSourceRoot.value = null
      }
    } else {
      closeEventStream()
      messages.value = []
      currentSourceRoot.value = null
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

/** 导入项目:弹系统目录选择器 → 选定后切换会话工作目录 → 更新本地展示。
 *  新对话无 currentId 时:先创建会话 + 跳转路由(同 handleSendNew),再弹选择器。 */
async function handleImportProject() {
  let id = currentId.value
  if (!id) {
    id = await store.createNew()
    store.select(id)
    router.push(`/chat/${id}`)
    // 等路由跳转 + watch 加载完(loadHistory + openEventStream + getSessionInfo)
    await new Promise((r) => setTimeout(r, 100))
  }
  try {
    const pick = await pickDirectory(id)
    if (pick.cancelled || !pick.path) return
    const res = await switchDirectory(id, pick.path)
    currentSourceRoot.value = res.source_root
    MessagePlugin.success('已切换工作目录')
  } catch (e) {
    MessagePlugin.error(`导入项目失败: ${(e as Error).message}`)
  }
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
.chat-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.connection-bar {
  padding: 8px 24px;
  font-size: 13px;
  text-align: center;
  font-family: var(--app-font-mono);
}
.connection-bar.reconnecting {
  background: #fff3e0;
  color: #b25803;
  border-bottom: 1px solid #ffcc80;
}
.connection-bar.failed {
  background: #fde7e7;
  color: #c0392b;
  border-bottom: 1px solid #f5b7b1;
}
</style>