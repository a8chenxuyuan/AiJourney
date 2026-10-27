<!--
  src/views/Messages.vue：消息中心（微信式双栏）
  作用：左栏三段——「新朋友」好友申请卡、「互动通知」（赞/评/回复/好友事件）、
       好友与会话列表（未读置顶）；右栏聊天窗（气泡 + 游标加载历史 + 发送）。
       实时消息经 notify store 的 WS 事件（lastEvent）驱动追加与红点刷新。
  子组件：Messages/（Sidebar 左栏、ChatPanel 聊天窗、CallOverlay 通话浮层）
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 挂载时并行拉取申请/通知/会话/好友与红点；
 * 2. ?peer= 深链（用户主页「发消息」跳入）自动选中对应会话；
 * 3. 选中会话拉历史（拉取即置位已读）→ 红点刷新；
 * 4. watch lastEvent：chat 事件追加气泡（当前会话再拉一次置已读），
 *    notification 事件刷新红点与列表。
 */
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useNotifyStore } from '@/stores/notify'
import {
  acceptFriend,
  getConversations,
  getFriendRequests,
  getFriends,
  getNotifications,
  readNotifications,
  rejectFriend,
  sendMessage,
  type ChatMessageItem,
  type Conversation,
  type FriendRequest,
  type FriendItem,
  type NotificationItem
} from '@/api/social'
import MessagesSidebar from './Messages/MessagesSidebar.vue'
import MessagesChatPanel from './Messages/MessagesChatPanel.vue'
import MessagesCallOverlay from './Messages/MessagesCallOverlay.vue'

const route = useRoute()
const router = useRouter()
const notify = useNotifyStore()

// 左栏数据
const requests = ref<FriendRequest[]>([])
const notifications = ref<NotificationItem[]>([])
const conversations = ref<Conversation[]>([])
const friends = ref<FriendItem[]>([])
const leftLoading = ref(true)

// 当前会话与子组件句柄
const activePeer = ref<{ id: number; name: string; online: boolean } | null>(null)
const chatRef = ref<InstanceType<typeof MessagesChatPanel> | null>(null)
const callRef = ref<InstanceType<typeof MessagesCallOverlay> | null>(null)

/**
 * loadLeft：加载左栏四类数据
 */
const loadLeft = async () => {
  leftLoading.value = true
  try {
    const [reqRes, ntfRes, convRes, frdRes] = await Promise.all([
      getFriendRequests(),
      getNotifications({ page: 1, size: 10 }),
      getConversations(),
      getFriends()
    ])
    requests.value = reqRes.data?.requests || []
    notifications.value = ntfRes.data?.items || []
    conversations.value = convRes.data?.conversations || []
    friends.value = frdRes.data?.friends || []
  } finally {
    leftLoading.value = false
  }
}

/**
 * openChat：选中会话并让聊天窗拉取历史（拉取即置位已读）
 */
const openChat = async (peer: { id: number; name: string; online: boolean }) => {
  activePeer.value = peer
  await chatRef.value?.openChat(peer)
}

/**
 * handleAccept / handleReject：处理好友申请
 */
const handleAccept = async (r: FriendRequest) => {
  const res = await acceptFriend(r.friendship_id)
  if (res.success) {
    message.success(`已添加 ${r.username}`)
    await loadLeft()
    // 顺势打开新会话
    const friend = friends.value.find((f) => f.user_id === r.user_id)
    openChat({
      id: r.user_id,
      name: r.username,
      online: friend?.is_online || false
    })
  }
}

const handleReject = async (r: FriendRequest) => {
  const res = await rejectFriend(r.friendship_id)
  if (res.success) {
    message.info('已拒绝')
    loadLeft()
  }
}

/**
 * readAllNotifications：一键全部已读
 */
const readAllNotifications = async () => {
  const res = await readNotifications()
  if (res.success) {
    await loadLeft()
    notify.refreshBadge()
  }
}

/**
 * handleCallRecord：通话结束后写入会话的通话记录卡片（仅当前会话回填气泡）
 */
const handleCallRecord = async (payload: { peerId: number; text: string }) => {
  const res = await sendMessage(payload.peerId, payload.text, 'call')
  if (res.success && res.data?.message && activePeer.value?.id === payload.peerId) {
    chatRef.value?.appendMessage(res.data.message)
  }
}

/**
 * onStartCall：聊天窗工具栏发起通话 → 通话浮层执行 WebRTC 呼叫
 */
const onStartCall = (kind: 'voice' | 'video') => {
  if (activePeer.value) callRef.value?.startCall(activePeer.value, kind)
}

/**
 * ?peer= 深链：从用户主页「发消息」跳入
 */
const openFromQuery = async () => {
  const peerId = Number(route.query.peer)
  if (!peerId) return
  const conv = conversations.value.find((c) => c.peer_id === peerId)
  const frd = friends.value.find((f) => f.user_id === peerId)
  await openChat({
    id: peerId,
    name: conv?.peer_name || frd?.username || `用户 ${peerId}`,
    online: conv?.is_online || frd?.is_online || false
  })
  router.replace({ query: { ...route.query, peer: undefined } })
}

onMounted(async () => {
  await loadLeft()
  await openFromQuery()
})

// 实时事件消费：聊天追加 + 通知刷新 + 通话信令
const stopWatch = watch(
  () => notify.lastEvent,
  async (event) => {
    if (!event) return
    if (event.type === 'chat') {
      const msg = event.message as ChatMessageItem | undefined
      if (!msg) return
      if (activePeer.value && msg.sender_id === activePeer.value.id) {
        await chatRef.value?.appendIncoming(msg)
      } else {
        notify.refreshBadge()
        message.info(`来自 ${msg.sender_name || '好友'} 的新消息`)
      }
      loadLeft()
    } else if (event.type === 'notification') {
      await loadLeft()
      notify.refreshBadge()
    } else if (event.type === 'call' && event.signal) {
      await callRef.value?.handleCallSignal(event.signal, event.from || 0, event.from_name || '好友')
    }
  }
)
onUnmounted(() => stopWatch())
</script>

<template>
  <div class="msg-page page-fade">
    <div class="msg-grid">
      <MessagesSidebar
        :requests="requests"
        :notifications="notifications"
        :friends="friends"
        :left-loading="leftLoading"
        :active-peer-id="activePeer?.id ?? null"
        @accept="handleAccept"
        @reject="handleReject"
        @read-all="readAllNotifications"
        @open-chat="openChat"
      />
      <MessagesChatPanel
        ref="chatRef"
        :peer="activePeer"
        @sent="loadLeft"
        @start-call="onStartCall"
      />
    </div>

    <MessagesCallOverlay ref="callRef" @record="handleCallRecord" />
  </div>
</template>

<style scoped>
/* 满屏应用式布局：撑满视口剩余高度（顶栏60 + 内容区上下padding 28/56），
   左栏与聊天窗内部各自滚动，页面不再留大段空白 */
.msg-page {
  height: calc(100vh - 144px);
  min-height: 420px;
  display: flex;
  flex-direction: column;
}
.msg-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 16px;
}
/* 左右栏外壳样式由主文件统一下发（子组件根节点继承父级 scope） */
.msg-left,
.msg-right {
  background: #fff;
  border-radius: 16px;
  border: 1px solid #f0f0f0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.msg-left {
  padding: 12px;
  overflow-y: auto;
}
@media (max-width: 780px) {
  /* 窄屏退化为纵向堆叠，恢复自然高度 */
  .msg-page {
    height: auto;
    min-height: calc(100vh - 144px);
  }
  .msg-grid {
    grid-template-columns: 1fr;
  }
}
</style>
