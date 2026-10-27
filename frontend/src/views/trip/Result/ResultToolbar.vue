<!-- ResultToolbar.vue：结果页顶部操作栏——导航、复制摘要、发布社区与长图/PDF/海报导出 -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Tag, Dropdown, Menu, message } from 'ant-design-vue'
import { type TripPlan } from '@/api/trip'
import { getJournal } from '@/api/trip/companion'
import PublishCommunityModal from '@/components/PublishCommunityModal.vue'

const props = defineProps<{
  plan: TripPlan | null
  planId: string
  isPaid: boolean
  shareLoading: boolean
  getShareQr: () => Promise<string>
}>()

const emit = defineEmits<{
  (e: 'share'): void
  (e: 'collab'): void
  (e: 'pay'): void
}>()

const router = useRouter()

/**
 * mealTypeText：将餐饮类型转为中文
 */
const mealTypeText = (type?: string) => {
  const map: Record<string, string> = {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐'
  }
  return map[type || ''] || type || '餐饮'
}

/**
 * buildSummaryText：把当前行程生成便于分享/保存的纯文本摘要
 */
const buildSummaryText = (): string => {
  const p = props.plan
  if (!p) return ''
  const lines: string[] = []
  lines.push(`📍 ${p.city} ${p.travel_days || ''} 日行程`)
  lines.push(`🗓 ${p.start_date || ''} ~ ${p.end_date || ''}`)
  if (p.budget?.total) lines.push(`💰 预估总预算：¥${p.budget.total}`)
  lines.push('')
  for (const day of p.day_plans || []) {
    lines.push(`— 第 ${day.day_index} 天（${day.date || ''}）—`)
    if (day.description) lines.push(`主题：${day.description}`)
    for (const a of day.attractions || []) {
      const ticket = a.ticket_price !== undefined && a.ticket_price !== null
        ? `（门票¥${a.ticket_price}）` : ''
      lines.push(`  🏞 ${a.name}${ticket}`)
    }
    for (const m of day.meals || []) {
      if (m.name) {
        const cost = m.estimated_cost ? `（人均¥${m.estimated_cost}）` : ''
        lines.push(`  🍜 ${mealTypeText(m.type)}：${m.name}${cost}`)
      }
    }
    if (day.hotel?.name) lines.push(`  🏨 酒店：${day.hotel.name}`)
    lines.push('')
  }
  if (p.overall_suggestions) lines.push(`💡 整体建议：${p.overall_suggestions}`)
  return lines.join('\n')
}

/**
 * handleCopySummary：复制行程摘要文本到剪贴板（便于粘贴到微信/备忘录分享）
 */
const handleCopySummary = async () => {
  const text = buildSummaryText()
  if (!text) {
    message.warning('暂无行程数据')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    message.success('行程摘要已复制，可粘贴分享')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    message.success('行程摘要已复制')
  }
}

// ==================== 分享到社区（游记转发） ====================

const publishVisible = ref(false)
const publishJournalId = ref('')
const publishTitle = ref('')

/**
 * openPublishCommunity：先查游记，已生成则弹发布弹窗，否则引导去游记页
 */
const openPublishCommunity = async () => {
  try {
    const res = await getJournal(props.planId)
    if (res.success && res.data && res.data.status === 'done') {
      publishJournalId.value = res.data.id
      publishTitle.value = res.data.title
      publishVisible.value = true
    } else {
      message.info('游记尚未生成完成，先到游记页生成一篇吧')
      router.push(`/trip/${props.planId}/journal`)
    }
  } catch {
    message.error('查询游记失败')
  }
}

// ==================== 行程导出（长图 / PDF / 分享海报） ====================

// exporting：导出进行中状态（长图/PDF/海报共用，防止重复点击）
const exporting = ref(false)

/**
 * renderResultCanvas：把结果页整体渲染为高分辨率 canvas（长图/PDF 共用）
 * html2canvas 按需动态导入，避免拖慢首屏加载
 */
const renderResultCanvas = async (): Promise<HTMLCanvasElement | null> => {
  const resultEl = document.getElementById('trip-result-container')
  if (!resultEl) return null
  const html2canvas = (await import('html2canvas')).default as any
  return await html2canvas(resultEl, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#f5f5f5'
  })
}

/**
 * downloadDataUrl：触发浏览器下载 Data URL 文件
 */
const downloadDataUrl = (dataUrl: string, filename: string) => {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}

/**
 * handleExportImage：导出整页长图（PNG），适合直接发微信群/朋友圈
 */
const handleExportImage = async () => {
  const canvas = await renderResultCanvas()
  if (!canvas) return
  downloadDataUrl(canvas.toDataURL('image/png'), `trip-plan-${props.planId}.png`)
  message.success('长图已导出')
}

/**
 * handleExportPdf：导出多页 A4 PDF
 * 把长图按 A4 宽高比纵向切片，每片作为一页写入
 */
const handleExportPdf = async () => {
  const canvas = await renderResultCanvas()
  if (!canvas) return
  const { jsPDF } = await import('jspdf') as any

  const pdf = new jsPDF('p', 'mm', 'a4')
  const pageW = 210
  const pageH = 297
  // A4 页面对应的原始像素高度（保持宽度铺满、比例不变形）
  const pageHpx = Math.floor((canvas.width * pageH) / pageW)

  let offsetY = 0
  let pageIndex = 0
  while (offsetY < canvas.height) {
    const sliceH = Math.min(pageHpx, canvas.height - offsetY)
    const pageCanvas = document.createElement('canvas')
    pageCanvas.width = canvas.width
    pageCanvas.height = sliceH
    const ctx = pageCanvas.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, pageCanvas.width, sliceH)
    ctx.drawImage(canvas, 0, offsetY, canvas.width, sliceH, 0, 0, canvas.width, sliceH)

    if (pageIndex > 0) pdf.addPage()
    pdf.addImage(
      pageCanvas.toDataURL('image/jpeg', 0.92), 'JPEG',
      0, 0, pageW, (sliceH * pageW) / canvas.width
    )
    offsetY += sliceH
    pageIndex++
  }
  pdf.save(`trip-plan-${props.planId}.pdf`)
  message.success(`PDF 已导出（共 ${pageIndex} 页）`)
}

/**
 * drawRoundRect：canvas 圆角矩形路径（兼容未实现 roundRect 的浏览器）
 */
const drawRoundRect = (ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) => {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

/**
 * loadImage：把 Data URL 加载为可绘制 Image
 */
const loadImage = (src: string) =>
  new Promise<HTMLImageElement>((resolve, reject) => {
    const img = document.createElement('img')
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })

/**
 * handleExportPoster：生成"行程摘要 + 分享二维码"海报（PNG）
 * 纯 canvas 绘制：渐变底 + 概览信息 + 每日景点摘要 + 扫码入口
 */
const handleExportPoster = async () => {
  const p = props.plan
  if (!p) {
    message.warning('暂无行程数据')
    return
  }
  try {
    const qrDataUrl = await props.getShareQr()

    const W = 750
    const pad = 48
    const days = p.day_plans || []
    const listTop = 330
    const dayRowH = 108
    const bottomH = 230
    const H = listTop + days.length * dayRowH + bottomH

    const canvas = document.createElement('canvas')
    canvas.width = W
    canvas.height = H
    const ctx = canvas.getContext('2d')!
    const font = '"PingFang SC", "Microsoft YaHei", sans-serif'

    // 背景：深蓝 → 青色渐变
    const bg = ctx.createLinearGradient(0, 0, W, H)
    bg.addColorStop(0, '#0b3d91')
    bg.addColorStop(1, '#0e9aa7')
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, W, H)

    // 头部：品牌 + 标题 + 日期 + 预算
    ctx.fillStyle = 'rgba(255,255,255,0.75)'
    ctx.font = `22px ${font}`
    ctx.fillText('AI 旅行规划助手', pad, 64)
    ctx.fillStyle = '#ffffff'
    ctx.font = `bold 56px ${font}`
    ctx.fillText(`${p.city} · ${p.travel_days || days.length}日行程`, pad, 150)
    ctx.font = `26px ${font}`
    ctx.fillStyle = 'rgba(255,255,255,0.9)'
    ctx.fillText(`${p.start_date || ''} 至 ${p.end_date || ''}`, pad, 205)
    if (p.budget?.total) {
      ctx.fillText(`预估总预算 ¥${p.budget.total}`, pad, 252)
    }

    // 每日行程摘要卡片（白色圆角卡）
    ctx.fillStyle = '#ffffff'
    drawRoundRect(ctx, pad - 16, listTop - 36, W - (pad - 16) * 2, days.length * dayRowH + 52, 24)
    ctx.fill()

    days.forEach((day, i) => {
      const rowY = listTop + i * dayRowH
      ctx.fillStyle = '#0e9aa7'
      drawRoundRect(ctx, pad, rowY, 86, 44, 22)
      ctx.fill()
      ctx.fillStyle = '#ffffff'
      ctx.font = `bold 24px ${font}`
      ctx.fillText(`Day ${day.day_index}`, pad + 12, rowY + 31)
      ctx.fillStyle = '#1f1f1f'
      ctx.font = `26px ${font}`
      const names = (day.attractions || []).slice(0, 3).map(a => a.name).join(' · ') || '自由活动'
      ctx.fillText(names.length > 22 ? `${names.slice(0, 22)}…` : names, pad + 110, rowY + 31)
      ctx.fillStyle = '#8c8c8c'
      ctx.font = `22px ${font}`
      const hotel = day.hotel?.name ? `酒店：${day.hotel.name}` : (day.description || '')
      ctx.fillText(hotel.length > 24 ? `${hotel.slice(0, 24)}…` : hotel, pad + 110, rowY + 68)
    })

    // 底部：二维码 + 扫码提示
    const qrY = H - bottomH + 40
    if (qrDataUrl) {
      const qrImg = await loadImage(qrDataUrl)
      const qrSize = 150
      ctx.fillStyle = '#ffffff'
      drawRoundRect(ctx, pad, qrY - 16, qrSize + 32, qrSize + 32, 16)
      ctx.fill()
      ctx.drawImage(qrImg, pad + 16, qrY, qrSize, qrSize)
      ctx.fillStyle = '#ffffff'
      ctx.font = `bold 28px ${font}`
      ctx.fillText('扫码查看完整行程', pad + qrSize + 56, qrY + 56)
      ctx.font = `22px ${font}`
      ctx.fillStyle = 'rgba(255,255,255,0.8)'
      ctx.fillText('手机打开即可查看每日详情与地图', pad + qrSize + 56, qrY + 100)
    }

    downloadDataUrl(canvas.toDataURL('image/png'), `trip-poster-${props.planId}.png`)
    message.success('分享海报已保存')
  } catch (err) {
    console.error('生成海报失败', err)
    message.error('海报生成失败，请重试')
  }
}

/**
 * handleExportMenu：导出下拉菜单分发（统一管理按钮 loading，防止重复点击）
 */
const handleExportMenu = async ({ key }: { key: string | number }) => {
  exporting.value = true
  try {
    if (key === 'image') await handleExportImage()
    else if (key === 'pdf') await handleExportPdf()
    else if (key === 'poster') await handleExportPoster()
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
    <h2 style="margin: 0; font-size: 24px;">行程结果</h2>
    <div style="display: flex; gap: 12px; align-items: center;">
      <Tag v-if="isPaid" color="success" style="margin: 0;">✓ 已预订</Tag>
      <Button type="primary" @click="router.push(`/trip/${planId}/today`)">今天</Button>
      <Button type="default" @click="router.push(`/trip/${planId}/footprints`)">足迹</Button>
      <Button type="default" @click="router.push(`/trip/${planId}/journal`)">游记</Button>
      <Button type="default" @click="openPublishCommunity">发布社区</Button>
      <Button type="default" @click="router.push('/')">返回首页</Button>
      <Button type="default" @click="handleCopySummary">复制行程</Button>
      <Button type="default" :loading="shareLoading" @click="emit('share')">分享</Button>
      <Button type="default" @click="emit('collab')">协作</Button>
      <Button type="default" @click="emit('pay')">预订行程</Button>
      <Dropdown>
        <template #overlay>
          <Menu @click="handleExportMenu">
            <Menu.Item key="image">导出长图（PNG）</Menu.Item>
            <Menu.Item key="pdf">导出 PDF（多页）</Menu.Item>
            <Menu.Item key="poster">保存分享海报</Menu.Item>
          </Menu>
        </template>
        <Button type="primary" :loading="exporting">导出</Button>
      </Dropdown>
    </div>
  </div>

  <!-- 发布到社区弹窗（游记转发） -->
  <PublishCommunityModal
    v-model:visible="publishVisible"
    :journal-id="publishJournalId"
    :default-title="publishTitle"
  />
</template>
