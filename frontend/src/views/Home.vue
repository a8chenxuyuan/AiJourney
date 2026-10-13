<!--
  src/views/Home.vue：首页（旅行规划表单页）
  作用：收集城市、日期、交通、住宿、偏好等旅行规划信息，提交后跳转到 /planning/:id
  设计说明（2026 现代风）：
    1. 沉浸式图片 Hero：真实目的地摄影图 + 深色渐变遮罩 + 大号标题，营造出发感；
    2. 灵感模板卡：图片卡片（图上文下），hover 图片微缩放 + 卡片上浮；
    3. Bento Grid 特性格：大小不一的模块化卡片展示核心能力；
    4. 图片统一使用平台 text_to_image 服务生成，提示词遵循 SDXL 最佳实践。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 定义旅行规划表单响应式数据
 * 2. 用户点击提交后调用 createPlan API
 * 3. 创建成功后携带 plan_id 跳转至规划进度页
 */

// 引入 Vue 的响应式 API
import { reactive, ref, computed, watch, onMounted } from 'vue'
// 引入 Vue Router 的 useRouter Hook
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 表单、输入框、日期选择器、选择器、按钮、卡片、栅格、消息提示组件
import { Form, Input, InputNumber, DatePicker, Select, Switch, Button, Card, Row, Col, Badge, Popover, message, Tag } from 'ant-design-vue'
// 引入创建规划 API 与请求类型
import { createPlan, getFavoriteCities, type TripRequest } from '@/api/trip'
import { getArchive, type ArchiveData } from '@/api/companion'
// 引入站内通知 API 与类型
import { getNotifications, markAllNotificationsRead, type NotificationItem } from '@/api/notification'
// 引入个性化推荐 API 与类型
import { getRecommendations, type RecommendationItem } from '@/api/recommend'

// 获取路由实例，用于提交成功后跳转
const router = useRouter()

/**
 * 封面图资源：
 * 由平台 text_to_image 服务按提示词预生成，已下载至 public/images/ 作为静态资源，
 * 避免运行时每次请求重复生成（生成耗时长且结果不稳定）。
 */
const IMG_HERO = '/images/hero.jpg'
const IMG_CHENGDU = '/images/chengdu.jpg'
const IMG_HANGZHOU = '/images/hangzhou.jpg'
const IMG_XIAMEN = '/images/xiamen.jpg'
const IMG_BEIJING = '/images/beijing.jpg'

// travelForm：旅行规划表单响应式数据
// 字段名与后端 Pydantic TripRequest 保持一致
const travelForm = reactive<TripRequest>({
  city: '',
  start_date: '',
  end_date: '',
  transportation: '公共交通',
  accommodation: '酒店',
  preferences: [],
  must_visit: [],
  budget_level: 'standard',
  free_text_input: ''
})

// loading：控制提交按钮的加载状态
const loading = ref(false)

// transportationOptions：交通方式选项（与后端 transportation 字段枚举保持一致）
const transportationOptions = [
  { label: '✈️ 飞机', value: '飞机' },
  { label: '🚄 高铁', value: '高铁' },
  { label: '🚗 自驾', value: '自驾' },
  { label: '🚌 公共交通', value: '公共交通' }
]

// accommodationOptions：住宿类型选项
const accommodationOptions = [
  { label: '🏨 酒店', value: '酒店' },
  { label: '🏡 民宿', value: '民宿' },
  { label: '🛏️ 青旅', value: '青旅' }
]

// preferenceOptions：旅行偏好选项（支持多选）
const preferenceOptions = [
  { label: '🏞️ 自然风光', value: '自然风光' },
  { label: '🏛️ 人文历史', value: '人文历史' },
  { label: '🍜 美食探店', value: '美食探店' },
  { label: '🎡 亲子游乐', value: '亲子游乐' },
  { label: '🏖️ 休闲度假', value: '休闲度假' }
]

// budgetLevelOptions：预算等级选项（与后端 budget_level 枚举保持一致）
const budgetLevelOptions = [
  { label: '💰 经济型', value: 'economy' },
  { label: '⚖️ 标准型', value: 'standard' },
  { label: '💎 豪华型', value: 'luxury' }
]

// ==================== 灵感模板（一键填充） ====================

/**
 * TemplateItem：灵感模板类型
 * days：行程天数（用于计算返程日期）；img：目的地封面图
 */
interface TemplateItem {
  title: string
  desc: string
  days: number
  img: string
  values: {
    city: string
    transportation: string
    accommodation: string
    preferences: string[]
    must_visit: string[]
    budget_level: string
    free_text_input: string
  }
}

// TEMPLATES：内置灵感模板列表（含目的地摄影封面图）
const TEMPLATES: TemplateItem[] = [
  {
    title: '成都 · 美食之旅',
    desc: '火锅串串 · 熊猫基地 · 宽窄巷子',
    days: 3,
    img: IMG_CHENGDU,
    values: {
      city: '成都',
      transportation: '高铁',
      accommodation: '酒店',
      preferences: ['美食探店', '休闲度假'],
      must_visit: ['大熊猫繁育研究基地', '宽窄巷子'],
      budget_level: 'standard',
      free_text_input: '想体验成都特色美食，节奏适中不要太赶，晚上方便出去逛吃'
    }
  },
  {
    title: '杭州 · 2 日经典游',
    desc: '西湖 · 灵隐寺 · 龙井茶园',
    days: 2,
    img: IMG_HANGZHOU,
    values: {
      city: '杭州',
      transportation: '高铁',
      accommodation: '酒店',
      preferences: ['自然风光', '人文历史'],
      must_visit: ['西湖', '灵隐寺'],
      budget_level: 'standard',
      free_text_input: '喜欢慢节奏的湖边漫步，想去茶园坐坐'
    }
  },
  {
    title: '厦门 · 海岛度假',
    desc: '鼓浪屿 · 环岛路 · 曾厝垵',
    days: 4,
    img: IMG_XIAMEN,
    values: {
      city: '厦门',
      transportation: '飞机',
      accommodation: '民宿',
      preferences: ['休闲度假', '美食探店'],
      must_visit: ['鼓浪屿', '环岛路'],
      budget_level: 'comfort',
      free_text_input: '海边度假放松为主，想住海景民宿，适合拍照'
    }
  },
  {
    title: '北京 · 文化之旅',
    desc: '故宫 · 长城 · 颐和园',
    days: 5,
    img: IMG_BEIJING,
    values: {
      city: '北京',
      transportation: '高铁',
      accommodation: '酒店',
      preferences: ['人文历史', '自然风光'],
      must_visit: ['故宫', '八达岭长城', '颐和园'],
      budget_level: 'standard',
      free_text_input: '第一次去北京，经典景点都想打卡，注意预约限制'
    }
  }
]

/**
 * applyTemplate：把模板值填充进表单，日期默认从一周后开始
 * @param tpl 模板对象
 */
const applyTemplate = (tpl: TemplateItem) => {
  // 计算默认日期：一周后出发，按模板天数返回
  const start = new Date()
  start.setDate(start.getDate() + 7)
  const end = new Date(start)
  end.setDate(end.getDate() + tpl.days - 1)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)

  travelForm.city = tpl.values.city
  travelForm.start_date = fmt(start)
  travelForm.end_date = fmt(end)
  travelForm.transportation = tpl.values.transportation
  travelForm.accommodation = tpl.values.accommodation
  travelForm.preferences = [...tpl.values.preferences]
  travelForm.must_visit = [...tpl.values.must_visit]
  travelForm.budget_level = tpl.values.budget_level
  travelForm.free_text_input = tpl.values.free_text_input

  message.success(`已填充「${tpl.title}」模板，可继续调整`)
  // 填充后自动滚到表单区，减少一次滚动操作
  document.getElementById('plan-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/**
 * scrollToForm：Hero CTA 按钮，平滑滚动到规划表单
 */

// ==================== 收藏城市快捷入口（复购） ====================

// favoriteCities：当前用户收藏内容涉及的城市（最近收藏优先），为空则不展示入口
const favoriteCities = ref<string[]>([])

/**
 * fetchFavoriteCities：组件挂载时拉取收藏城市列表（未登录或无收藏时静默忽略）
 */
const fetchFavoriteCities = async () => {
  try {
    const res = await getFavoriteCities()
    if (res.success && res.data) {
      favoriteCities.value = res.data.cities
    }
  } catch {
    // 未登录等场景下拉取失败不影响首页正常使用
  }
}

/**
 * applyFavoriteCity：点击收藏城市 → 填充目的地并预填一周后的 3 天行程
 * @param city 收藏内容涉及的城市名
 */
const applyFavoriteCity = (city: string) => {
  const start = new Date()
  start.setDate(start.getDate() + 7)
  const end = new Date(start)
  end.setDate(end.getDate() + 2)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)

  travelForm.city = city
  travelForm.start_date = fmt(start)
  travelForm.end_date = fmt(end)

  message.success(`已选择你收藏过的城市「${city}」，补充偏好后即可规划`)
  document.getElementById('plan-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ==================== 我的足迹条（旅行档案入口） ====================

// archiveStats：旅行档案统计（去过城市/打卡数），为空则不展示入口
const archiveStats = ref<ArchiveData['stats'] | null>(null)

/**
 * fetchArchiveStats：组件挂载时拉取档案统计（未登录或无数据时静默忽略）
 */
const fetchArchiveStats = async () => {
  try {
    const res = await getArchive()
    if (res.success && res.data && res.data.stats.plan_count > 0) {
      archiveStats.value = res.data.stats
    }
  } catch {
    // 拉取失败不影响首页正常使用
  }
}

// 组件挂载时拉取收藏城市、站内通知与个性化推荐
onMounted(() => {
  fetchFavoriteCities()
  fetchNotifications()
  fetchRecommendations()
  fetchArchiveStats()
})
const scrollToForm = () => {
  document.getElementById('plan-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ==================== 站内通知（右上角铃铛） ====================

// notifications：通知列表；unreadCount：未读数
const notifications = ref<NotificationItem[]>([])
const unreadCount = ref(0)

// hasLoginToken：是否已登录（未登录则不请求需登录接口，避免无谓的 401 报错）
const hasLoginToken = () => !!localStorage.getItem('agent1_travel_token')

/**
 * fetchNotifications：拉取通知列表与未读数（失败静默，不影响首页使用）
 */
const fetchNotifications = async () => {
  if (!hasLoginToken()) return
  try {
    const res = await getNotifications()
    if (res.success && res.data) {
      notifications.value = res.data.notifications || []
      unreadCount.value = res.data.unread_count || 0
    }
  } catch {
    // 拉取失败时保持空态，不显示报错
  }
}

/**
 * markAllRead：一键全部已读，成功后刷新通知列表
 */
const markAllRead = async () => {
  try {
    const res = await markAllNotificationsRead()
    if (res.success) {
      message.success(`已将 ${res.data?.marked ?? 0} 条通知标记为已读`)
      await fetchNotifications()
    }
  } catch {
    // 失败静默
  }
}

// ==================== "为你推荐"目的地 ====================

// recommendItems：推荐目的地列表（接口失败或为空时隐藏整个区块）
const recommendItems = ref<RecommendationItem[]>([])

// sourceLabel：推荐来源中文映射（Tag 展示用）
const sourceLabel: Record<string, string> = {
  favorites: '来自收藏',
  memory: '来自偏好记忆',
  history: '来自历史行程',
  knowledge: '热门推荐'
}

/**
 * fetchRecommendations：拉取"为你推荐"目的地（失败静默，空列表时隐藏区块）
 */
const fetchRecommendations = async () => {
  if (!hasLoginToken()) return
  try {
    const res = await getRecommendations()
    if (res.success && res.data) {
      recommendItems.value = res.data.items || []
    }
  } catch {
    // 拉取失败时隐藏推荐区块
  }
}

/**
 * applyRecommendCity：点击推荐城市 → 填充目的地（单城填 city 字段；多城开关开启则填入首行城市）
 * @param city 推荐城市名
 */
const applyRecommendCity = (city: string) => {
  if (multiCityEnabled.value) {
    if (cityStays.value[0]) cityStays.value[0].city = city
  } else {
    travelForm.city = city
  }
  message.success('已为你填入目的地')
  document.getElementById('plan-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ==================== 多城市联游 ====================

// multiCityEnabled：是否开启多城市联游模式（开启后按城市列表提交 cities 字段）
const multiCityEnabled = ref(false)
// cityStays：按出发顺序的城市与停留天数，默认两行占位示例（杭州2天/苏州1天）
const cityStays = ref<{ city: string; days: number }[]>([
  { city: '', days: 2 },
  { city: '', days: 1 }
])

// addCityStay：底部"添加城市"按钮，新增一行（默认停留 1 天）
const addCityStay = () => {
  cityStays.value.push({ city: '', days: 1 })
}

// removeCityStay：删除指定行，至少保留一行
const removeCityStay = (idx: number) => {
  if (cityStays.value.length > 1) cityStays.value.splice(idx, 1)
}

// totalDays：由出发/返程日期计算的总旅行天数（含首尾两天），未选齐日期时为 0
const totalDays = computed(() => {
  if (!travelForm.start_date || !travelForm.end_date) return 0
  const start = new Date(travelForm.start_date).getTime()
  const end = new Date(travelForm.end_date).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return 0
  return Math.round((end - start) / 86400000) + 1
})

// assignedDays：已分配给各城市的停留天数之和
const assignedDays = computed(() => cityStays.value.reduce((sum, c) => sum + (c.days || 0), 0))

// multiCityReady：多城模式可提交条件——日期已选、天数恰好分配完、各城市名已填写
const multiCityReady = computed(
  () =>
    totalDays.value > 0 &&
    assignedDays.value === totalDays.value &&
    cityStays.value.length > 0 &&
    cityStays.value.every(c => c.city.trim() !== '')
)

// submitDisabled：多城模式下分配未完成（含 sum(days)≠总天数）时禁用提交按钮
const submitDisabled = computed(() => multiCityEnabled.value && !multiCityReady.value)

// multiCityTip：天数分配提示文案（"已分配 X / 总 N 天"）
const multiCityTip = computed(() => {
  if (totalDays.value === 0) return '请先选择出发与返程日期，再分配各城市停留天数'
  return assignedDays.value === totalDays.value
    ? `已分配 ${assignedDays.value} / 总 ${totalDays.value} 天，可以开始规划 ✓`
    : `已分配 ${assignedDays.value} / 总 ${totalDays.value} 天，各城市停留天数之和需等于总天数`
})

// displayCity：目的地输入框的双向绑定——多城模式读写首行城市，单城模式维持原表单字段
const displayCity = computed({
  get: () => (multiCityEnabled.value ? cityStays.value[0]?.city ?? '' : travelForm.city),
  set: (val: string) => {
    if (multiCityEnabled.value) {
      if (cityStays.value[0]) cityStays.value[0].city = val
    } else {
      travelForm.city = val
    }
  }
})

// 开启多城时，把已填写的单城目的地带入首行，减少重复输入
watch(multiCityEnabled, on => {
  if (on && travelForm.city && cityStays.value[0] && !cityStays.value[0].city) {
    cityStays.value[0].city = travelForm.city
  }
})

/**
 * handleSubmit：表单提交处理函数
 * 作用：校验必填项、调用 createPlan 接口、成功后跳转规划进度页
 */
const handleSubmit = async () => {
  // 多城模式：校验日期、城市名与天数分配（sum(days) 必须等于总天数）
  if (multiCityEnabled.value) {
    if (!travelForm.start_date || !travelForm.end_date) {
      message.warning('请先选择出发与返程日期')
      return
    }
    if (cityStays.value.some(c => !c.city.trim())) {
      message.warning('请填写每个联游城市')
      return
    }
    if (assignedDays.value !== totalDays.value) {
      message.warning(`各城市停留天数之和（${assignedDays.value}）需等于旅行总天数（${totalDays.value}）`)
      return
    }
  } else if (!travelForm.city || !travelForm.start_date || !travelForm.end_date) {
    message.warning('请填写目的地与出行日期')
    return
  }

  loading.value = true
  try {
    // 多城开启时携带 cities（city 字段填首城）；单城维持原表单，不带 cities
    const params: TripRequest = multiCityEnabled.value
      ? {
          ...travelForm,
          city: cityStays.value[0].city.trim(),
          cities: cityStays.value.map(c => ({ city: c.city.trim(), days: c.days }))
        }
      : travelForm
    // 调用创建规划 API
    const res = await createPlan(params)
    if (res.success && res.data?.plan_id) {
      message.success('规划任务已创建')
      // 跳转至规划进度页，携带 plan_id
      router.push(`/planning/${res.data.plan_id}`)
    } else {
      message.error(res.message || '创建规划失败')
    }
  } catch (error) {
    console.error('创建规划异常', error)
  } finally {
    loading.value = false
  }
}

/**
 * onStartDateChange：出发日期变化回调
 * @param date 日期字符串
 * @param dateString 格式化后的日期字符串
 */
const onStartDateChange = (_date: any, dateString: string) => {
  travelForm.start_date = dateString
}

/**
 * onEndDateChange：返程日期变化回调
 * @param date 日期对象
 * @param dateString 格式化后的日期字符串
 */
const onEndDateChange = (_date: any, dateString: string) => {
  travelForm.end_date = dateString
}
</script>

<template>
  <!-- 页面容器（relative 用于右上角通知入口定位） -->
  <div class="page-fade home-page" style="max-width: 1160px; margin: 0 auto; position: relative">
    <!-- 右上角通知入口：Badge 未读数 + 铃铛按钮 + Popover 通知面板 -->
    <div style="position: absolute; top: 14px; right: 20px; z-index: 10;">
      <Popover trigger="click" placement="bottomRight">
        <template #content>
          <div style="width: 320px; max-height: 360px; overflow-y: auto;">
            <!-- 空态 -->
            <div v-if="notifications.length === 0" style="color: #999; text-align: center; padding: 24px 0;">
              暂无通知
            </div>
            <!-- 通知列表：title/content/created_at，未读高亮 -->
            <div v-else>
              <div
                v-for="n in notifications"
                :key="n.id"
                style="padding: 10px 4px; border-bottom: 1px solid #f0f0f0;"
              >
                <div style="display: flex; align-items: center; gap: 6px;">
                  <Badge v-if="!n.is_read" status="processing" />
                  <span style="font-weight: 600; font-size: 13px;">{{ n.title }}</span>
                </div>
                <div style="color: #666; font-size: 12px; margin-top: 4px; line-height: 1.6;">{{ n.content }}</div>
                <div style="color: #bbb; font-size: 11px; margin-top: 4px;">{{ n.created_at }}</div>
              </div>
            </div>
            <!-- 底部操作：全部已读 -->
            <div style="text-align: center; padding-top: 8px; border-top: 1px solid #f0f0f0; margin-top: 4px;">
              <Button type="link" size="small" :disabled="unreadCount === 0" @click="markAllRead">全部已读</Button>
            </div>
          </div>
        </template>
        <Badge :count="unreadCount" size="small" :overflow-count="99">
          <Button size="small" style="border-radius: 999px; background: rgba(255,255,255,0.9);">🔔 通知</Button>
        </Badge>
      </Popover>
    </div>

    <!-- ============ 1. 沉浸式图片 Hero ============ -->
    <section class="hero-media">
      <!-- 背景摄影图（fetchpriority 提升首屏加载优先级） -->
      <img class="hero-media-img" :src="IMG_HERO" alt="旅行目的地风光" fetchpriority="high" />
      <div class="hero-media-overlay"></div>

      <div class="hero-media-content">
        <span class="hero-eyebrow">✦ AI 多智能体旅行规划</span>
        <h1 class="hero-title">
          让 AI 为你定制<br />
          <em>下一次心动旅程</em>
        </h1>
        <p class="hero-subtitle">
          11 个智能体协同工作：理解需求 → 挑选景点 → 查天气 → 排路线 → 算预算，<br />
          一键生成可交互的行程地图，还能随时对话式修改。
        </p>
        <!-- 数据条：玻璃胶囊 -->
        <div class="hero-stats">
          <div class="hero-stat"><b>11</b><span>AI 智能体协作</span></div>
          <div class="hero-stat"><b>1 分钟</b><span>生成完整行程</span></div>
          <div class="hero-stat"><b>∞</b><span>目的地组合玩法</span></div>
        </div>
      </div>
    </section>

    <!-- Hero 下方 CTA：引导滚动到表单 -->
    <div style="display: flex; justify-content: center; margin-top: -22px; position: relative; z-index: 2">
      <Button type="primary" style="height: 44px; padding: 0 28px; font-size: 15px; border-radius: 999px" @click="scrollToForm">
        立即开始规划 ↓
      </Button>
    </div>

    <!-- ============ 2. 灵感模板（图片卡） ============ -->
    <section class="reveal">
      <div class="section-head">
        <div class="section-head-left">
          <h2>灵感模板</h2>
          <p>从热门目的地开始，点击卡片一键填充下方表单</p>
        </div>
        <span class="section-head-tag">🔥 本周热门</span>
      </div>

      <div class="tpl-grid">
        <article v-for="tpl in TEMPLATES" :key="tpl.title" class="tpl-card" @click="applyTemplate(tpl)">
          <!-- 封面图 -->
          <div class="tpl-cover">
            <img :src="tpl.img" :alt="tpl.title" loading="lazy" />
            <span class="tpl-days">{{ tpl.days }} 天</span>
          </div>
          <!-- 文字区 -->
          <div class="tpl-body">
            <h3 class="tpl-title">{{ tpl.title }}</h3>
            <p class="tpl-desc">{{ tpl.desc }}</p>
            <span class="tpl-cta">一键填充 →</span>
          </div>
        </article>
      </div>
    </section>

    <!-- ============ 2.4 我的足迹条（旅行档案入口） ============ -->
    <section v-if="archiveStats" class="reveal" style="margin-top: 32px">
      <div class="section-head">
        <div class="section-head-left">
          <h2>我的足迹</h2>
          <p>走过的每一步都被记录，随时回顾你的旅行档案</p>
        </div>
        <span class="section-head-tag">🎒 行中伴侣</span>
      </div>
      <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
        <div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: center;">
          <Tag
            v-for="city in archiveStats.cities.slice(0, 8)"
            :key="city"
            color="blue"
            style="font-size: 15px; padding: 8px 20px; border-radius: 999px;"
          >🏙️ {{ city }}</Tag>
        </div>
        <span style="color: #888; font-size: 14px;">
          已去过 {{ archiveStats.city_count }} 座城市 · {{ archiveStats.checkin_total }} 次打卡
        </span>
        <router-link to="/profile/archive" style="margin-left: auto; font-weight: 600;">查看旅行档案 →</router-link>
      </div>
    </section>

    <!-- ============ 2.4b 旅行社区入口 ============ -->
    <section class="reveal" style="margin-top: 32px">
      <div class="section-head">
        <div class="section-head-left">
          <h2>旅行社区</h2>
          <p>看看别人的路线与游记，喜欢的可以一键「照着走」复制成自己的行程</p>
        </div>
        <span class="section-head-tag">🧭 可复制的路线</span>
      </div>
      <div style="display: flex; align-items: center;">
        <router-link to="/notes" style="font-weight: 600;">进入旅行笔记 →</router-link>
      </div>
    </section>

    <!-- ============ 2.5 你可能想去（基于收藏城市的个性化入口） ============ -->
    <section v-if="favoriteCities.length > 0" class="reveal" style="margin-top: 32px">
      <div class="section-head">
        <div class="section-head-left">
          <h2>你可能想去</h2>
          <p>根据你收藏过的内容推荐，点击直接填充目的地</p>
        </div>
        <span class="section-head-tag">⭐ 来自你的收藏</span>
      </div>
      <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <Tag
          v-for="city in favoriteCities.slice(0, 8)"
          :key="city"
          style="font-size: 15px; padding: 8px 20px; border-radius: 999px; cursor: pointer;"
          @click="applyFavoriteCity(city)"
        >📍 {{ city }}</Tag>
      </div>
    </section>

    <!-- ============ 3. 创建旅行规划表单 ============ -->
    <section id="plan-form" class="reveal" style="margin-top: 44px">
      <Card class="plan-card">
        <template #title>🧭 创建旅行规划</template>

        <Form layout="vertical">
          <!-- 为你推荐：个性化目的地推荐（接口失败或空列表时隐藏整个区块） -->
          <div v-if="recommendItems.length > 0" style="margin-bottom: 20px;">
            <div class="form-section-title" style="margin-bottom: 12px;">✨ 为你推荐</div>
            <div style="display: flex; gap: 12px; flex-wrap: wrap;">
              <div
                v-for="rec in recommendItems.slice(0, 6)"
                :key="rec.city"
                style="
                  flex: 1 1 220px; max-width: 300px; padding: 12px 14px;
                  background: #fafafa; border: 1px solid #f0f0f0; border-radius: 10px;
                  cursor: pointer; transition: all 0.2s;
                "
                @click="applyRecommendCity(rec.city)"
              >
                <div style="display: flex; align-items: center; gap: 8px;">
                  <strong style="font-size: 15px;">{{ rec.city }}</strong>
                  <Tag color="blue" style="margin: 0; font-size: 11px; line-height: 18px; padding: 0 6px;">
                    {{ sourceLabel[rec.source] || '推荐' }}
                  </Tag>
                </div>
                <div style="color: #666; font-size: 12px; margin-top: 6px; line-height: 1.6;">{{ rec.reason }}</div>
                <!-- 推荐景点：仅展示前 3 个 -->
                <div v-if="rec.spots && rec.spots.length" style="color: #999; font-size: 12px; margin-top: 6px;">
                  {{ rec.spots.slice(0, 3).join(' · ') }}
                </div>
              </div>
            </div>
          </div>

          <!-- 分区一：目的地与日期 -->
          <div class="form-section-title">📍 目的地与日期</div>
          <Row :gutter="16">
            <Col :xs="24" :sm="8">
              <Form.Item label="目的地城市">
                <Input v-model:value="displayCity" placeholder="例如：杭州" allow-clear />
              </Form.Item>
            </Col>
            <Col :xs="12" :sm="8">
              <Form.Item label="出发日期">
                <DatePicker style="width: 100%" placeholder="选择出发日期" @change="onStartDateChange" />
              </Form.Item>
            </Col>
            <Col :xs="12" :sm="8">
              <Form.Item label="返程日期">
                <DatePicker style="width: 100%" placeholder="选择返程日期" @change="onEndDateChange" />
              </Form.Item>
            </Col>
          </Row>

          <!-- 多城市联游：开关 + 动态城市列表（开启后按出发顺序提交 cities） -->
          <div style="display: flex; align-items: center; gap: 10px; margin-top: 4px;">
            <Switch v-model:checked="multiCityEnabled" />
            <span style="font-weight: 600;">多城市联游</span>
            <span style="color: #999; font-size: 12px;">开启后可一次规划多个城市，按出发顺序依次游玩</span>
          </div>
          <div v-if="multiCityEnabled" style="margin-top: 12px; padding: 16px; background: #fafafa; border-radius: 8px;">
            <div
              v-for="(stay, idx) in cityStays"
              :key="idx"
              style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;"
            >
              <span style="color: #999; flex-shrink: 0; width: 52px;">第{{ idx + 1 }}站</span>
              <Input
                v-model:value="stay.city"
                :placeholder="idx === 0 ? '如：杭州' : idx === 1 ? '如：苏州' : '请输入城市名'"
                allow-clear
              />
              <InputNumber v-model:value="stay.days" :min="1" :precision="0" style="width: 110px; flex-shrink: 0;" />
              <span style="color: #999; flex-shrink: 0;">天</span>
              <Button danger type="text" size="small" :disabled="cityStays.length <= 1" @click="removeCityStay(idx)">
                删除
              </Button>
            </div>
            <div style="display: flex; align-items: center; gap: 12px; margin-top: 4px;">
              <Button size="small" @click="addCityStay">+ 添加城市</Button>
              <span
                :style="{
                  fontSize: '13px',
                  color: totalDays === 0 ? '#faad14' : assignedDays === totalDays ? '#52c41a' : '#fa541c'
                }"
              >{{ multiCityTip }}</span>
            </div>
          </div>

          <!-- 分区二：出行偏好 -->
          <div class="form-section-title" style="margin-top: 10px">🧳 出行方式</div>
          <Row :gutter="16">
            <Col :xs="24" :sm="8">
              <Form.Item label="交通方式">
                <Select v-model:value="travelForm.transportation" :options="transportationOptions" />
              </Form.Item>
            </Col>
            <Col :xs="24" :sm="8">
              <Form.Item label="住宿类型">
                <Select v-model:value="travelForm.accommodation" :options="accommodationOptions" />
              </Form.Item>
            </Col>
            <Col :xs="24" :sm="8">
              <Form.Item label="预算等级">
                <Select v-model:value="travelForm.budget_level" :options="budgetLevelOptions" />
              </Form.Item>
            </Col>
          </Row>

          <!-- 分区三：个性化 -->
          <div class="form-section-title" style="margin-top: 10px">❤️ 个性化定制</div>
          <Form.Item label="旅行偏好">
            <Select
              v-model:value="travelForm.preferences"
              mode="multiple"
              :options="preferenceOptions"
              placeholder="请选择旅行偏好（可多选）"
            />
          </Form.Item>

          <Form.Item label="必去景点">
            <Select v-model:value="travelForm.must_visit" mode="tags" placeholder="输入并回车添加必去景点" style="width: 100%" />
          </Form.Item>

          <Form.Item label="补充说明">
            <Input.TextArea
              v-model:value="travelForm.free_text_input"
              placeholder="可填写其他需求，例如：带老人小孩、不想爬山、想体验当地美食等"
              :rows="3"
            />
          </Form.Item>

          <!-- 提交栏 -->
          <div class="plan-submit-bar">
            <div class="plan-submit-tip">
              提交后 11 个智能体将自动接力规划，全程可在进度页实时观看，生成后支持对话式修改。
            </div>
            <Button
              type="primary"
              :loading="loading"
              :disabled="submitDisabled"
              style="height: 46px; padding: 0 34px; font-size: 16px; border-radius: 12px; flex-shrink: 0"
              @click="handleSubmit"
            >
              开始规划 →
            </Button>
          </div>
        </Form>
      </Card>
    </section>

    <!-- ============ 4. Bento 特性格 ============ -->
    <section class="reveal" style="margin-top: 52px">
      <div class="section-head">
        <div class="section-head-left">
          <h2>为什么选择我们</h2>
          <p>多智能体编排 + 可视化 + 对话式交互，一站式旅行规划体验</p>
        </div>
      </div>

      <div class="bento-grid">
        <!-- 大卡（深色）：Multi-Agent 编排 -->
        <div class="bento-item bento-span-2 bento-dark">
          <div class="bento-blob" style="width: 160px; height: 160px; background: rgba(77, 214, 198, 0.35); top: -60px; right: -40px"></div>
          <div class="bento-icon">🤖</div>
          <h3 class="bento-title">Multi-Agent 智能体编排</h3>
          <p class="bento-desc">
            11 个专业智能体各司其职，像真实旅行管家团队一样接力协作，规划过程全程透明可见。
          </p>
          <div class="bento-steps">
            <span class="bento-step">理解需求</span>
            <span class="bento-step">挑选景点</span>
            <span class="bento-step">查询天气</span>
            <span class="bento-step">规划路线</span>
            <span class="bento-step">核算预算</span>
          </div>
        </div>

        <!-- 小卡：行程地图 -->
        <div class="bento-item">
          <div class="bento-icon">🗺️</div>
          <h3 class="bento-title">行程地图可视化</h3>
          <p class="bento-desc">每日行程自动落图，景点动线一目了然。</p>
        </div>

        <!-- 小卡：对话式修改 -->
        <div class="bento-item">
          <div class="bento-icon">💬</div>
          <h3 class="bento-title">对话式修改</h3>
          <p class="bento-desc">「把第二天换成博物馆」，说一句话即可改行程。</p>
        </div>

        <!-- 大卡：长期偏好记忆 -->
        <div class="bento-item bento-span-2">
          <div class="bento-blob" style="width: 140px; height: 140px; background: rgba(22, 119, 255, 0.1); bottom: -50px; right: -30px"></div>
          <div class="bento-icon">🧠</div>
          <h3 class="bento-title">长期偏好记忆</h3>
          <p class="bento-desc">
            系统会记住你的旅行偏好与历史选择，越用越懂你，每次规划都更贴近你的口味。
          </p>
        </div>
      </div>
    </section>
  </div>
</template>
