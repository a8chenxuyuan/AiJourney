<!--
  src/components/PlanCard.vue：行程卡片组件
  作用：接收 plan 对象，展示城市、日期、预算、状态等关键信息
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 通过 defineProps 接收外部传入的 plan 对象
 * 2. 计算并展示城市、日期、预算、状态等字段
 * 3. 点击卡片可跳转对应结果页（若 plan_id 存在）
 */

// 引入 Vue Router 的 useRouter Hook
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 卡片、标签组件
import { Card, Tag } from 'ant-design-vue'

/**
 * PlanCardProps：组件 props 类型
 * plan：行程对象，包含城市、日期、预算、状态等字段
 * 字段名与后端 TripPlan / PlanCard 使用保持一致
 */
interface PlanCardProps {
  plan: {
    plan_id: string
    city: string
    start_date: string
    end_date: string
    budget?: { total: number }
    status: string
  }
}

// 声明 props，脚本中通过 props 访问，模板中可直接使用 plan
const props = defineProps<PlanCardProps>()

// 获取路由实例
const router = useRouter()

/**
 * statusColor：根据行程状态返回对应标签颜色
 * @param status 行程状态字符串
 * @returns Tag 组件可用的颜色字符串
 */
const statusColor = (status: string): string => {
  switch (status) {
    case 'completed':
      return 'green'
    case 'planning':
      return 'blue'
    case 'failed':
      return 'red'
    default:
      return 'default'
  }
}

/**
 * handleClick：点击卡片时跳转结果页
 */
const handleClick = () => {
  if (props.plan.plan_id) {
    router.push(`/result/${props.plan.plan_id}`)
  }
}
</script>

<template>
  <!-- Card：行程卡片，hover 时显示手型光标 -->
  <Card hoverable style="border-radius: 8px; cursor: pointer;" @click="handleClick">
    <h4 style="margin: 0 0 8px 0;">{{ plan.city }}</h4>
    <p style="margin: 4px 0; color: #555;">
      {{ plan.start_date }} 至 {{ plan.end_date }}
    </p>
    <p v-if="plan.budget" style="margin: 4px 0; color: #888;">
      预算：{{ plan.budget.total }} 元
    </p>
    <p style="margin: 4px 0;">
      状态：<Tag :color="statusColor(plan.status)">{{ plan.status }}</Tag>
    </p>
  </Card>
</template>
