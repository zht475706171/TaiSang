import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { McpServer, McpServerInfo, ImportBatchResult } from '@/api/mcp'
import {
  listMcpServers,
  addMcpServer,
  updateMcpServer,
  deleteMcpServer,
  toggleMcpServer,
  reconnectMcpServer,
  getMcpServerInfo,
  importCliMcp,
  importBatchMcp,
} from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServer[]>([])
  const serverInfos = ref<Record<string, McpServerInfo>>({})
  const loading = ref(false)

  async function fetchServers() {
    loading.value = true
    try {
      servers.value = await listMcpServers()
      await Promise.all(
        servers.value.map(async (s) => {
          try {
            serverInfos.value[s.name] = await getMcpServerInfo(s.name)
          } catch {
            // 忽略单个 server 的错误
          }
        }),
      )
    } finally {
      loading.value = false
    }
  }

  async function addServer(cfg: Partial<McpServer>) {
    const res = await addMcpServer(cfg)
    await fetchServers()
    return res
  }

  async function updateServer(name: string, cfg: Partial<McpServer>) {
    const res = await updateMcpServer(name, cfg)
    await fetchServers()
    return res
  }

  async function removeServer(name: string) {
    await deleteMcpServer(name)
    await fetchServers()
  }

  async function toggleServer(name: string, enabled: boolean) {
    const res = await toggleMcpServer(name, enabled)
    await fetchServers()
    return res
  }

  async function reconnectServer(name: string) {
    const res = await reconnectMcpServer(name)
    serverInfos.value[name] = res
    return res
  }

  async function importCli(line: string) {
    const res = await importCliMcp(line)
    await fetchServers()
    return res
  }

  async function importBatch(text: string): Promise<ImportBatchResult> {
    const res = await importBatchMcp(text)
    await fetchServers()
    return res
  }

  return {
    servers,
    serverInfos,
    loading,
    fetchServers,
    addServer,
    updateServer,
    removeServer,
    toggleServer,
    reconnectServer,
    importCli,
    importBatch,
  }
})