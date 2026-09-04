<template>
  <div class="skill-manage">
    <div class="page-header">
      <h2 class="page-title">Skill 管理</h2>
      <t-button variant="outline" aria-label="重载 skills" @click="reload">
        <template #icon>
          <t-icon name="refresh" />
        </template>
        重载
      </t-button>
    </div>

    <t-table row-key="name" :data="skills" :columns="columns" :loading="loading">
      <template #source="{ row }">
        <t-tag :theme="row.source === 'project' ? 'primary' : 'default'" size="small">
          {{ row.source === 'project' ? '项目' : '用户' }}
        </t-tag>
      </template>
      <template #allowed_tools="{ row }">
        <span v-if="row.allowed_tools">{{ row.allowed_tools.join(', ') }}</span>
        <span v-else class="dim">不限制</span>
      </template>
      <template #enabled="{ row }">
        <t-switch :value="!row.disabled" @change="() => toggle(row.name)" />
      </template>
      <template #empty>
        <div class="empty-tip">
          暂无 skill。在 <code>~/.taisang/skills/&lt;name&gt;/SKILL.md</code> 或
          <code>&lt;repo&gt;/.taisang/skills/&lt;name&gt;/SKILL.md</code> 放置 SKILL.md
          后点重载。
        </div>
      </template>
    </t-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

interface SkillRow {
  name: string
  description: string
  when_to_use: string
  source: 'user' | 'project'
  allowed_tools: string[] | null
  disabled: boolean
}

const skills = ref<SkillRow[]>([])
const loading = ref(false)

const columns = [
  { colKey: 'name', title: '名称', width: 160 },
  { colKey: 'description', title: '描述', ellipsis: true },
  { colKey: 'source', title: '来源', width: 90, cell: 'source' },
  { colKey: 'allowed_tools', title: '工具限制', width: 140, cell: 'allowed_tools' },
  { colKey: 'enabled', title: '启用', width: 80, cell: 'enabled' },
]

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
    await fetchSkills()
    MessagePlugin.success('已重载')
  } catch {
    MessagePlugin.error('重载失败')
  }
}

onMounted(fetchSkills)
</script>

<style scoped>
.skill-manage {
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
.dim {
  color: var(--td-text-color-placeholder);
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
