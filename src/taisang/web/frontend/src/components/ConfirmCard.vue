<template>
  <div class="confirm-card" :class="{ answered: msg.answered }">
    <div class="title">
      <template v-if="msg.kind === 'confirm'">
        <template v-if="msg.answered">{{ msg.approved ? '✓ 已允许' : '✗ 已拒绝' }}</template>
        <template v-else>▸ agent 想修改文件</template>
      </template>
      <template v-else>
        <template v-if="msg.answered">{{ msg.approved ? '✓ 已允许' : '✗ 已拒绝' }}</template>
        <template v-else>▸ agent 想访问目录</template>
      </template>
    </div>
    <div class="path">{{ msg.kind === 'confirm' ? msg.filePath : msg.path }}</div>
    <div v-if="msg.kind === 'confirm'" class="diff">
      <template v-if="msg.oldContent">
        <div class="del-line">- {{ msg.oldContent.slice(0, 500) }}</div>
        <div class="add-line">+ {{ msg.newContent?.slice(0, 500) }}</div>
      </template>
      <template v-else>
        (新文件, {{ msg.newContent?.length ?? 0 }} 字符)
      </template>
    </div>
    <div v-if="!msg.answered" class="actions">
      <t-button size="small" theme="primary" @click="handle(true)">允许</t-button>
      <t-button size="small" theme="danger" variant="outline" @click="handle(false)">拒绝</t-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage } from '@/types'

const props = defineProps<{ msg: ChatMessage }>()
const emit = defineEmits<{ answer: [token: string, approve: boolean] }>()

function handle(approve: boolean) {
  if (props.msg.token) {
    emit('answer', props.msg.token, approve)
  }
}
</script>

<style scoped>
.confirm-card {
  margin: 8px 0;
  padding: 12px;
  border: 1px solid var(--td-warning-color, #ed7b2f);
  border-radius: 8px;
  background: var(--td-bg-color-container);
  font-size: 13px;
}
.confirm-card.answered {
  border-color: var(--td-component-stroke);
  opacity: 0.7;
}
.title {
  font-weight: 500;
  color: var(--td-text-color-primary);
  margin-bottom: 6px;
}
.path {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--td-text-color-secondary);
  margin-bottom: 8px;
  word-break: break-all;
}
.diff {
  font-family: var(--app-font-mono);
  font-size: 11px;
  margin-bottom: 8px;
  max-height: 160px;
  overflow-y: auto;
}
.del-line {
  color: var(--td-error-color, #d54941);
  white-space: pre-wrap;
}
.add-line {
  color: var(--td-success-color, #2ba471);
  white-space: pre-wrap;
}
.actions {
  display: flex;
  gap: 8px;
}
</style>