<template>
  <div class="prompt-manage">
    <div class="page-header">
      <h2 class="page-title">Prompt 管理</h2>
      <div class="page-hint">Prompt 修改全局生效,对所有会话立即应用。</div>
    </div>

    <div class="prompt-editor">
      <t-tabs v-model="activeKey">
        <t-tab-panel
          v-for="p in panels"
          :key="p.key"
          :value="p.key"
          :label="p.title"
        >
          <div class="editor-body">
            <div class="panel-toolbar">
              <t-tag
                :theme="state[p.key].useDefault ? 'default' : 'primary'"
                size="small"
              >
                {{ state[p.key].useDefault ? '使用默认' : '自定义' }}
              </t-tag>
              <span class="status-line" :class="statusClass(p.key)">
                {{ statusText(p.key) }}
              </span>
              <div class="toolbar-spacer" />
              <t-button
                variant="outline"
                size="small"
                :disabled="state[p.key].useDefault && !dirty(p.key)"
                @click="onReset(p.key)"
              >
                恢复默认
              </t-button>
              <t-button
                theme="primary"
                size="small"
                :disabled="!dirty(p.key) || !state[p.key].draft"
                :loading="state[p.key].saving"
                @click="onSave(p.key)"
              >
                保存
              </t-button>
            </div>
            <textarea
              v-model="state[p.key].draft"
              class="prompt-textarea"
              spellcheck="false"
            />
          </div>
        </t-tab-panel>
      </t-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  fetchPrompts,
  savePrompt,
  resetPrompt,
  type PromptKey,
  type PromptsMap,
} from '@/api/prompts'

interface PanelState {
  original: string
  draft: string
  useDefault: boolean
  saving: boolean
  justSaved: boolean
}

interface PanelMeta {
  key: PromptKey
  title: string
  confirmText: string
}

const panels: PanelMeta[] = [
  {
    key: 'system_prompt',
    title: '主 System Prompt',
    confirmText:
      '⚠️ 修改主 System Prompt 将立即应用到所有活跃会话。\n' +
      '- 当前进行中的对话,agent 行为指令会中途切换,可能导致前后风格/约束不一致;\n' +
      '- API 的 prompt cache 会失效,下一次响应稍慢、多消耗一次前缀 token,之后自动重建。\n\n' +
      '建议在新会话开始前修改。是否继续?',
  },
  {
    key: 'autocompact_prompt',
    title: 'Autocompact 摘要',
    confirmText:
      '⚠️ 修改后将立即保存。下次触发上下文压缩时使用新 prompt。\n' +
      '当前进行中的对话不受影响(只有触发 compaction 时才用到)。\n\n' +
      '是否继续?\n\n' +
      '注意:自定义文本必须包含 {conversation} 占位符,否则保存会失败。',
  },
  {
    key: 'session_memory_template',
    title: 'Session Memory 模板',
    confirmText:
      '⚠️ 修改后将立即保存。下次触发笔记更新时使用新模板。\n' +
      '当前进行中的对话不受影响(只有触发 compaction 时才用到)。\n\n是否继续?',
  },
  {
    key: 'session_memory_update_prompt',
    title: 'Session Memory 更新指令',
    confirmText:
      '⚠️ 修改后将立即保存。下次触发笔记更新时使用新指令。\n' +
      '当前进行中的对话不受影响(只有触发 compaction 时才用到)。\n\n' +
      '注意:自定义文本支持 {current_notes} 和 {memory_path} 占位符(缺了不报错)。\n\n是否继续?',
  },
]

const activeKey = ref<PromptKey>('system_prompt')

const state = reactive<Record<PromptKey, PanelState>>({
  system_prompt: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
  autocompact_prompt: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
  session_memory_template: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
  session_memory_update_prompt: { original: '', draft: '', useDefault: true, saving: false, justSaved: false },
})

function dirty(key: PromptKey): boolean {
  return state[key].draft !== state[key].original
}

function statusClass(key: PromptKey): string {
  if (state[key].justSaved) return 'status-saved'
  if (dirty(key)) return 'status-dirty'
  if (state[key].useDefault) return 'status-default'
  return 'status-clean'
}

function statusText(key: PromptKey): string {
  if (state[key].justSaved) return '已保存'
  if (dirty(key)) return '未保存改动'
  if (state[key].useDefault) return '使用默认值'
  return '已保存'
}

function applyResponse(data: PromptsMap) {
  for (const p of panels) {
    const item = data[p.key]
    state[p.key].original = item.current
    state[p.key].draft = item.current
    state[p.key].useDefault = item.use_default
  }
}

async function load() {
  try {
    const data = await fetchPrompts()
    applyResponse(data)
  } catch (e) {
    MessagePlugin.error('加载 prompt 配置失败')
  }
}

async function onSave(key: PromptKey) {
  const meta = panels.find((p) => p.key === key)!
  if (!confirm(meta.confirmText)) return
  state[key].saving = true
  try {
    const data = await savePrompt(key, state[key].draft)
    applyResponse(data)
    state[key].justSaved = true
    MessagePlugin.success('保存成功')
    setTimeout(() => {
      state[key].justSaved = false
    }, 2000)
  } catch (e: any) {
    const msg = e?.message || '保存失败'
    MessagePlugin.error(msg)
  } finally {
    state[key].saving = false
  }
}

async function onReset(key: PromptKey) {
  if (!confirm('将恢复为内置默认值,自定义内容会被覆盖。是否继续?')) return
  state[key].saving = true
  try {
    const data = await resetPrompt(key)
    applyResponse(data)
    MessagePlugin.success('已恢复默认')
  } catch (e: any) {
    MessagePlugin.error(e?.message || '恢复失败')
  } finally {
    state[key].saving = false
  }
}

function anyDirty(): boolean {
  return panels.some((p) => dirty(p.key))
}

onMounted(() => {
  load()
  window.addEventListener('beforeunload', onBeforeUnload)
})

onBeforeRouteLeave(() => {
  if (anyDirty() && !confirm('有未保存的 prompt 修改,确定离开?')) {
    return false
  }
  return true
})

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (anyDirty()) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<style scoped>
.prompt-manage {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.page-header {
  margin-bottom: 16px;
  flex-shrink: 0;
}
.page-title {
  margin: 0 0 4px 0;
}
.page-hint {
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.prompt-editor {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* t-tabs 撑满编辑区 */
.prompt-editor :deep(.t-tabs) {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.prompt-editor :deep(.t-tabs__nav-container) {
  flex-shrink: 0;
}
.prompt-editor :deep(.t-tabs__content) {
  flex: 1;
  min-height: 0;
  display: flex;
}
.prompt-editor :deep(.t-tab-panel) {
  flex: 1;
  display: flex;
}
.prompt-editor :deep(.t-tab-panel__panel) {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.editor-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}
.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.toolbar-spacer {
  flex: 1;
}
.status-line {
  font-size: 13px;
  color: var(--td-text-color-placeholder);
}
.status-dirty {
  color: var(--td-warning-color);
}
.status-saved {
  color: var(--td-success-color);
}
.status-default {
  color: var(--td-text-color-placeholder);
}
.status-clean {
  color: var(--td-success-color);
}
.prompt-textarea {
  flex: 1;
  width: 100%;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  line-height: 1.5;
  padding: 12px;
  border: 1px solid var(--td-border-level-2-color);
  border-radius: 4px;
  resize: none;
  min-height: 0;
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
  box-sizing: border-box;
}
</style>