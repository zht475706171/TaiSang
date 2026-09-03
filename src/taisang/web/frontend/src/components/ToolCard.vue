<template>
  <div class="tool-card" :class="{ expanded }">
    <div class="tool-card-header" @click="expanded = !expanded">
      <span class="arrow">▶</span>
      <span class="name">{{ msg.toolName }}</span>
      <span class="args">{{ argsLabel }}</span>
    </div>
    <div class="tool-card-body">{{ msg.toolPreview || '执行中...' }}</div>
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
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--td-text-color-secondary);
  max-height: 200px;
  overflow-y: auto;
  display: none;
}
.tool-card.expanded .tool-card-body {
  display: block;
}
</style>