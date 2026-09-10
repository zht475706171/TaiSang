<template>
  <div ref="listRef" class="message-list">
    <template v-for="m in messages" :key="m.id">
      <div v-if="m.kind === 'user'" class="msg user">{{ m.text }}</div>
      <div v-else-if="m.kind === 'assistant'" class="msg assistant">
        <div class="content" v-html="renderMarkdown(m.text || '')"></div>
      </div>
      <ToolCard v-else-if="m.kind === 'tool_call' || m.kind === 'tool_result'" :msg="m" />
      <div v-else-if="m.kind === 'thinking'" class="msg thinking">
        <div class="content reasoning">{{ m.text }}</div>
      </div>
      <div v-else-if="m.kind === 'compacted'" class="compacted">
        <template v-if="m.stage === 1">
          · ① tool_result_budget 压缩:{{ m.replaced?.length || 0 }} 个大结果持久化到磁盘
          <span v-if="m.replaced?.length" class="compacted-detail">
            ({{ m.replaced.map(r => r.tool_call_id.slice(0, 8)).join(', ') }})
          </span>
        </template>
        <template v-else-if="m.stage === 2">
          · ② autocompact {{ m.via === 'llm' ? 'LLM 摘要' : 'session_memory 摘要' }}:
          {{ m.beforeTokens }} → {{ m.afterTokens }} tokens
          <span v-if="m.summaryMessages">({{ m.summaryMessages }} 条摘要)</span>
        </template>
        <template v-else-if="m.stage === 3">
          · ③ session_memory 提取:触发 {{ m.trigger }} 分支
          <span v-if="m.currentTokens != null">
            (当前 {{ m.currentTokens }} tokens<template v-if="m.deltaTokens != null">, 增量 {{ m.deltaTokens }}</template>)
          </span>
        </template>
        <template v-else>
          · context compacted via {{ m.via }}
        </template>
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
    <!-- thinking / stopping 指示器放底部:用户视线在最新消息下方,符合"等待回复出现"的直觉 -->
    <ThinkingIndicator
      v-if="thinking || stopping"
      :stopping="stopping"
      :retry-info="retryInfo"
      :reasoning-text="reasoningText"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import type { ChatMessage } from '@/types'
import ThinkingIndicator from './ThinkingIndicator.vue'
import ToolCard from './ToolCard.vue'
import ConfirmCard from './ConfirmCard.vue'
import UsageLine from './UsageLine.vue'

const props = defineProps<{
  messages: ChatMessage[]
  thinking: boolean
  stopping?: boolean
  retryInfo?: { attempt: number; delaySec: number } | null
  reasoningText?: string
}>()

const listRef = ref<HTMLDivElement | null>(null)

function scrollToBottom() {
  const el = listRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

// 消息列表变化(新增/更新)→ 自动滚到底
watch(
  () => props.messages.length,
  () => nextTick(scrollToBottom),
)

// thinking 出现也滚(用户发完消息立刻看到 loading 态)
watch(
  () => props.thinking,
  () => nextTick(scrollToBottom),
)

// stopping 出现也滚(停止中提示要可见)
watch(
  () => props.stopping,
  () => nextTick(scrollToBottom),
)

// retryInfo 出现也滚(重试提示要可见)
watch(
  () => props.retryInfo,
  () => nextTick(scrollToBottom),
)

onMounted(scrollToBottom)

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
.compacted-detail {
  color: var(--td-text-color-placeholder);
  font-size: 11px;
}
.msg.thinking {
  align-self: flex-start;
  background: var(--td-bg-color-secondarycontainer, #f5f5f5);
  border-left: 3px solid var(--td-brand-color, #0052d9);
  padding: 8px 12px;
  margin: 4px 0;
  border-radius: 4px;
  max-width: 100%;
}
.msg.thinking .reasoning {
  font-size: 13px;
  color: var(--td-text-color-secondary, #666);
  font-family: var(--app-font-mono);
  white-space: pre-wrap;
  line-height: 1.6;
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