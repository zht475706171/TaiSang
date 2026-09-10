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

      <t-form-item name="debug">
        <div class="debug-row">
          <div class="debug-label">
            <div class="debug-title">Debug 模式</div>
            <div class="debug-desc">
              开启后展示所有工具调用 + 思考过程 + 完整工具结果;关闭后只展示用户问题和最终答案
            </div>
          </div>
          <t-switch v-model="formData.debug" />
        </div>
      </t-form-item>

      <div v-if="msg" class="cfg-msg" :class="{ error: msgError }">{{ msg }}</div>

      <div class="config-actions">
        <t-button variant="text" @click="visible = false">取消</t-button>
        <t-button
          variant="outline"
          :loading="testing"
          :disabled="!canTest"
          @click="handleTestConnection"
        >
          测试连接
        </t-button>
        <t-button theme="primary" :loading="saving" @click="handleSubmit">保存</t-button>
      </div>

      <div v-if="testResult" class="test-result" :class="{ ok: testResult.ok, error: !testResult.ok }">
        <template v-if="testResult.ok">
          ✅ 连接成功 · {{ testResult.latency_ms }}ms · 回复:{{ testResult.reply || '(空)' }}
        </template>
        <template v-else>
          ❌ 连接失败:{{ testResult.error }}
        </template>
      </div>
    </t-form>
  </t-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { getConfig, saveConfig, testConfig, type ConfigTestResult } from '@/api/config'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'debug-changed': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const formData = ref({
  model: '',
  api_key: '',
  base_url: '',
  debug: false,
})
const apiKeyReadonly = ref(true)
const apiKeyPlaceholder = ref('(未设置)')
const apiKeyOriginal = ref('')  // 打码后的原值,用于恢复
const apiKeySet = ref(false)
const msg = ref('')
const msgError = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<ConfigTestResult | null>(null)
const debugOriginal = ref(false)  // 加载时的 debug 值,用于判断是否变了

// 测试连接需要 model + base_url 都填了
const canTest = computed(() => {
  return formData.value.model.trim() !== '' && formData.value.base_url.trim() !== ''
})

async function loadConfig() {
  msg.value = ''
  msgError.value = false
  testResult.value = null
  try {
    const cfg = await getConfig()
    formData.value.model = cfg.model || ''
    formData.value.base_url = cfg.base_url || ''
    formData.value.api_key = cfg.api_key || ''
    formData.value.debug = cfg.debug ?? false
    apiKeyOriginal.value = cfg.api_key || ''
    apiKeySet.value = cfg.api_key_set
    apiKeyPlaceholder.value = cfg.api_key_set ? cfg.api_key : '(未设置)'
    apiKeyReadonly.value = true
    debugOriginal.value = cfg.debug ?? false
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

async function handleTestConnection() {
  msg.value = ''
  msgError.value = false
  testResult.value = null

  const model = formData.value.model.trim()
  const baseUrl = formData.value.base_url.trim()
  const apiKey = apiKeyReadonly.value ? '__unchanged__' : formData.value.api_key

  testing.value = true
  try {
    testResult.value = await testConfig(model, apiKey, baseUrl)
  } catch (e) {
    testResult.value = { ok: false, error: (e as Error).message }
  } finally {
    testing.value = false
  }
}

async function handleSubmit() {
  msg.value = ''
  msgError.value = false
  testResult.value = null

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
    await saveConfig(model, apiKey, baseUrl, formData.value.debug)
    // 通知外部 debug 状态变了(useChatStream 据 debug 决定是否 gate 工具卡片)
    if (formData.value.debug !== debugOriginal.value) {
      emit('debug-changed', formData.value.debug)
      debugOriginal.value = formData.value.debug
    }
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
    testResult.value = null
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
.debug-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.debug-label {
  flex: 1;
}
.debug-title {
  font-size: 14px;
  font-weight: 500;
}
.debug-desc {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin-top: 2px;
  line-height: 1.5;
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
.test-result {
  font-size: 12px;
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 4px;
  line-height: 1.5;
}
.test-result.ok {
  color: var(--td-success-color, #2ba471);
  background: var(--td-success-bg-color, #e8f7ef);
}
.test-result.error {
  color: var(--td-error-color, #d54941);
  background: var(--td-error-bg-color, #fdecee);
}
</style>