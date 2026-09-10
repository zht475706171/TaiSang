<template>
  <div class="empty-state">
    <p class="subtitle">
      你好，我是TaiSang。<br />
      你的私人agent，有什么可以帮助你的吗？
    </p>
    <div class="input-wrap">
      <MessageInput
        placeholder="输入问题,Enter 发送..."
        autofocus
        :source-root="sourceRoot"
        @send="handleSend"
        @import-project="handleImportProject"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import MessageInput from './MessageInput.vue'

defineProps<{ sourceRoot?: string | null }>()
const emit = defineEmits<{
  send: [query: string]
  importProject: []
}>()

function handleSend(q: string) {
  emit('send', q)
}

function handleImportProject() {
  emit('importProject')
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
.subtitle {
  font-size: 28px;
  font-weight: 600;
  color: var(--td-brand-color);
  line-height: 1.4;
  text-align: center;
  margin: 0 0 24px;
}
.input-wrap {
  width: 100%;
  max-width: 800px;
}
.input-wrap :deep(.message-input) {
  padding: 0;
}
</style>