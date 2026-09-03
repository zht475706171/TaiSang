<template>
  <div class="message-input">
    <div class="input-row">
      <t-textarea
        v-model="text"
        :placeholder="placeholder"
        :autosize="{ minRows: 1, maxRows: 6 }"
        @keydown="handleKeydown"
      />
      <t-button theme="primary" :disabled="!text.trim()" @click="handleSend">
        <template #icon>
          <t-icon name="send" />
        </template>
        发送
      </t-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

withDefaults(defineProps<{ placeholder?: string }>(), {
  placeholder: '输入问题,Enter 发送,Shift+Enter 换行...',
})

const emit = defineEmits<{ send: [query: string] }>()
const text = ref('')

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleSend() {
  const q = text.value.trim()
  if (!q) return
  emit('send', q)
  text.value = ''
}
</script>

<style scoped>
.message-input {
  padding: 12px 24px 20px;
  background: var(--td-bg-color-container);
  border-top: 1px solid var(--td-component-stroke);
}
.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  max-width: 800px;
  margin: 0 auto;
}
.input-row :deep(.t-textarea) {
  flex: 1;
}
</style>