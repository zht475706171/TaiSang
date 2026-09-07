<template>
  <div class="mcp-manage">
    <div class="page-header">
      <h2 class="page-title">MCP 管理</h2>
      <t-button theme="primary" aria-label="添加 MCP 服务器" @click="openAdd">
        <template #icon>
          <t-icon name="add" />
        </template>
        添加服务器
      </t-button>
    </div>

    <div v-if="mcpStore.loading" class="loading-tip">加载中…</div>

    <div v-else-if="mcpStore.servers.length === 0" class="empty-tip">
      暂无 MCP 服务器。点右上角"添加服务器"配置。
    </div>

    <div v-else class="server-cards">
      <t-card v-for="server in mcpStore.servers" :key="server.name" class="server-card">
        <template #title>
          <div class="card-header">
            <span class="server-name">{{ server.name }}</span>
            <t-tag :theme="statusTheme(server.name)" size="small">{{ statusLabel(server.name) }}</t-tag>
            <t-tag theme="default" size="small">{{ server.transport === 'stdio' ? 'stdio' : 'SSE' }}</t-tag>
            <t-tag v-if="!server.enabled" theme="warning" size="small">已禁用</t-tag>
          </div>
        </template>

        <div class="config-summary">
          <template v-if="server.transport === 'stdio'">
            <code>{{ server.command }} {{ server.args.join(' ') }}</code>
          </template>
          <template v-else>
            <code>{{ server.url }}</code>
          </template>
        </div>

        <div class="capabilities" v-if="getInfo(server.name)">
          <t-collapse>
            <t-collapse-panel
              v-if="getInfo(server.name)?.tools?.length"
              :header="`工具 (${getInfo(server.name)?.tools?.length ?? 0})`"
            >
              <ul class="cap-list">
                <li v-for="t in getInfo(server.name)?.tools" :key="t.name">
                  <code>mcp__{{ server.name }}__{{ t.name }}</code> — {{ t.description }}
                </li>
              </ul>
            </t-collapse-panel>
            <t-collapse-panel
              v-if="getInfo(server.name)?.resources?.length"
              :header="`资源 (${getInfo(server.name)?.resources?.length ?? 0})`"
            >
              <ul class="cap-list">
                <li v-for="r in getInfo(server.name)?.resources" :key="r.uri">
                  <code>{{ r.uri }}</code> — {{ r.name }}
                </li>
              </ul>
            </t-collapse-panel>
            <t-collapse-panel
              v-if="getInfo(server.name)?.prompts?.length"
              :header="`提示 (${getInfo(server.name)?.prompts?.length ?? 0})`"
            >
              <ul class="cap-list">
                <li v-for="p in getInfo(server.name)?.prompts" :key="p.name">
                  <code>{{ p.name }}</code> — {{ p.description }}
                </li>
              </ul>
            </t-collapse-panel>
          </t-collapse>
          <div v-if="getInfo(server.name)?.error" class="error-text">
            {{ getInfo(server.name)?.error }}
          </div>
        </div>

        <template #footer>
          <div class="card-footer">
            <t-switch :value="server.enabled" @change="(v: boolean) => onToggle(server.name, v)" />
            <t-button variant="text" size="small" :aria-label="`重连 ${server.name}`" @click="onReconnect(server.name)">重连</t-button>
            <t-button variant="text" size="small" :aria-label="`编辑 ${server.name}`" @click="openEdit(server)">编辑</t-button>
            <t-button variant="text" theme="danger" size="small" :aria-label="`删除 ${server.name}`" @click="confirmDelete(server.name)">
              删除
            </t-button>
          </div>
        </template>
      </t-card>
    </div>

    <t-dialog v-model:visible="showDialog" :header="editing ? '编辑服务器' : '添加服务器'" @confirm="onSubmit">
      <t-form ref="formRef" :data="formData" :rules="formRules" label-width="80px">
        <t-form-item label="名称" name="name">
          <t-input v-model="formData.name" placeholder="如 filesystem" :disabled="editing" />
        </t-form-item>
        <t-form-item label="传输方式" name="transport">
          <t-select v-model="formData.transport">
            <t-option value="stdio" label="stdio (本地子进程)" />
            <t-option value="sse" label="SSE (远程 HTTP)" />
          </t-select>
        </t-form-item>
        <template v-if="formData.transport === 'stdio'">
          <t-form-item label="命令" name="command">
            <t-input v-model="formData.command" placeholder="如 npx" />
          </t-form-item>
          <t-form-item label="参数" name="argsText">
            <t-textarea v-model="formData.argsText" placeholder="每行一个参数" :autosize="{ minRows: 2 }" />
          </t-form-item>
        </template>
        <template v-else>
          <t-form-item label="URL" name="url">
            <t-input v-model="formData.url" placeholder="https://example.com/sse" />
          </t-form-item>
        </template>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive, computed } from 'vue'
import { MessagePlugin, DialogPlugin, type FormInstanceFunctions } from 'tdesign-vue-next'
import { useMcpStore } from '@/stores/mcp'
import type { McpServer, McpServerInfo } from '@/api/mcp'

type TagTheme = 'default' | 'success' | 'danger' | 'warning'

const mcpStore = useMcpStore()
const showDialog = ref(false)
const editing = ref(false)
const formRef = ref<FormInstanceFunctions>()

const formData = reactive({
  name: '',
  transport: 'stdio' as 'stdio' | 'sse',
  command: '',
  argsText: '',
  url: '',
})

const formRules = computed(() => ({
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  command: formData.transport === 'stdio'
    ? [{ required: true, message: '请输入命令', trigger: 'blur' }]
    : [],
  url: formData.transport === 'sse'
    ? [{ required: true, message: '请输入 URL', trigger: 'blur' }]
    : [],
}))

function getInfo(name: string): McpServerInfo | undefined {
  return mcpStore.serverInfos[name]
}

function statusTheme(name: string): TagTheme {
  const info = getInfo(name)
  if (!info) return 'default'
  const map: Record<string, TagTheme> = {
    connected: 'success',
    failed: 'danger',
    disabled: 'warning',
    disconnected: 'default',
  }
  return map[info.status] ?? 'default'
}

function statusLabel(name: string): string {
  const info = getInfo(name)
  if (!info) return '未知'
  const map: Record<string, string> = {
    connected: '已连接',
    failed: '失败',
    disabled: '已禁用',
    disconnected: '未连接',
  }
  return map[info.status] || info.status
}

function openAdd() {
  editing.value = false
  Object.assign(formData, { name: '', transport: 'stdio', command: '', argsText: '', url: '' })
  showDialog.value = true
}

function openEdit(server: McpServer) {
  editing.value = true
  Object.assign(formData, {
    name: server.name,
    transport: server.transport,
    command: server.command || '',
    argsText: server.args.join('\n'),
    url: server.url || '',
  })
  showDialog.value = true
}

async function onSubmit() {
  const valid = await formRef.value?.validate?.()
  if (valid !== true) return

  const cfg: Partial<McpServer> = {
    name: formData.name,
    transport: formData.transport,
    command: formData.transport === 'stdio' ? formData.command : null,
    args:
      formData.transport === 'stdio'
        ? formData.argsText.split('\n').map((s) => s.trim()).filter(Boolean)
        : [],
    url: formData.transport === 'sse' ? formData.url : null,
  }

  try {
    if (editing.value) {
      await mcpStore.updateServer(formData.name, cfg)
      MessagePlugin.success('已更新')
    } else {
      await mcpStore.addServer(cfg)
      MessagePlugin.success('已添加')
    }
    showDialog.value = false
  } catch (e) {
    MessagePlugin.error(`保存失败: ${e}`)
  }
}

async function onToggle(name: string, enabled: boolean) {
  try {
    await mcpStore.toggleServer(name, enabled)
  } catch (e) {
    MessagePlugin.error(`切换失败: ${e}`)
  }
}

async function onReconnect(name: string) {
  try {
    await mcpStore.reconnectServer(name)
    MessagePlugin.success(`已重连 ${name}`)
  } catch (e) {
    MessagePlugin.error(`重连失败: ${e}`)
  }
}

function confirmDelete(name: string) {
  const dialog = DialogPlugin.confirm({
    header: '删除 MCP 服务器',
    body: `确定删除 "${name}"?该操作不可恢复。`,
    confirmBtn: '删除',
    cancelBtn: '取消',
    theme: 'danger',
    onConfirm: async () => {
      dialog.destroy()
      try {
        await mcpStore.removeServer(name)
        MessagePlugin.success('已删除')
      } catch (e) {
        MessagePlugin.error(`删除失败: ${e}`)
      }
    },
  })
}

onMounted(() => mcpStore.fetchServers())
</script>

<style scoped>
.mcp-manage {
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
.loading-tip,
.empty-tip {
  padding: 32px 16px;
  color: var(--td-text-color-placeholder);
  font-size: 13px;
  text-align: center;
}
.server-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.server-card {
  width: 100%;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.server-name {
  font-weight: 600;
}
.config-summary {
  margin: 8px 0;
  padding: 8px 12px;
  background: var(--td-bg-color-component);
  border-radius: 4px;
}
.config-summary code {
  font-size: 12px;
  word-break: break-all;
}
.capabilities {
  margin-top: 12px;
}
.cap-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
}
.cap-list code {
  background: var(--td-bg-color-component);
  padding: 1px 6px;
  border-radius: 4px;
}
.error-text {
  color: var(--td-error-color);
  font-size: 12px;
  margin-top: 8px;
}
.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>