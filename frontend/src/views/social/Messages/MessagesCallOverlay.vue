<!--
  MessagesCallOverlay.vue：WebRTC 实时音视频通话浮层——信令处理、媒体协商、通话状态机与控制条
-->
<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { message } from 'ant-design-vue'
import { sendCallSignal } from '@/api/social'

const emit = defineEmits<{
  /** 通话结束需要写入会话的通话记录（peerId + 记录文本） */
  record: [payload: { peerId: number; text: string }]
}>()

// 流程：主叫 getUserMedia → offer（含呼叫类型）→ 被叫响铃 → 接听后
// setRemote + answer → 双向交换 ICE 候选 → 点对点音视频直连。
// 信令经 HTTP /chat/call/signal 发送、WS 实时到达对端（只推不收架构）。

// callState：通话状态机（idle 空闲 / outgoing 呼出中 / incoming 来电 / active 通话中）
const callState = ref<'idle' | 'outgoing' | 'incoming' | 'active'>('idle')
const callType = ref<'voice' | 'video'>('voice')
const callPeer = ref<{ id: number; name: string } | null>(null)
const callStatusText = ref('')
const localStream = ref<MediaStream | null>(null)
const remoteStream = ref<MediaStream | null>(null)
const pcRef = ref<RTCPeerConnection | null>(null)
const callSeconds = ref(0)
const micOn = ref(true)
const camOn = ref(true)
const localVideoRef = ref<HTMLVideoElement | null>(null)
const remoteVideoRef = ref<HTMLVideoElement | null>(null)
// 内部句柄：计时器 / 响铃超时 / 早到的 ICE 候选缓冲
let callTimer: number | null = null
let ringTimer: number | null = null
let pendingIce: RTCIceCandidateInit[] = []

// 免费 STUN：帮助不同 NAT 后的浏览器互相发现（同机/局域网场景 host 候选即可直连）
const RTC_CONFIG: RTCConfiguration = {
  iceServers: [{ urls: ['stun:stun.miwifi.com:3478', 'stun:stun.chat.bilibili.com:3478'] }]
}

/** 秒数格式化为 mm:ss */
const fmtDuration = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

/** 按通话类型申请麦克风/摄像头；设备缺失时逐级降级（无声视频 / 纯音频） */
const getMedia = async (kind: 'voice' | 'video') => {
  const wantVideo = kind === 'video'
  const attempts: MediaStreamConstraints[] = wantVideo
    ? [{ audio: true, video: true }, { video: true }, { audio: true }]
    : [{ audio: true }]
  for (const c of attempts) {
    try {
      return await navigator.mediaDevices.getUserMedia(c)
    } catch {
      /* 本档设备不可用，尝试下一档 */
    }
  }
  throw new Error('no-media-device')
}

/** 创建 RTCPeerConnection，挂接本地轨道与信令回调 */
const setupPeer = () => {
  teardownPeer()
  const pc = new RTCPeerConnection(RTC_CONFIG)
  pcRef.value = pc
  localStream.value?.getTracks().forEach((t) => pc.addTrack(t, localStream.value!))
  pc.onicecandidate = (e) => {
    if (e.candidate && callPeer.value) {
      sendCallSignal(callPeer.value.id, { event: 'ice', candidate: e.candidate.toJSON() })
    }
  }
  pc.ontrack = (e) => {
    remoteStream.value = e.streams[0]
    nextTick(() => {
      if (remoteVideoRef.value) remoteVideoRef.value.srcObject = remoteStream.value
    })
  }
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'connected' && callState.value !== 'active') {
      callState.value = 'active'
      callStatusText.value = '通话中'
      if (ringTimer) {
        window.clearTimeout(ringTimer)
        ringTimer = null
      }
      callTimer = window.setInterval(() => callSeconds.value++, 1000)
    }
    if (pc.connectionState === 'failed') {
      message.error('连接失败，请检查网络')
      cleanupCall(true)
    }
  }
  nextTick(() => {
    if (localVideoRef.value) localVideoRef.value.srcObject = localStream.value
  })
}

/** 仅销毁连接层（pc + 计时器），保留媒体流 */
const teardownPeer = () => {
  pcRef.value?.close()
  pcRef.value = null
  if (callTimer) {
    window.clearInterval(callTimer)
    callTimer = null
  }
}

/** 结束通话全量清理；log=true 时上报通话记录待写入会话 */
const cleanupCall = (log: boolean) => {
  const kind = callType.value
  const secs = callSeconds.value
  const peerId = callPeer.value?.id
  teardownPeer()
  localStream.value?.getTracks().forEach((t) => t.stop())
  localStream.value = null
  remoteStream.value = null
  if (ringTimer) {
    window.clearTimeout(ringTimer)
    ringTimer = null
  }
  callState.value = 'idle'
  callPeer.value = null
  callSeconds.value = 0
  micOn.value = true
  camOn.value = true
  pendingIce = []
  // 通话记录卡片：谁挂断谁写入（时长超 1 秒才记录时长）
  if (log && peerId) {
    const text = secs > 1 ? `${kind}|${fmtDuration(secs)}` : kind
    emit('record', { peerId, text })
  }
}

/** 呼出 30 秒无人接听自动取消 */
const armRingTimeout = () => {
  if (ringTimer) window.clearTimeout(ringTimer)
  ringTimer = window.setTimeout(() => {
    if (callState.value === 'outgoing') {
      message.info('对方未接听')
      cleanupCall(false)
    }
  }, 30000)
}

/** 发起呼叫：申请媒体 → 建连 → 发 offer */
const startCall = async (peer: { id: number; name: string }, kind: 'voice' | 'video') => {
  if (callState.value !== 'idle') return
  callPeer.value = peer
  callType.value = kind
  callState.value = 'outgoing'
  callStatusText.value = '正在等待对方接受…'
  try {
    localStream.value = await getMedia(kind)
    micOn.value = !!localStream.value?.getAudioTracks().length
    camOn.value = !!localStream.value?.getVideoTracks().length
    if (kind === 'video' && !micOn.value) message.info('未检测到麦克风，已切换为无声视频')
    setupPeer()
    const offer = await pcRef.value!.createOffer()
    await pcRef.value!.setLocalDescription(offer)
    const res = await sendCallSignal(peer.id, {
      event: 'offer',
      call_type: kind,
      sdp: pcRef.value!.localDescription
    })
    if (!res.data?.delivered) {
      message.warning('对方当前不在线')
      cleanupCall(false)
    } else {
      armRingTimeout()
    }
  } catch {
    message.error(kind === 'video' ? '无法访问摄像头/麦克风' : '无法访问麦克风')
    cleanupCall(false)
  }
}

/** 被叫接听 —— 申请媒体、应答 offer */
const acceptCall = async () => {
  if (callState.value !== 'incoming' || !incomingOffer.value) return
  callState.value = 'active'
  callStatusText.value = '正在接通…'
  try {
    localStream.value = await getMedia(callType.value)
    micOn.value = !!localStream.value?.getAudioTracks().length
    camOn.value = !!localStream.value?.getVideoTracks().length
    if (callType.value === 'video' && !micOn.value) message.info('未检测到麦克风，已切换为无声视频')
    setupPeer()
    await pcRef.value!.setRemoteDescription(incomingOffer.value)
    for (const c of pendingIce) await pcRef.value!.addIceCandidate(c)
    pendingIce = []
    const answer = await pcRef.value!.createAnswer()
    await pcRef.value!.setLocalDescription(answer)
    await sendCallSignal(callPeer.value!.id, { event: 'answer', sdp: pcRef.value!.localDescription })
  } catch {
    message.error('无法访问麦克风/摄像头')
    sendCallSignal(callPeer.value!.id, { event: 'hangup' })
    cleanupCall(false)
  }
}

/** 拒绝来电 */
const rejectCall = () => {
  sendCallSignal(callPeer.value?.id || 0, { event: 'reject' })
  cleanupCall(false)
}

/** 主动挂断（写通话记录） */
const hangupCall = () => {
  if (callPeer.value) sendCallSignal(callPeer.value.id, { event: 'hangup' })
  cleanupCall(true)
}

/** 静音与关摄像头（本地预览同步） */
const toggleMic = () => {
  micOn.value = !micOn.value
  localStream.value?.getAudioTracks().forEach((t) => (t.enabled = micOn.value))
}
const toggleCam = () => {
  camOn.value = !camOn.value
  localStream.value?.getVideoTracks().forEach((t) => (t.enabled = camOn.value))
}

// incomingOffer：来电时缓存的 offer SDP（接听后才用）
const incomingOffer = ref<RTCSessionDescriptionInit | null>(null)

/** 处理对端信令（由 WS call 事件分发进来） */
const handleCallSignal = async (
  sig: Record<string, any>,
  fromId: number,
  fromName: string
) => {
  switch (sig.event) {
    case 'offer': {
      // 来电：正在通话中则自动拒接（忙线）
      if (callState.value !== 'idle') {
        sendCallSignal(fromId, { event: 'reject', reason: 'busy' })
        return
      }
      incomingOffer.value = sig.sdp
      callType.value = sig.call_type === 'video' ? 'video' : 'voice'
      callPeer.value = { id: fromId, name: fromName }
      callState.value = 'incoming'
      callStatusText.value = callType.value === 'video' ? '📹 邀请你视频通话' : '📞 邀请你语音通话'
      break
    }
    case 'answer': {
      if (!pcRef.value) return
      await pcRef.value.setRemoteDescription(sig.sdp)
      for (const c of pendingIce) await pcRef.value.addIceCandidate(c)
      pendingIce = []
      break
    }
    case 'ice': {
      if (sig.candidate) {
        if (pcRef.value?.remoteDescription) await pcRef.value.addIceCandidate(sig.candidate)
        else pendingIce.push(sig.candidate) // 远端描述未就绪先缓冲
      }
      break
    }
    case 'reject': {
      message.info(sig.reason === 'busy' ? '对方正在通话中' : '对方已拒绝')
      cleanupCall(false)
      break
    }
    case 'hangup': {
      message.info(callState.value === 'active' ? '对方已挂断' : '对方已取消')
      cleanupCall(true)
      break
    }
  }
}

defineExpose({ startCall, handleCallSignal })
</script>

<template>
  <Teleport to="body">
    <div v-if="callState !== 'idle'" class="call-overlay" :class="{ video: callType === 'video' }">
      <template v-if="callType === 'video'">
        <video ref="remoteVideoRef" autoplay playsinline class="call-video-remote"></video>
        <video
          ref="localVideoRef"
          autoplay
          playsinline
          muted
          class="call-video-local"
        ></video>
      </template>
      <div class="call-center">
        <div class="call-avatar">{{ (callPeer?.name || '?').charAt(0).toUpperCase() }}</div>
        <h3 class="call-name">{{ callPeer?.name }}</h3>
        <p class="call-status">
          {{ callState === 'active' ? fmtDuration(callSeconds) : callStatusText }}
        </p>
      </div>
      <div class="call-controls">
        <template v-if="callState === 'incoming'">
          <button class="call-btn danger" title="拒绝" @click="rejectCall">✕</button>
          <button class="call-btn ok" title="接听" @click="acceptCall">✓</button>
        </template>
        <template v-else>
          <button
            class="call-btn ghost-btn"
            :class="{ off: !micOn }"
            :title="micOn ? '静音' : '取消静音'"
            @click="toggleMic"
          >
            {{ micOn ? '🎙️' : '🔇' }}
          </button>
          <button
            v-if="callType === 'video'"
            class="call-btn ghost-btn"
            :class="{ off: !camOn }"
            :title="camOn ? '关闭摄像头' : '打开摄像头'"
            @click="toggleCam"
          >
            {{ camOn ? '📹' : '🚫' }}
          </button>
          <button class="call-btn danger" title="挂断" @click="hangupCall">✕</button>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* ==================== 通话浮层（WebRTC 实时音视频） ==================== */
.call-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 深藏青夜幕：语音通话背景（视频通话时被画面铺满） */
  background: linear-gradient(180deg, #14211d 0%, #0a0f0d 100%);
}
.call-overlay.video {
  background: #05090d;
}
.call-video-remote {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.call-video-local {
  position: absolute;
  right: 24px;
  bottom: 116px;
  width: 220px;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  border-radius: 14px;
  border: 2px solid rgba(255, 255, 255, 0.28);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  background: #0b1620;
}
.call-center {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #fff;
  text-align: center;
}
.call-avatar {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: var(--grad-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40px;
  font-weight: 800;
  color: #fff;
  /* 来电呼吸光圈 */
  animation: callPulse 1.8s ease-in-out infinite;
}
@keyframes callPulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(46, 107, 94, 0.45);
  }
  50% {
    box-shadow: 0 0 0 22px rgba(46, 107, 94, 0);
  }
}
.call-name {
  margin: 4px 0 0;
  font-size: 24px;
  font-weight: 700;
  color: #fff;
}
.call-status {
  margin: 0;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.68);
  font-variant-numeric: tabular-nums;
}
.call-controls {
  position: absolute;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  display: flex;
  gap: 18px;
}
.call-btn {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: none;
  font-size: 22px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}
.call-btn.danger {
  background: #ef4444;
  color: #fff;
  box-shadow: 0 8px 20px rgba(239, 68, 68, 0.4);
}
.call-btn.danger:hover {
  background: #dc2626;
}
.call-btn.ok {
  background: #22c55e;
  color: #fff;
  box-shadow: 0 8px 20px rgba(34, 197, 94, 0.4);
  font-size: 26px;
}
.call-btn.ok:hover {
  background: #16a34a;
}
.call-btn.ghost-btn {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  backdrop-filter: blur(6px);
}
.call-btn.ghost-btn:hover {
  background: rgba(255, 255, 255, 0.24);
}
.call-btn.ghost-btn.off {
  background: rgba(255, 255, 255, 0.9);
}
</style>
