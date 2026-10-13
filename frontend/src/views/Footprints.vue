<!--
  src/views/Footprints.vue：足迹地图
  作用：高德地图渲染行程内的全部打卡点（按天配色）并按天连线，
       支持按天筛选，侧栏展示打卡明细（可删除）。
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted } from 'vue'
// 引入路由
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Tag, Card, Spin, message, Popconfirm, List } from 'ant-design-vue'
// 引入打卡 API 与类型
import { getCheckins, deleteCheckin, type CheckinRecord } from '@/api/companion'
// 引入行程地图组件（复用序号标记/连线/信息窗能力）
import PlanMap, { type MapMarker, type MapPolyline } from '@/components/PlanMap.vue'

const route = useRoute()
const router = useRouter()

// planId：行程 ID
const planId = route.params.id as string

// checkins：全部打卡记录；loading：加载状态；activeDay：当前筛选天（null=全部）
const checkins = ref<CheckinRecord[]>([])
const loading = ref(true)
const activeDay = ref<number | null>(null)

// 按天配色（与结果页总览地图配色一致）
const DAY_COLORS = ['#1890ff', '#52c41a', '#fa8c16', '#722ed1', '#eb2f96', '#13c2c2', '#fadb14', '#fa541c']

// dayIndexes：出现的打卡天数（升序）
const dayIndexes = computed(() =>
  Array.from(new Set(checkins.value.map((c) => c.day_index))).sort((a, b) => a - b)
)

// filteredCheckins：按天筛选后的打卡记录
const filteredCheckins = computed(() =>
  activeDay.value === null
    ? checkins.value
    : checkins.value.filter((c) => c.day_index === activeDay.value)
)

/**
 * dayColor：取某天的配色
 */
const dayColor = (day: number) => DAY_COLORS[(day - 1) % DAY_COLORS.length]

/**
 * mapMarkers：打卡点 → 地图标记（点击信息窗展示感想）
 */
const mapMarkers = computed<MapMarker[]>(() =>
  filteredCheckins.value
    .filter((c) => c.longitude && c.latitude)
    .map((c) => ({
      longitude: c.longitude,
      latitude: c.latitude,
      title: c.spot_name,
      color: dayColor(c.day_index),
      info: { address: c.note || undefined }
    }))
)

/**
 * mapPolylines：按天把打卡点按打卡时间连成路线
 */
const mapPolylines = computed<MapPolyline[]>(() => {
  const byDay: Record<number, CheckinRecord[]> = {}
  for (const c of filteredCheckins.value) {
    if (!c.longitude || !c.latitude) continue
    ;(byDay[c.day_index] ||= []).push(c)
  }
  return Object.entries(byDay).map(([day, items]) => ({
    path: items
      .sort((a, b) => (a.checkin_at ?? '').localeCompare(b.checkin_at ?? ''))
      .map((c) => `${c.longitude},${c.latitude}`)
      .join(';'),
    color: dayColor(Number(day))
  }))
})

/**
 * mapCenter：以第一个打卡点为地图中心
 */
const mapCenter = computed(() => {
  const first = filteredCheckins.value.find((c) => c.longitude && c.latitude)
  return first ? { longitude: first.longitude, latitude: first.latitude } : undefined
})

/**
 * fetchCheckins：拉取打卡记录
 */
const fetchCheckins = async () => {
  loading.value = true
  try {
    const res = await getCheckins(planId)
    if (res.success && res.data) {
      checkins.value = res.data.checkins
    }
  } catch {
    message.error('加载足迹失败')
  } finally {
    loading.value = false
  }
}

/**
 * handleDelete：删除打卡（仅本人打卡可删，后端校验）
 */
const handleDelete = async (checkin: CheckinRecord) => {
  try {
    const res = await deleteCheckin(checkin.id)
    if (res.success) {
      message.success('已删除打卡')
      await fetchCheckins()
    } else {
      message.error(res.message || '删除失败')
    }
  } catch {
    message.error('删除失败')
  }
}

onMounted(fetchCheckins)
</script>

<template>
  <div class="page-fade" style="max-width: 1160px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0; flex-wrap: wrap; gap: 12px;">
      <h2 style="margin: 0; font-size: 24px;">足迹地图</h2>
      <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
        <Tag :color="activeDay === null ? 'blue' : 'default'" style="cursor: pointer; padding: 4px 14px;" @click="activeDay = null">
          全部（{{ checkins.length }}）
        </Tag>
        <Tag
          v-for="day in dayIndexes"
          :key="day"
          :color="activeDay === day ? dayColor(day) : 'default'"
          style="cursor: pointer; padding: 4px 14px;"
          @click="activeDay = day"
        >第 {{ day }} 天</Tag>
        <Button type="primary" @click="router.push(`/trip/${planId}/today`)">今日行程</Button>
      </div>
    </div>

    <Spin :spinning="loading">
      <!-- 无打卡数据 -->
      <Card v-if="!loading && checkins.length === 0" style="border-radius: 12px; text-align: center; padding: 32px 0;">
        <p style="font-size: 40px; margin: 8px 0;">👣</p>
        <p style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">还没有足迹</p>
        <p style="color: #999; margin-bottom: 16px;">去「今日行程」打卡，走过的路会出现在这张地图上</p>
        <Button type="primary" @click="router.push(`/trip/${planId}/today`)">去打卡</Button>
      </Card>

      <!-- 地图 + 明细 -->
      <div v-else style="display: flex; gap: 16px; align-items: stretch; flex-wrap: wrap;">
        <Card style="border-radius: 12px; flex: 1 1 640px; min-width: 320px; overflow: hidden;">
          <div style="height: 520px;">
            <PlanMap :markers="mapMarkers" :polylines="mapPolylines" :center="mapCenter" />
          </div>
        </Card>

        <Card style="border-radius: 12px; flex: 1 1 320px; min-width: 280px;">
          <template #title>打卡明细（{{ filteredCheckins.length }}）</template>
          <List :data-source="filteredCheckins" :locale="{ emptyText: '该天暂无打卡' }" style="max-height: 480px; overflow-y: auto;">
            <template #renderItem="{ item }">
              <List.Item>
                <List.Item.Meta>
                  <template #title>
                    <span style="font-weight: 600;">{{ item.spot_name }}</span>
                  </template>
                  <template #description>
                    <div style="font-size: 12px; color: #999;">
                      <Tag :color="dayColor(item.day_index)" style="margin-right: 6px;">第 {{ item.day_index }} 天</Tag>
                      <span>{{ (item.checkin_at || '').replace('T', ' ').slice(0, 16) }}</span>
                      <p v-if="item.note" style="margin: 4px 0 0; color: #666;">"{{ item.note }}"</p>
                    </div>
                  </template>
                </List.Item.Meta>
                <template #actions>
                  <Popconfirm title="确定删除这条打卡吗？" @confirm="handleDelete(item)">
                    <a style="color: #ff4d4f;">删除</a>
                  </Popconfirm>
                </template>
              </List.Item>
            </template>
          </List>
        </Card>
      </div>
    </Spin>
  </div>
</template>
