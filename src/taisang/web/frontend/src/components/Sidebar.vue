<template>
  <aside class="sidebar">
    <div class="brand">
      <t-icon name="robot" class="brand-icon" />
      <span class="brand-name">TaiSang</span>
    </div>

    <!-- 固定区:新对话 + 管理入口,不参与滚动 -->
    <div class="new-session-wrap">
      <t-button
        block
        theme="primary"
        aria-label="新建对话(Cmd/Ctrl+K)"
        @click="emit('new-session')"
      >
        <template #icon>
          <t-icon name="add" />
        </template>
        新对话
      </t-button>
    </div>

    <nav class="nav-menu" aria-label="管理入口">
      <div class="menu-item" @click="router.push('/skills')">
        <t-icon name="code" class="menu-icon" />
        <span class="menu-title">Skill 管理</span>
      </div>
      <div class="menu-item" @click="router.push('/mcp')">
        <t-icon name="server" class="menu-icon" />
        <span class="menu-title">MCP 管理</span>
      </div>
      <div class="menu-item" @click="router.push('/prompts')">
        <t-icon name="edit-1" class="menu-icon" />
        <span class="menu-title">Prompt 管理</span>
      </div>
      <div class="menu-item" @click="router.push('/agents')">
        <t-icon name="user-circle" class="menu-icon" />
        <span class="menu-title">Agent 管理</span>
      </div>
    </nav>

    <!-- 唯一滚动区:历史会话 -->
    <div class="session-section">
      <div class="section-label">历史会话</div>
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
    </div>

    <div class="sidebar-footer">
      <t-button
        block
        variant="text"
        aria-label="LLM 配置(Cmd/Ctrl+,)"
        @click="emit('open-config')"
      >
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

const emit = defineEmits<{ 'open-config': []; 'new-session': [] }>()
const router = useRouter()
const store = useSessionStore()

function handleSelect(id: string) {
  store.select(id)
  router.push(`/chat/${id}`)
}

async function handleDelete(id: string) {
  if (!confirm('确认删除该会话?')) return
  try {
    await store.remove(id)
  } catch {
    alert('删除失败: 会话正在运行,请等当前回复结束后再删')
    return
  }
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
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 16px 0;
}
.brand-icon {
  font-size: 22px;
  color: var(--td-brand-color);
}
.brand-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}
/* 固定区:新对话按钮 */
.new-session-wrap {
  padding: 8px 12px 12px;
}
/* 固定区:管理入口(skill/mcp 页面跳转),底部分隔线隔开滚动区 */
.nav-menu {
  padding: 0 8px 8px;
  border-bottom: 1px solid var(--td-component-stroke);
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 38px;
  padding: 8px 10px;
  box-sizing: border-box;
  margin-bottom: 2px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--td-text-color-secondary);
  transition: background-color 0.2s ease;
}
.menu-item:hover {
  background: var(--td-bg-color-container-hover);
  color: var(--td-text-color-primary);
}
.menu-icon {
  font-size: 18px;
}
.menu-title {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 唯一滚动区:只有历史会话滚,上方新对话/管理入口固定 */
.session-section {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  /* Claude 风格细滚动条:默认透明,悬浮显示 */
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
  transition: scrollbar-color 0.2s ease;
}
.session-section::-webkit-scrollbar {
  width: 6px;
}
.session-section::-webkit-scrollbar-track {
  background: transparent;
}
.session-section::-webkit-scrollbar-thumb {
  background-color: transparent;
  border-radius: 6px;
  transition: background-color 0.2s ease;
}
.session-section:hover {
  scrollbar-color: rgba(0, 0, 0, 0.18) transparent;
}
.session-section:hover::-webkit-scrollbar-thumb {
  background-color: rgba(0, 0, 0, 0.18);
}
.section-label {
  padding: 12px 12px 4px;
  font-size: 12px;
  color: var(--td-text-color-placeholder);
}
.session-list {
  padding: 0 8px;
}
.empty-list {
  padding: 24px 12px;
  text-align: center;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.sidebar-footer {
  flex-shrink: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--td-component-stroke);
}
</style>
