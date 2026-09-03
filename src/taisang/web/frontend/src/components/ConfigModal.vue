<template>
  <t-dialog
    v-model:visible="visible"
    header="LLM 配置"
    :footer="false"
    width="520px"
    destroy-on-close
  >
    <t-form :data="formData" label-align="top" @submit="handleSubmit">
      <t-form-item label="Model" name="model">
        <t-input
          v-model="formData.model"
          placeholder="gpt-4o / glm-5.2 / Kimi-K2.6 / ..."
        />
      </t-form-item>

      <t-form-item label="API Key" name="api_key">
        <div class="api-key-row">
          <t-input
            v-model="formData.api_key"
            :readonly="apiKeyReadonly"
            :placeholder="apiKeyPlaceholder"
          />
          <t-button variant="outline" @click="handleEditApiKey">修改</t-button>
        </div>
      </t-form-item>

      <t-form-item label="Base URL" name="base_url">
        <t-input
          v-model="formData.base_url"
          placeholder="https://api.openai.com/v1"
        />
      </t-form-item>

      <div v-if="msg" class="cfg-msg" :class="{ error: msgError }">{{ msg }}</div>

      <div class="config-actions">
        <t-button variant="text" @click="visible = false">取消</t-button>
        <t-button theme="primary" :loading="saving" @click="handleSubmit">保存</t-button>
      </div>
    </t-form>
  </t-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { getConfig, saveConfig } from '@/api/config'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const formData = ref({
  model: '',
  api_key: '',
  base_url: '',
})
const apiKeyReadonly = ref(true)
const apiKeyPlaceholder = ref('(未设置)')
const apiKeyOriginal = ref('')  // 打码后的原值,用于恢复
const apiKeySet = ref(false)
const msg = ref('')
const msgError = ref(false)
const saving = ref(false)

async function loadConfig() {
  msg.value = ''
  msgError.value = false
  try {
    const cfg = await getConfig()
    formData.value.model = cfg.model || ''
    formData.value.base_url = cfg.base_url || ''
    formData.value.api_key = cfg.api_key || ''
    apiKeyOriginal.value = cfg.api_key || ''
    apiKeySet.value = cfg.api_key_set
    apiKeyPlaceholder.value = cfg.api_key_set ? cfg.api_key : '(未设置)'
    apiKeyReadonly.value = true
  } catch (e) {
    msg.value = '加载配置失败: ' + (e as Error).message
    msgError.value = true
  }
}

function handleEditApiKey() {
  apiKeyReadonly.value = false
  formData.value.api_key = ''
  apiKeyPlaceholder.value = '输入新的 api_key'
}

async function handleSubmit() {
  msg.value = ''
  msgError.value = false

  const model = formData.value.model.trim()
  const baseUrl = formData.value.base_url.trim()
  if (!model) {
    msg.value = 'model 不能为空'
    msgError.value = true
    return
  }
  if (!baseUrl) {
    msg.value = 'base_url 不能为空'
    msgError.value = true
    return
  }

  // api_key 只读 → __unchanged__ sentinel;可编辑 → 提交明文
  const apiKey = apiKeyReadonly.value ? '__unchanged__' : formData.value.api_key

  saving.value = true
  try {
    await saveConfig(model, apiKey, baseUrl)
    // 保存成功后恢复 readonly
    apiKeyReadonly.value = true
    formData.value.api_key = apiKeyOriginal.value
    visible.value = false
  } catch (e) {
    msg.value = '保存失败: ' + (e as Error).message
    msgError.value = true
  } finally {
    saving.value = false
  }
}

// 对话框打开时加载配置,关闭时重置
watch(visible, (v) => {
  if (v) {
    loadConfig()
  } else {
    msg.value = ''
    msgError.value = false
  }
})
</script>

<style scoped>
.api-key-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.api-key-row :deep(.t-input) {
  flex: 1;
}
.cfg-msg {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin: 8px 0;
  min-height: 18px;
}
.cfg-msg.error {
  color: var(--td-error-color, #d54941);
}
.config-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>