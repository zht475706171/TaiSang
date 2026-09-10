<template>
  <div class="api-key-input">
    <!-- 只读态:显示 ******** 占位 + 眼睛看明文 + 修改按钮 -->
    <template v-if="readonly">
      <t-input
        :value="displayValue"
        :type="eyeOpen ? 'text' : 'password'"
        readonly
        :placeholder="placeholder"
      >
        <template #suffix>
          <t-button
            variant="text"
            shape="square"
            size="small"
            class="eye-btn"
            :title="eyeOpen ? '隐藏' : '查看'"
            @click="eyeOpen = !eyeOpen"
          >
            <template #icon>
              <t-icon :name="eyeOpen ? 'browse' : 'browse-off'" />
            </template>
          </t-button>
        </template>
      </t-input>
      <t-button variant="outline" size="small" @click="$emit('edit')">修改</t-button>
    </template>

    <!-- 编辑态:明文输入 + 眼睛切换显隐 -->
    <template v-else>
      <t-input
        :model-value="modelValue"
        :type="eyeOpen ? 'text' : 'password'"
        :placeholder="editPlaceholder"
        @update:model-value="$emit('update:modelValue', $event)"
      >
        <template #Suffix>
          <t-button
            variant="text"
            shape="square"
            size="small"
            class="eye-btn"
            :title="eyeOpen ? '隐藏' : '查看'"
            @click="eyeOpen = !eyeOpen"
          >
            <template #icon>
              <t-icon :name="eyeOpen ? 'browse' : 'browse-off'" />
            </template>
          </t-button>
        </template>
      </t-input>
      <t-button variant="text" size="small" @click="$emit('cancel')">取消</t-button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = withDefaults(defineProps<{
  /** 编辑态 v-model 值(明文) */
  modelValue?: string
  /** 只读态:是否已设置 key(决定显示 ******** 还是 placeholder) */
  apiKeySet?: boolean
  /** 只读态:打码后的原值(如 sk-***xxxx),眼睛打开时显示 */
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

const eyeOpen = ref(false)

/** 只读态显示值:已设置 → 固定 ********(不暴露打码内容);未设置 → 空(走 placeholder) */
const displayValue = computed(() => {
  if (props.apiKeySet) {
    return eyeOpen.value ? props.maskedValue : '********'
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
.eye-btn {
  color: var(--td-text-color-placeholder);
}
.eye-btn:hover {
  color: var(--td-brand-color);
}
</style>