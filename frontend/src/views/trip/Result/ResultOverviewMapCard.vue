<!-- ResultOverviewMapCard.vue：全程总览地图卡片——汇总各天标记与路线一图展示 -->
<script setup lang="ts">
import { computed } from 'vue'
import { Card, Tag } from 'ant-design-vue'
import type { TripPlan } from '@/api/trip'
import PlanMap from '@/components/PlanMap.vue'

const props = defineProps<{
  plan: TripPlan | null
  dayColor: (dayIndex: number) => string
}>()

// 是否有每日行程数据（控制总览卡片显隐）
const hasDayPlans = computed(() => (props.plan?.day_plans?.length || 0) > 0)

// overviewMarkers：总览地图的全部标记（含序号/按天配色/信息窗内容）
const overviewMarkers = computed(() => {
  const markers: any[] = []
  for (const day of props.plan?.day_plans || []) {
    ;(day.attractions || []).forEach((spot: any, idx: number) => {
      if (!spot?.location?.longitude || !spot?.location?.latitude) return
      markers.push({
        longitude: spot.location.longitude,
        latitude: spot.location.latitude,
        title: spot.name,
        order: idx + 1,
        color: props.dayColor(day.day_index),
        info: { rating: spot.rating, ticket: spot.ticket_price, hours: spot.business_hours }
      })
    })
  }
  return markers
})

// overviewPolylines：总览地图的多天路线（每条按天配色）
const overviewPolylines = computed(() => {
  const lines: { path: string; color: string }[] = []
  for (const day of props.plan?.day_plans || []) {
    if (day.route_polyline) {
      lines.push({ path: day.route_polyline, color: props.dayColor(day.day_index) })
    }
  }
  return lines
})
</script>

<template>
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
</template>
