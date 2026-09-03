# Vue 脚手架实施计划(Plan 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭起 Vue3 + Vite + TDesign 脚手架,构建产物落到 src/taisang/web/static/,FastAPI 零改动 serve Vue 占位页。

**Architecture:** frontend/ 子目录放 Vue 源码,Vite outDir 指向 ../static/,dev server proxy /api → FastAPI:8765。TDesign 主题 brand 色浅蓝 #3B82F6,保留 IBM Plex 字体。

**Tech Stack:** Vue 3.5 + Vite 7 + TDesign 1.19 + Pinia 3 + vue-router 4.5 + TypeScript 5.6 (strict) + npm

---

### Task 1: 初始化 frontend/ 目录 + package.json + tsconfig

**Files:**
- Create: `src/taisang/web/frontend/package.json`
- Create: `src/taisang/web/frontend/tsconfig.json`
- Create: `src/taisang/web/frontend/tsconfig.node.json`
- Create: `src/taisang/web/frontend/.gitignore`

- [ ] **Step 1: 创建 frontend/ 目录 + .gitignore**

`src/taisang/web/frontend/.gitignore`:
```
node_modules
dist
*.local
.vite
```

- [ ] **Step 2: 写 package.json**

`src/taisang/web/frontend/package.json`:
```json
{
  "name": "taisang-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "type-check": "vue-tsc -b --noEmit"
  },
  "dependencies": {
    "vue": "^3.5.34",
    "vue-router": "^4.5.0",
    "pinia": "^3.0.4",
    "tdesign-vue-next": "^1.19.2",
    "tdesign-icons-vue-next": "0.4.4"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^6.0.6",
    "typescript": "~5.6.0",
    "vite": "^7.3.5",
    "vue-tsc": "^2.2.0",
    "less": "^4.6.4",
    "@types/node": "^22.0.0"
  }
}
```

- [ ] **Step 3: 写 tsconfig.json(strict)**

`src/taisang/web/frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "useDefineForClassFields": true,
    "jsx": "preserve",
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] },
    "types": ["vite/client"]
  },
  "include": ["src/**/*", "src/**/*.vue"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: 写 tsconfig.node.json**

`src/taisang/web/frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "skipLibCheck": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true,
    "types": ["node"]
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: 验证目录结构**

Run: `ls src/taisang/web/frontend/`
Expected: 看到 package.json, tsconfig.json, tsconfig.node.json, .gitignore

- [ ] **Step 6: Commit**

```bash
git add src/taisang/web/frontend/package.json src/taisang/web/frontend/tsconfig.json src/taisang/web/frontend/tsconfig.node.json src/taisang/web/frontend/.gitignore
git commit -m "feat(frontend): 初始化 Vue 脚手架 — package.json + tsconfig(strict)"
```

---

### Task 2: vite.config.ts + index.html + npm install

**Files:**
- Create: `src/taisang/web/frontend/vite.config.ts`
- Create: `src/taisang/web/frontend/index.html`

- [ ] **Step 1: 写 vite.config.ts**

`src/taisang/web/frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: '../static',
    emptyOutDir: false,
    assetsDir: 'assets',
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

- [ ] **Step 2: 写 index.html**

`src/taisang/web/frontend/index.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TaiSang · coding agent</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

- [ ] **Step 3: npm install**

Run: `cd src/taisang/web/frontend && npm install`
Expected: 安装成功,生成 node_modules/ 和 package-lock.json。可能有 deprecation warning,无 error。

- [ ] **Step 4: 验证 vite 可执行**

Run: `cd src/taisang/web/frontend && npx vite --version`
Expected: 输出 vite 版本号(7.x)

- [ ] **Step 5: Commit(不含 node_modules)**

```bash
git add src/taisang/web/frontend/vite.config.ts src/taisang/web/frontend/index.html src/taisang/web/frontend/package-lock.json
git commit -m "feat(frontend): vite.config.ts + index.html + 依赖安装"
```

---

### Task 3: theme.css + main.ts + App.vue + router + HomeView

**Files:**
- Create: `src/taisang/web/frontend/src/assets/theme.css`
- Create: `src/taisang/web/frontend/src/main.ts`
- Create: `src/taisang/web/frontend/src/App.vue`
- Create: `src/taisang/web/frontend/src/router/index.ts`
- Create: `src/taisang/web/frontend/src/views/HomeView.vue`
- Create: `src/taisang/web/frontend/src/vite-env.d.ts`

- [ ] **Step 1: 写 theme.css(浅蓝 brand + IBM Plex 字体)**

`src/taisang/web/frontend/src/assets/theme.css`:
```css
/* IBM Plex 字体 — 从 FastAPI /static/fonts/ 加载 */
@font-face {
  font-family: 'IBM Plex Sans';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/static/fonts/IBMPlexSans-Regular.woff2') format('woff2');
}
@font-face {
  font-family: 'IBM Plex Sans';
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url('/static/fonts/IBMPlexSans-Medium.woff2') format('woff2');
}
@font-face {
  font-family: 'IBM Plex Sans';
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url('/static/fonts/IBMPlexSans-SemiBold.woff2') format('woff2');
}
@font-face {
  font-family: 'IBM Plex Sans';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url('/static/fonts/IBMPlexSans-Bold.woff2') format('woff2');
}
@font-face {
  font-family: 'IBM Plex Mono';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/static/fonts/IBMPlexMono-Regular.woff2') format('woff2');
}
@font-face {
  font-family: 'IBM Plex Mono';
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url('/static/fonts/IBMPlexMono-Medium.woff2') format('woff2');
}
@font-face {
  font-family: 'IBM Plex Mono';
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url('/static/fonts/IBMPlexMono-SemiBold.woff2') format('woff2');
}

/* TDesign 主题覆盖 — 浅蓝 brand */
:root:root {
  --td-brand-color: #3B82F6;
  --td-brand-color-hover: #2563EB;
  --td-brand-color-active: #1D4ED8;
  --td-brand-color-light: #DBEAFE;
  --td-brand-color-focus: #3B82F6;
  --td-brand-color-disabled: #93C5FD;

  --td-brand-color-1: #EFF6FF;
  --td-brand-color-2: #DBEAFE;
  --td-brand-color-3: #BFDBFE;
  --td-brand-color-4: #93C5FD;
  --td-brand-color-5: #60A5FA;
  --td-brand-color-6: #3B82F6;
  --td-brand-color-7: #2563EB;
  --td-brand-color-8: #1D4ED8;
  --td-brand-color-9: #1E40AF;
  --td-brand-color-10: #1E3A8A;

  --td-text-color-primary: rgba(0, 0, 0, 0.9);
  --td-text-color-secondary: rgba(0, 0, 0, 0.6);
  --td-text-color-placeholder: rgba(0, 0, 0, 0.4);
  --td-bg-color-container: #fff;
  --td-bg-color-page: #f6f6f6;
  --td-bg-color-secondarycontainer: #f3f3f3;
  --td-component-stroke: var(--td-gray-color-3, #e7e7e7);

  --app-font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --app-font-mono: 'IBM Plex Mono', 'SF Mono', Consolas, monospace;
}

:root:root[theme-mode="dark"] {
  --td-brand-color: #60A5FA;
  --td-brand-color-hover: #3B82F6;
  --td-brand-color-active: #2563EB;
  --td-brand-color-light: #1E3A8A;

  --td-text-color-primary: rgba(255, 255, 255, 0.9);
  --td-text-color-secondary: rgba(255, 255, 255, 0.6);
  --td-text-color-placeholder: rgba(255, 255, 255, 0.4);
  --td-bg-color-container: #242424;
  --td-bg-color-page: #181818;
  --td-bg-color-secondarycontainer: #2c2c2c;
  --td-component-stroke: var(--td-gray-color-11, #414141);
}

body {
  margin: 0;
  font-family: var(--app-font-family);
  background: var(--td-bg-color-page);
  color: var(--td-text-color-primary);
}
```

- [ ] **Step 2: 写 vite-env.d.ts**

`src/taisang/web/frontend/src/vite-env.d.ts`:
```typescript
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
```

- [ ] **Step 3: 写 main.ts**

`src/taisang/web/frontend/src/main.ts`:
```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import './assets/theme.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(TDesign)
app.mount('#app')
```

- [ ] **Step 4: 写 App.vue**

`src/taisang/web/frontend/src/App.vue`:
```vue
<template>
  <router-view />
</template>

<script setup lang="ts">
</script>
```

- [ ] **Step 5: 写 router/index.ts**

`src/taisang/web/frontend/src/router/index.ts`:
```typescript
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
  ],
})

export default router
```

- [ ] **Step 6: 写 HomeView.vue(占位)**

`src/taisang/web/frontend/src/views/HomeView.vue`:
```vue
<template>
  <div class="home-placeholder">
    <h1>TaiSang Vue</h1>
    <p>脚手架就位,等待 Plan 2 实现 Sidebar + 空状态首页</p>
  </div>
</template>

<style scoped>
.home-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100vh;
  font-family: var(--app-font-family);
}
.home-placeholder h1 {
  font-size: 32px;
  font-weight: 600;
  color: var(--td-brand-color);
  margin: 0 0 8px;
}
.home-placeholder p {
  color: var(--td-text-color-placeholder);
  font-size: 14px;
}
</style>
```

- [ ] **Step 7: type-check**

Run: `cd src/taisang/web/frontend && npm run type-check`
Expected: 无错误退出(exit 0)

- [ ] **Step 8: Commit**

```bash
git add src/taisang/web/frontend/src/
git commit -m "feat(frontend): theme.css(浅蓝 brand) + main.ts + App.vue + router + HomeView"
```

---

### Task 4: npm run dev 验证 + npm run build 验证 + FastAPI 集成

**Files:** 无新文件,只验证

- [ ] **Step 1: 启动 Vite dev server 验证**

Run: `cd src/taisang/web/frontend && npm run dev`(后台运行)
Expected: Vite 起在 http://localhost:5173/,无 error

- [ ] **Step 2: curl dev server 验证 HTML 返回**

Run: `curl -s http://localhost:5173/ | head -20`
Expected: 返回 HTML,包含 `<div id="app"></div>` 和 `<script type="module" src="/src/main.ts">`

- [ ] **Step 3: 停 dev server**

- [ ] **Step 4: npm run build 验证产物落到 static/**

Run: `cd src/taisang/web/frontend && npm run build`
Expected:
- 构建成功,无 error
- `src/taisang/web/static/index.html` 被覆盖(Vite 生成)
- `src/taisang/web/static/assets/` 目录存在(含 JS/CSS chunks)
- `src/taisang/web/static/fonts/` 保留(IBM Plex woff2 还在)

- [ ] **Step 5: 验证 static/ 目录结构**

Run: `ls src/taisang/web/static/`
Expected: 看到 index.html, assets/, fonts/

Run: `ls src/taisang/web/static/assets/`
Expected: 看到 index-[hash].js, index-[hash].css 等

Run: `ls src/taisang/web/static/fonts/`
Expected: 看到 IBMPlex*.woff2(7 个文件)

- [ ] **Step 6: 启动 FastAPI 验证集成**

启动 FastAPI(端口 8765),然后:
Run: `curl -s http://127.0.0.1:8765/ | head -20`
Expected: 返回 Vite 构建的 index.html(含 `<script type="module" src="/assets/index-[hash].js">`)

Run: `curl -s http://127.0.0.1:8765/static/fonts/IBMPlexSans-Regular.woff2 -o /dev/null -w "%{http_code}"`
Expected: 200

Run: `curl -s http://127.0.0.1:8765/api/config`
Expected: 返回 JSON `{"model":"Kimi-K2.6",...}`

- [ ] **Step 7: 停 FastAPI**

- [ ] **Step 8: Python 测试回归验证**

Run: `cd /d/GoProject/TaiSang && python -m pytest --tb=short -q`
Expected: 188 passed(后端没改,应该全过)

- [ ] **Step 9: Commit 构建产物**

注意:构建产物(index.html + assets/)要不要入库?这是个小决策。
- 入库:仓库里有可运行的静态文件,clone 后不用 build 就能跑。但每次前端改动都会 dirty。
- 不入库:仓库干净,但 clone 后必须 build 才能跑。

我倾向**入库 index.html 但 .gitignore assets/**,这样 FastAPI 至少能 serve 一个能用的页面,assets 用 hash 命名每次都变,不入库避免噪音。但这样不一致。

更干净的方案:**整个 assets/ 入库**,反正 TaiSang 不是大项目,产物不大。每次前端改重新 build + commit 产物。

```bash
git add src/taisang/web/static/index.html src/taisang/web/static/assets/
git commit -m "build(frontend): Vite 构建产物 — index.html + assets/(Vue 占位页)"
```

---

### Task 5: 最终验证 + spec 状态更新

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-vue-scaffold-design.md`

- [ ] **Step 1: 完整端到端验证**

启动 FastAPI,用 Playwright 或 curl 验证:
- 访问 http://127.0.0.1:8765/ 看到"TaiSang Vue"占位页
- 页面样式正确(浅蓝标题)
- 字体加载(IBM Plex Sans)
- /api/config 返回正常
- /static/fonts/IBMPlexSans-Regular.woff2 返回 200

- [ ] **Step 2: 更新 spec 状态**

`docs/superpowers/specs/2026-09-03-vue-scaffold-design.md` 第 2 行:
```
**状态**: 已实施(2026-09-03) — Plan 1 完成
```

- [ ] **Step 3: Commit spec 状态**

```bash
git add docs/superpowers/specs/2026-09-03-vue-scaffold-design.md
git commit -m "docs(spec): Vue 脚手架设计 — 标记为已实施(Plan 1 完成)"
```

- [ ] **Step 4: 标记 Plan 1 todo 完成**

在 TodoWrite 里把 Plan 1 标记为 completed。

---

## 自检 checklist

写完 plan 后我自检过:

1. **Spec 覆盖**:
   - ✅ 脚手架搭建 → Task 1-3
   - ✅ 主题 brand 浅蓝 → Task 3 Step 1
   - ✅ 路由配置 → Task 3 Step 5
   - ✅ 构建链 Vite + FastAPI 集成 → Task 4
   - ✅ 验证标准 → Task 4-5

2. **Placeholder 扫描**:无 TBD/TODO,每个步骤都有完整代码。

3. **类型一致性**:
   - `@/*` alias 在 tsconfig.json 和 vite.config.ts 都配了
   - `vite-env.d.ts` 声明了 `*.vue` 模块
   - `theme.css` 变量名跟 TDesign 官方一致(`--td-brand-color` 等)

4. **风险预案**:
   - Vite 7 + Node 24 兼容性 → Task 2 Step 4 验证
   - emptyOutDir: false → Task 4 Step 5 验证 fonts/ 保留
   - 构建产物入库策略 → Task 4 Step 9 说明