<template>
  <div class="command-manage">
    <div class="page-header">
      <h2 class="page-title">Command 管理</h2>
      <div class="header-actions">
        <t-button variant="outline" aria-label="导入 command" @click="fileInput?.click()">
          <template #icon>
            <t-icon name="upload" />
          </template>
          导入 Command
        </t-button>
        <t-button variant="outline" aria-label="重载 commands" @click="reload">
          <template #icon>
            <t-icon name="refresh" />
          </template>
          重载
        </t-button>
      </div>
    </div>
    <input
      ref="fileInput"
      type="file"
      accept=".md,.markdown"
      style="display: none"
      @change="onImportFile"
    />

    <t-table row-key="name" :data="commands" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag
          :theme="row.source === 'project' ? 'primary' : row.source === 'system' ? 'warning' : 'default'"
          size="small"
        >
          {{ row.source === 'project' ? '项目' : row.source === 'system' ? '内置' : '用户' }}
        </t-tag>
      </template>
      <template #allowed_tools="{ row }">
        <span v-if="row.allowed_tools">{{ row.allowed_tools.join(', ') }}</span>
        <span v-else class="dim">不限制</span>
      </template>
      <template #argument_hint="{ row }">
        <span v-if="row.argument_hint" class="hint">{{ row.argument_hint }}</span>
        <span v-else class="dim">-</span>
      </template>
      <template #enabled="{ row }">
        <t-switch :value="!row.disabled" @change="() => toggle(row.name)" />
      </template>
      <template #op="{ row }">
        <t-button
          v-if="row.source !== 'system'"
          variant="text"
          theme="danger"
          size="small"
          @click="confirmDelete(row.name)"
        >
          删除
        </t-button>
        <span v-else class="dim">-</span>
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无自定义 command。点右上角"导入 Command"上传 .md 文件,
          或手动放置到 <code>~/.taisang/commands/&lt;name&gt;.md</code>。
          在聊天里输入 <code>/name args</code> 触发。
        </div>
      </template>
    </t-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import type { Command } from '@/types'

const commands = ref<Command[]>([])
const loading = ref(false)
const fileInput = ref<HTMLInputElement>()

const columns = [
  { colKey: 'name', title: '名称', width: 140 },
  { colKey: 'description', title: '描述', ellipsis: true },
  { colKey: 'argument_hint', title: '参数提示', width: 140, cell: 'argument_hint' },
  { colKey: 'source', title: '来源', width: 80, cell: 'source' },
  { colKey: 'allowed_tools', title: '工具限制', width: 130, cell: 'allowed_tools' },
  { colKey: 'enabled', title: '启用', width: 70, cell: 'enabled' },
  { colKey: 'op', title: '操作', width: 70, cell: 'op' },
]

async function fetchCommands() {
  loading.value = true
  try {
    const r = await fetch('/api/commands')
    const data = await r.json()
    commands.value = data.commands ?? []
  } catch {
    MessagePlugin.error('加载 commands 失败')
  } finally {
    loading.value = false
  }
}

async function toggle(name: string) {
  try {
    await fetch(`/api/commands/${name}/toggle`, { method: 'POST' })
    await fetchCommands()
  } catch {
    MessagePlugin.error('切换失败')
  }
}

async function reload() {
  try {
    await fetch('/api/commands/reload', { method: 'POST' })
    await fetchCommands()
    MessagePlugin.success('已重载')
  } catch {
    MessagePlugin.error('重载失败')
  }
}

async function onImportFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const ok = await doImport(file, false)
  if (ok) {
    await fetchCommands()
    MessagePlugin.success(`已导入 ${file.name}`)
  }
  input.value = ''
}

async function doImport(file: File, overwrite: boolean): Promise<boolean> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`/api/commands/import?overwrite=${overwrite}`, {
    method: 'POST',
    body: fd,
  })
  if (r.status === 409) {
    const confirmed = await new Promise<boolean>((resolve) => {
      const dialog = DialogPlugin.confirm({
        header: 'Command 已存在',
        body: '同名 command 已存在,是否覆盖?',
        confirmBtn: '覆盖',
        cancelBtn: '取消',
        onConfirm: () => {
          dialog.destroy()
          resolve(true)
        },
        onClose: () => {
          dialog.destroy()
          resolve(false)
        },
      })
    })
    if (confirmed) return doImport(file, true)
    return false
  }
  if (!r.ok) {
    const data = (await r.json().catch(() => ({}))) as { detail?: string }
    MessagePlugin.error(data.detail ?? '导入失败')
    return false
  }
  return true
}

function confirmDelete(name: string) {
  const dialog = DialogPlugin.confirm({
    header: '删除 command',
    body: `确定删除 "${name}"?该操作不可恢复。`,
    confirmBtn: '删除',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      const r = await fetch(`/api/commands/${name}`, { method: 'DELETE' })
      if (r.ok) {
        await fetchCommands()
        MessagePlugin.success('已删除')
      } else {
        const data = (await r.json().catch(() => ({}))) as { detail?: string }
        MessagePlugin.error(data.detail ?? '删除失败')
      }
    },
  })
}

onMounted(fetchCommands)
</script>

<style scoped>
.command-manage {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 960px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.dim {
  color: var(--td-text-color-placeholder);
}
.hint {
  font-family: monospace;
  font-size: 12px;
}
.empty-tip {
  padding: 32px 16px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.empty-tip code {
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
</style>