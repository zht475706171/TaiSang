<template>
  <div class="profile-manage">
    <div class="header">
      <h2>用户画像</h2>
      <p class="hint">
        agent 在对话中发现你的偏好时会自动更新;你也可手动编辑。
        画像注入 system prompt,让 agent 更懂你。
      </p>
    </div>

    <div v-if="store.loading" class="loading">加载中...</div>

    <div v-else-if="store.profile" class="fields">
      <div
        v-for="key in fieldKeys"
        :key="key"
        class="field-block"
      >
        <div class="field-header">
          <label>{{ fieldLabels[key] }}</label>
          <div class="field-actions">
            <t-button size="small" @click="handleSave(key)" :disabled="!isDirty(key)">
              保存
            </t-button>
            <t-button size="small" variant="text" @click="handleReset(key)">
              清空
            </t-button>
          </div>
        </div>
        <t-textarea
          v-model="drafts[key]"
          :autosize="{ minRows: 2, maxRows: 6 }"
          :placeholder="`输入你的${fieldLabels[key]}偏好...`"
        />
      </div>

      <div class="total-chars" :class="{ over: totalChars > 500 }">
        总字数:{{ totalChars }} / 500
        <span v-if="totalChars > 500" class="warn">
          超过 500 字符,注入 system prompt 时将截断尾部
        </span>
      </div>

      <div class="bottom-actions">
        <t-button
          theme="warning"
          variant="outline"
          @click="handleRollback"
          :disabled="store.history.length === 0"
        >
          恢复上一版本
        </t-button>
      </div>

      <div class="history-section">
        <h3>变更历史(最近 5 条)</h3>
        <div v-if="store.history.length === 0" class="empty">暂无历史</div>
        <div v-else class="history-list">
          <div v-for="(rec, idx) in [...store.history].reverse()" :key="idx" class="history-item">
            <div class="history-meta">
              <span class="source-tag" :class="`source-${rec.source}`">{{ sourceLabel(rec.source) }}</span>
              <span class="field-name">{{ fieldLabel(rec.field) }}</span>
              <span class="ts">{{ formatTs(rec.ts) }}</span>
            </div>
            <div class="history-diff">
              <div v-if="rec.old" class="old">旧:{{ rec.old }}</div>
              <div class="new">新:{{ rec.new }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useProfileStore } from '@/stores/profile'
import type { ProfileFieldKey } from '@/api/profile'

const store = useProfileStore()

const fieldKeys: ProfileFieldKey[] = [
  'tech_stack', 'code_style', 'communication', 'environment', 'taboos',
]
const fieldLabels: Record<ProfileFieldKey, string> = {
  tech_stack: '技术栈',
  code_style: '代码风格',
  communication: '沟通',
  environment: '环境',
  taboos: '禁忌',
}

const drafts = reactive<Record<ProfileFieldKey, string>>({
  tech_stack: '',
  code_style: '',
  communication: '',
  environment: '',
  taboos: '',
})

const totalChars = computed(() =>
  fieldKeys.reduce((sum, k) => sum + (drafts[k]?.length || 0), 0)
)

function isDirty(key: ProfileFieldKey): boolean {
  return drafts[key] !== (store.profile?.[key] || '')
}

function syncDrafts() {
  if (!store.profile) return
  for (const k of fieldKeys) {
    drafts[k] = store.profile[k] || ''
  }
}

async function handleSave(key: ProfileFieldKey) {
  try {
    await store.saveField(key, drafts[key])
    MessagePlugin.success('已保存,当前会话下次压缩时生效;新会话立即生效')
  } catch {
    MessagePlugin.error('保存失败')
  }
}

async function handleReset(key: ProfileFieldKey) {
  if (!confirm(`确认清空【${fieldLabels[key]}】栏?`)) return
  try {
    await store.resetField(key)
    drafts[key] = ''
    MessagePlugin.success('已清空')
  } catch {
    MessagePlugin.error('清空失败')
  }
}

async function handleRollback() {
  if (!confirm('确认恢复到上一版本?当前画像将被覆盖。')) return
  try {
    await store.rollback()
    syncDrafts()
    MessagePlugin.success('已恢复到上一版本')
  } catch {
    MessagePlugin.error('恢复失败:无可用历史版本')
  }
}

function sourceLabel(s: string): string {
  if (s === 'user') return '用户'
  if (s === 'agent') return 'agent'
  if (s === 'rollback') return '回滚'
  return s
}

function fieldLabel(f: string): string {
  if (f === '*') return '整体'
  return (fieldLabels as Record<string, string>)[f] || f
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

onMounted(async () => {
  await store.load()
  syncDrafts()
})
</script>

<style scoped>
.profile-manage {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px;
}
.header h2 {
  margin: 0 0 8px;
}
.hint {
  color: var(--td-text-color-secondary);
  font-size: 13px;
  margin: 0 0 24px;
}
.field-block {
  margin-bottom: 20px;
}
.field-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.field-header label {
  font-weight: 500;
}
.field-actions {
  display: flex;
  gap: 8px;
}
.total-chars {
  margin: 16px 0;
  font-size: 13px;
  color: var(--td-text-color-secondary);
}
.total-chars.over {
  color: var(--td-error-color);
}
.total-chars .warn {
  margin-left: 8px;
}
.bottom-actions {
  margin: 24px 0;
}
.history-section {
  margin-top: 32px;
  border-top: 1px solid var(--td-component-stroke);
  padding-top: 16px;
}
.history-section h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.history-item {
  padding: 8px 0;
  border-bottom: 1px solid var(--td-component-stroke);
}
.history-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  margin-bottom: 4px;
}
.source-tag {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}
.source-user { background: var(--td-brand-color-light); }
.source-agent { background: var(--td-success-color-light); }
.source-rollback { background: var(--td-warning-color-light); }
.history-diff {
  font-size: 13px;
  padding-left: 12px;
}
.history-diff .old {
  color: var(--td-text-color-secondary);
  text-decoration: line-through;
}
</style>