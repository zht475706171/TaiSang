<template>
  <div class="skill-manage">
    <div class="page-header">
      <h2 class="page-title">Skill 管理</h2>
      <div class="header-actions">
        <t-button theme="primary" aria-label="安装 plugin" @click="openInstallDialog">
          <template #icon>
            <t-icon name="cloud-download" />
          </template>
          安装 Plugin
        </t-button>
        <t-button variant="outline" aria-label="导入 skill" @click="fileInput?.click()">
          <template #icon>
            <t-icon name="upload" />
          </template>
          导入 Skill
        </t-button>
        <t-button variant="outline" aria-label="重载 skills" @click="reload">
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
      accept=".md,.zip"
      style="display: none"
      @change="onImportFile"
    />

    <!-- 已装 Plugin 面板 -->
    <t-collapse v-model="pluginPanelExpanded" class="plugin-panel">
      <t-collapse-panel value="plugins" header="已装 Plugin">
        <template #header>
          <span class="panel-title">已装 Plugin</span>
          <t-tag theme="primary" size="small" shape="round" class="panel-count">
            {{ plugins.length }}
          </t-tag>
        </template>
        <t-table
          v-if="plugins.length > 0"
          row-key="name"
          :data="plugins"
          :columns="pluginColumns"
          :pagination="false"
          size="small"
        >
          <template #source="{ row }">
            <code class="mono">{{ row.source }}</code>
          </template>
          <template #version="{ row }">
            <t-tag size="small" variant="light">v{{ row.version }}</t-tag>
          </template>
          <template #skillsCount="{ row }">
            <span class="skill-count">{{ row.skills.length }} 个</span>
          </template>
          <template #installedAt="{ row }">
            <span class="dim">{{ formatTime(row.installed_at) }}</span>
          </template>
          <template #op="{ row }">
            <t-button variant="text" size="small" @click="upgradePlugin(row)">
              升级
            </t-button>
            <t-button variant="text" theme="danger" size="small" @click="confirmUninstall(row)">
              卸载
            </t-button>
          </template>
        </t-table>
        <div v-else class="empty-tip">
          暂无已安装 plugin。点右上角"安装 Plugin"输入 github 地址(如 <code>obra/superpowers</code>)。
        </div>
      </t-collapse-panel>
    </t-collapse>

    <!-- Skill 表格 -->
    <t-table row-key="name" :data="skills" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag
          :theme="row.source === 'project' ? 'primary' : row.source === 'system' ? 'warning' : 'default'"
          size="small"
        >
          {{ row.source === 'project' ? '项目' : row.source === 'system' ? '内置' : '用户' }}
        </t-tag>
      </template>
      <template #pluginName="{ row }">
        <t-tag v-if="row.plugin_name" theme="primary" size="small" shape="round">
          {{ row.plugin_name }}
        </t-tag>
        <span v-else class="dim">—</span>
      </template>
      <template #allowed_tools="{ row }">
        <span v-if="row.allowed_tools">{{ row.allowed_tools.join(', ') }}</span>
        <span v-else class="dim">不限制</span>
      </template>
      <template #enabled="{ row }">
        <t-switch :value="!row.disabled" @change="() => toggle(row.name)" />
      </template>
      <template #op="{ row }">
        <t-button
          v-if="row.source !== 'system' && !row.plugin_name"
          variant="text"
          theme="danger"
          size="small"
          @click="confirmDelete(row.name)"
        >
          删除
        </t-button>
        <span v-else-if="row.plugin_name" class="dim" title="plugin 来源 skill 请到已装 Plugin 面板整包卸载">
          整包卸载
        </span>
        <span v-else class="dim">-</span>
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无自定义 skill。点右上角"导入 Skill"上传 .md 或 .zip,
          或用"安装 Plugin"从 github 拉取整包。
        </div>
      </template>
    </t-table>

    <!-- 安装 Plugin Dialog -->
    <t-dialog
      v-model:visible="installDialogVisible"
      header="安装 Plugin"
      :confirm-btn="installing ? null : '安装'"
      :cancel-btn="installing ? null : '取消'"
      :close-on-overlay-click="!installing"
      :close-on-esc-keydown="!installing"
      @confirm="doInstall"
    >
      <t-form>
        <t-form-item label="GitHub 地址" help="支持 owner/repo、https://github.com/owner/repo[.git]">
          <t-input
            v-model="installSource"
            placeholder="obra/superpowers"
            :disabled="installing"
            @enter="doInstall"
          />
        </t-form-item>
      </t-form>
      <t-alert
        v-if="installError"
        theme="error"
        :message="installError"
        class="install-error"
      />
      <div v-if="installing" class="install-progress">
        <t-loading />
        <span class="install-step">正在安装 {{ installSource }} ...</span>
        <div class="install-steps-text">
          git clone → 扫描 plugin 结构 → 批量导入 skills
        </div>
      </div>
      <t-alert
        v-else
        theme="warning"
        message="同名 plugin 重复安装会覆盖升级(先删后装),原有 skill 会被清空重拉。"
        class="install-warning"
      />
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'

interface SkillRow {
  name: string
  description: string
  when_to_use: string
  source: 'user' | 'project' | 'system'
  allowed_tools: string[] | null
  disabled: boolean
  plugin_name: string | null
}

interface InstalledPlugin {
  name: string
  source: string
  version: string
  git_commit_sha: string
  installed_at: string
  skills: string[]
}

const skills = ref<SkillRow[]>([])
const plugins = ref<InstalledPlugin[]>([])
const loading = ref(false)
const fileInput = ref<HTMLInputElement>()

// 已装 Plugin 面板:默认展开
const pluginPanelExpanded = ref<string[]>(['plugins'])

// 安装 Dialog 状态
const installDialogVisible = ref(false)
const installSource = ref('')
const installing = ref(false)
const installError = ref('')

const columns = [
  { colKey: 'name', title: '名称', width: 160 },
  { colKey: 'description', title: '描述', ellipsis: true },
  { colKey: 'source', title: '来源', width: 80, cell: 'source' },
  { colKey: 'pluginName', title: 'Plugin', width: 120, cell: 'pluginName' },
  { colKey: 'allowed_tools', title: '工具限制', width: 130, cell: 'allowed_tools' },
  { colKey: 'enabled', title: '启用', width: 70, cell: 'enabled' },
  { colKey: 'op', title: '操作', width: 100, cell: 'op' },
]

const pluginColumns = [
  { colKey: 'name', title: '名称', width: 140 },
  { colKey: 'version', title: '版本', width: 80, cell: 'version' },
  { colKey: 'skillsCount', title: 'Skills', width: 80, cell: 'skillsCount' },
  { colKey: 'source', title: '来源', cell: 'source' },
  { colKey: 'installedAt', title: '安装时间', width: 140, cell: 'installedAt' },
  { colKey: 'op', title: '操作', width: 140, cell: 'op' },
]

function formatTime(iso: string): string {
  if (!iso) return ''
  // 取 YYYY-MM-DD HH:MM
  return iso.replace('T', ' ').slice(0, 16)
}

async function fetchSkills() {
  loading.value = true
  try {
    const r = await fetch('/api/skills')
    const data = await r.json()
    skills.value = data.skills ?? []
  } catch {
    MessagePlugin.error('加载 skills 失败')
  } finally {
    loading.value = false
  }
}

async function fetchPlugins() {
  try {
    const r = await fetch('/api/skills/plugins')
    const data = await r.json()
    plugins.value = data.plugins ?? []
  } catch {
    MessagePlugin.error('加载 plugins 失败')
  }
}

async function toggle(name: string) {
  try {
    await fetch(`/api/skills/${name}/toggle`, { method: 'POST' })
    await fetchSkills()
  } catch {
    MessagePlugin.error('切换失败')
  }
}

async function reload() {
  try {
    await fetch('/api/skills/reload', { method: 'POST' })
    await Promise.all([fetchSkills(), fetchPlugins()])
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
    await fetchSkills()
    MessagePlugin.success(`已导入 ${file.name}`)
  }
  input.value = ''
}

async function doImport(file: File, overwrite: boolean): Promise<boolean> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`/api/skills/import?overwrite=${overwrite}`, {
    method: 'POST',
    body: fd,
  })
  if (r.status === 409) {
    const confirmed = await new Promise<boolean>((resolve) => {
      const dialog = DialogPlugin.confirm({
        header: 'Skill 已存在',
        body: '同名 skill 已存在,是否覆盖?',
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
    header: '删除 skill',
    body: `确定删除 "${name}"?该操作不可恢复。`,
    confirmBtn: '删除',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      const r = await fetch(`/api/skills/${name}`, { method: 'DELETE' })
      if (r.ok) {
        await fetchSkills()
        MessagePlugin.success('已删除')
      } else {
        const data = (await r.json().catch(() => ({}))) as { detail?: string }
        MessagePlugin.error(data.detail ?? '删除失败')
      }
    },
  })
}

// ===== Plugin 安装/卸载 =====

function openInstallDialog() {
  installSource.value = ''
  installError.value = ''
  installing.value = false
  installDialogVisible.value = true
}

async function doInstall() {
  if (!installSource.value.trim()) {
    installError.value = '请输入 github 地址'
    return
  }
  installing.value = true
  installError.value = ''
  try {
    const r = await fetch('/api/skills/install-plugin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: installSource.value.trim() }),
    })
    const data = (await r.json().catch(() => ({}))) as {
      plugin?: string
      version?: string
      skills?: string[]
      detail?: string
    }
    if (!r.ok) {
      installError.value = data.detail ?? '安装失败'
      installing.value = false
      return
    }
    installDialogVisible.value = false
    installing.value = false
    MessagePlugin.success(
      `已安装 ${data.plugin} v${data.version}（${(data.skills ?? []).length} 个 skill）`
    )
    await Promise.all([fetchSkills(), fetchPlugins()])
  } catch (e) {
    installError.value = `安装失败: ${e}`
    installing.value = false
  }
}

function upgradePlugin(row: InstalledPlugin) {
  // 升级 = 用同样 source 再装一次
  installSource.value = row.source.replace(/^github:/, '')
  installError.value = ''
  installing.value = false
  installDialogVisible.value = true
}

function confirmUninstall(row: InstalledPlugin) {
  const dialog = DialogPlugin.confirm({
    header: `确认卸载 ${row.name}?`,
    body: `将同时删除该 plugin 下的 ${row.skills.length} 个 skills。此操作不可撤销。`,
    confirmBtn: '确认卸载',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      const r = await fetch(`/api/skills/plugin/${row.name}`, { method: 'DELETE' })
      if (r.ok) {
        await Promise.all([fetchSkills(), fetchPlugins()])
        MessagePlugin.success(`已卸载 ${row.name}（移除 ${row.skills.length} 个 skill）`)
      } else {
        const data = (await r.json().catch(() => ({}))) as { detail?: string }
        MessagePlugin.error(data.detail ?? '卸载失败')
      }
    },
  })
}

onMounted(() => {
  fetchSkills()
  fetchPlugins()
})
</script>

<style scoped>
.skill-manage {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 1100px;
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
.empty-tip {
  padding: 24px 16px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
}
.empty-tip code {
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
.plugin-panel {
  margin-bottom: 16px;
}
.panel-title {
  font-weight: 600;
}
.panel-count {
  margin-left: 8px;
}
.mono {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
.skill-count {
  color: var(--td-brand-color);
}
.install-error {
  margin-top: 12px;
}
.install-warning {
  margin-top: 12px;
}
.install-progress {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.install-step {
  font-weight: 500;
}
.install-steps-text {
  color: var(--td-text-color-placeholder);
  font-size: 12px;
}
</style>