<!-- ResultOverviewCard.vue：行程概览卡片——目的地/日期/天数/预算/天气与版本 diff 记录 -->
<script setup lang="ts">
import { ref } from 'vue'
import { Card, Row, Col, Tag, Space, Button } from 'ant-design-vue'
import type { TripPlan } from '@/api/trip'

interface DiffSummary {
  total_changes: number
  days: Array<{
    day_index: number
    change_count: number
    attractions: { added: string[]; removed: string[] }
    meals: { changed: Array<{ meal_type: string; from: string; to: string }> }
    hotel: { from: string; to: string } | null
  }>
}

defineProps<{
  plan: TripPlan | null
  diffSummary: DiffSummary | null
  currentVersion: number | null
  isMultiCity: boolean
  multiCityStays: Array<{ city: string }>
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
}>()

// 是否显示修改记录（默认隐藏，避免初次访问时的视觉噪音）
const showDiffSummary = ref(false)
</script>

<template>
  <Card title="行程概览" style="margin-bottom: 24px; border-radius: 12px;">
    <template #extra>
      <Space>
        <Button size="small" @click="emit('refresh')">刷新</Button>
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
</template>
