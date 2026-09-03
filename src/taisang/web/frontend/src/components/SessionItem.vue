<template>
  <div
    class="session-item"
    :class="{ active }"
    @click="emit('select')"
  >
    <div class="session-content">
      <div class="session-title">{{ session.title }}</div>
      <div class="session-meta">
        <span>{{ session.relative_time }}</span>
        <span class="dot">·</span>
        <span class="sid">{{ session.id }}</span>
      </div>
    </div>
    <button
      class="delete-btn"
      title="删除会话"
      @click.stop="emit('delete')"
    >
      <t-icon name="close" />
    </button>
  </div>
</template>

<script setup lang="ts">
import type { Session } from '@/types'

defineProps<{
  session: Session
  active: boolean
}>()

const emit = defineEmits<{
  select: []
  delete: []
}>()
</script>

<style scoped>
.session-item {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  gap: 4px;
  transition: background 0.15s;
}
.session-item:hover {
  background: var(--td-bg-color-secondarycontainer);
}
.session-item.active {
  background: var(--td-brand-color-light);
}
.session-content {
  flex: 1;
  min-width: 0;
}
.session-title {
  font-size: 13px;
  color: var(--td-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  font-size: 11px;
  color: var(--td-text-color-placeholder);
  margin-top: 2px;
  display: flex;
  gap: 4px;
  align-items: center;
}
.dot {
  opacity: 0.5;
}
.sid {
  font-family: var(--app-font-mono);
}
.delete-btn {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--td-text-color-placeholder);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  display: none;
  align-items: center;
  justify-content: center;
}
.session-item:hover .delete-btn {
  display: flex;
}
.delete-btn:hover {
  color: var(--td-error-color, #d54941);
  background: var(--td-bg-color-secondarycontainer);
}
</style>