<!--
  src/views/Result.vue：结果展示页
  作用：页面骨架 + 路由级数据加载（规划/反馈/收藏/订单）与跨区块共享状态；
       概览、地图、每日行程、反馈抽屉、AI 助手等区块拆至 ./Result/ 子组件。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从路由参数获取 plan_id，调用 getPlan API 获取规划结果
 * 2. 挂载时并行拉取反馈列表、收藏、订单
 * 3. 各展示/交互区块由 Result/ 子组件承担，经 props/emits 与本页通信
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Card, Tag, List, Space, Divider, message } from 'ant-design-vue'
import {
  getPlan,
  withdrawPlanFeedback,
  getPlanFeedbacks,
  regeneratePlan,
  addFavorite,
  getFavorites,
  removeFavorite,
  type TripPlan,
  type FavoriteRecord
} from '@/api/trip'
import { getOrders, type OrderSummary } from '@/api/trip/payment'
import BudgetCharts from '@/components/BudgetCharts.vue'
import ResultToolbar from './Result/ResultToolbar.vue'
import ResultPayModal from './Result/ResultPayModal.vue'
import ResultShareModal from './Result/ResultShareModal.vue'
import ResultCollabModal from './Result/ResultCollabModal.vue'
import ResultOverviewCard from './Result/ResultOverviewCard.vue'
import ResultOverviewMapCard from './Result/ResultOverviewMapCard.vue'
import ResultDailyPlans from './Result/ResultDailyPlans.vue'
import ResultFeedbackDrawer from './Result/ResultFeedbackDrawer.vue'
import ResultChatDrawer from './Result/ResultChatDrawer.vue'

const route = useRoute()
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
// isOwner：当前登录用户是否为行程所有者（来自 GET /trip/{id} 的 is_owner）
const isOwner = ref(false)

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

// ==================== 反馈列表与重新生成（跨区块共享） ====================

// feedbackList：当前 plan 的所有有效反馈（修改记录卡片 + 反馈抽屉共用）
const feedbackList = ref<any[]>([])
// pendingCount：待处理（未撤回）的反馈数量（AI 助手角标用）
const pendingCount = ref(0)
// regenerateLoading：基于所有反馈重新生成行程中
const regenerateLoading = ref(false)

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

// ==================== 地图配色与多城市（总览/每日卡片共用） ====================

// DAY_COLORS：总览地图的每日主题配色（循环使用）
const DAY_COLORS = ['#1890ff', '#52c41a', '#faad14', '#fa541c', '#722ed1', '#13c2c2', '#eb2f96', '#2f54eb', '#a0d911', '#fa8c16']

/**
 * dayColor：按天序号返回主题色（用于总览/单日地图的标记与路线配色）
 */
const dayColor = (dayIndex: number) => DAY_COLORS[(dayIndex - 1) % DAY_COLORS.length]

// multiCityStays：多城市联游的城市列表（单城为空数组）
const multiCityStays = computed(() => plan.value?.cities || [])
// isMultiCity：是否为多城市联游行程（≥2 个城市才展示城市标识）
const isMultiCity = computed(() => multiCityStays.value.length >= 2)

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
 * toggleItemFavorite：收藏 / 取消收藏任意条目（景点、酒店、餐厅通用）
 * 未收藏 → 以名称做唯一标识收藏（保存完整快照）；
 * 已收藏 → 按记录 ID 取消收藏。
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

// ==================== 预订支付（沙箱）共享状态 ====================

// payVisible：支付弹窗是否展示
const payVisible = ref(false)
// paidOrders：该行程下的历史订单
const paidOrders = ref<OrderSummary[]>([])

// isPaid：该行程是否存在已支付订单（决定操作栏徽标）
const isPaid = computed(() => paidOrders.value.some((o) => o.status === 'paid'))

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
 * openPayModal：打开支付弹窗
 */
const openPayModal = () => {
  payVisible.value = true
}

// ==================== 子组件引用与共享回调 ====================

// shareLoading：分享请求中状态（顶栏分享按钮 loading）
const shareLoading = ref(false)
const shareModalRef = ref<InstanceType<typeof ResultShareModal> | null>(null)
const collabModalRef = ref<InstanceType<typeof ResultCollabModal> | null>(null)
const feedbackDrawerRef = ref<InstanceType<typeof ResultFeedbackDrawer> | null>(null)

/**
 * getShareQr：分享海报所需的二维码（委托分享弹窗静默创建/复用）
 */
const getShareQr = async (): Promise<string> =>
  (await shareModalRef.value?.ensureShareQr()) || ''

// 组件挂载时获取规划结果、反馈列表、收藏与订单
onMounted(() => {
  fetchPlan()
  fetchFeedbacks()
  fetchFavorites()
  fetchOrders()
})

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
  <div id="trip-result-container" class="page-fade" style="max-width: 1900px; margin: 0 auto; padding: 0 16px;">
    <!-- 顶部操作栏 -->
    <ResultToolbar
      :plan="plan"
      :plan-id="planId"
      :is-paid="isPaid"
      :share-loading="shareLoading"
      :get-share-qr="getShareQr"
      @share="shareModalRef?.handleShare()"
      @collab="collabModalRef?.open()"
      @pay="openPayModal"
    />

    <!-- 预订支付弹窗（沙箱） -->
    <ResultPayModal
      v-model:visible="payVisible"
      :plan-id="planId"
      :amount="plan?.budget?.total"
      @paid="fetchOrders"
    />

    <!-- 行程分享弹窗 -->
    <ResultShareModal ref="shareModalRef" v-model:loading="shareLoading" :plan-id="planId" />

    <!-- 协作弹窗 -->
    <ResultCollabModal ref="collabModalRef" :plan-id="planId" :is-owner="isOwner" />

    <!-- 概览卡片 -->
    <ResultOverviewCard
      :plan="plan"
      :diff-summary="diffSummary"
      :current-version="currentVersion"
      :is-multi-city="isMultiCity"
      :multi-city-stays="multiCityStays"
      @refresh="manualRefresh"
    />

    <!-- 预算可视化卡片 -->
    <Card v-if="plan?.budget" title="预算分析" style="margin-bottom: 24px; border-radius: 12px;">
      <BudgetCharts :budget="plan.budget" :day-plans="plan?.day_plans || []" />
    </Card>

    <!-- 全程总览地图卡片 -->
    <ResultOverviewMapCard :plan="plan" :day-color="dayColor" />

    <!-- 每日行程卡片 -->
    <ResultDailyPlans
      :plan="plan"
      :day-color="dayColor"
      :is-multi-city="isMultiCity"
      :favorite-map="favoriteMap"
      @edit-day="feedbackDrawerRef?.open($event)"
      @toggle-favorite="(p) => toggleItemFavorite(p.itemType, p.item as Record<string, any>, p.name)"
    />

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
                    <Button type="link" size="small" @click="feedbackDrawerRef?.open(item.day_index || 0, 'edit', item)">
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
    <ResultFeedbackDrawer
      ref="feedbackDrawerRef"
      :plan-id="planId"
      :city="plan?.city"
      @submitted="fetchFeedbacks"
    />

    <!-- AI 修改助手（悬浮入口 + 聊天抽屉） -->
    <ResultChatDrawer
      v-model:pending-count="pendingCount"
      :plan-id="planId"
      :regenerate-loading="regenerateLoading"
      @regenerate="handleRegeneratePlan"
      @refresh-feedbacks="fetchFeedbacks"
    />
  </div>
</template>
