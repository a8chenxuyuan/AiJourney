<!-- ResultShareModal.vue：行程分享弹窗——生成/复制分享链接与二维码、关闭分享 -->
<script setup lang="ts">
import { ref } from 'vue'
import { Modal, Input, Button, message } from 'ant-design-vue'
import { createShare, closeShare } from '@/api/trip'
import QRCode from 'qrcode'

const props = defineProps<{
  planId: string
}>()

const loading = defineModel<boolean>('loading', { default: false })

const shareVisible = ref(false)
// shareUrl：分享链接（前端路由完整地址）
const shareUrl = ref('')
// shareViewCount：分享页累计访问次数（传播效果）
const shareViewCount = ref(0)
// shareQrDataUrl：分享链接的二维码图片（Data URL）
const shareQrDataUrl = ref('')

/**
 * handleShare：开启行程分享并弹出链接与二维码
 * 后端会复用未过期的旧令牌，重复点击不会更换链接
 */
const handleShare = async () => {
  loading.value = true
  try {
    const res = await createShare(props.planId, 7)
    if (res.success && res.data) {
      shareUrl.value = `${window.location.origin}/share/${res.data.share_token}`
      shareViewCount.value = res.data.share_view_count ?? 0
      shareQrDataUrl.value = await QRCode.toDataURL(shareUrl.value, { width: 160, margin: 1 })
      shareVisible.value = true
    } else {
      message.error(res.message || '开启分享失败')
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '开启分享失败')
  } finally {
    loading.value = false
  }
}

/**
 * handleCopyShareLink：复制分享链接到剪贴板
 */
const handleCopyShareLink = async () => {
  try {
    await navigator.clipboard.writeText(shareUrl.value)
    message.success('分享链接已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = shareUrl.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    message.success('分享链接已复制')
  }
}

/**
 * handleCloseShare：关闭分享（二次确认），原链接立即失效
 */
const handleCloseShare = () => {
  Modal.confirm({
    title: '关闭分享',
    content: '关闭后原分享链接将立即失效，确定关闭吗？',
    okText: '关闭分享',
    cancelText: '取消',
    onOk: async () => {
      try {
        await closeShare(props.planId)
        message.success('分享已关闭')
        shareVisible.value = false
      } catch {
        message.error('关闭分享失败')
      }
    }
  })
}

/**
 * ensureShareQr：海报需要二维码；尚未分享时静默创建分享并生成大尺寸二维码
 * （不走 handleShare，避免弹出分享弹窗）
 */
const ensureShareQr = async (): Promise<string> => {
  if (shareQrDataUrl.value) return shareQrDataUrl.value
  const res = await createShare(props.planId, 7)
  if (!res.success || !res.data) return ''
  shareUrl.value = `${window.location.origin}/share/${res.data.share_token}`
  shareViewCount.value = res.data.share_view_count ?? 0
  shareQrDataUrl.value = await QRCode.toDataURL(shareUrl.value, { width: 240, margin: 1 })
  return shareQrDataUrl.value
}

defineExpose({ handleShare, ensureShareQr })
</script>

<template>
  <Modal v-model:open="shareVisible" title="分享行程" :footer="null" style="border-radius: 12px;">
    <p style="color: #666; margin-bottom: 12px;">
      任何人通过此链接可在 7 天内只读查看这份行程，无需登录。
      <span v-if="shareViewCount > 0" style="color: #fa8c16;">累计被浏览 {{ shareViewCount }} 次</span>
    </p>
    <div style="display: flex; gap: 16px; align-items: flex-start;">
      <div style="flex: 1;">
        <div style="display: flex; gap: 8px; margin-bottom: 12px;">
          <Input :value="shareUrl" readonly />
          <Button type="primary" @click="handleCopyShareLink">复制链接</Button>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #999; font-size: 13px;">分享内容仅含行程数据，不含你的个人信息</span>
          <Button danger size="small" @click="handleCloseShare">关闭分享</Button>
        </div>
      </div>
      <div v-if="shareQrDataUrl" style="text-align: center;">
        <img :src="shareQrDataUrl" alt="分享二维码" style="width: 120px; height: 120px; border: 1px solid #eee; border-radius: 8px;" />
        <p style="color: #999; font-size: 12px; margin: 4px 0 0;">手机扫码查看</p>
      </div>
    </div>
  </Modal>
</template>
