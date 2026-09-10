<template>
  <t-dialog
    v-model:visible="visible"
    header="LLM 配置"
    :footer="false"
    width="520px"
    destroy-on-close
    class="config-dialog"
  >
    <div class="cfg-body">
      <!-- 顶部:子 Agent 独立配置开关卡 -->
      <div class="toggle-card" :class="{ active: subForm.enabled }">
        <div class="toggle-left">
          <div class="toggle-icon">
            <t-icon name="root-list" />
          </div>
          <div class="toggle-text">
            <div class="toggle-title-row">
              <span class="toggle-title">子 Agent 独立配置</span>
              <t-tag v-if="subForm.enabled" size="small" class="enabled-pill">已启用</t-tag>
            </div>
            <div class="toggle-desc">开启时,主子 Agent 将分别使用独立的配置</div>
          </div>
        </div>
        <t-switch v-model="subForm.enabled" />
      </div>

      <!-- 主 Agent 卡 -->
      <div class="config-card">
        <div class="card-title-row">
          <span class="card-accent-bar"></span>
          <span class="card-title">主 Agent</span>
          <t-tag v-if="mainKeySet" theme="success" size="small" variant="light">已配置</t-tag>
        </div>
        <t-form-item label="Model" name="main_model">
          <t-input
            v-model="mainForm.model"
            placeholder="gpt-4o / glm-5.2 / Kimi-K2.6 / ..."
          />
        </t-form-item>
        <t-form-item label="API Key" name="main_api_key">
          <ApiKeyInput
            v-model="mainForm.api_key"
            :read-only="mainKeyReadonly"
            :api-key-set="mainKeySet"
            :masked-value="mainKeyMasked"
            @edit="mainKeyReadonly = false"
            @cancel="cancelEditMainKey"
          />
        </t-form-item>
        <t-form-item label="Base URL" name="main_base_url">
          <t-input
            v-model="mainForm.base_url"
            placeholder="https://api.openai.com/v1"
          />
        </t-form-item>
        <div class="card-test-row">
          <t-button
            variant="outline"
            size="small"
            :loading="mainTesting"
            :disabled="!canTestMain"
            @click="handleTestMain"
          >
            测试连接
          </t-button>
          <span v-if="mainTestResult" class="test-result" :class="{ ok: mainTestResult.ok, error: !mainTestResult.ok }">
            <template v-if="mainTestResult.ok">✅ 连接成功 · {{ mainTestResult.latency_ms }}ms</template>
            <template v-else>❌ {{ mainTestResult.error }}</template>
          </span>
        </div>
      </div>

      <div class="card-divider"></div>

      <!-- 子 Agent 卡(仅 enabled 时渲染) -->
      <div v-if="subForm.enabled" class="config-card">
        <div class="card-title-row">
          <span class="card-accent-bar"></span>
          <span class="card-title">子 Agent</span>
        </div>
        <t-form-item label="Model" name="sub_model">
          <t-input
            v-model="subForm.model"
            placeholder="子 agent 使用的模型"
          />
        </t-form-item>
        <t-form-item label="API Key" name="sub_api_key">
          <ApiKeyInput
            v-model="subForm.api_key"
            :read-only="subKeyReadonly"
            :api-key-set="subKeySet"
            :masked-value="subKeyMasked"
            @edit="subKeyReadonly = false"
            @cancel="cancelEditSubKey"
          />
        </t-form-item>
        <t-form-item label="Base URL" name="sub_base_url">
          <t-input
            v-model="subForm.base_url"
            placeholder="https://api.openai.com/v1"
          />
        </t-form-item>
        <div class="card-test-row">
          <t-button
            variant="outline"
            size="small"
            :loading="subTesting"
            :disabled="!canTestSub"
            @click="handleTestSub"
          >
            测试连接
          </t-button>
          <span v-if="subTestResult" class="test-result" :class="{ ok: subTestResult.ok, error: !subTestResult.ok }">
            <template v-if="subTestResult.ok">✅ 连接成功 · {{ subTestResult.latency_ms }}ms</template>
            <template v-else>❌ {{ subTestResult.error }}</template>
          </span>
        </div>
      </div>

      <div class="card-divider" v-if="subForm.enabled"></div>

      <!-- Debug 卡 -->
      <div class="config-card debug-card">
        <div class="debug-row">
          <div class="debug-label">
            <div class="card-title-row">
              <span class="card-accent-bar"></span>
              <span class="card-title">Debug 模式</span>
            </div>
            <div class="debug-desc">
              开启后展示所有工具调用 + 思考过程 + 完整工具结果;关闭后只展示用户问题和最终答案
            </div>
          </div>
          <t-switch v-model="debugForm" />
        </div>
      </div>

      <div v-if="msg" class="cfg-msg" :class="{ error: msgError }">{{ msg }}</div>

      <!-- 操作区 -->
      <div class="config-actions">
        <t-button variant="text" @click="visible = false">取消</t-button>
        <t-button theme="primary" :loading="saving" @click="handleSubmit">保存</t-button>
      </div>
    </div>
  </t-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { getConfig, saveConfig, testConfig, type ConfigTestResult } from '@/api/config'
import ApiKeyInput from './ApiKeyInput.vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'debug-changed': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

interface SectionForm {
  model: string
  api_key: string
  base_url: string
}

const mainForm = ref<SectionForm>({ model: '', api_key: '', base_url: '' })
const subForm = ref<SectionForm & { enabled: boolean }>({ enabled: false, model: '', api_key: '', base_url: '' })
const debugForm = ref(false)

const mainKeyReadonly = ref(true)
const subKeyReadonly = ref(true)
const mainKeySet = ref(false)
const subKeySet = ref(false)
const mainKeyMasked = ref('')
const subKeyMasked = ref('')

const msg = ref('')
const msgError = ref(false)
const saving = ref(false)
const mainTesting = ref(false)
const subTesting = ref(false)
const mainTestResult = ref<ConfigTestResult | null>(null)
const subTestResult = ref<ConfigTestResult | null>(null)
const debugOriginal = ref(false)

const canTestMain = computed(() => mainForm.value.model.trim() !== '' && mainForm.value.base_url.trim() !== '')
const canTestSub = computed(() => subForm.value.model.trim() !== '' && subForm.value.base_url.trim() !== '')

async function loadConfig() {
  msg.value = ''
  msgError.value = false
  mainTestResult.value = null
  subTestResult.value = null
  try {
    const cfg = await getConfig()
    mainForm.value.model = cfg.main.model || ''
    mainForm.value.base_url = cfg.main.base_url || ''
    mainForm.value.api_key = ''
    mainKeySet.value = cfg.main.api_key_set
    mainKeyMasked.value = cfg.main.api_key || ''
    mainKeyReadonly.value = true
    debugForm.value = cfg.main.debug ?? false
    debugOriginal.value = cfg.main.debug ?? false

    subForm.value.enabled = cfg.subagent.enabled ?? false
    subForm.value.model = cfg.subagent.model || ''
    subForm.value.base_url = cfg.subagent.base_url || ''
    subForm.value.api_key = ''
    subKeySet.value = cfg.subagent.api_key_set
    subKeyMasked.value = cfg.subagent.api_key || ''
    subKeyReadonly.value = true
  } catch (e) {
    msg.value = '加载配置失败: ' + (e as Error).message
    msgError.value = true
  }
}

function cancelEditMainKey() {
  mainKeyReadonly.value = true
  mainForm.value.api_key = ''
}
function cancelEditSubKey() {
  subKeyReadonly.value = true
  subForm.value.api_key = ''
}

async function handleTestMain() {
  mainTestResult.value = null
  const model = mainForm.value.model.trim()
  const baseUrl = mainForm.value.base_url.trim()
  const apiKey = mainKeyReadonly.value ? '__unchanged__' : mainForm.value.api_key
  mainTesting.value = true
  try {
    mainTestResult.value = await testConfig(model, apiKey, baseUrl, 'main')
  } catch (e) {
    mainTestResult.value = { ok: false, error: (e as Error).message }
  } finally {
    mainTesting.value = false
  }
}

async function handleTestSub() {
  subTestResult.value = null
  const model = subForm.value.model.trim()
  const baseUrl = subForm.value.base_url.trim()
  const apiKey = subKeyReadonly.value ? '__unchanged__' : subForm.value.api_key
  subTesting.value = true
  try {
    subTestResult.value = await testConfig(model, apiKey, baseUrl, 'subagent')
  } catch (e) {
    subTestResult.value = { ok: false, error: (e as Error).message }
  } finally {
    subTesting.value = false
  }
}

async function handleSubmit() {
  msg.value = ''
  msgError.value = false
  mainTestResult.value = null
  subTestResult.value = null

  const mainModel = mainForm.value.model.trim()
  const mainBaseUrl = mainForm.value.base_url.trim()
  if (!mainModel) {
    msg.value = '主 Agent: model 不能为空'
    msgError.value = true
    return
  }
  if (!mainBaseUrl) {
    msg.value = '主 Agent: base_url 不能为空'
    msgError.value = true
    return
  }
  if (subForm.value.enabled) {
    const subModel = subForm.value.model.trim()
    const subBaseUrl = subForm.value.base_url.trim()
    if (!subModel || !subBaseUrl) {
      msg.value = '启用独立配置后,子 Agent 的 model 和 base_url 不能为空'
      msgError.value = true
      return
    }
  }

  const mainApiKey = mainKeyReadonly.value ? '__unchanged__' : mainForm.value.api_key
  const subApiKey = subKeyReadonly.value ? '__unchanged__' : subForm.value.api_key

  saving.value = true
  try {
    await saveConfig({
      main: { model: mainModel, api_key: mainApiKey, base_url: mainBaseUrl },
      subagent: subForm.value.enabled
        ? { enabled: true, model: subForm.value.model.trim(), api_key: subApiKey, base_url: subForm.value.base_url.trim() }
        : { enabled: false, model: '', api_key: '', base_url: '' },
      debug: debugForm.value,
    })
    if (debugForm.value !== debugOriginal.value) {
      emit('debug-changed', debugForm.value)
      debugOriginal.value = debugForm.value
    }
    mainKeyReadonly.value = true
    subKeyReadonly.value = true
    mainForm.value.api_key = ''
    subForm.value.api_key = ''
    visible.value = false
  } catch (e) {
    msg.value = '保存失败: ' + (e as Error).message
    msgError.value = true
  } finally {
    saving.value = false
  }
}

watch(visible, (v) => {
  if (v) {
    loadConfig()
  } else {
    msg.value = ''
    msgError.value = false
    mainTestResult.value = null
    subTestResult.value = null
  }
})

// 切换子 Agent 开关时清空子测试结果
watch(() => subForm.value.enabled, () => {
  subTestResult.value = null
})
</script>

<style scoped>
.cfg-body {
  padding: 4px 0;
}

/* 顶部开关卡 */
.toggle-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 8px;
  margin-bottom: 20px;
  background: var(--td-bg-color-container);
  transition: all 0.2s ease;
}
.toggle-card.active {
  border: 1px solid var(--td-brand-color);
  box-shadow: 0 0 0 3px var(--td-brand-color-1);
}
.toggle-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toggle-icon {
  width: 36px;
  height: 36px;
  background: var(--td-brand-color-1);
  border-radius: 8px;
  color: var(--td-brand-color);
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}
.toggle-card.active .toggle-icon {
  background: var(--td-brand-color);
  color: #fff;
}
.toggle-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toggle-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}
.toggle-desc {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin-top: 2px;
  line-height: 1.5;
}
.enabled-pill {
  background: var(--td-brand-color-1);
  color: var(--td-brand-color);
  border-radius: 10px;
  border: none;
}

/* 配置卡片 */
.config-card {
  border: 1px solid var(--td-component-stroke);
  border-radius: 8px;
  padding: 16px 20px;
  background: var(--td-bg-color-container);
}
.card-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.card-accent-bar {
  width: 6px;
  height: 18px;
  background: var(--td-brand-color);
  border-radius: 2px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.card-test-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}

.card-divider {
  height: 1px;
  background: var(--td-component-stroke);
  margin: 20px 0;
}

/* Debug 卡 */
.debug-card {
  padding: 16px 20px;
}
.debug-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.debug-label {
  flex: 1;
}
.debug-label .card-title-row {
  margin-bottom: 4px;
}
.debug-desc {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  line-height: 1.5;
}

/* 测试结果 */
.test-result {
  font-size: 12px;
  line-height: 1.5;
}
.test-result.ok {
  color: var(--td-success-color, #2ba471);
}
.test-result.error {
  color: var(--td-error-color, #d54941);
}

/* 消息 + 操作区 */
.cfg-msg {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  margin: 12px 0 0;
  min-height: 18px;
}
.cfg-msg.error {
  color: var(--td-error-color, #d54941);
}
.config-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

/* TDesign form-item 在卡内的间距微调 */
.config-card :deep(.t-form__item) {
  margin-bottom: 12px;
}
.config-card :deep(.t-form__item:last-of-type) {
  margin-bottom: 0;
}
</style>