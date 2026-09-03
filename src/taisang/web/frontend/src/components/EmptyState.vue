<template>
  <div class="empty-state">
    <h1 class="title">开始对话</h1>
    <p class="subtitle">输入问题,Enter 发送</p>
    <div class="input-wrap">
      <MessageInput placeholder="输入问题,Enter 发送..." @send="handleSend" />
    </div>
  </div>
</template>

<script setup lang="ts">
import MessageInput from './MessageInput.vue'

const emit = defineEmits<{ send: [query: string] }>()

function handleSend(q: string) {
  emit('send', q)
}
</script>

<style scoped>
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  gap: 8px;
}
.title {
  font-size: 28px;
  font-weight: 600;
  color: var(--td-brand-color);
  margin: 0;
}
.subtitle {
  font-size: 14px;
  color: var(--td-text-color-placeholder);
  margin: 0 0 24px;
}
.input-wrap {
  width: 100%;
  max-width: 800px;
}
.input-wrap :deep(.message-input) {
  border-top: none;
  padding: 0;
}
</style>