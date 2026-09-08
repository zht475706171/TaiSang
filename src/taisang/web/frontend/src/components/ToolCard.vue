<template>
  <div class="tool-card" :class="{ expanded }" :data-tool-name="msg.toolName">
    <div class="tool-card-header" @click="expanded = !expanded">
      <span class="arrow">▶</span>
      <span class="name">{{ msg.toolName }}</span>
      <span class="args">{{ argsLabel }}</span>
      <span v-if="msg.subAgentEvents?.length" class="sub-badge">{{ msg.subAgentEvents.length }} 子事件</span>
    </div>
    <div class="tool-card-body">
      <div class="main-preview">{{ msg.toolPreview || '执行中...' }}</div>
      <div v-if="msg.subAgentEvents?.length" class="sub-events">
        <div
          v-for="sub in msg.subAgentEvents"
          :key="sub.id"
          class="sub-event"
          :data-sub-agent-event="sub.kind"
        >
          <span class="sub-kind">{{ subLabel(sub) }}</span>
          <span v-if="sub.kind === 'tool_call'" class="sub-text">{{ sub.toolName }} {{ sub.toolArgs }}</span>
          <span v-else-if="sub.kind === 'tool_result'" class="sub-text">{{ sub.toolPreview }}</span>
          <span v-else-if="sub.kind === 'assistant'" class="sub-text">{{ sub.text }}</span>
          <span v-else-if="sub.kind === 'usage'" class="sub-text usage">{{ usageLabel(sub) }}</span>
          <span v-else-if="sub.kind === 'compacted'" class="sub-text">[compact: {{ sub.via }}]</span>
          <span v-else class="sub-text">{{ sub.kind }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChatMessage } from '@/types'

const props = defineProps<{ msg: ChatMessage }>()
const expanded = ref(false)

const argsLabel = computed(() => {
  if (props.msg.toolFilled && props.msg.toolBytes != null) {
    return `${props.msg.toolBytes} bytes`
  }
  return props.msg.toolArgs || ''
})

// Task 14: 子 agent 事件标签 + 用量标注
function subLabel(sub: ChatMessage): string {
  const map: Record<string, string> = {
    tool_call: '🔧',
    tool_result: '↩',
    assistant: '✓',
    usage: '📊',
    llm_thinking: '…',
    thinking: '…',
    compacted: '∙',
  }
  return map[sub.kind] || '·'
}

function usageLabel(sub: ChatMessage): string {
  if (!sub.usage) return ''
  const t = sub.usage.turn?.total ?? 0
  return `子 agent 用了 ${t} token`
}
</script>

<style scoped>
.tool-card {
  margin: 6px 0;
  border: 1px solid var(--td-component-stroke);
  border-radius: 6px;
  background: var(--td-bg-color-secondarycontainer);
  overflow: hidden;
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.tool-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
}
.tool-card-header:hover {
  background: var(--td-bg-color-container);
}
.arrow {
  color: var(--td-brand-color);
  transition: transform 0.15s;
  font-size: 10px;
}
.tool-card.expanded .arrow {
  transform: rotate(90deg);
}
.name {
  color: var(--td-text-color-primary);
  font-weight: 500;
}
.args {
  color: var(--td-text-color-placeholder);
  margin-left: auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 40%;
}
.tool-card-body {
  padding: 8px 10px;
  border-top: 1px solid var(--td-component-stroke);
  color: var(--td-text-color-secondary);
  max-height: 240px;
  overflow-y: auto;
  display: none;
}
.tool-card.expanded .tool-card-body {
  display: block;
}
.main-preview {
  white-space: pre-wrap;
  word-break: break-all;
}
.sub-badge {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--td-brand-color-1);
  color: var(--td-brand-color);
  font-size: 10px;
  white-space: nowrap;
}
.sub-events {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--td-component-stroke);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sub-event {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding-left: 8px;
  border-left: 2px solid var(--td-component-stroke);
  font-size: 11px;
  color: var(--td-text-color-secondary);
}
.sub-kind {
  flex: 0 0 auto;
  width: 14px;
  text-align: center;
  color: var(--td-brand-color);
}
.sub-text {
  flex: 1 1 auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.sub-text.usage {
  color: var(--td-warning-color);
  font-style: italic;
}
</style>