<template>
  <t-dialog
    v-model:visible="visible"
    header="LLM 配置"
    :footer="false"
    width="500px"
    destroy-on-close
  >
    <div class="config-placeholder">
      <p>配置页将在 Plan 4 实现</p>
      <p class="hint">当前入口已就位,表单待填</p>
    </div>
  </t-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})
</script>

<style scoped>
.config-placeholder {
  padding: 24px 0;
  text-align: center;
  color: var(--td-text-color-placeholder);
}
.config-placeholder p {
  margin: 4px 0;
}
.config-placeholder .hint {
  font-size: 12px;
}
</style>