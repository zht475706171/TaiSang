# Vue 脚手架设计(Plan 1)

**日期**: 2026-09-03
**状态**: 已实施(2026-09-03) — Plan 1 完成,FastAPI 集成验证通过
**作者**: 泰哥 + Claude

## 背景

TaiSang 前端现在是纯 JS + 单 HTML 文件(`src/taisang/web/static/index.html`),功能已跑通但视觉粗糙。决定全量迁移到 Vue3 + Vite + TDesign,复刻 WeKnora 风格。拆成 5 个 plan,本设计只覆盖 **Plan 1:脚手架 + 主题 + 路由 + 构建链**。

## 目标

Plan 1 结束时:
- `src/taisang/web/frontend/` 有完整 Vue 项目,`npm run dev` 能起 Vite dev server(proxy /api → FastAPI)
- `npm run build` 产物输出到 `src/taisang/web/static/`(覆盖现有 index.html)
- FastAPI serve 后访问 `http://127.0.0.1:8765/` 能看到 Vue 空白页(带 TaiSang logo + "TaiSang Vue" 占位标题)
- TDesign 主题就位,brand 色浅蓝 #3B82F6,light/dark mode CSS 变量双套
- vue-router 配置 `/` 路由,指向占位 HomeView
- FastAPI 后端**零改动**

## 非目标(Plan 1 不做)

- Sidebar / 会话列表 / 新对话按钮(Plan 2)
- 空状态首页(Plan 2)
- SSE 流式对话 / 消息列表(Plan 3)
- LLM 配置页(Plan 4)
- Playwright e2e(Plan 5)

## 技术栈

| 依赖 | 版本 | 用途 |
|------|------|------|
| vue | ^3.5.34 | 框架 |
| vite | ^7.3.5 | 构建 |
| @vitejs/plugin-vue | ^6.0.6 | Vue SFC 支持 |
| typescript | ~5.6.0 | 类型(不用 6.0,太激进) |
| vue-tsc | ^2.2.0 | Vue 类型检查 |
| tdesign-vue-next | ^1.19.2 | UI 组件库 |
| tdesign-icons-vue-next | 0.4.4 | 图标 |
| vue-router | ^4.5.0 | 路由 |
| pinia | ^3.0.4 | 状态管理 |
| less | ^4.6.4 | 样式预处理(TDesign 依赖) |

不用:i18n / axios / @microsoft/fetch-event-source(用原生 fetch + EventSource)

## 目录结构

```
src/taisang/web/frontend/              # Vue 源码(新建)
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── index.html                         # Vite 入口 HTML
├── .gitignore                         # node_modules / dist 等
└── src/
    ├── main.ts                        # createApp + TDesign + Pinia + Router
    ├── App.vue                        # 根:RouterView
    ├── router/
    │   └── index.ts                   # 路由配置
    ├── views/
    │   └── HomeView.vue               # 占位首页(Plan 2 替换)
    └── assets/
        └── theme.css                  # TDesign 主题变量(浅蓝 brand)
```

构建产物(`npm run build` 后):
```
src/taisang/web/static/
├── index.html                         # Vite 生成(覆盖旧的)
├── assets/
│   ├── index-[hash].js
│   ├── index-[hash].css
│   └── ...vendor chunks
└── fonts/                             # 保留(从旧 static/ 继承)
    └── IBMPlex*.woff2
```

## 关键配置

### vite.config.ts

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
    outDir: '../static',           # 相对于 frontend/ → src/taisang/web/static/
    emptyOutDir: false,            # 不清空(保留 fonts/)
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

**关键点**:
- `outDir: '../static'` — 产物直接落到 FastAPI serve 的目录
- `emptyOutDir: false` — 不删 fonts/,但 Vite 会覆盖 index.html 和 assets/
- dev server proxy `/api` 和 `/static` → FastAPI(8765)

### 主题 theme.css

复刻 WeKnora 的 `theme.css` 双 root 覆盖技巧,brand 色改成浅蓝:

```css
:root:root {
  --td-brand-color: #3B82F6;
  --td-brand-color-hover: #2563EB;
  --td-brand-color-active: #1D4ED8;
  --td-brand-color-light: #DBEAFE;
  --td-brand-color-focus: #3B82F6;
  --td-brand-color-disabled: #93C5FD;
  /* 1-10 阶调色板 */
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
  --td-bg-color-container: #fff;
  --td-bg-color-page: #f6f6f6;
  --td-component-stroke: var(--td-gray-color-3);
  --app-font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
}

:root:root[theme-mode="dark"] {
  --td-brand-color: #60A5FA;
  --td-brand-color-hover: #3B82F6;
  --td-brand-color-active: #2563EB;
  --td-brand-color-light: #1E3A8A;
  --td-text-color-primary: rgba(255, 255, 255, 0.9);
  --td-bg-color-container: #242424;
  --td-bg-color-page: #181818;
  --td-component-stroke: var(--td-gray-color-11);
}
```

**字体**:保留 `src/taisang/web/static/fonts/IBMPlex*.woff2`,FastAPI 继续从 `/static/fonts/` serve。theme.css 里 `@font-face` 引用 `/static/fonts/IBMPlexSans-Regular.woff2` 等。

### main.ts

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

**注意**:不用 `installTDesignIconOfflineGuard`(WeKnora 的图标外网屏蔽),因为 TaiSang 不需要离线运行。如果发现图标请求外网,再加。

### App.vue

```vue
<template>
  <router-view />
</template>
```

### HomeView.vue(占位,Plan 2 替换)

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

### router/index.ts

```typescript
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
  ],
})

export default router
```

### package.json scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "type-check": "vue-tsc -b --noEmit"
  }
}
```

## 验证标准(Plan 1 完成)

1. `cd src/taisang/web/frontend && npm install` 成功
2. `npm run dev` 起 Vite dev server,访问 `http://localhost:5173/` 看到"TaiSang Vue"占位页
3. `npm run build` 产物落到 `src/taisang/web/static/`(index.html + assets/),fonts/ 保留
4. FastAI 启动后访问 `http://127.0.0.1:8765/` 看到 Vue 占位页(FastAPI serve 构建产物)
5. `npm run type-check` 无错误
6. 现有 Python 测试全过(`pytest` 188/188,因为后端没改)

## 风险

1. **Vite 7 + Node 24 兼容性** — WeKnora 用 Vite 7 + Node 20,我们 Node 24,理论兼容,但可能有 deprecation warning。出问题就降 Vite 到 6.x。
2. **TDesign 1.19 + Vue 3.5** — WeKnora 已验证这套组合,应该没问题。
3. **emptyOutDir: false 的副作用** — Vite 不会清空 static/,但会覆盖同名文件。旧 index.html 会被覆盖(正是我们要的),fonts/ 保留。如果旧 assets/ 有残留,手动清。
4. **构建产物路径** — `outDir: '../static'` 是相对于 `frontend/` 目录,要确认 Vite 运行时 cwd 是 frontend/。npm script 自动处理。
5. **FastAPI StaticFiles 缓存** — 构建后浏览器可能缓存旧 index.html。开发时用 Vite dev server,生产时硬刷新或加 cache-control(Plan 1 不处理)。

## 已确认决策

1. **包管理器**:npm(单项目,简单)
2. **TypeScript 严格模式**:`strict: true`
3. **字体**:保留 IBM Plex Sans/Mono,theme.css 引用 `/static/fonts/IBMPlex*.woff2`