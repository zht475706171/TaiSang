<template>
  <div class="profile-manage">
    <div class="header">
      <h2>用户画像</h2>
      <p class="hint">
        agent 在对话中发现你的偏好时会自动更新;你也可手动编辑。
        画像注入 system prompt,让 agent 更懂你。
        用 ### 标题分段(技术栈/代码风格/沟通/环境/禁忌),标题下写自由文本。
      </p>
    </div>

    <div v-if="store.loading" class="loading">加载中...</div>

    <div v-else-if="store.profile" class="editor-section">
      <div class="field-header">
        <label>画像内容</label>
        <div class="field-actions">
          <t-button size="small" @click="handleSave" :disabled="!isDirty">
            保存
          </t-button>
          <t-button size="small" variant="text" @click="handleResetDefault">
            恢复默认模板
          </t-button>
          <t-button size="small" variant="text" theme="danger" @click="handleClear">
            清空
          </t-button>
        </div>
      </div>
      <t-textarea
        v-model="draft"
        :autosize="{ minRows: 10, maxRows: 25 }"
        placeholder="### 技术栈&#10;Python/Go,偏好 pnpm&#10;&#10;### 代码风格&#10;4 空格缩进,snake_case"
      />

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
              <span class="ts">{{ formatTs(rec.ts) }}</span>
            </div>
            <div class="history-diff">
              <div v-if="rec.old" class="old">旧:{{ truncate(rec.old, 80) }}</div>
              <div class="new">新:{{ truncate(rec.new, 80) }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useProfileStore } from '@/stores/profile'

const store = useProfileStore()

const draft = ref('')

const totalChars = computed(() => draft.value.length)

function isDirty(): boolean {
  return draft.value !== (store.profile?.content || '')
}

function syncDraft() {
  draft.value = store.profile?.content || ''
}

async function handleSave() {
  try {
    await store.save(draft.value)
    MessagePlugin.success('已保存,当前会话下次压缩时生效;新会话立即生效')
  } catch {
    MessagePlugin.error('保存失败')
  }
}

async function handleResetDefault() {
  if (!confirm('确认恢复默认模板?当前内容将被覆盖(可回滚)。')) return
  try {
    await store.resetDefault()
    syncDraft()
    MessagePlugin.success('已恢复默认模板')
  } catch {
    MessagePlugin.error('恢复失败')
  }
}

async function handleClear() {
  if (!confirm('确认清空所有画像内容?')) return
  try {
    await store.clear()
    syncDraft()
    MessagePlugin.success('已清空')
  } catch {
    MessagePlugin.error('清空失败')
  }
}

async function handleRollback() {
  if (!confirm('确认恢复到上一版本?当前画像将被覆盖。')) return
  try {
    await store.rollback()
    syncDraft()
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

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

function truncate(s: string, n: number): string {
  if (!s) return '(空)'
  if (s.length <= n) return s
  return s.slice(0, n) + '...'
}

onMounted(async () => {
  await store.load()
  syncDraft()
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