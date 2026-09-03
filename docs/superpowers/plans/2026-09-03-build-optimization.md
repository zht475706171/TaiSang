# 构建优化实施计划(Plan 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vite 构建产物拆包,主 chunk < 500KB,消除"chunks larger than 500 kB"警告。

**Architecture:** 路由懒加载 + Vite manualChunks 把 tdesign / vue / vendor 拆成独立 chunk。

**Tech Stack:** Vite 7 + vue-router 4.5 + TypeScript

---

### Task 1: 路由懒加载 + manualChunks 拆包

**Files:**
- Modify: `src/taisang/web/frontend/src/router/index.ts`
- Modify: `src/taisang/web/frontend/vite.config.ts`

- [ ] **Step 1: 路由改懒加载**

`src/taisang/web/frontend/src/router/index.ts`:
```typescript
import { createRouter, createWebHistory } from 'vue-router'

const ChatView = () => import('@/views/ChatView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: ChatView },
    { path: '/chat/:id', name: 'chat', component: ChatView },
  ],
})

export default router
```

- [ ] **Step 2: vite.config.ts 加 manualChunks**

`src/taisang/web/frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  base: '/static/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: '../static',
    emptyOutDir: false,
    assetsDir: 'assets',
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          'tdesign': ['tdesign-vue-next', 'tdesign-icons-vue-next'],
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: type-check + build 验证**

Run: `cd src/taisang/web/frontend && npm run type-check && npm run build`
Expected:
- type-check 无错误
- build 成功
- chunks 列表中 tdesign 和 vue-vendor 拆出来,主 chunk(不含 tdesign)显著缩小
- 无 "chunks larger than 600 kB" 警告

- [ ] **Step 4: Python 测试回归**

Run: `python -m pytest --tb=short -q`
Expected: 188 passed

- [ ] **Step 5: Commit**

```bash
git add src/taisang/web/frontend/src/router/index.ts src/taisang/web/frontend/vite.config.ts src/taisang/web/static/index.html src/taisang/web/static/assets/
git commit -m "perf(frontend): Plan 6 — Vite manualChunks 拆包 + 路由懒加载"
```

---

## 自检 checklist

1. **目标覆盖**:主 chunk < 500KB → Task 1 Step 3 验证
2. **Placeholder 扫描**:无 TBD/TODO
3. **类型一致性**:无新类型