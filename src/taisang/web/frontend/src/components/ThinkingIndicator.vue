<template>
  <div class="thinking">
    <span class="label">thinking</span>
    <span v-if="retryInfo" class="retry-badge">
      第 {{ retryInfo.attempt }} 次重试中({{ retryInfo.delaySec.toFixed(1) }}s 后)
    </span>
    <span class="dots">
      <span></span>
      <span></span>
      <span></span>
    </span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  retryInfo?: { attempt: number; delaySec: number } | null
}>()
</script>

<style scoped>
.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
  font-family: var(--app-font-mono);
}
.retry-badge {
  color: var(--td-warning-color, #b25803);
  background: var(--td-warning-color-1, #fff3e0);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  border: 1px solid var(--td-warning-color-2, #ffcc80);
}
.dots {
  display: inline-flex;
  gap: 3px;
}
.dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--td-brand-color);
  animation: thinking-bounce 1.2s infinite ease-in-out;
}
.dots span:nth-child(2) { animation-delay: 0.15s; }
.dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes thinking-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-4px); opacity: 1; }
}
</style>