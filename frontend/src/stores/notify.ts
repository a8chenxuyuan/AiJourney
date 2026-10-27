/**
 * src/stores/notify.ts：消息通知全局状态（红点 + WebSocket 长连）
 * 作用：登录后建立 WS /api/chat/ws/notify 长连（token 走 query 鉴权），
 *      接收 chat / notification 实时事件驱动侧边栏红点；断线 5 秒自动重连，
 *      重连成功后 HTTP 全量对账（refreshBadge），保证最终一致。
 *      页面层（Messages.vue）通过 watch lastEvent 追加实时消息。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { message } from 'ant-design-vue'
import { useAuthStore } from './auth'
import { getBadge, type BadgeData, type ChatMessageItem } from '@/api/social'

/** 实时事件载体：与后端 WS 推送同构（chat 带 message，notification 带 notification，call 带 WebRTC 信令） */
export interface RealtimeEvent {
  type: 'chat' | 'notification' | 'call'
  message?: ChatMessageItem
  /** call 事件：发起人与信令负载 */
  from?: number
  from_name?: string
  signal?: Record<string, any>
  notification?: {
    id: number
    ntype: string
    text: string
    payload?: Record<string, any>
    actor_name?: string | null
    created_at: string | null
  }
}

export const useNotifyStore = defineStore('notify', () => {
  // badge：侧边栏红点聚合；connected：WS 连接状态
  const badge = ref<BadgeData | null>(null)
  const connected = ref(false)

  // lastEvent：最近一次实时事件（引用替换触发 watch）
  const lastEvent = ref<RealtimeEvent | null>(null)

  // 内部：WS 实例与重连定时器
  let socket: WebSocket | null = null
  let reconnectTimer: number | null = null

  /**
   * refreshBadge：HTTP 全量对账红点（登录后 / 收到事件后 / 重连后调用）
   */
  const refreshBadge = async () => {
    const auth = useAuthStore()
    if (!auth.isAuthenticated) return
    try {
      const res = await getBadge()
      if (res.success && res.data) badge.value = res.data
    } catch {
      // 红点拉取失败不打扰用户
    }
  }

  /**
   * buildWsUrl：由 HTTP API 基地址推导 WS 地址（http(s)→ws(s)）
   */
  const buildWsUrl = (token: string) => {
    const base =
      import.meta.env.VITE_API_BASE_URL || `http://${window.location.hostname}:8000/api`
    const wsBase = base.replace(/^http/, 'ws')
    return `${wsBase}/chat/ws/notify?token=${encodeURIComponent(token)}`
  }

  /**
   * handleMessage：WS 事件分发 → 更新红点 / 广播给页面
   */
  const handleMessage = (raw: string) => {
    try {
      const event = JSON.parse(raw) as RealtimeEvent
      lastEvent.value = event
      // 聊天消息：若 Messages.vue 正开着当前会话会自行消费并置已读；
      // 这里统一刷红点做兜底（打开会话后 refreshBadge 会把数清零回来）
      if (event.type === 'chat') {
        refreshBadge()
      } else if (event.type === 'notification') {
        refreshBadge()
        const text = event.notification?.text
        if (text) message.info(text)
      }
      // call 事件由页面层（Messages.vue）消费，这里不做全局提示
    } catch {
      // 非 JSON 帧忽略
    }
  }

  /**
   * connect：建立 WS 长连（未登录不连；重复调用幂等）
   */
  const connect = () => {
    const auth = useAuthStore()
    if (!auth.isAuthenticated || socket) return
    socket = new WebSocket(buildWsUrl(auth.token || ''))

    socket.onopen = () => {
      connected.value = true
      refreshBadge() // 重连后全量对账
    }
    socket.onmessage = (ev) => handleMessage(ev.data as string)
    socket.onclose = () => {
      connected.value = false
      socket = null
      // 断线 5 秒自动重连（仍登录时）
      const stillAuthed = useAuthStore().isAuthenticated
      if (stillAuthed && reconnectTimer === null) {
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = null
          connect()
        }, 5000)
      }
    }
    socket.onerror = () => socket?.close()
  }

  /**
   * disconnect：登出时关闭连接并清空红点
   */
  const disconnect = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    socket?.close()
    socket = null
    connected.value = false
    badge.value = null
  }

  // 红点总数（侧边栏徽标显示）
  const totalBadge = computed(() => badge.value?.total || 0)

  return { badge, connected, lastEvent, totalBadge, refreshBadge, connect, disconnect }
})
