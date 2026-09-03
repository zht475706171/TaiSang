<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">
        <span class="diamond">◆</span>TaiSang
      </div>
      <div class="brand-tag">coding agent</div>
    </div>

    <div class="new-session-wrap">
      <t-button block theme="primary" @click="handleNewSession">
        <template #icon>
          <t-icon name="add" />
        </template>
        新对话
      </t-button>
    </div>

    <div class="session-list">
      <SessionItem
        v-for="s in store.sessions"
        :key="s.id"
        :session="s"
        :active="s.id === store.currentId"
        @select="handleSelect(s.id)"
        @delete="handleDelete(s.id)"
      />
      <div v-if="store.sessions.length === 0" class="empty-list">
        暂无会话
      </div>
    </div>

    <div class="sidebar-footer">
      <t-button block variant="text" @click="emit('open-config')">
        <template #icon>
          <t-icon name="setting" />
        </template>
        设置
      </t-button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import SessionItem from './SessionItem.vue'
import { useSessionStore } from '@/stores/session'

const emit = defineEmits<{ 'open-config': [] }>()
const router = useRouter()
const store = useSessionStore()

async function handleNewSession() {
  const id = await store.createNew()
  store.select(id)
  router.push(`/chat/${id}`)
}

function handleSelect(id: string) {
  store.select(id)
  router.push(`/chat/${id}`)
}

async function handleDelete(id: string) {
  if (!confirm('确认删除该会话?')) return
  await store.remove(id)
  if (store.currentId === null) {
    router.push('/')
  }
}
</script>

<style scoped>
.sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--td-bg-color-container);
  border-right: 1px solid var(--td-component-stroke);
  height: 100vh;
}
.brand {
  padding: 16px 16px 8px;
}
.brand-mark {
  font-size: 18px;
  font-weight: 600;
  color: var(--td-text-color-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.diamond {
  color: var(--td-brand-color);
}
.brand-tag {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin-top: 2px;
}
.new-session-wrap {
  padding: 8px 12px 12px;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.empty-list {
  padding: 24px 12px;
  text-align: center;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.sidebar-footer {
  padding: 8px 12px;
  border-top: 1px solid var(--td-component-stroke);
}
</style>