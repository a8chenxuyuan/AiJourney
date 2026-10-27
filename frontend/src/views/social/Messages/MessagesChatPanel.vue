<!--
  MessagesChatPanel.vue：消息中心右栏聊天窗——会话头、游标加载历史、媒体/表情/文本发送
-->
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Empty, Input, message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { useNotifyStore } from '@/stores/notify'
import { getMessages, sendMessage, uploadChatMedia, type ChatMessageItem } from '@/api/social'
import { resolveImageUrl } from '@/api/community'

const props = defineProps<{
  peer: { id: number; name: string; online: boolean } | null
}>()

const emit = defineEmits<{
  sent: []
  'start-call': [kind: 'voice' | 'video']
}>()

const router = useRouter()
const auth = useAuthStore()
const notify = useNotifyStore()

const messages = ref<ChatMessageItem[]>([])
const hasMore = ref(false)
const chatLoading = ref(false)
const sending = ref(false)
const draft = ref('')
const listEl = ref<HTMLElement | null>(null)

const myId = computed(() => auth.user?.id ?? 0)

/** 聊天区滚到底（新消息/切换会话后） */
const scrollToBottom = () => {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  })
}

/** 选中会话（含拉取历史；拉取即置位已读） */
const openChat = async (peer: { id: number; name: string; online: boolean }) => {
  chatLoading.value = true
  try {
    const res = await getMessages(peer.id)
    messages.value = res.data?.messages || []
    hasMore.value = res.data?.has_more || false
    notify.refreshBadge() // 已读置位后红点回落
  } finally {
    chatLoading.value = false
  }
  scrollToBottom()
}

/** 向上加载更早历史（游标 = 当前最早一条 ID） */
const loadEarlier = async () => {
  if (!props.peer || !messages.value.length) return
  const earliest = messages.value[0].id
  const res = await getMessages(props.peer.id, earliest)
  const earlier = res.data?.messages || []
  messages.value = [...earlier, ...messages.value]
  hasMore.value = res.data?.has_more || false
}

/** 通用发送（文本/媒体/通话卡片共用；本地立即追加，接收方经 WS 实时收到） */
const doSend = async (content: string, type = 'text') => {
  if (!props.peer) return false
  const res = await sendMessage(props.peer.id, content, type)
  if (res.success && res.data?.message) {
    messages.value.push(res.data.message)
    scrollToBottom()
    emit('sent') // 会话列表的最后一条同步刷新
    return true
  }
  return false
}

/** 发送文本消息 */
const send = async () => {
  const text = draft.value.trim()
  if (!text || !props.peer) return
  sending.value = true
  try {
    if (await doSend(text)) draft.value = ''
  } finally {
    sending.value = false
  }
}

// 表情面板与常用表情
const emojiOpen = ref(false)
const EMOJIS = [
  '😀', '😁', '😂', '🤣', '😊', '😍', '😘', '😜', '🤔', '😎',
  '🥳', '😴', '😭', '😡', '👍', '👏', '🙏', '💪', '🤝', '✌️',
  '🎉', '🎊', '❤️', '💔', '🌹', '🍺', '☕', '🍰', '🏖️', '✈️',
  '🚄', '🗺️', '📸', '⛺', '🔥', '⭐', '🌈', '☀️', '🌧️', '🎒'
]

// uploading：媒体上传中（发送按钮同步禁用）
const uploading = ref(false)
const imgInput = ref<HTMLInputElement | null>(null)
const videoInput = ref<HTMLInputElement | null>(null)

const goUserHome = (uid: number) => router.push(`/user/${uid}`)

/** 选择图片/视频后上传并发送 */
const onMediaChange = async (e: Event, kind: 'image' | 'video') => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !props.peer) return
  if (kind === 'image' && file.size > 5 * 1024 * 1024) {
    message.warning('图片不能超过 5MB')
    return
  }
  if (kind === 'video' && file.size > 50 * 1024 * 1024) {
    message.warning('视频不能超过 50MB')
    return
  }
  uploading.value = true
  try {
    const up = await uploadChatMedia(file)
    if (up.success && up.data?.url) await doSend(up.data.url, kind)
  } finally {
    uploading.value = false
  }
}

/** 收起表情面板并请求主文件发起通话 */
const requestCall = (kind: 'voice' | 'video') => {
  emojiOpen.value = false
  emit('start-call', kind)
}

const insertEmoji = (em: string) => {
  draft.value += em
}

/** 点击图片新窗口查看原图 */
const openMedia = (url: string) => {
  const full = resolveImageUrl(url)
  if (full) window.open(full)
}

/** 收到 WS 新消息（当前会话）：追加气泡、补拉一次置已读、红点回落 */
const appendIncoming = async (msg: ChatMessageItem) => {
  messages.value.push(msg)
  scrollToBottom()
  await getMessages(msg.sender_id)
  notify.refreshBadge()
}

/** 本地追加一条消息（通话记录回填用） */
const appendMessage = (msg: ChatMessageItem) => {
  messages.value.push(msg)
  scrollToBottom()
}

defineExpose({ openChat, appendIncoming, appendMessage })
</script>

<template>
  <div class="msg-right">
    <template v-if="peer">
      <div class="msg-chat-head">
        <div
          class="msg-avatar clickable"
          :class="{ online: peer.online }"
          title="查看主页"
          @click="goUserHome(peer.id)"
        >
          {{ peer.name.charAt(0).toUpperCase() }}
        </div>
        <div>
          <b>{{ peer.name }}</b>
          <p class="msg-online-text">{{ peer.online ? '在线' : '离线' }}</p>
        </div>
        <Button size="small" class="msg-head-btn" @click="goUserHome(peer.id)">
          🏠 查看主页
        </Button>
      </div>

      <div ref="listEl" class="msg-list">
        <div v-if="hasMore" class="msg-more">
          <Button size="small" type="text" :loading="chatLoading" @click="loadEarlier">
            加载更早消息
          </Button>
        </div>
        <div
          v-for="m in messages"
          :key="m.id"
          class="msg-row"
          :class="{ mine: m.sender_id === myId }"
        >
          <img
            v-if="m.content_type === 'image'"
            class="msg-media"
            :src="resolveImageUrl(m.content) || ''"
            alt="图片消息"
            @click="openMedia(m.content)"
          />
          <video
            v-else-if="m.content_type === 'video'"
            class="msg-media"
            controls
            :src="resolveImageUrl(m.content) || ''"
          />
          <!-- 通话卡片：voice|mm:ss 为真实通话记录，纯 voice/video 为旧版邀请卡 -->
          <div v-else-if="m.content_type === 'call'" class="msg-call">
            <span class="msg-call-ico">{{ m.content.startsWith('video') ? '📹' : '📞' }}</span>
            <div>
              <b>{{ m.content.startsWith('video') ? '视频通话' : '语音通话' }}</b>
              <p v-if="m.content.includes('|')">
                {{ m.sender_id === myId ? '通话时长' : '已结束' }} {{ m.content.split('|')[1] }}
              </p>
              <p v-else>{{ m.sender_id === myId ? '已发出通话邀请' : '向你发起通话邀请' }}</p>
            </div>
          </div>
          <div v-else class="msg-bubble">{{ m.content }}</div>
          <span class="msg-time">{{ m.created_at?.slice(5, 16).replace('T', ' ') }}</span>
        </div>
        <Empty
          v-if="!messages.length && !chatLoading"
          description="还没有消息，打个招呼吧"
          style="margin-top: 80px;"
        />
      </div>

      <div class="msg-input">
        <div v-if="emojiOpen" class="msg-emoji-panel">
          <button v-for="em in EMOJIS" :key="em" class="msg-emoji" @click="insertEmoji(em)">
            {{ em }}
          </button>
        </div>
        <div class="msg-tools">
          <button class="msg-tool" title="发送图片" @click="imgInput?.click()">🖼️</button>
          <button class="msg-tool" title="发送视频" @click="videoInput?.click()">🎬</button>
          <button class="msg-tool" title="表情" @click="emojiOpen = !emojiOpen">😊</button>
          <button class="msg-tool" title="语音通话" @click="requestCall('voice')">📞</button>
          <button class="msg-tool" title="视频通话" @click="requestCall('video')">📹</button>
          <input
            ref="imgInput"
            type="file"
            accept="image/*"
            hidden
            @change="onMediaChange($event, 'image')"
          />
          <input
            ref="videoInput"
            type="file"
            accept="video/*"
            hidden
            @change="onMediaChange($event, 'video')"
          />
        </div>
        <div class="msg-input-row">
          <Input.TextArea
            v-model:value="draft"
            :rows="2"
            :maxlength="2000"
            placeholder="输入消息，回车发送"
            @keydown.enter.exact.prevent="send"
          />
          <Button
            type="primary"
            :loading="sending || uploading"
            :disabled="!draft.trim()"
            @click="send"
          >
            发送
          </Button>
        </div>
      </div>
    </template>
    <div v-else class="msg-placeholder">
      <Empty description="选择一个会话开始聊天" style="margin-top: 120px;" />
    </div>
  </div>
</template>

<style scoped>
.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e6f2e7;
  color: #2e7d32;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  flex-shrink: 0;
}
.msg-avatar.clickable {
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s;
}
.msg-avatar.clickable:hover {
  box-shadow: 0 0 0 3px rgba(46, 125, 50, 0.15);
  transform: scale(1.06);
}
.msg-chat-head {
  padding: 12px 18px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.msg-online-text {
  color: #aaa;
  font-size: 12px;
  margin: 0;
}
.msg-head-btn {
  margin-left: auto;
}
.msg-media {
  max-width: 260px;
  max-height: 200px;
  border-radius: 12px;
  cursor: zoom-in;
  display: block;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
video.msg-media {
  cursor: default;
  background: #000;
}
.msg-call {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #eee;
}
.msg-row.mine .msg-call {
  background: #d9f2dd;
  border-color: #c8e6c9;
}
.msg-call-ico {
  font-size: 24px;
}
.msg-call b {
  display: block;
  font-size: 14px;
}
.msg-call p {
  margin: 2px 0 0;
  font-size: 12px;
  color: #7d95a8;
}
.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #fafafa;
}
.msg-more {
  text-align: center;
}
.msg-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: 78%;
}
.msg-row.mine {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.msg-bubble {
  padding: 9px 13px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #eee;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}
.msg-row.mine .msg-bubble {
  background: #d9f2dd;
  border-color: #c8e6c9;
}
.msg-time {
  color: #bbb;
  font-size: 11px;
  flex-shrink: 0;
}
.msg-input {
  padding: 10px 14px 12px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.msg-tools {
  display: flex;
  gap: 2px;
}
.msg-tool {
  border: none;
  background: transparent;
  font-size: 18px;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.msg-tool:hover {
  background: #f2f8f2;
}
.msg-emoji-panel {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 2px;
  padding: 8px;
  border: 1px solid #f0f0f0;
  border-radius: 12px;
  background: #fafafa;
}
.msg-emoji {
  border: none;
  background: transparent;
  font-size: 20px;
  padding: 4px;
  cursor: pointer;
  border-radius: 6px;
}
.msg-emoji:hover {
  background: #eef7ef;
}
.msg-input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.msg-placeholder {
  flex: 1;
}
</style>
