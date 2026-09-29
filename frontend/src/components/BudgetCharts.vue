<!--
  src/components/BudgetCharts.vue：预算可视化组件
  作用：使用 ECharts 展示两张图表：
       1. 预算构成环形图（景点 / 餐饮 / 住宿 / 交通 四大项占比）；
       2. 每日花费估算柱状图（当天景点门票 + 餐饮人均 + 酒店房费）。
  说明：
       - 每日花费为"估算值"（基于 POI 门票与人均餐饮），与预算总览的分项合计可能略有出入；
       - 未配置相关字段的天（如无酒店）按 0 处理。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. props 接收预算分项与每日行程
 * 2. computed 计算环形图数据与每日柱状图数据
 * 3. 组件挂载后初始化两个 ECharts 实例
 * 4. 监听数据变化与窗口尺寸变化，更新/自适应图表
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
// 引入 ECharts（完整包，项目体量下无需按需裁剪）
import * as echarts from 'echarts'
// 引入 Ant Design Vue 栅格组件
import { Row, Col } from 'ant-design-vue'

/**
 * Budget：预算分项类型（与后端 schemas.Budget 对齐）
 */
export interface Budget {
  total: number
  attractions: number
  meals: number
  hotels: number
  transportation: number
}

/**
 * BudgetChartsProps：组件 props 类型
 */
interface BudgetChartsProps {
  budget?: Budget
  /** 每日行程（仅需 attractions/meals/hotel 的花费字段） */
  dayPlans?: any[]
}

// 声明 props，设置默认值
const props = withDefaults(defineProps<BudgetChartsProps>(), {
  budget: undefined,
  dayPlans: () => []
})

// pieRef / barRef：两个图表容器 DOM 引用
const pieRef = ref<HTMLDivElement | null>(null)
const barRef = ref<HTMLDivElement | null>(null)
// pieChart / barChart：ECharts 实例
let pieChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null

// 四大分项的固定配色（与项目蓝色系协调）
const CATEGORY_COLORS = ['#1890ff', '#52c41a', '#faad14', '#fa541c']

/**
 * pieOption：预算构成环形图配置
 */
const pieOption = computed(() => {
  const b = props.budget
  const data = b
    ? [
        { name: '景点门票', value: b.attractions || 0 },
        { name: '餐饮', value: b.meals || 0 },
        { name: '住宿', value: b.hotels || 0 },
        { name: '交通', value: b.transportation || 0 }
      ].filter((item) => item.value > 0)
    : []

  return {
    color: CATEGORY_COLORS,
    tooltip: { trigger: 'item', formatter: '{b}：¥{c}（{d}%）' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 12, color: '#666' } },
    // 环形图中间展示总预算
    graphic: b
      ? [
          {
            type: 'text',
            left: 'center',
            top: '40%',
            style: {
              text: `¥${b.total || 0}`,
              fontSize: 20,
              fontWeight: 700,
              fill: '#333',
              textAlign: 'center'
            }
          },
          {
            type: 'text',
            left: 'center',
            top: '52%',
            style: { text: '预估总预算', fontSize: 12, fill: '#999', textAlign: 'center' }
          }
        ]
      : [],
    series: [
      {
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
        label: { show: false },
        emphasis: {
          label: { show: false },
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' }
        },
        data
      }
    ]
  }
})

/**
 * dayCost：计算某天花费估算（门票 + 餐饮 + 酒店）
 * @param day 单日行程对象
 */
const dayCost = (day: any): number => {
  const tickets = (day?.attractions || []).reduce(
    (sum: number, a: any) => sum + (Number(a?.ticket_price) || 0),
    0
  )
  const meals = (day?.meals || []).reduce(
    (sum: number, m: any) => sum + (Number(m?.estimated_cost) || 0),
    0
  )
  const hotel = Number(day?.hotel?.price_per_night) || 0
  return tickets + meals + hotel
}

/**
 * barOption：每日花费柱状图配置
 */
const barOption = computed(() => {
  const days = props.dayPlans || []
  const values = days.map((d) => Math.round(dayCost(d)))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        return `第 ${p.name} 天<br/>预估花费：¥${p.value}`
      }
    },
    grid: { left: 8, right: 8, top: 28, bottom: 0, containLabel: true },
    xAxis: {
      type: 'category',
      data: days.map((d) => String(d?.day_index ?? '')),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e0e0e0' } },
      axisLabel: { formatter: (v: string) => `第${v}天`, color: '#666', fontSize: 12 }
    },
    yAxis: {
      type: 'value',
      name: '元',
      nameTextStyle: { color: '#999', fontSize: 11 },
      splitLine: { lineStyle: { color: '#f0f0f0' } },
      axisLabel: { color: '#666', fontSize: 12 }
    },
    series: [
      {
        type: 'bar',
        data: values,
        barMaxWidth: 36,
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          // 柱子按数值从蓝到绿渐变，视觉上区分高花费日
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#40a9ff' },
            { offset: 1, color: '#1890ff' }
          ])
        },
        label: {
          show: values.length <= 10,
          position: 'top',
          fontSize: 11,
          color: '#888',
          formatter: (p: any) => (p.value > 0 ? `¥${p.value}` : '')
        }
      }
    ]
  }
})

/**
 * renderCharts：应用最新配置到图表实例（实例存在时）
 */
const renderCharts = () => {
  pieChart?.setOption(pieOption.value, true)
  barChart?.setOption(barOption.value, true)
}

/**
 * handleResize：窗口尺寸变化时自适应图表
 */
const handleResize = () => {
  pieChart?.resize()
  barChart?.resize()
}

// 组件挂载后初始化图表实例并渲染
onMounted(() => {
  if (pieRef.value) {
    pieChart = echarts.init(pieRef.value)
  }
  if (barRef.value) {
    barChart = echarts.init(barRef.value)
  }
  renderCharts()
  window.addEventListener('resize', handleResize)
})

// 卸载前移除监听并销毁实例
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  pieChart?.dispose()
  barChart?.dispose()
  pieChart = null
  barChart = null
})

// 数据变化时重新渲染
watch(() => [props.budget, props.dayPlans], renderCharts, { deep: true })
</script>

<template>
  <div style="width: 100%;">
    <Row :gutter="[24, 16]" style="display: flex; flex-wrap: wrap;">
      <Col :xs="24" :md="10">
        <p style="font-weight: 600; margin: 0 0 8px;">预算构成</p>
        <div ref="pieRef" style="width: 100%; height: 240px;"></div>
      </Col>
      <Col :xs="24" :md="14">
        <p style="font-weight: 600; margin: 0 0 8px;">每日花费估算</p>
        <div ref="barRef" style="width: 100%; height: 240px;"></div>
      </Col>
    </Row>
  </div>
</template>
