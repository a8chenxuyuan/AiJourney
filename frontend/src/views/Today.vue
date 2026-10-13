<!--
  src/views/Today.vue：当日视图（行中伴侣）
  作用：出行当天打开，按时间轴展示今天的安排（景点/餐饮/酒店），
       每项可一键打卡或唤起高德导航，可查看周边设施；底部提供"临时调整"入口。
  降级策略：
       - 浏览器定位失败时，打卡坐标降级为行程内该地点的坐标；
       - 天气查询失败不阻塞页面。
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, onMounted, onUnmounted, computed } from 'vue'
// 引入路由
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Card, Tag, Button, Timeline, TimelineItem, Modal, Input, message, Empty, Spin, Drawer, List } from 'ant-design-vue'
// 引入当日视图 / 打卡 / 附近推荐 API 与类型
import { getTodayView, createCheckin, getNearby, type TodayViewData, type TodaySpot, type NearbyPoi } from '@/api/companion'

const route = useRoute()
const router = useRouter()

// planId：行程 ID
const planId = route.params.id as string

// data：当日视图数据；loading：加载状态
const data = ref<TodayViewData | null>(null)
const loading = ref(true)

// ==================== 打卡 ====================

// checkinVisible：打卡弹窗；checkinTarget：正在打卡的地点；checkinNote：感想文本；checkinSubmitting：提交中
const checkinVisible = ref(false)
const checkinTarget = ref<TodaySpot | null>(null)
const checkinNote = ref('')
const checkinSubmitting = ref(false)

// ==================== 附近推荐 ====================

// nearbyVisible：附近抽屉；nearbyLoading：加载中；nearbyPois：POI 列表；nearbyAnchor：锚定地点
const nearbyVisible = ref(false)
const nearbyLoading = ref(false)
const nearbyPois = ref<NearbyPoi[]>([])
const nearbyAnchor = ref<TodaySpot | null>(null)

// nearbyTypeOptions：附近搜索类型
const nearbyTypeOptions = [
  { key: 'restaurant', label: '🍜 美食' },
  { key: 'cafe', label: '☕ 咖啡' },
  { key: 'toilet', label: '🚻 洗手间' }
]
// nearbyType：当前选中的搜索类型
const nearbyType = ref('restaurant')

// 轮询定时器（页面停留期间刷新打卡状态，30s 一次足够）
let refreshTimer: number | null = null

/**
 * fetchToday：拉取当日视图数据
 */
const fetchToday = async () => {
  try {
    const res = await getTodayView(planId)
    if (res.success) {
      data.value = res.data
    }
  } catch {
    message.error('加载当日视图失败')
  } finally {
    loading.value = false
  }
}

/**
 * openCheckin：打开打卡弹窗
 * @param spot 要打卡的地点
 */
const openCheckin = (spot: TodaySpot) => {
  checkinTarget.value = spot
  checkinNote.value = ''
  checkinVisible.value = true
}

/**
 * submitCheckin：提交打卡
 * 浏览器 geolocation 成功用真实坐标，失败降级为行程内地点坐标（不阻塞打卡）
 */
const submitCheckin = async () => {
  const spot = checkinTarget.value
  if (!spot) return
  checkinSubmitting.value = true
  try {
    let longitude = spot.location?.longitude ?? 0
    let latitude = spot.location?.latitude ?? 0
    try {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 5000 })
      })
      longitude = pos.coords.longitude
      latitude = pos.coords.latitude
    } catch {
      // 定位失败：使用行程内地点坐标
    }
    const res = await createCheckin(planId, {
      day_index: data.value?.today_plan?.day_index ?? 1,
      spot_type: spot.spot_type,
      spot_name: spot.name,
      longitude,
      latitude,
      note: checkinNote.value || undefined
    })
    if (res.success) {
      message.success(`已在「${spot.name}」打卡`)
      checkinVisible.value = false
      await fetchToday()
    } else {
      message.error(res.message || '打卡失败')
    }
  } catch {
    message.error('打卡失败')
  } finally {
    checkinSubmitting.value = false
  }
}

/**
 * openNavi：唤起高德导航（URI Scheme 网页版，新窗口打开，纯前端拼接零后端依赖）
 * @param spot 目标地点
 */
const openNavi = (spot: TodaySpot) => {
  const loc = spot.location
  if (!loc?.longitude || !loc?.latitude) {
    message.warning('该地点缺少坐标信息，无法导航')
    return
  }
  const name = encodeURIComponent(spot.name)
  const url = `https://uri.amap.com/navigation?to=${loc.longitude},${loc.latitude},${name}&mode=car&src=agent1&coordinate=gaode&callnative=1`
  window.open(url, '_blank')
}

/**
 * openNearby：打开附近推荐抽屉
 * @param spot 中心点（当前地点）
 */
const openNearby = (spot: TodaySpot) => {
  nearbyAnchor.value = spot
  nearbyType.value = 'restaurant'
  nearbyVisible.value = true
  fetchNearby()
}

/**
 * fetchNearby：按当前类型拉取附近 POI
 */
const fetchNearby = async () => {
  const spot = nearbyAnchor.value
  if (!spot?.location?.longitude) {
    message.warning('该地点缺少坐标信息')
    return
  }
  nearbyLoading.value = true
  try {
    const res = await getNearby(
      planId,
      spot.location.longitude,
      spot.location.latitude,
      nearbyType.value
    )
    if (res.success) {
      nearbyPois.value = res.data?.pois ?? []
    }
  } catch {
    message.error('附近搜索失败')
  } finally {
    nearbyLoading.value = false
  }
}

/**
 * goAdjust：跳转结果页进行"临时调整"（复用对话式修改助手）
 */
const goAdjust = () => {
  router.push(`/result/${planId}`)
}

/**
 * weatherText：天气摘要（当日白天/夜间）
 */
const weatherText = computed(() => {
  const w = data.value?.weather
  if (!w) return ''
  return `${w.day_weather ?? ''} ${w.day_temp ?? ''}℃`
})

onMounted(() => {
  fetchToday()
  // 页面停留期间定时刷新打卡状态（其他协作者的打卡也能看到）
  refreshTimer = window.setInterval(fetchToday, 30000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="page-fade" style="max-width: 880px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
      <h2 style="margin: 0; font-size: 24px;">今日行程</h2>
      <Button type="default" @click="router.push(`/result/${planId}`)">查看完整行程</Button>
    </div>

    <Spin :spinning="loading">
      <!-- 行程尚未生成 -->
      <Empty v-if="!loading && !data" description="行程尚未生成" />

      <template v-else-if="data">
        <!-- 不在行程中：行前/行后提示 -->
        <Card v-if="!data.in_trip" style="border-radius: 12px; text-align: center; padding: 24px 0;">
          <template v-if="data.days_until_start">
            <p style="font-size: 40px; margin: 8px 0;">🧳</p>
            <p style="font-size: 17px; font-weight: 600;">
              距出发还有 {{ data.days_until_start }} 天（{{ data.start_date }} 出发 · {{ data.plan_city }}）
            </p>
            <p style="color: #999;">出发当天打开本页，即可按时间轴执行行程、打卡与导航</p>
          </template>
          <template v-else>
            <p style="font-size: 40px; margin: 8px 0;">🏞️</p>
            <p style="font-size: 17px; font-weight: 600;">
              行程已结束{{ data.days_after_end ? ` ${data.days_after_end} 天` : '' }}，回顾美好回忆吧
            </p>
          </template>
          <div style="display: flex; gap: 12px; justify-content: center; margin-top: 16px;">
            <Button type="primary" @click="router.push(`/result/${planId}`)">查看行程</Button>
            <Button @click="router.push(`/trip/${planId}/footprints`)">我的足迹</Button>
            <Button @click="router.push(`/trip/${planId}/journal`)">生成游记</Button>
          </div>
        </Card>

        <!-- 行中：当日时间轴 -->
        <template v-else-if="data.today_plan">
          <!-- 概要条：第 X 天 + 城市 + 天气 -->
          <Card style="border-radius: 12px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
              <div>
                <span style="font-size: 20px; font-weight: 700;">第 {{ data.today_plan.day_index }} 天</span>
                <Tag color="blue" style="margin-left: 12px;">📍 {{ data.today_plan.city || data.plan_city }}</Tag>
                <Tag v-if="weatherText" color="cyan">🌤 {{ weatherText }}</Tag>
              </div>
              <span style="color: #999; font-size: 14px;">{{ data.today_plan.date }}</span>
            </div>
            <p v-if="data.today_plan.description" style="color: #666; margin: 10px 0 0;">
              {{ data.today_plan.description }}
            </p>
            <p v-if="data.today_plan.intercity_note" style="color: #fa8c16; margin: 10px 0 0; font-size: 13px;">
              🚄 {{ data.today_plan.intercity_note }}
            </p>
          </Card>

          <!-- 时间轴 -->
          <Card style="border-radius: 12px;">
            <Timeline>
              <TimelineItem v-for="(spot, idx) in [...data.today_plan.attractions, ...data.today_plan.meals, ...(data.today_plan.hotel ? [data.today_plan.hotel] : [])]" :key="idx">
                <template #dot>
                  <span style="font-size: 16px;">{{ spot.spot_type === 'meal' ? '🍽️' : spot.spot_type === 'hotel' ? '🏨' : '📍' }}</span>
                </template>
                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; padding-bottom: 4px;">
                  <div>
                    <p style="margin: 0; font-weight: 600; font-size: 15px;">
                      {{ spot.name }}
                      <Tag v-if="spot.checked_in" color="success" style="margin-left: 6px;">✓ 已打卡</Tag>
                    </p>
                    <p v-if="spot.location?.address" style="margin: 4px 0 0; color: #999; font-size: 13px;">{{ spot.location.address }}</p>
                  </div>
                  <div style="display: flex; gap: 8px; flex-shrink: 0;">
                    <Button size="small" :type="spot.checked_in ? 'default' : 'primary'" @click="openCheckin(spot)">
                      {{ spot.checked_in ? '再打卡' : '打卡' }}
                    </Button>
                    <Button size="small" @click="openNavi(spot)">导航</Button>
                    <Button size="small" @click="openNearby(spot)">附近</Button>
                  </div>
                </div>
              </TimelineItem>
            </Timeline>
          </Card>

          <!-- 底部操作 -->
          <div style="display: flex; justify-content: center; gap: 12px; margin: 20px 0;">
            <Button @click="goAdjust">临时调整行程</Button>
            <Button @click="router.push(`/trip/${planId}/footprints`)">查看足迹地图</Button>
          </div>
        </template>
      </template>
    </Spin>

    <!-- 打卡弹窗 -->
    <Modal v-model:open="checkinVisible" title="地点打卡" @ok="submitCheckin" :confirm-loading="checkinSubmitting" ok-text="打卡">
      <template v-if="checkinTarget">
        <p style="font-weight: 600; font-size: 16px; margin-bottom: 12px;">📍 {{ checkinTarget.name }}</p>
        <Input.TextArea
          v-model:value="checkinNote"
          placeholder="记录一句话感想（可选）"
          :rows="3"
          :maxlength="200"
          show-count
        />
        <p style="color: #999; font-size: 12px; margin-top: 8px;">
          将自动使用当前位置打卡；浏览器定位不可用时使用该地点在行程中的坐标
        </p>
      </template>
    </Modal>

    <!-- 附近推荐抽屉 -->
    <Drawer v-model:open="nearbyVisible" :title="`附近推荐 · ${nearbyAnchor?.name ?? ''}`" width="380">
      <div style="display: flex; gap: 8px; margin-bottom: 12px;">
        <Button
          v-for="opt in nearbyTypeOptions"
          :key="opt.key"
          size="small"
          :type="nearbyType === opt.key ? 'primary' : 'default'"
          @click="nearbyType = opt.key; fetchNearby()"
        >{{ opt.label }}</Button>
      </div>
      <Spin :spinning="nearbyLoading">
        <List :data-source="nearbyPois" :locale="{ emptyText: '附近暂无推荐地点' }">
          <template #renderItem="{ item }">
            <List.Item>
              <List.Item.Meta>
                <template #title>
                  <span style="font-weight: 600;">{{ item.name }}</span>
                  <span v-if="item.rating" style="color: #fa8c16; margin-left: 8px; font-size: 12px;">⭐ {{ item.rating }}</span>
                </template>
                <template #description>
                  <div style="font-size: 12px; color: #999;">
                    <p style="margin: 0;">{{ item.address || '暂无地址' }}</p>
                    <p style="margin: 2px 0 0;">距离 {{ item.distance }} 米</p>
                  </div>
                </template>
              </List.Item.Meta>
              <template #actions>
                <a
                  @click.prevent="openNavi({ name: item.name, spot_type: 'nearby', checked_in: false, location: item.location })"
                >导航</a>
              </template>
            </List.Item>
          </template>
        </List>
      </Spin>
    </Drawer>
  </div>
</template>
