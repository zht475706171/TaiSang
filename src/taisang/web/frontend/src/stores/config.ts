import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getConfig } from '@/api/config'

/** 全局配置 store:debug 模式 + LLM 配置缓存。

 * ConfigModal 保存后写 store,useChatStream 从 store 读 debug 控制 tool gate。
 * 跨组件同步(ConfigModal 在 App.vue,useChatStream 在 ChatView)靠这个 store。
 */
export const useConfigStore = defineStore('config', () => {
  const debug = ref(false)
  const loaded = ref(false)

  /** 从后端拉一次配置(应用启动时调)。 */
  async function load() {
    try {
      const cfg = await getConfig()
      debug.value = cfg.debug ?? false
      loaded.value = true
    } catch (e) {
      console.warn('load config failed:', e)
    }
  }

  /** ConfigModal 保存 debug 后调用,同步 store。 */
  function setDebug(on: boolean) {
    debug.value = on
  }

  return { debug, loaded, load, setDebug }
})