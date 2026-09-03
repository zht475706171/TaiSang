<template>
  <div class="usage-line">
    <span>turn: prompt={{ turn?.prompt ?? '-' }} completion={{ turn?.completion ?? '-' }} total={{ turn?.total ?? '-' }}</span>
    <span> · session: {{ session.total }}</span>
    <span v-if="cache.available"> · cache {{ cacheRate }}%</span>
    <span v-else> · cache N/A</span>
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
  color: var(--td-text-color-placeholder);
  padding: 2px 4px;
  margin-top: -4px;
}
</style>