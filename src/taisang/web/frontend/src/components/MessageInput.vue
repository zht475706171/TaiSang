<template>
  <div class="message-input">
    <div class="input-row">
      <textarea
        ref="taRef"
        v-model="text"
        class="query-textarea"
        :placeholder="placeholder"
        rows="1"
        @keydown="handleKeydown"
        @input="autoResize"
      ></textarea>
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
import { ref, nextTick } from 'vue'

withDefaults(defineProps<{ placeholder?: string }>(), {
  placeholder: '输入问题,Enter 发送,Shift+Enter 换行...',
})

const emit = defineEmits<{ send: [query: string] }>()
const text = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)

function autoResize() {
  const el = taRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

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
  nextTick(autoResize)
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
.query-textarea {
  flex: 1;
  resize: none;
  padding: 8px 12px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 6px;
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
  font-family: var(--app-font-family);
  font-size: 14px;
  line-height: 1.5;
  min-height: 36px;
  max-height: 200px;
  overflow-y: auto;
  outline: none;
  transition: border-color 0.15s;
}
.query-textarea:focus {
  border-color: var(--td-brand-color);
}
.query-textarea::placeholder {
  color: var(--td-text-color-placeholder);
}
</style>