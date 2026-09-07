import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { McpServer, McpServerInfo } from '@/api/mcp'
import {
  listMcpServers,
  addMcpServer,
  updateMcpServer,
  deleteMcpServer,
  toggleMcpServer,
  reconnectMcpServer,
  getMcpServerInfo,
} from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServer[]>([])
  const serverInfos = ref<Record<string, McpServerInfo>>({})
  const loading = ref(false)

  async function fetchServers() {
    loading.value = true
    try {
      servers.value = await listMcpServers()
      // 并行拉取每个 server 的详细信息(tools/resources/prompts/status)
      await Promise.all(
        servers.value.map(async (s) => {
          try {
            serverInfos.value[s.name] = await getMcpServerInfo(s.name)
          } catch {
            // 忽略单个 server 的错误,其他 server 仍能展示
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
  }
})