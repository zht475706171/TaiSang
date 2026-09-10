<template>
  <div class="api-key-input">
    <!-- 只读态:type=password(密文) + TDesign 内置眼睛切换 + 修改按钮 -->
    <template v-if="readonly">
      <t-input
        :value="displayValue"
        type="password"
        readonly
        :placeholder="placeholder"
      />
      <t-button variant="outline" size="small" @click="$emit('edit')">修改</t-button>
    </template>

    <!-- 编辑态:type=password(密文) + TDesign 内置眼睛切换 + 取消按钮 -->
    <template v-else>
      <t-input
        :model-value="modelValue"
        type="password"
        :placeholder="editPlaceholder"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <t-button variant="text" size="small" @click="$emit('cancel')">取消</t-button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  /** 编辑态 v-model 值(明文) */
  modelValue?: string
  /** 只读态:是否已设置 key */
  apiKeySet?: boolean
  /** 只读态:完整 api_key(后端返回完整明文,前端 type=password 自动遮成密文) */
  maskedValue?: string
  /** 只读态 placeholder */
  placeholder?: string
  /** 编辑态 placeholder */
  editPlaceholder?: string
  /** 是否只读 */
  readonly?: boolean
}>(), {
  modelValue: '',
  apiKeySet: false,
  maskedValue: '',
  placeholder: '(未设置)',
  editPlaceholder: '输入新的 api_key',
  readonly: true,
})

defineEmits<{
  'update:modelValue': [value: string]
  edit: []
  cancel: []
}>()

/** 只读态显示值:已设置 → 完整 key(TDesign password 模式自动遮密文,眼睛切换显隐);未设置 → 空 */
const displayValue = computed(() => {
  if (props.apiKeySet) {
    return props.maskedValue
  }
  return ''
})
</script>

<style scoped>
.api-key-input {
  display: flex;
  gap: 8px;
  width: 100%;
  align-items: center;
}
.api-key-input :deep(.t-input) {
  flex: 1;
}
</style>