<template>
  <div class="agent-manage">
    <div class="page-header">
      <h2 class="page-title">Agent 管理</h2>
      <div class="header-actions">
        <t-button variant="outline" aria-label="重载 agents" @click="reload">
          <template #icon>
            <t-icon name="refresh" />
          </template>
          重载
        </t-button>
      </div>
    </div>

    <t-table row-key="agent_type" :data="agents" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag
          :theme="row.source === 'project' ? 'primary' : row.source === 'system' ? 'warning' : 'default'"
          size="small"
        >
          {{ row.source === 'project' ? '项目' : row.source === 'system' ? '内置' : '用户' }}
        </t-tag>
      </template>
      <template #tools_display="{ row }">
        <span>{{ formatTools(row) }}</span>
      </template>
      <template #enabled="{ row }">
        <t-switch :value="!row.disabled" @change="() => toggle(row.agent_type)" />
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无自定义 agent。手动放置到
          <code>~/.taisang/agents/&lt;name&gt;/AGENT.md</code>
          或项目 <code>.taisang/agents/&lt;name&gt;/AGENT.md</code>。
        </div>
      </template>
    </t-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

interface AgentRow {
  agent_type: string
  when_to_use: string
  source: 'user' | 'project' | 'system'
  tools: string[] | null
  disallowed_tools: string[]
  disabled: boolean
  background: boolean
  max_turns: number | null
}

const agents = ref<AgentRow[]>([])
const loading = ref(false)

const columns = [
  { colKey: 'agent_type', title: '名称', width: 160, fixed: 'left' },
  { colKey: 'when_to_use', title: '描述', ellipsis: true },
  { colKey: 'source', title: '来源', width: 100, cell: 'source' },
  { colKey: 'tools_display', title: '工具集', width: 240, cell: 'tools_display' },
  { colKey: 'enabled', title: '启用', width: 80, cell: 'enabled' },
]

function formatTools(row: AgentRow): string {
  const hasAllow = row.tools && row.tools.length > 0
  const hasDeny = row.disallowed_tools && row.disallowed_tools.length > 0
  if (hasAllow && hasDeny) {
    const denySet = new Set(row.disallowed_tools)
    const effective = row.tools!.filter((t) => !denySet.has(t))
    if (!effective.length) return 'None'
    return effective.join(', ')
  }
  if (hasAllow) return row.tools!.join(', ')
  if (hasDeny) return `全工具除 ${row.disallowed_tools.join(', ')}`
  return '全工具'
}

async function fetchAgents() {
  loading.value = true
  try {
    const r = await fetch('/api/agents')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json()
    agents.value = data.agents ?? []
  } catch (e) {
    MessagePlugin.error(`加载 agent 失败: ${e}`)
  } finally {
    loading.value = false
  }
}

async function toggle(name: string) {
  try {
    const r = await fetch(`/api/agents/${name}/toggle`, { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    await fetchAgents()
  } catch (e) {
    MessagePlugin.error(`切换失败: ${e}`)
  }
}

async function reload() {
  try {
    const r = await fetch('/api/agents/reload', { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    MessagePlugin.success('已重载')
    await fetchAgents()
  } catch (e) {
    MessagePlugin.error(`重载失败: ${e}`)
  }
}

onMounted(fetchAgents)
</script>

<style scoped>
.agent-manage {
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