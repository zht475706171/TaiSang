<template>
  <div class="app-layout">
    <Sidebar @open-config="configOpen = true" />
    <main class="app-main">
      <router-view />
    </main>
    <ConfigModal v-model="configOpen" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Sidebar from '@/components/Sidebar.vue'
import ConfigModal from '@/components/ConfigModal.vue'
import { useSessionStore } from '@/stores/session'

const configOpen = ref(false)
const store = useSessionStore()

onMounted(() => {
  store.fetchSessions()
})
</script>

<style>
.app-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--td-bg-color-page);
}
</style>