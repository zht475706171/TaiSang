<template>
  <div class="message-list">
    <ThinkingIndicator v-if="thinking" />
    <template v-for="m in messages" :key="m.id">
      <div v-if="m.kind === 'user'" class="msg user">{{ m.text }}</div>
      <div v-else-if="m.kind === 'assistant'" class="msg assistant">
        <div class="content" v-html="renderMarkdown(m.text || '')"></div>
      </div>
      <ToolCard v-else-if="m.kind === 'tool_call' || m.kind === 'tool_result'" :msg="m" />
      <div v-else-if="m.kind === 'compacted'" class="compacted">
        · context compacted via {{ m.via }}
      </div>
      <ConfirmCard
        v-else-if="m.kind === 'confirm' || m.kind === 'permission'"
        :msg="m"
        @answer="handleAnswer"
      />
      <div v-else-if="m.kind === 'usage'" class="usage">
        <UsageLine :usage="m.usage!" />
      </div>
      <div v-else-if="m.kind === 'run_error'" class="run-error">
        错误: {{ m.error }}
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage } from '@/types'
import ThinkingIndicator from './ThinkingIndicator.vue'
import ToolCard from './ToolCard.vue'
import ConfirmCard from './ConfirmCard.vue'
import UsageLine from './UsageLine.vue'

defineProps<{
  messages: ChatMessage[]
  thinking: boolean
}>()

const emit = defineEmits<{ answer: [token: string, approve: boolean] }>()

function handleAnswer(token: string, approve: boolean) {
  emit('answer', token, approve)
}

// 简单 markdown 渲染:暂不引入 marked,先做 **code** 和 `inline code`
function renderMarkdown(text: string): string {
  // 转义
  const esc = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  // code block ```
  return esc
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}
.msg {
  margin: 12px 0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}
.msg.user {
  background: var(--td-brand-color-light);
  color: var(--td-text-color-primary);
  margin-left: 40px;
}
.msg.assistant {
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);
}
.msg.assistant :deep(pre) {
  background: var(--td-bg-color-secondarycontainer);
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  font-family: var(--app-font-mono);
  font-size: 12px;
  margin: 8px 0;
}
.msg.assistant :deep(code) {
  font-family: var(--app-font-mono);
  font-size: 13px;
}
.msg.assistant :deep(pre code) {
  background: transparent;
  padding: 0;
}
.compacted {
  text-align: center;
  color: var(--td-text-color-placeholder);
  font-size: 12px;
  font-family: var(--app-font-mono);
  padding: 4px;
  margin: 8px 0;
}
.usage {
  margin: 4px 0;
}
.run-error {
  color: var(--td-error-color, #d54941);
  background: var(--td-error-color-1, #fff0f0);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  margin: 8px 0;
}
</style>