import { createRouter, createWebHistory } from 'vue-router'

const ChatView = () => import('@/views/ChatView.vue')
const SkillManage = () => import('@/views/SkillManage.vue')
const McpManage = () => import('@/views/McpManage.vue')
const PromptManage = () => import('@/views/PromptManage.vue')
const AgentManage = () => import('@/views/AgentManage.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: ChatView },
    { path: '/chat/:id', name: 'chat', component: ChatView },
    { path: '/skills', name: 'skills', component: SkillManage },
    { path: '/mcp', name: 'mcp', component: McpManage },
    { path: '/prompts', name: 'prompts', component: PromptManage },
    { path: '/agents', name: 'agents', component: AgentManage },
  ],
})

export default router