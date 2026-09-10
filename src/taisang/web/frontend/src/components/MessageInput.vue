<template>
  <div class="message-input">
    <!-- 当前工作目录小字:用户导入项目后展示,点击可重新选择 -->
    <div v-if="sourceRoot" class="cwd-line" :title="sourceRoot">
      <t-icon name="folder" class="cwd-icon" />
      <span class="cwd-text">{{ sourceRoot }}</span>
    </div>
    <div class="input-row">
      <!-- + 按钮:弹出菜单(预留扩展位,目前仅"导入项目") -->
      <t-dropdown
        trigger="click"
        placement="top-left"
        :min-column-width="120"
        @click="handleMenuClick"
      >
        <t-button shape="circle" variant="outline" aria-label="更多操作">
          <template #icon>
            <t-icon name="add" />
          </template>
        </t-button>
        <template #dropdown>
          <t-dropdown-menu>
            <t-dropdown-item value="import-project">
              导入项目
            </t-dropdown-item>
            <!-- 预留扩展位:后续可加"附加文件""新建会话"等 -->
          </t-dropdown-menu>
        </template>
      </t-dropdown>
      <textarea
        ref="taRef"
        v-model="text"
        class="query-textarea"
        :placeholder="placeholder"
        rows="1"
        aria-label="输入消息,Enter 发送,Shift+Enter 换行"
        @keydown="handleKeydown"
        @input="autoResize"
      ></textarea>
      <t-button
        v-if="!streaming"
        shape="circle"
        theme="primary"
        aria-label="发送"
        :disabled="!text.trim()"
        @click="handleSend"
      >
        <template #icon>
          <t-icon name="send" />
        </template>
      </t-button>
      <t-button
        v-else
        shape="circle"
        theme="danger"
        aria-label="停止"
        @click="handleStop"
      >
        <template #icon>
          <t-icon name="stop" />
        </template>
      </t-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'

const props = withDefaults(
  defineProps<{
    placeholder?: string
    autofocus?: boolean
    streaming?: boolean
    sourceRoot?: string | null
  }>(),
  {
    placeholder: '输入问题,Enter 发送,Shift+Enter 换行...',
    autofocus: false,
    streaming: false,
    sourceRoot: null,
  },
)

const emit = defineEmits<{
  send: [query: string]
  stop: []
  importProject: []
}>()
const text = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)

onMounted(() => {
  if (props.autofocus && taRef.value) {
    taRef.value.focus()
  }
})

function autoResize() {
  const el = taRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleSend() {
  const q = text.value.trim()
  if (!q) return
  emit('send', q)
  text.value = ''
  nextTick(autoResize)
}

function handleStop() {
  emit('stop')
}

function handleMenuClick(data: { value?: string } | string) {
  // tdesign v1:回调参数 {value, label};v2:可能直接 value。两种都兼容。
  const value = typeof data === 'string' ? data : data?.value
  if (value === 'import-project') {
    emit('importProject')
  }
}
</script>

<style scoped>
.message-input {
  padding: 0 24px 20px;
}
.cwd-line {
  max-width: 800px;
  margin: 0 auto 6px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  font-family: var(--app-font-mono);
  padding: 0 8px;
  cursor: default;
}
.cwd-icon {
  flex-shrink: 0;
  font-size: 12px;
}
.cwd-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
/* 一体化输入行:大圆角容器,textarea 与圆形发送按钮同体 */
.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  max-width: 800px;
  margin: 0 auto;
  padding: 8px 8px 8px 8px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 14px;
  background: var(--td-bg-color-container);
  transition: border-color 0.15s;
}
.input-row:focus-within {
  border-color: var(--td-brand-color);
}
.query-textarea {
  flex: 1;
  resize: none;
  border: none;
  background: transparent;
  padding: 7px 0;
  color: var(--td-text-color-primary);
  font-family: var(--app-font-family);
  font-size: 14px;
  line-height: 1.5;
  min-height: 36px;
  max-height: 200px;
  overflow-y: auto;
  outline: none;
}
.query-textarea::placeholder {
  color: var(--td-text-color-placeholder);
}
</style>