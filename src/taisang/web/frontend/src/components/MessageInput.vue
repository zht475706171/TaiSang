<template>
  <div class="message-input">
    <div class="input-row">
      <textarea
        ref="taRef"
        v-model="text"
        class="query-textarea"
        :placeholder="placeholder"
        rows="1"
        aria-label="输入消息,Enter 发送,Shift+Enter 换行"
        @keydown="handleKeydown"
        @input="autoResize"
      ></textarea>
      <t-button
        v-if="!streaming"
        shape="circle"
        theme="primary"
        aria-label="发送"
        :disabled="!text.trim()"
        @click="handleSend"
      >
        <template #icon>
          <t-icon name="send" />
        </template>
      </t-button>
      <t-button
        v-else
        shape="circle"
        theme="danger"
        aria-label="停止"
        @click="handleStop"
      >
        <template #icon>
          <t-icon name="stop" />
        </template>
      </t-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'

const props = withDefaults(defineProps<{ placeholder?: string; autofocus?: boolean; streaming?: boolean }>(), {
  placeholder: '输入问题,Enter 发送,Shift+Enter 换行...',
  autofocus: false,
  streaming: false,
})

const emit = defineEmits<{ send: [query: string]; stop: [] }>()
const text = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)

onMounted(() => {
  if (props.autofocus && taRef.value) {
    taRef.value.focus()
  }
})

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

function handleStop() {
  emit('stop')
}
</script>

<style scoped>
.message-input {
  padding: 0 24px 20px;
}
/* 一体化输入行:大圆角容器,textarea 与圆形发送按钮同体 */
.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  max-width: 800px;
  margin: 0 auto;
  padding: 8px 8px 8px 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 14px;
  background: var(--td-bg-color-container);
  transition: border-color 0.15s;
}
.input-row:focus-within {
  border-color: var(--td-brand-color);
}
.query-textarea {
  flex: 1;
  resize: none;
  border: none;
  background: transparent;
  padding: 7px 0;
  color: var(--td-text-color-primary);
  font-family: var(--app-font-family);
  font-size: 14px;
  line-height: 1.5;
  min-height: 36px;
  max-height: 200px;
  overflow-y: auto;
  outline: none;
}
.query-textarea::placeholder {
  color: var(--td-text-color-placeholder);
}
</style>
