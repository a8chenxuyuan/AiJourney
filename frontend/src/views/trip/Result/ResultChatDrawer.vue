<!-- ResultChatDrawer.vue：AI 修改助手——悬浮入口（待处理意见角标）与对话抽屉 -->
<script setup lang="ts">
import { ref } from 'vue'
import { Drawer, Badge, Button, Input, Tag } from 'ant-design-vue'
import { sendPlanChat } from '@/api/trip'

const props = defineProps<{
  planId: string
  regenerateLoading: boolean
}>()

const pendingCount = defineModel<number>('pendingCount', { default: 0 })

const emit = defineEmits<{
  (e: 'regenerate'): void
  (e: 'refresh-feedbacks'): void
}>()

const chatDrawerVisible = ref(false)
// chatMessages：聊天记录（meta 字段仅在 assistant 反馈类消息上携带结构化信息）
const chatMessages = ref<Array<{
  role: 'user' | 'assistant'
  content: string
  day_index?: number | null
  tags?: string[]
}>>([
  {
    role: 'assistant',
    content: '你好！我是本次行程的修改助手。直接告诉我你想怎么调整，例如："第二天太赶了，去掉一个景点"、"换一家海鲜餐厅"。我也可以回答行程相关的问题。'
  }
])
const chatInput = ref('')
const chatSending = ref(false)
// chatListRef：消息列表 DOM 引用（自动滚动到底部用）
const chatListRef = ref<HTMLDivElement | null>(null)

/**
 * openChatDrawer：打开聊天抽屉
 */
const openChatDrawer = () => {
  chatDrawerVisible.value = true
  scrollChatToBottom()
}

/**
 * scrollChatToBottom：把聊天列表滚动到底部（下一帧执行，确保 DOM 已更新）
 */
const scrollChatToBottom = () => {
  requestAnimationFrame(() => {
    if (chatListRef.value) {
      chatListRef.value.scrollTop = chatListRef.value.scrollHeight
    }
  })
}

/**
 * handleSendChat：发送一条消息给修改助手
 *
 * 流程：本地追加用户消息 → 调用后端 /chat（带最近对话历史）→
 * 追加助手回复（feedback 类回复带 天数/标签 元信息）→ 同步反馈列表。
 */
const handleSendChat = async () => {
  const text = chatInput.value.trim()
  if (!text || chatSending.value) return

  chatMessages.value.push({ role: 'user', content: text })
  chatInput.value = ''
  scrollChatToBottom()

  chatSending.value = true
  try {
    // 除刚追加的这条用户消息外，全部作为历史传给后端
    const history = chatMessages.value
      .slice(0, -1)
      .map((m) => ({ role: m.role, content: m.content }))
    const res = await sendPlanChat(props.planId, text, history)
    if (res.success && res.data) {
      chatMessages.value.push({
        role: 'assistant',
        content: res.data.reply,
        day_index: res.data.day_index,
        tags: res.data.tags
      })
      pendingCount.value = res.data.pending_count
      // 有新反馈入库时刷新"修改记录"卡片
      if (res.data.intent === 'feedback') emit('refresh-feedbacks')
    } else {
      chatMessages.value.push({ role: 'assistant', content: res.message || '服务暂时不可用，请稍后再试。' })
    }
  } catch (error) {
    console.error('发送消息失败', error)
    chatMessages.value.push({ role: 'assistant', content: '网络异常，请稍后再试。' })
  } finally {
    chatSending.value = false
    scrollChatToBottom()
  }
}

/**
 * onChatEnter：聊天输入框回车处理
 * Enter 直接发送；Shift+Enter 换行
 */
const onChatEnter = (e: KeyboardEvent) => {
  if (e.shiftKey) return
  e.preventDefault()
  handleSendChat()
}
</script>

<template>
  <!-- AI 修改助手悬浮入口（带待处理意见数角标） -->
  <div style="position: fixed; right: 32px; bottom: 32px; z-index: 100;">
    <Badge :count="pendingCount" :offset="[-6, 6]">
      <Button
        type="primary"
        size="large"
        style="border-radius: 26px; height: 52px; padding: 0 24px; font-size: 15px; box-shadow: 0 4px 12px rgba(24, 144, 255, 0.45);"
        @click="openChatDrawer"
      >
        AI 修改助手
      </Button>
    </Badge>
  </div>

  <!-- AI 修改助手聊天抽屉 -->
  <Drawer v-model:visible="chatDrawerVisible" title="AI 修改助手" placement="right" width="420">
    <!-- 消息列表 -->
    <div ref="chatListRef" style="height: calc(100vh - 260px); overflow-y: auto; padding-right: 4px;">
      <div
        v-for="(msg, idx) in chatMessages"
        :key="idx"
        :style="{
          display: 'flex',
          justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          marginBottom: '12px'
        }"
      >
        <div
          :style="{
            maxWidth: '86%',
            padding: '10px 14px',
            borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
            background: msg.role === 'user' ? '#1890ff' : '#f5f5f5',
            color: msg.role === 'user' ? '#fff' : '#333',
            fontSize: '13px',
            lineHeight: '1.7',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word'
          }"
        >
          <div>{{ msg.content }}</div>
          <!-- feedback 类回复的结构化确认信息 -->
          <div
            v-if="msg.role === 'assistant' && (msg.day_index || (msg.tags && msg.tags.length))"
            style="margin-top: 6px;"
          >
            <Tag v-if="msg.day_index" color="blue">第 {{ msg.day_index }} 天</Tag>
            <Tag v-else color="purple">整体</Tag>
            <Tag v-for="t in msg.tags || []" :key="t" color="orange">{{ t }}</Tag>
            <span style="font-size: 11px; color: #999; margin-left: 4px;">已记入修改意见</span>
          </div>
        </div>
      </div>
      <div v-if="chatSending" style="color: #999; font-size: 12px; margin: 4px 0 12px;">
        助手正在思考…
      </div>
    </div>

    <!-- 底部：输入区 + 重新生成入口 -->
    <template #footer>
      <div style="display: flex; gap: 8px; align-items: flex-end;">
        <Input.TextArea
          v-model:value="chatInput"
          :rows="2"
          placeholder="描述你想怎么修改行程，Enter 发送（Shift+Enter 换行）"
          style="flex: 1;"
          @press-enter="onChatEnter"
        />
        <Button type="primary" :loading="chatSending" @click="handleSendChat">发送</Button>
      </div>
      <div style="margin-top: 10px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: #999;">已积累 {{ pendingCount }} 条修改意见</span>
        <Button
          size="small"
          type="primary"
          ghost
          :disabled="pendingCount === 0"
          :loading="regenerateLoading"
          @click="emit('regenerate')"
        >
          根据反馈重新生成行程
        </Button>
      </div>
    </template>
  </Drawer>
</template>
