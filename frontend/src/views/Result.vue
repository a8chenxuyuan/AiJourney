<!--
  src/views/Result.vue：结果展示页
  作用：以卡片式布局展示 TripPlan 的概览、每日行程、天气、预算；
       每天右侧显示 PlanMap 地图，标记当天景点并画出路线。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从路由参数获取 plan_id
 * 2. 调用 getPlan API 获取规划结果
 * 3. 展示概览、每日行程卡片、天气、预算、每日地图
 * 4. 支持导出行程长图（PNG）/ 多页 PDF / 分享海报（含分享二维码）
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, computed, onMounted, watch } from 'vue'
// 引入 Vue Router 的 useRoute 与 useRouter Hook
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import {
  Alert,
  Button,
  Card,
  Tag,
  Timeline,
  message,
  Row,
  Col,
  Image,
  Rate,
  Drawer,
  Select,
  Input,
  Space,
  List,
  Spin,
  Divider,
  Badge,
  Modal,
  Radio,
  RadioGroup,
  Dropdown,
  Menu
} from 'ant-design-vue'
// 引入获取规划结果 API 与类型
import {
  getPlan,
  submitPlanFeedback,
  editPlanFeedback,
  withdrawPlanFeedback,
  getPlanFeedbacks,
  regeneratePlan,
  sendPlanChat,
  createShare,
  closeShare,
  addFavorite,
  getFavorites,
  removeFavorite,
  type TripPlan,
  type PlanFeedbackRequest,
  type FavoriteRecord,
  type AttractionInfo
} from '@/api/trip'
// 引入 POI 搜索 API
import { searchPoi, type PoiItem } from '@/api/map'
// 引入支付（沙箱）API 与类型
import { createPayment, getOrders, payNotify, type OrderSummary } from '@/api/payment'
// 引入多人协作 API 与类型
import {
  inviteCollaborator,
  listCollaborators,
  removeCollaborator,
  type CollaboratorItem,
  type InviteInfo
} from '@/api/collab'
// 引入二维码生成库（分享链接 → 二维码图片）
import QRCode from 'qrcode'
// 引入每日地图组件
import PlanMap from '@/components/PlanMap.vue'
// 引入预算可视化组件
import BudgetCharts from '@/components/BudgetCharts.vue'

// 获取当前路由信息
const route = useRoute()
// 获取路由实例
const router = useRouter()

// planId：当前规划任务 ID
const planId = route.params.id as string

// plan：规划结果对象
const plan = ref<TripPlan | null>(null)
// diffSummary：本次版本相对上一版的差异摘要（"修改了 N 处"用）
const diffSummary = ref<{
  total_changes: number
  days: Array<{
    day_index: number
    change_count: number
    attractions: { added: string[]; removed: string[] }
    meals: { changed: Array<{ meal_type: string; from: string; to: string }> }
    hotel: { from: string; to: string } | null
  }>
} | null>(null)
// currentVersion：当前显示的版本号
const currentVersion = ref<number | null>(null)
// loading：数据加载状态
const loading = ref(false)
// showDiffSummary：是否显示修改记录（默认隐藏，避免初次访问时的视觉噪音）
const showDiffSummary = ref(false)

/**
 * fetchPlan：获取规划结果
 */
const fetchPlan = async () => {
  loading.value = true
  try {
    const res = await getPlan(planId)
    if (res.success && res.data?.plan) {
      plan.value = res.data.plan
      // 后端 GET /api/trip/{id} 透出了 diff_summary + version
      diffSummary.value = res.data.diff_summary || null
      currentVersion.value = res.data.version || null
      // is_owner：当前用户是否为行程所有者（非所有者即为协作者，仅可见成员列表）
      isOwner.value = res.data.is_owner === true
    } else {
      message.warning(res.message || '暂无规划结果')
    }
  } catch (error) {
    console.error('获取规划结果异常', error)
  } finally {
    loading.value = false
  }
}

// ==================== 反馈与修改相关状态 ====================

// feedbackDrawerVisible：反馈抽屉是否可见
const feedbackDrawerVisible = ref(false)
// currentDayIndex：当前正在反馈的第几天
const currentDayIndex = ref<number | null>(null)
// feedbackMode：'create' 新建反馈 / 'edit' 编辑反馈
const feedbackMode = ref<'create' | 'edit'>('create')
// editingFeedbackId：正在编辑的反馈 ID
const editingFeedbackId = ref<number | null>(null)
// feedbackTags：用户选择的快捷标签
const feedbackTags = ref<string[]>([])
// feedbackText：用户输入的反馈文本
const feedbackText = ref('')
// feedbackSubmitting：反馈提交中状态
const feedbackSubmitting = ref(false)
// feedbackList：当前 plan 的所有有效反馈
const feedbackList = ref<any[]>([])
// regenerateLoading：基于所有反馈重新生成行程中
const regenerateLoading = ref(false)
// candidateLoading：候选池加载中
const candidateLoading = ref(false)
// candidateList：候选池结果
const candidateList = ref<PoiItem[]>([])
// candidateKeyword：候选池搜索关键词
const candidateKeyword = ref('')

// 反馈快捷标签选项
const feedbackTagsOptions = [
  { label: '餐饮不满意', value: '餐饮不满意' },
  { label: '景点不喜欢', value: '景点不喜欢' },
  { label: '行程太满', value: '行程太满' },
  { label: '想加某地', value: '想加某地' },
  { label: '想删某地', value: '想删某地' },
  { label: '换酒店', value: '换酒店' },
  { label: '其他', value: '其他' }
]

/**
 * openFeedbackDrawer：打开反馈抽屉
 * @param dayIndex 第几天（从 1 开始）
 * @param mode 模式：create 或 edit
 * @param feedback 可选，编辑时传入已有反馈
 */
const openFeedbackDrawer = (
  dayIndex: number,
  mode: 'create' | 'edit' = 'create',
  feedback?: any
) => {
  currentDayIndex.value = dayIndex
  feedbackMode.value = mode
  feedbackDrawerVisible.value = true

  if (mode === 'edit' && feedback) {
    editingFeedbackId.value = feedback.feedback_id
    feedbackTags.value = feedback.tags || []
    feedbackText.value = feedback.raw_text || ''
  } else {
    editingFeedbackId.value = null
    feedbackTags.value = []
    feedbackText.value = ''
  }
  candidateList.value = []
  candidateKeyword.value = ''
}

/**
 * closeFeedbackDrawer：关闭反馈抽屉
 */
const closeFeedbackDrawer = () => {
  feedbackDrawerVisible.value = false
  currentDayIndex.value = null
  feedbackMode.value = 'create'
  editingFeedbackId.value = null
  feedbackTags.value = []
  feedbackText.value = ''
  candidateList.value = []
  candidateKeyword.value = ''
}

/**
 * fetchFeedbacks：获取当前 plan 的反馈列表
 */
const fetchFeedbacks = async () => {
  try {
    const res = await getPlanFeedbacks(planId)
    if (res.success && Array.isArray(res.data?.feedbacks)) {
      feedbackList.value = res.data.feedbacks
      // 同步更新聊天助手的"已积累意见数"
      pendingCount.value = res.data.feedbacks.filter((f: any) => !f.is_withdrawn).length
    }
  } catch (error) {
    console.error('获取反馈列表失败', error)
  }
}

/**
 * handleSearchCandidates：根据关键词搜索候选池
 */
const handleSearchCandidates = async () => {
  if (!candidateKeyword.value.trim() || !plan.value) return
  candidateLoading.value = true
  try {
    const res = await searchPoi(candidateKeyword.value.trim(), plan.value.city, 10)
    if (res.success && Array.isArray(res.data)) {
      candidateList.value = res.data
    } else {
      candidateList.value = []
    }
  } catch (error) {
    console.error('搜索候选池失败', error)
    candidateList.value = []
  } finally {
    candidateLoading.value = false
  }
}

/**
 * handleSubmitFeedback：提交或更新反馈
 */
const handleSubmitFeedback = async () => {
  if (!currentDayIndex.value || !feedbackText.value.trim()) {
    message.warning('请填写反馈内容')
    return
  }

  feedbackSubmitting.value = true
  const feedback: PlanFeedbackRequest = {
    day_index: currentDayIndex.value,
    tags: feedbackTags.value,
    raw_text: feedbackText.value
  }

  try {
    let res
    if (feedbackMode.value === 'edit' && editingFeedbackId.value) {
      res = await editPlanFeedback(planId, editingFeedbackId.value, feedback)
    } else {
      res = await submitPlanFeedback(planId, feedback)
    }

    if (res.success) {
      // 单条意见只保存到数据库，不立即触发重新规划。
      // 等用户在前端点"根据所有反馈重新生成行程"按钮时再统一处理。
      message.success(
        feedbackMode.value === 'edit'
          ? '意见已更新，点底部"根据所有反馈重新生成行程"统一处理'
          : '意见已保存，点底部"根据所有反馈重新生成行程"统一处理'
      )
      closeFeedbackDrawer()
      // 只刷新反馈列表，让用户继续提下一条意见
      fetchFeedbacks()
    }
  } catch (error) {
    console.error('提交反馈失败', error)
  } finally {
    feedbackSubmitting.value = false
  }
}

/**
 * handleWithdrawFeedback：撤回指定反馈
 */
const handleWithdrawFeedback = async (feedbackId: number) => {
  try {
    const res = await withdrawPlanFeedback(planId, feedbackId)
    if (res.success) {
      message.success('反馈已撤回')
      fetchFeedbacks()
    }
  } catch (error) {
    console.error('撤回反馈失败', error)
  }
}

/**
 * handleRegeneratePlan：基于所有有效反馈重新生成完整行程
 *
 * 点击后调用后端 regenerate 接口触发完整重排，然后跳转到规划进度页，
 * 通过 SSE 实时观看 Agent 重新执行过程，完成后自动返回结果页。
 */
const handleRegeneratePlan = async () => {
  if (feedbackList.value.length === 0) {
    message.warning('暂无有效反馈，无法重新生成')
    return
  }

  regenerateLoading.value = true
  try {
    const res = await regeneratePlan(planId)
    if (res.success) {
      message.success(res.message || '正在根据所有反馈重新生成行程')
      // 跳转到规划进度页，实时观看 Agent 执行和 SSE 进度
      router.push(`/planning/${planId}`)
    } else {
      message.warning(res.message || '重新生成失败')
    }
  } catch (error) {
    console.error('重新生成行程失败', error)
  } finally {
    regenerateLoading.value = false
  }
}

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

// ==================== 总览地图相关 ====================

// DAY_COLORS：总览地图的每日主题配色（循环使用）
const DAY_COLORS = ['#1890ff', '#52c41a', '#faad14', '#fa541c', '#722ed1', '#13c2c2', '#eb2f96', '#2f54eb', '#a0d911', '#fa8c16']

/**
 * dayColor：按天序号返回主题色（用于总览/单日地图的标记与路线配色）
 */
const dayColor = (dayIndex: number) => DAY_COLORS[(dayIndex - 1) % DAY_COLORS.length]

// hasDayPlans：是否有每日行程数据（控制总览卡片显隐）
const hasDayPlans = computed(() => (plan.value?.day_plans?.length || 0) > 0)

// ==================== 多城市联游展示 ====================

// multiCityStays：多城市联游的城市列表（单城为空数组）
const multiCityStays = computed(() => plan.value?.cities || [])
// isMultiCity：是否为多城市联游行程（≥2 个城市才展示城市标识）
const isMultiCity = computed(() => multiCityStays.value.length >= 2)

// CITY_TAG_COLORS：城市 Tag 的候选配色（按城市在行程中的顺序循环取色）
const CITY_TAG_COLORS = ['blue', 'green', 'purple', 'orange', 'cyan', 'magenta', 'volcano', 'geekblue']

/**
 * cityTagColor：返回某城市对应的 Tag 颜色（同一城市恒定同色，便于跨天区分）
 */
const cityTagColor = (city?: string | null) => {
  if (!city) return 'default'
  const idx = multiCityStays.value.findIndex(c => c.city === city)
  return idx >= 0 ? CITY_TAG_COLORS[idx % CITY_TAG_COLORS.length] : 'default'
}

// overviewMarkers：总览地图的全部标记（含序号/按天配色/信息窗内容）
const overviewMarkers = computed(() => {
  const markers: any[] = []
  for (const day of plan.value?.day_plans || []) {
    ;(day.attractions || []).forEach((spot: any, idx: number) => {
      if (!spot?.location?.longitude || !spot?.location?.latitude) return
      markers.push({
        longitude: spot.location.longitude,
        latitude: spot.location.latitude,
        title: spot.name,
        order: idx + 1,
        color: dayColor(day.day_index),
        info: { rating: spot.rating, ticket: spot.ticket_price, hours: spot.business_hours }
      })
    })
  }
  return markers
})

// overviewPolylines：总览地图的多天路线（每条按天配色）
const overviewPolylines = computed(() => {
  const lines: { path: string; color: string }[] = []
  for (const day of plan.value?.day_plans || []) {
    if (day.route_polyline) {
      lines.push({ path: day.route_polyline, color: dayColor(day.day_index) })
    }
  }
  return lines
})

// ==================== AI 修改助手（对话式） ====================

// chatDrawerVisible：聊天抽屉显隐
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
// chatInput：输入框内容
const chatInput = ref('')
// chatSending：发送中状态
const chatSending = ref(false)
// pendingCount：待处理（未撤回）的反馈数量
const pendingCount = ref(0)
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
    const res = await sendPlanChat(planId, text, history)
    if (res.success && res.data) {
      chatMessages.value.push({
        role: 'assistant',
        content: res.data.reply,
        day_index: res.data.day_index,
        tags: res.data.tags
      })
      pendingCount.value = res.data.pending_count
      // 有新反馈入库时刷新"修改记录"卡片
      if (res.data.intent === 'feedback') fetchFeedbacks()
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

/**
 * buildSummaryText：把当前行程生成便于分享/保存的纯文本摘要
 */
const buildSummaryText = (): string => {
  const p = plan.value
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
    // 兼容不支持 clipboard API 的环境：用隐藏 textarea 兜底
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    message.success('行程摘要已复制')
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
    scale: 2,              // 2 倍采样，导出文字清晰
    useCORS: true,         // 允许跨域图片（如高德静态图）参与绘制
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
  downloadDataUrl(canvas.toDataURL('image/png'), `trip-plan-${planId}.png`)
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
    // 每页一个临时 canvas，白底后贴入当前切片
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
  pdf.save(`trip-plan-${planId}.pdf`)
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
 * 注意：本文件已引入 antd 的 Image 组件，需用 createElement 避免遮蔽全局 Image 构造器
 */
const loadImage = (src: string) =>
  new Promise<HTMLImageElement>((resolve, reject) => {
    const img = document.createElement('img')
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })

/**
 * ensureShareQr：海报需要二维码；尚未分享时静默创建分享并生成大尺寸二维码
 * （不走 handleShare，避免弹出分享弹窗）
 */
const ensureShareQr = async (): Promise<string> => {
  if (shareQrDataUrl.value) return shareQrDataUrl.value
  const res = await createShare(planId, 7)
  if (!res.success || !res.data) return ''
  shareUrl.value = `${window.location.origin}/share/${res.data.share_token}`
  shareViewCount.value = res.data.share_view_count ?? 0
  shareQrDataUrl.value = await QRCode.toDataURL(shareUrl.value, { width: 240, margin: 1 })
  return shareQrDataUrl.value
}

/**
 * handleExportPoster：生成"行程摘要 + 分享二维码"海报（PNG）
 * 纯 canvas 绘制：渐变底 + 概览信息 + 每日景点摘要 + 扫码入口
 */
const handleExportPoster = async () => {
  const p = plan.value
  if (!p) {
    message.warning('暂无行程数据')
    return
  }
  try {
    const qrDataUrl = await ensureShareQr()

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
      // 左侧 Day 徽标
      ctx.fillStyle = '#0e9aa7'
      drawRoundRect(ctx, pad, rowY, 86, 44, 22)
      ctx.fill()
      ctx.fillStyle = '#ffffff'
      ctx.font = `bold 24px ${font}`
      ctx.fillText(`Day ${day.day_index}`, pad + 12, rowY + 31)
      // 右侧：景点名摘要 + 酒店
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

    downloadDataUrl(canvas.toDataURL('image/png'), `trip-poster-${planId}.png`)
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

// 组件挂载时获取规划结果和反馈列表
onMounted(() => {
  fetchPlan()
  fetchFeedbacks()
  fetchFavorites()
  fetchOrders()
})

// ==================== 预订支付（沙箱） ====================

// payVisible：支付弹窗是否展示
const payVisible = ref(false)
// payMethod：选中的支付方式
const payMethod = ref<'alipay' | 'wechat' | 'bank_card'>('alipay')
// payCreating / paying：创建订单与沙箱支付的请求中状态
const payCreating = ref(false)
const paying = ref(false)
// currentOrder：本次弹窗内正在操作的订单（创建后填充）
const currentOrder = ref<OrderSummary | null>(null)
// paidOrders：该行程下的历史订单
const paidOrders = ref<OrderSummary[]>([])

// isPaid：该行程是否存在已支付订单（决定操作栏徽标）
const isPaid = computed(() => paidOrders.value.some((o) => o.status === 'paid'))

// payMethodOptions：支付方式选项
const payMethodOptions = [
  { label: '支付宝', value: 'alipay' },
  { label: '微信支付', value: 'wechat' },
  { label: '银行卡', value: 'bank_card' }
]

/**
 * fetchOrders：拉取该行程的订单列表（判断"已预订"徽标）
 */
const fetchOrders = async () => {
  try {
    const res = await getOrders(planId)
    if (res.success && res.data) {
      paidOrders.value = res.data.orders
    }
  } catch {
    // 拉取失败不影响主流程
  }
}

/**
 * openPayModal：打开支付弹窗，重置为选择支付方式步骤
 */
const openPayModal = () => {
  currentOrder.value = null
  payVisible.value = true
}

/**
 * handleCreateOrder：创建支付订单（沙箱）
 */
const handleCreateOrder = async () => {
  const amount = plan.value?.budget?.total || 0
  if (!amount) {
    message.warning('行程还没有预算信息，无法创建订单')
    return
  }
  payCreating.value = true
  try {
    const res = await createPayment({ plan_id: planId, amount, payment_method: payMethod.value })
    if (res.success && res.data) {
      currentOrder.value = {
        order_id: res.data.order_id,
        plan_id: planId,
        amount: res.data.amount,
        status: res.data.status,
        payment_method: payMethod.value,
        created_at: null,
        paid_at: null
      }
      message.success('订单已创建，请确认支付')
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    payCreating.value = false
  }
}

/**
 * handleSandboxPay：模拟第三方支付成功，调用回调更新订单状态
 */
const handleSandboxPay = async () => {
  if (!currentOrder.value) return
  paying.value = true
  try {
    const res = await payNotify(currentOrder.value.order_id)
    if (res.success) {
      currentOrder.value.status = 'paid'
      message.success('支付成功，行程已预订！')
      await fetchOrders()
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    paying.value = false
  }
}

// ==================== 行程分享 ====================

// shareVisible：分享弹窗是否展示
const shareVisible = ref(false)
// shareUrl：分享链接（前端路由完整地址）
const shareUrl = ref('')
// shareLoading：开启/关闭分享的请求中状态
const shareLoading = ref(false)
// shareViewCount：分享页累计访问次数（传播效果）
const shareViewCount = ref(0)
// shareQrDataUrl：分享链接的二维码图片（Data URL）
const shareQrDataUrl = ref('')

/**
 * handleShare：开启行程分享并弹出链接与二维码
 * 后端会复用未过期的旧令牌，重复点击不会更换链接
 */
const handleShare = async () => {
  shareLoading.value = true
  try {
    const res = await createShare(planId, 7)
    if (res.success && res.data) {
      shareUrl.value = `${window.location.origin}/share/${res.data.share_token}`
      shareViewCount.value = res.data.share_view_count ?? 0
      // 生成二维码（手机扫码直接打开分享页）
      shareQrDataUrl.value = await QRCode.toDataURL(shareUrl.value, { width: 160, margin: 1 })
      shareVisible.value = true
    } else {
      message.error(res.message || '开启分享失败')
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '开启分享失败')
  } finally {
    shareLoading.value = false
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
        await closeShare(planId)
        message.success('分享已关闭')
        shareVisible.value = false
      } catch {
        message.error('关闭分享失败')
      }
    }
  })
}

// ==================== 多人协作 ====================

// isOwner：当前登录用户是否为行程所有者（来自 GET /trip/{id} 的 is_owner）
const isOwner = ref(false)
// collabVisible：协作弹窗是否展示
const collabVisible = ref(false)
// collabLoading：成员列表加载中状态
const collabLoading = ref(false)
// collaborators：行程成员列表（所有者 + 协作者）
const collaborators = ref<CollaboratorItem[]>([])
// inviteLoading：生成邀请链接的请求中状态
const inviteLoading = ref(false)
// inviteInfo：最近一次生成的邀请信息（token / 有效期等）
const inviteInfo = ref<InviteInfo | null>(null)
// inviteUrl：完整邀请链接（站点 origin + 前端路由 /join/{token}）
const inviteUrl = computed(() =>
  inviteInfo.value ? `${window.location.origin}${inviteInfo.value.invite_path}` : ''
)

/**
 * fetchCollaborators：拉取行程成员列表（所有者与协作者均可查看）
 */
const fetchCollaborators = async () => {
  collabLoading.value = true
  try {
    const res = await listCollaborators(planId)
    if (res.success && res.data) {
      collaborators.value = res.data.collaborators
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    collabLoading.value = false
  }
}

/**
 * openCollabModal：打开协作弹窗并刷新成员列表
 */
const openCollabModal = () => {
  inviteInfo.value = null
  collabVisible.value = true
  fetchCollaborators()
}

/**
 * handleGenerateInvite：所有者生成邀请链接（有效期 7 天）
 */
const handleGenerateInvite = async () => {
  inviteLoading.value = true
  try {
    const res = await inviteCollaborator(planId)
    if (res.success && res.data) {
      inviteInfo.value = res.data
      message.success('邀请链接已生成，复制发给对方即可')
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '生成邀请链接失败')
  } finally {
    inviteLoading.value = false
  }
}

/**
 * handleCopyInviteLink：复制邀请链接到剪贴板
 * 与分享链接相同的降级方案：clipboard API 失败时用隐藏 textarea 兜底
 */
const handleCopyInviteLink = async () => {
  if (!inviteUrl.value) return
  try {
    await navigator.clipboard.writeText(inviteUrl.value)
    message.success('邀请链接已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = inviteUrl.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    message.success('邀请链接已复制')
  }
}

/**
 * handleRemoveCollaborator：所有者移除协作者（二次确认）
 * 移除后该用户立即失去行程访问权
 */
const handleRemoveCollaborator = (item: CollaboratorItem) => {
  Modal.confirm({
    title: '移除协作者',
    content: `确定移除协作者「${item.username}」吗？移除后其将无法再查看该行程。`,
    okText: '移除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await removeCollaborator(planId, item.user_id)
        message.success('已移除协作者')
        fetchCollaborators()
      } catch {
        message.error('移除协作者失败')
      }
    }
  })
}

// ==================== 景点收藏 ====================

// favoriteMap：item_id → 收藏记录，用于判断收藏状态与取消收藏时取记录 ID
const favoriteMap = ref<Map<string, FavoriteRecord>>(new Map())

/**
 * fetchFavorites：拉取当前用户收藏列表，填充 favoriteMap
 */
const fetchFavorites = async () => {
  try {
    const res = await getFavorites()
    if (res.success && res.data) {
      favoriteMap.value = new Map(res.data.favorites.map((f) => [f.item_id, f]))
    }
  } catch {
    // 收藏列表拉取失败不阻塞主流程，静默忽略
  }
}

/**
 * isItemFavorited：按名称判断任意条目（景点/酒店/餐厅）是否已收藏
 */
const isItemFavorited = (name?: string): boolean => !!name && favoriteMap.value.has(name)

/**
 * toggleItemFavorite：收藏 / 取消收藏任意条目（景点、酒店、餐厅通用）
 * 未收藏 → 以名称做唯一标识收藏（保存完整快照）；
 * 已收藏 → 按记录 ID 取消收藏。
 *
 * @param itemType 收藏类型：attraction / hotel / restaurant
 * @param item 条目完整数据（作为快照保存）
 * @param name 条目名称（作为唯一标识）
 */
const toggleItemFavorite = async (
  itemType: 'attraction' | 'hotel' | 'restaurant',
  item: Record<string, any>,
  name: string
) => {
  const existing = favoriteMap.value.get(name)
  try {
    if (existing) {
      await removeFavorite(existing.id)
      favoriteMap.value.delete(name)
      message.success('已取消收藏')
    } else {
      const res = await addFavorite({
        item_type: itemType,
        item_id: name,
        item_name: name,
        city: plan.value?.city,
        item_data: item
      })
      if (res.success && res.data) {
        favoriteMap.value.set(name, res.data)
        message.success(`已收藏「${name}」，可在个人中心查看`)
      }
    }
    // 触发响应式更新（Map 内容变化不会自动触发视图刷新）
    favoriteMap.value = new Map(favoriteMap.value)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '收藏操作失败')
  }
}

/**
 * isFavorited：判断景点是否已收藏（isItemFavorited 的景点便捷包装）
 */
const isFavorited = (spot: AttractionInfo): boolean => isItemFavorited(spot.name)

/**
 * toggleFavorite：收藏 / 取消收藏景点（toggleItemFavorite 的景点便捷包装）
 */
const toggleFavorite = (spot: AttractionInfo) => toggleItemFavorite('attraction', spot as unknown as Record<string, any>, spot.name)

// 监听路由参数和 refresh query 的变化。
// 重要：当 SSE 跳回 /result/{id} 时，Vue Router 会复用同一个组件实例，
// onMounted 不会再触发，必须用 watch 强制重新拉取最新数据。
watch(
  () => [route.params.id, route.query.refresh, route.query.from],
  () => {
    fetchPlan()
    fetchFeedbacks()
  }
)

// 手动刷新：用于当用户怀疑页面没更新到最新版本时点击。
// 某些浏览器扩展或页面缓存可能导致 watch 不触发，强制 reload 是最后的兜底。
const manualRefresh = () => {
  fetchPlan()
  fetchFeedbacks()
  message.success('已刷新')
}
</script>

<template>
  <div id="trip-result-container" class="page-fade" style="max-width: 1200px; margin: 0 auto; padding: 0 16px;">
    <!-- 顶部操作栏 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
      <h2 style="margin: 0; font-size: 24px;">行程结果</h2>
      <div style="display: flex; gap: 12px; align-items: center;">
        <Tag v-if="isPaid" color="success" style="margin: 0;">✓ 已预订</Tag>
        <Button type="primary" @click="router.push(`/trip/${planId}/today`)">今天</Button>
        <Button type="default" @click="router.push(`/trip/${planId}/footprints`)">足迹</Button>
        <Button type="default" @click="router.push(`/trip/${planId}/journal`)">游记</Button>
        <Button type="default" @click="router.push('/')">返回首页</Button>
        <Button type="default" @click="handleCopySummary">复制行程</Button>
        <Button type="default" :loading="shareLoading" @click="handleShare">分享</Button>
        <Button type="default" @click="openCollabModal">协作</Button>
        <Button type="default" @click="openPayModal">预订行程</Button>
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

    <!-- 预订支付弹窗（沙箱）：选支付方式 → 创建订单 → 模拟支付 -->
    <Modal v-model:open="payVisible" title="预订行程（沙箱支付）" :footer="null" style="border-radius: 12px;">
      <!-- 步骤一：创建订单 -->
      <template v-if="!currentOrder">
        <p style="color: #666; margin-bottom: 12px;">
          根据行程预算创建预订订单：预估总额
          <strong style="color: #fa541c; font-size: 18px;">¥{{ plan?.budget?.total ?? '-' }}</strong>
          <span style="color: #999; font-size: 12px;">（沙箱环境，不涉及真实资金）</span>
        </p>
        <p style="margin-bottom: 8px; font-weight: 600;">选择支付方式</p>
        <RadioGroup v-model:value="payMethod" style="margin-bottom: 16px;">
          <Radio v-for="m in payMethodOptions" :key="m.value" :value="m.value">{{ m.label }}</Radio>
        </RadioGroup>
        <Button type="primary" block :loading="payCreating" @click="handleCreateOrder">创建订单</Button>
      </template>
      <!-- 步骤二：沙箱支付 / 支付完成 -->
      <template v-else>
        <div style="text-align: center; padding: 8px 0 16px;">
          <template v-if="currentOrder.status !== 'paid'">
            <p style="font-size: 28px; color: #fa541c; margin: 8px 0;">¥{{ currentOrder.amount }}</p>
            <p style="color: #999; font-size: 13px; margin-bottom: 16px;">订单号：{{ currentOrder.order_id }}</p>
            <Button type="primary" size="large" block :loading="paying" @click="handleSandboxPay">
              模拟支付成功（沙箱）
            </Button>
          </template>
          <template v-else>
            <p style="font-size: 40px; margin: 8px 0;">✅</p>
            <p style="font-size: 16px; font-weight: 600; color: #52c41a;">支付成功，行程已预订</p>
            <p style="color: #999; font-size: 13px;">订单号：{{ currentOrder.order_id }}</p>
          </template>
        </div>
      </template>
    </Modal>

    <!-- 分享弹窗：展示链接 / 二维码，支持复制 / 关闭分享 -->
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

    <!-- 协作弹窗：成员列表（所有者+协作者可见）；所有者可生成/复制邀请链接、移除协作者 -->
    <Modal v-model:open="collabVisible" title="行程协作" :footer="null" style="border-radius: 12px;">
      <p style="color: #666; margin-bottom: 12px;">
        协作者可查看这份行程并提交反馈修订，删除与邀请管理仅所有者可用。
      </p>

      <!-- 邀请区：仅所有者可见 -->
      <div v-if="isOwner" style="margin-bottom: 16px;">
        <template v-if="!inviteInfo">
          <Button type="primary" :loading="inviteLoading" @click="handleGenerateInvite">生成邀请链接（7 天有效）</Button>
        </template>
        <template v-else>
          <div style="display: flex; gap: 8px; margin-bottom: 8px;">
            <Input :value="inviteUrl" readonly />
            <Button type="primary" @click="handleCopyInviteLink">复制链接</Button>
          </div>
          <p style="color: #999; font-size: 12px; margin: 0;">
            对方打开链接并登录后即加入协作；再次生成会创建新链接，旧链接在有效期内仍可用。
          </p>
        </template>
      </div>

      <!-- 成员列表 -->
      <Spin :spinning="collabLoading">
        <List :data-source="collaborators" size="small">
          <template #renderItem="{ item }">
            <List.Item>
              <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                <span>
                  <strong>{{ item.username }}</strong>
                  <Tag :color="item.role === 'owner' ? 'gold' : 'blue'" style="margin-left: 8px;">
                    {{ item.role === 'owner' ? '所有者' : '协作者' }}
                  </Tag>
                  <span v-if="item.joined_at" style="color: #999; font-size: 12px; margin-left: 8px;">
                    {{ item.joined_at.slice(0, 10) }} 加入
                  </span>
                </span>
                <Button
                  v-if="isOwner && item.role !== 'owner'"
                  danger
                  size="small"
                  @click="handleRemoveCollaborator(item)"
                >移除</Button>
              </div>
            </List.Item>
          </template>
        </List>
      </Spin>
    </Modal>

    <!-- 概览卡片 -->
    <Card title="行程概览" style="margin-bottom: 24px; border-radius: 12px;">
      <template #extra>
        <Space>
          <Button size="small" @click="manualRefresh">刷新</Button>
          <Button size="small" type="primary" @click="showDiffSummary = !showDiffSummary">
            {{ showDiffSummary ? '隐藏' : '显示' }}修改记录
          </Button>
        </Space>
      </template>
      <Row :gutter="[24, 12]">
        <Col :xs="24" :md="12">
          <p style="margin: 8px 0;">
            <strong>目的地：</strong>
            <!-- 多城联游：按出发顺序展示"杭州 → 苏州（共X天）"；单城维持原样 -->
            <template v-if="isMultiCity">
              {{ multiCityStays.map(c => c.city).join(' → ') }}（共 {{ plan?.travel_days }} 天）
            </template>
            <template v-else>{{ plan?.city || '示例城市' }}</template>
          </p>
          <p style="margin: 8px 0;">
            <strong>出行日期：</strong>{{ plan?.start_date || '2026-08-01' }} 至 {{ plan?.end_date || '2026-08-03' }}
          </p>
          <p style="margin: 8px 0;">
            <strong>行程天数：</strong>{{ plan?.travel_days || 3 }} 天
            <Tag v-if="currentVersion" color="purple" style="margin-left: 8px;">v{{ currentVersion }}</Tag>
          </p>
        </Col>
        <Col :xs="24" :md="12">
          <p v-if="plan?.budget" style="margin: 8px 0;">
            <strong>预算估算：</strong>总计 {{ plan.budget.total }} 元<br>
            <span style="color: #666; font-size: 13px;">
              景点 {{ plan.budget.attractions }} / 餐饮 {{ plan.budget.meals }} / 住宿 {{ plan.budget.hotels }} / 交通 {{ plan.budget.transportation }}
            </span>
          </p>
          <p v-if="plan?.weather && plan.weather.length > 0" style="margin: 8px 0;">
            <strong>天气：</strong>
            <span v-for="(w, idx) in plan.weather" :key="idx" style="margin-right: 12px; color: #555;">
              {{ w.date }} {{ w.weather }} {{ w.temperature || '' }}
            </span>
          </p>
        </Col>
      </Row>

      <p v-if="plan?.overall_suggestions" style="color: #555; margin-top: 12px; background: #f6f6f6; padding: 12px; border-radius: 8px;">
        <strong>整体建议：</strong>{{ plan.overall_suggestions }}
      </p>

      <!-- 版本信息 + diff 提示 -->
      <div
        v-if="currentVersion"
        style="margin-top: 12px; padding: 10px 16px; background: #fafafa; border: 1px dashed #d9d9d9; border-radius: 8px; font-size: 13px; color: #666;"
      >
        <span>当前版本：<strong style="color: #722ed1;">v{{ currentVersion }}</strong></span>
        <span style="margin-left: 16px;" v-if="diffSummary && diffSummary.total_changes > 0">
          相比上一版修改了
          <strong style="color: #0050b3;">{{ diffSummary.total_changes }}</strong>
          处
        </span>
        <span v-else style="margin-left: 16px; color: #999;">（这是初始版本，没有 diff 数据）</span>
      </div>

      <!-- 本次重新生成修改了 N 处 -->
      <div
        v-if="showDiffSummary && diffSummary && diffSummary.total_changes > 0"
        style="margin-top: 12px; background: #e6f7ff; border: 1px solid #91d5ff; padding: 12px 16px; border-radius: 8px;"
      >
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <Tag color="cyan">本次重新生成生效</Tag>
          <strong style="color: #0050b3;">共修改了 {{ diffSummary.total_changes }} 处</strong>
        </div>
        <div
          v-for="day in diffSummary.days"
          :key="day.day_index"
          style="font-size: 13px; color: #333; margin: 4px 0; line-height: 1.7;"
        >
          <Tag color="blue" size="small">第 {{ day.day_index }} 天</Tag>
          <span v-if="day.attractions.removed.length">
            移除景点：
            <span style="color: #cf1322;">{{ day.attractions.removed.join('、') }}</span>
          </span>
          <span v-if="day.attractions.added.length" style="margin-left: 8px;">
            新增景点：
            <span style="color: #389e0d;">{{ day.attractions.added.join('、') }}</span>
          </span>
          <span
            v-for="m in day.meals.changed"
            :key="m.meal_type"
            style="margin-left: 12px; display: inline-block;"
          >
            {{ m.meal_type === 'breakfast' ? '早餐' : m.meal_type === 'lunch' ? '午餐' : '晚餐' }}:
            <span style="color: #cf1322; text-decoration: line-through;">{{ m.from || '—' }}</span>
            →
            <span style="color: #389e0d;">{{ m.to || '—' }}</span>
          </span>
          <span v-if="day.hotel" style="margin-left: 12px;">
            酒店：
            <span style="color: #cf1322; text-decoration: line-through;">{{ day.hotel.from }}</span>
            →
            <span style="color: #389e0d;">{{ day.hotel.to }}</span>
          </span>
        </div>
      </div>
    </Card>

    <!-- 预算可视化卡片 -->
    <Card v-if="plan?.budget" title="预算分析" style="margin-bottom: 24px; border-radius: 12px;">
      <BudgetCharts :budget="plan.budget" :day-plans="plan?.day_plans || []" />
    </Card>

    <!-- 全程总览地图卡片 -->
    <Card v-if="hasDayPlans" title="行程总览地图" style="margin-bottom: 24px; border-radius: 12px;">
      <template #extra>
        <div style="display: flex; gap: 6px; flex-wrap: wrap;">
          <Tag v-for="day in plan?.day_plans || []" :key="day.day_index" :color="dayColor(day.day_index)">
            第 {{ day.day_index }} 天
          </Tag>
        </div>
      </template>
      <PlanMap
        :markers="overviewMarkers"
        :polylines="overviewPolylines"
        style="width: 100%; height: 420px; border-radius: 12px; overflow: hidden;"
      />
    </Card>

    <!-- 每日行程卡片 -->
    <Card title="每日行程" style="margin-bottom: 24px; border-radius: 12px;">
      <div v-if="plan?.day_plans && plan.day_plans.length > 0">
        <Card
          v-for="day in plan.day_plans"
          :key="day.day_index"
          size="small"
          style="margin-bottom: 24px; border-radius: 12px; background: #fafafa;"
          :body-style="{ padding: '20px' }"
        >
          <Row :gutter="[24, 24]">
            <!-- 左侧：当天行程内容 -->
            <Col :xs="24" :lg="14">
              <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap;">
                <h3 style="margin: 0;">第 {{ day.day_index }} 天</h3>
                <Tag color="blue">{{ day.date }}</Tag>
                <!-- 多城联游：当日所在城市 Tag（按城市配色区分） -->
                <Tag v-if="isMultiCity && day.city" :color="cityTagColor(day.city)">📍 {{ day.city }}</Tag>
              </div>
              <!-- 城际交通说明（如"上午高铁 杭州→苏州（约1.5小时）"） -->
              <Alert
                v-if="day.intercity_note"
                type="info"
                show-icon
                :message="day.intercity_note"
                style="margin-bottom: 12px;"
              />
              <p v-if="day.description" style="color: #888; font-size: 14px; margin-bottom: 16px;">
                {{ day.description }}
              </p>
              <p v-if="day.transportation" style="color: #555; font-size: 13px; margin-bottom: 16px;">
                <strong>当日交通：</strong>{{ day.transportation }}
              </p>

              <!-- 景点卡片列表 -->
              <div v-if="day.attractions && day.attractions.length > 0" style="margin-bottom: 16px;">
                <p style="font-weight: 600; margin-bottom: 12px;">景点安排</p>
                <Timeline>
                  <Timeline.Item v-for="(spot, idx) in day.attractions" :key="idx">
                    <Card size="small" style="border-radius: 8px; margin-bottom: 8px;">
                      <Row :gutter="[12, 12]">
                        <Col :span="7">
                          <Image
                            :src="spot.image_url || 'https://placehold.co/120x90?text=景点'"
                            :alt="spot.name"
                            style="width: 100%; height: 90px; object-fit: cover; border-radius: 6px;"
                            fallback="https://placehold.co/120x90?text=景点"
                          />
                        </Col>
                        <Col :span="17">
                          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                            <strong>{{ spot.name }}</strong>
                            <Tag v-if="spot.duration" size="small" color="orange">{{ spot.duration }}</Tag>
                            <Tag v-if="spot.ticket_price" size="small" color="green">¥{{ spot.ticket_price }}</Tag>
                            <a
                              style="margin-left: auto; font-size: 13px;"
                              :style="{ color: isFavorited(spot) ? '#faad14' : '#1890ff' }"
                              @click="toggleFavorite(spot)"
                            >{{ isFavorited(spot) ? '★ 已收藏' : '☆ 收藏' }}</a>
                          </div>
                          <div v-if="spot.rating" style="margin-top: 4px;">
                            <Rate :value="spot.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 12px;" />
                            <span style="font-size: 12px; color: #888; margin-left: 6px;">{{ spot.rating }} 分</span>
                          </div>
                          <p v-if="spot.description" style="color: #666; font-size: 13px; margin: 6px 0 0; line-height: 1.5;">
                            {{ spot.description }}
                          </p>
                          <div v-if="spot.phone || spot.business_hours || spot.detail_url" style="margin-top: 8px; font-size: 12px; color: #888;">
                            <span v-if="spot.phone">电话：{{ spot.phone }}</span>
                            <span v-if="spot.business_hours" style="margin-left: 8px;">营业：{{ spot.business_hours }}</span>
                            <a
                              v-if="spot.detail_url"
                              :href="spot.detail_url"
                              target="_blank"
                              style="margin-left: 8px; color: #1890ff;"
                            >查看详情</a>
                          </div>
                        </Col>
                      </Row>
                    </Card>
                  </Timeline.Item>
                </Timeline>
              </div>

              <!-- 餐饮安排 -->
              <div v-if="day.meals && day.meals.length > 0" style="margin-bottom: 16px;">
                <p style="font-weight: 600; margin-bottom: 12px;">餐饮安排</p>
                <Row :gutter="[12, 12]">
                  <Col v-for="(meal, idx) in day.meals" :key="`meal-${idx}`" :xs="24" :sm="12" :md="8">
                    <Card size="small" style="border-radius: 8px; background: #fff;">
                      <Row :gutter="[10, 10]">
                        <Col :span="8">
                          <Image
                            :src="meal.image_url || 'https://placehold.co/120x90?text=餐厅'"
                            :alt="meal.name || '餐厅'"
                            style="width: 100%; height: 72px; object-fit: cover; border-radius: 6px;"
                            fallback="https://placehold.co/120x90?text=餐厅"
                          />
                        </Col>
                        <Col :span="16">
                          <div style="display: flex; justify-content: space-between; align-items: center;">
                            <strong>{{ mealTypeText(meal.type) }}</strong>
                            <Tag v-if="meal.estimated_cost" size="small" color="green">人均 ¥{{ meal.estimated_cost }}</Tag>
                          </div>
                          <p v-if="meal.name" style="margin: 4px 0 0; color: #333; font-weight: 500;">
                            {{ meal.name }}
                            <a
                              v-if="meal.name"
                              style="font-size: 12px; font-weight: 400; margin-left: 6px; color: #1890ff;"
                              :style="{ color: isItemFavorited(meal.name) ? '#faad14' : '#1890ff' }"
                              @click="toggleItemFavorite('restaurant', meal as unknown as Record<string, any>, meal.name)"
                            >{{ isItemFavorited(meal.name) ? '★ 已收藏' : '☆ 收藏' }}</a>
                          </p>
                          <div v-if="meal.rating" style="margin-top: 2px;">
                            <Rate :value="meal.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 11px;" />
                            <span style="font-size: 11px; color: #888; margin-left: 4px;">{{ meal.rating }} 分</span>
                          </div>
                          <p v-if="meal.cuisine" style="margin: 2px 0 0; font-size: 12px; color: #888;">{{ meal.cuisine }}</p>
                          <p v-if="meal.address || meal.location_name" style="margin: 2px 0 0; font-size: 12px; color: #888;">
                            <span>地址：{{ meal.address || meal.location_name }}</span>
                          </p>
                          <div v-if="meal.phone || meal.business_hours || meal.detail_url" style="margin-top: 4px; font-size: 11px; color: #888;">
                            <span v-if="meal.phone">电话：{{ meal.phone }}</span>
                            <span v-if="meal.business_hours" style="margin-left: 6px;">营业：{{ meal.business_hours }}</span>
                            <a
                              v-if="meal.detail_url"
                              :href="meal.detail_url"
                              target="_blank"
                              style="margin-left: 6px; color: #1890ff;"
                            >查看详情</a>
                          </div>
                        </Col>
                      </Row>
                    </Card>
                  </Col>
                </Row>
              </div>

              <!-- 酒店 -->
              <div v-if="day.hotel">
                <p style="font-weight: 600; margin-bottom: 12px;">推荐酒店</p>
                <Card size="small" style="border-radius: 8px; background: #fff;">
                  <Row :gutter="[12, 12]">
                    <Col :span="7">
                      <Image
                        :src="day.hotel.image_url || 'https://placehold.co/120x90?text=酒店'"
                        :alt="day.hotel.name"
                        style="width: 100%; height: 90px; object-fit: cover; border-radius: 6px;"
                        fallback="https://placehold.co/120x90?text=酒店"
                      />
                    </Col>
                    <Col :span="17">
                      <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <strong>{{ day.hotel.name }}</strong>
                        <Tag v-if="day.hotel.price_per_night" size="small" color="green">¥{{ day.hotel.price_per_night }} / 晚</Tag>
                        <a
                          style="font-size: 12px;"
                          :style="{ color: isItemFavorited(day.hotel.name) ? '#faad14' : '#1890ff' }"
                          @click="toggleItemFavorite('hotel', day.hotel as unknown as Record<string, any>, day.hotel.name)"
                        >{{ isItemFavorited(day.hotel.name) ? '★ 已收藏' : '☆ 收藏' }}</a>
                      </div>
                      <div v-if="day.hotel.rating" style="margin-top: 4px;">
                        <Rate :value="day.hotel.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 12px;" />
                        <span style="font-size: 12px; color: #888; margin-left: 6px;">{{ day.hotel.rating }} 分</span>
                      </div>
                      <div v-if="day.hotel.phone || day.hotel.business_hours || day.hotel.detail_url" style="margin-top: 8px; font-size: 12px; color: #888;">
                        <span v-if="day.hotel.phone">电话：{{ day.hotel.phone }}</span>
                        <span v-if="day.hotel.business_hours" style="margin-left: 8px;">营业：{{ day.hotel.business_hours }}</span>
                        <a
                          v-if="day.hotel.detail_url"
                          :href="day.hotel.detail_url"
                          target="_blank"
                          style="margin-left: 8px; color: #1890ff;"
                        >查看详情</a>
                      </div>
                    </Col>
                  </Row>
                </Card>
              </div>
            </Col>

            <!-- 右侧：当天地图 -->
            <Col :xs="24" :lg="10">
              <PlanMap
                :markers="day.attractions.map((a, i) => ({
                  longitude: a.location?.longitude || 0,
                  latitude: a.location?.latitude || 0,
                  title: a.name,
                  order: i + 1,
                  color: dayColor(day.day_index),
                  info: { rating: a.rating, ticket: a.ticket_price, hours: a.business_hours }
                }))"
                :polyline="day.route_polyline || ''"
                :line-color="dayColor(day.day_index)"
                :center="day.map_center ? {
                  longitude: day.map_center.longitude,
                  latitude: day.map_center.latitude
                } : undefined"
                style="width: 100%; height: 360px; border-radius: 12px; overflow: hidden;"
              />
            </Col>
          </Row>

          <!-- 当天反馈操作栏 -->
          <Divider style="margin: 16px 0 12px;" />
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #888; font-size: 13px;">对这一天不满意？</span>
            <Button type="link" @click="openFeedbackDrawer(day.day_index)">
              修改这一天
            </Button>
          </div>
        </Card>
      </div>
      <div v-else style="color: #888;">
        暂无详细行程数据，以下为示例：
        <Timeline>
          <Timeline.Item>示例景点 A <Tag size="small">约 2 小时</Tag></Timeline.Item>
          <Timeline.Item>示例餐厅 B <Tag size="small">餐饮</Tag></Timeline.Item>
          <Timeline.Item>示例景点 C <Tag size="small">约 1.5 小时</Tag></Timeline.Item>
        </Timeline>
      </div>
    </Card>

    <!-- 反馈记录卡片 -->
    <Card title="修改记录" style="margin-bottom: 24px; border-radius: 12px;">
      <div v-if="feedbackList.length > 0">
        <List
          :data-source="feedbackList"
          :split="true"
        >
          <template #renderItem="{ item }">
            <List.Item>
              <div style="width: 100%;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <span>
                    <Tag v-if="item.day_index" color="blue">第 {{ item.day_index }} 天</Tag>
                    <Tag v-else color="purple">整体</Tag>
                    <Tag v-if="item.is_withdrawn" color="red">已撤回</Tag>
                    <span style="font-size: 12px; color: #888; margin-left: 8px;">{{ new Date(item.created_at).toLocaleString() }}</span>
                  </span>
                  <Space>
                    <Button type="link" size="small" @click="openFeedbackDrawer(item.day_index || 0, 'edit', item)">
                      编辑
                    </Button>
                    <Button type="link" size="small" danger @click="handleWithdrawFeedback(item.feedback_id)">
                      撤回
                    </Button>
                  </Space>
                </div>
                <p style="margin: 8px 0 0; color: #555;">{{ item.raw_text }}</p>
                <div v-if="item.tags && item.tags.length > 0" style="margin-top: 6px;">
                  <Tag v-for="(tag, idx) in item.tags" :key="idx" size="small">{{ tag }}</Tag>
                </div>
              </div>
            </List.Item>
          </template>
        </List>

        <Divider style="margin: 16px 0;" />
        <div style="display: flex; justify-content: flex-end;">
          <Button
            type="primary"
            :loading="regenerateLoading"
            @click="handleRegeneratePlan"
          >
            根据所有反馈重新生成行程
          </Button>
        </div>
      </div>
      <div v-else style="color: #888; text-align: center; padding: 24px 0;">
        暂无修改记录
      </div>
    </Card>

    <!-- 反馈/修改抽屉 -->
    <Drawer
      v-model:visible="feedbackDrawerVisible"
      :title="(feedbackMode === 'edit' ? '编辑反馈' : '修改这一天') + (currentDayIndex ? ` · 第 ${currentDayIndex} 天` : '')"
      placement="right"
      width="480"
      @close="closeFeedbackDrawer"
    >
      <div style="margin-bottom: 16px;">
        <p style="font-weight: 600; margin-bottom: 8px;">快捷标签</p>
        <Select
          v-model:value="feedbackTags"
          mode="multiple"
          style="width: 100%;"
          :options="feedbackTagsOptions"
          placeholder="选择反馈类型"
        />
      </div>

      <div style="margin-bottom: 16px;">
        <p style="font-weight: 600; margin-bottom: 8px;">具体修改意见</p>
        <Input.TextArea
          v-model:value="feedbackText"
          :rows="4"
          placeholder="例如：这家餐厅太贵了，想换一家海鲜餐厅；或者这一天行程太满，删掉一个景点"
        />
      </div>

      <div style="margin-bottom: 16px;">
        <p style="font-weight: 600; margin-bottom: 8px;">候选池</p>
        <div style="display: flex; gap: 8px; margin-bottom: 12px;">
          <Input
            v-model:value="candidateKeyword"
            placeholder="输入想替换/添加的地点类型，如：海鲜餐厅、博物馆"
            @press-enter="handleSearchCandidates"
          />
          <Button type="primary" :loading="candidateLoading" @click="handleSearchCandidates">
            搜索
          </Button>
        </div>
        <Spin :spinning="candidateLoading">
          <div v-if="candidateList.length > 0" style="max-height: 300px; overflow-y: auto;">
            <List :data-source="candidateList" size="small">
              <template #renderItem="{ item }">
                <List.Item>
                  <div style="display: flex; gap: 10px; width: 100%;">
                    <Image
                      :src="item.image_url || 'https://placehold.co/80x60?text=POI'"
                      style="width: 80px; height: 60px; object-fit: cover; border-radius: 6px; flex-shrink: 0;"
                      fallback="https://placehold.co/80x60?text=POI"
                    />
                    <div style="flex: 1; min-width: 0;">
                      <div style="font-weight: 500;">{{ item.name }}</div>
                      <div v-if="item.rating" style="font-size: 12px; color: #888;">
                        <Rate :value="item.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 11px;" />
                        {{ item.rating }} 分
                      </div>
                      <div v-if="item.address" style="font-size: 12px; color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        {{ item.address }}
                      </div>
                    </div>
                  </div>
                </List.Item>
              </template>
            </List>
          </div>
          <div v-else-if="!candidateLoading" style="color: #888; text-align: center; padding: 24px 0;">
            输入关键词搜索候选替换项
          </div>
        </Spin>
      </div>

      <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;">
        <Button @click="closeFeedbackDrawer">取消</Button>
        <Button type="primary" :loading="feedbackSubmitting" @click="handleSubmitFeedback">
          {{ feedbackMode === 'edit' ? '更新反馈' : '提交反馈' }}
        </Button>
      </div>
    </Drawer>

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
            @click="handleRegeneratePlan"
          >
            根据反馈重新生成行程
          </Button>
        </div>
      </template>
    </Drawer>
  </div>
</template>
