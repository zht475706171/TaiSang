<template>
  <div v-if="todos.length" class="todo-list">
    <div v-for="(t, i) in todos" :key="i" class="todo-item" :class="t.status">
      <span class="icon">
        <span v-if="t.status === 'completed'" class="check">✓</span>
        <span v-else-if="t.status === 'in_progress'" class="spinner"></span>
        <span v-else class="pending-dot">○</span>
      </span>
      <span class="content">
        <span v-if="t.status === 'in_progress' && t.activeForm" class="active-form">{{ t.activeForm }}</span>
        <span v-else>{{ t.content }}</span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Todo } from '@/types'
defineProps<{ todos: Todo[] }>()
</script>

<style scoped>
.todo-list {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--td-bg-color-container);
  border-bottom: 1px solid var(--td-component-stroke);
  padding: 8px 24px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
  font-size: 13px;
}
.todo-item {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  align-items: center;
  line-height: 1.5;
}
.todo-item.completed {
  color: var(--td-text-color-placeholder);
  text-decoration: line-through;
}
.todo-item.in_progress {
  color: var(--td-brand-color);
  font-weight: 500;
}
.todo-item.pending {
  color: var(--td-text-color-secondary);
}
.icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
}
.check {
  color: var(--td-success-color, #00a870);
  font-weight: bold;
}
.pending-dot {
  color: var(--td-text-color-placeholder);
}
.spinner {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--td-brand-color-light, #d9e5ff);
  border-top-color: var(--td-brand-color);
  animation: spin 0.8s linear infinite;
  display: inline-block;
}
.content {
  flex: 1 1 auto;
  word-break: break-word;
}
.active-form {
  font-style: italic;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>