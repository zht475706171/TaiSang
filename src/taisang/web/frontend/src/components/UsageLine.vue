<template>
  <div class="usage-line">
    <span class="label">本轮:</span>
    <span class="k-prompt">输入 {{ turn?.prompt ?? '-' }}</span>
    <span class="k-completion">输出 {{ turn?.completion ?? '-' }}</span>
    <span class="k-total">共 {{ turn?.total ?? '-' }}</span>
    <span class="sep">·</span>
    <span class="k-session">累计 {{ session.total }}</span>
    <span class="sep">·</span>
    <span v-if="cache.available" class="k-cache">缓存 {{ cacheRate }}%</span>
    <span v-else class="k-cache-na">缓存 N/A</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { UsageData } from '@/types'

const props = defineProps<{ usage: UsageData }>()
const turn = computed(() => props.usage.turn)
const session = computed(() => props.usage.session)
const cache = computed(() => props.usage.cache)
const cacheRate = computed(() => {
  const hit = cache.value.cached_tokens ?? 0
  const prompt = turn.value?.prompt ?? 0
  return prompt ? (hit / prompt * 100).toFixed(1) : '0.0'
})
</script>

<style scoped>
.usage-line {
  font-family: var(--app-font-mono);
  font-size: 11px;
  padding: 2px 4px;
  margin-top: -4px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.label {
  color: var(--td-text-color-placeholder);
}
.k-prompt {
  color: var(--td-text-color-secondary);
}
.k-completion {
  color: var(--td-brand-color);
}
.k-total {
  color: var(--td-text-color-secondary);
}
.k-session {
  color: var(--td-success-color);
}
.k-cache {
  color: var(--td-text-color-placeholder);
}
.k-cache-na {
  color: var(--td-text-color-placeholder);
  opacity: 0.6;
}
.sep {
  color: var(--td-text-color-placeholder);
  opacity: 0.5;
}
</style>