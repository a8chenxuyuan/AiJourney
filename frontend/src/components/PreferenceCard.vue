<!--
  src/components/PreferenceCard.vue：用户偏好画像卡片组件
  作用：
    1. 展示用户的旅行偏好（预算档位/交通/住宿/忌口/喜好标签/去过的城市）；
    2. 用 ECharts 雷达图对偏好做可视化（五维画像）；
    3. 提供"编辑偏好"弹窗，用户可手动修改并保存（写回后端，影响下次规划的 IntentAgent）。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. props 接收用户 ID，挂载后拉取偏好数据（getMyPreference）
 * 2. computed 生成雷达图数据与展示文案
 * 3. 编辑弹窗内以表单收集修改，保存时调用 updateMyPreference 并刷新
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
// 引入 Ant Design Vue 组件
import {
  Card,
  Tag,
  Button,
  Modal,
  Form,
  Input,
  Select,
  message,
  Descriptions,
  DescriptionsItem,
  Empty
} from 'ant-design-vue'
// 引入 ECharts
import * as echarts from 'echarts'
// 引入偏好 API 与类型
import { getMyPreference, updateMyPreference, type UserPreference } from '@/api/trip/memory'

/**
 * PreferenceCardProps：组件 props
 */
interface PreferenceCardProps {
  userId?: number
}

const props = defineProps<PreferenceCardProps>()

// preference：偏好画像数据
const preference = ref<UserPreference | null>(null)
// loading：加载状态
const loading = ref(false)
// saving：保存状态
const saving = ref(false)
// editVisible：编辑弹窗显隐
const editVisible = ref(false)

// 雷达图容器 DOM 引用与实例
const radarRef = ref<HTMLDivElement | null>(null)
let radarChart: echarts.ECharts | null = null

// 编辑表单数据（弹窗内使用）
const editForm = ref({
  budget_level: 'standard',
  transportation: 'public',
  accommodation: 'comfort',
  dietary_restrictions: '',
  favorite_tags: [] as string[],
  disliked_tags: [] as string[]
})

// 选项字典（展示与编辑共用；key 与后端约定一致）
const BUDGET_OPTIONS = [
  { value: 'economy', label: '经济型' },
  { value: 'standard', label: '标准型' },
  { value: 'comfort', label: '舒适型' },
  { value: 'luxury', label: '豪华型' }
]
const TRANSPORT_OPTIONS = [
  { value: 'public', label: '公共交通优先' },
  { value: 'taxi', label: '打车优先' },
  { value: 'drive', label: '自驾' },
  { value: 'walk', label: '步行+骑行' }
]
const ACCOMMODATION_OPTIONS = [
  { value: 'budget', label: '经济连锁' },
  { value: 'comfort', label: '舒适型酒店' },
  { value: 'high_end', label: '高端酒店' },
  { value: 'homestay', label: '民宿' }
]

// 标签快捷选项（编辑弹窗中可勾选）
const TAG_OPTIONS = [
  '自然风光', '历史文化', '博物馆', '美食', '购物', '亲子',
  '摄影', '徒步', '夜生活', '文艺', '温泉', '海岛'
]

/**
 * labelOf：按选项字典把 value 转为中文标签。
 * 兼容数组值（模型字段为 JSON list）：逐项翻译后拼接；空数组/空串显示「未设置」，
 * 避免空值渲染成空豆腐块。
 */
const labelOf = (
  options: Array<{ value: string; label: string }>,
  value: string | string[] | null
): string => {
  if (Array.isArray(value)) {
    if (!value.length) return '未设置'
    return value.map((v) => options.find((o) => o.value === v)?.label || v).join('、')
  }
  return options.find((o) => o.value === value)?.label || value || '未设置'
}

/**
 * radarOption：五维偏好雷达图配置
 *
 * 维度映射（把离散偏好转为 1-4 分）：
 * - 消费水平：budget_level 映射
 * - 住宿品质：accommodation 映射
 * - 出行自由度：transportation 映射
 * - 兴趣广度：favorite_tags 数量
 * - 旅行经验：visited_cities 数量
 */
const radarOption = computed(() => {
  const p = preference.value
  if (!p) return null

  const budgetScore = { economy: 1, standard: 2, comfort: 3, luxury: 4 }[p.budget_level || 'standard'] ?? 2
  const accommodationScore = { budget: 1, homestay: 2, comfort: 3, high_end: 4 }[p.accommodation || 'comfort'] ?? 2
  const transportScore = { walk: 1, public: 2, taxi: 3, drive: 4 }[p.transportation || 'public'] ?? 2
  const interestScore = Math.min(4, (p.favorite_tags?.length || 1))
  const expScore = Math.min(4, (p.visited_cities?.length || 0))

  return {
    radar: {
      indicator: [
        { name: '消费水平', max: 4 },
        { name: '住宿品质', max: 4 },
        { name: '出行自由', max: 4 },
        { name: '兴趣广度', max: 4 },
        { name: '旅行经验', max: 4 }
      ],
      radius: '65%',
      axisName: { color: '#666', fontSize: 12 },
      splitArea: { areaStyle: { color: ['#fff', '#fafafa'] } },
      splitLine: { lineStyle: { color: '#e8e8e8' } }
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: [budgetScore, accommodationScore, transportScore, interestScore, expScore],
            name: '偏好画像',
            areaStyle: { color: 'rgba(24, 144, 255, 0.25)' },
            lineStyle: { color: '#1890ff', width: 2 },
            itemStyle: { color: '#1890ff' }
          }
        ]
      }
    ]
  }
})

/**
 * renderRadar：渲染/更新雷达图
 */
const renderRadar = () => {
  if (!radarRef.value) return
  if (!radarChart) {
    radarChart = echarts.init(radarRef.value)
  }
  const opt = radarOption.value
  if (opt) {
    radarChart.setOption(opt, true)
  }
}

/**
 * handleResize：窗口尺寸变化时自适应
 */
const handleResize = () => radarChart?.resize()

/**
 * fetchPreference：拉取偏好数据
 */
const fetchPreference = async () => {
  if (!props.userId) return
  loading.value = true
  try {
    const res = await getMyPreference(props.userId)
    if (res.success && res.data) {
      preference.value = res.data
    }
  } catch (error) {
    console.error('获取偏好失败', error)
  } finally {
    loading.value = false
  }
}

/**
 * openEdit：打开编辑弹窗，用当前偏好填充表单
 */
const openEdit = () => {
  const p = preference.value
  editForm.value = {
    budget_level: p?.budget_level || 'standard',
    transportation: p?.transportation || 'public',
    accommodation: p?.accommodation || 'comfort',
    dietary_restrictions: p?.dietary_restrictions || '',
    favorite_tags: [...(p?.favorite_tags || [])],
    disliked_tags: [...(p?.disliked_tags || [])]
  }
  editVisible.value = true
}

/**
 * handleSave：保存编辑后的偏好
 */
const handleSave = async () => {
  if (!props.userId) return
  saving.value = true
  try {
    const res = await updateMyPreference(props.userId, {
      budget_level: editForm.value.budget_level,
      transportation: editForm.value.transportation,
      accommodation: editForm.value.accommodation,
      dietary_restrictions: editForm.value.dietary_restrictions,
      favorite_tags: editForm.value.favorite_tags,
      disliked_tags: editForm.value.disliked_tags
    })
    if (res.success) {
      message.success('偏好已更新，下次规划将自动应用')
      editVisible.value = false
      // 用后端返回值刷新展示
      if (res.data) preference.value = res.data
      else fetchPreference()
    } else {
      message.warning(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存偏好失败', error)
    message.error('保存失败，请稍后重试')
  } finally {
    saving.value = false
  }
}

// 组件挂载：拉取数据并初始化图表
onMounted(async () => {
  await fetchPreference()
  renderRadar()
  window.addEventListener('resize', handleResize)
})

// 卸载：清理
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  radarChart?.dispose()
  radarChart = null
})

// 数据变化后重绘雷达图
watch([preference, radarOption], () => renderRadar())
</script>

<template>
  <Card title="偏好画像" style="border-radius: 12px;">
    <template #extra>
      <Button type="link" @click="openEdit">编辑偏好</Button>
    </template>

    <div v-if="preference" style="display: flex; flex-wrap: wrap; gap: 24px;">
      <!-- 左：雷达图 -->
      <div ref="radarRef" style="flex: 1 1 300px; min-width: 280px; height: 260px;"></div>

      <!-- 右：偏好明细 -->
      <div style="flex: 1 1 300px; min-width: 280px;">
        <Descriptions :column="1" size="small" bordered>
          <DescriptionsItem label="预算档位">{{ labelOf(BUDGET_OPTIONS, preference.budget_level) }}</DescriptionsItem>
          <DescriptionsItem label="出行方式">{{ labelOf(TRANSPORT_OPTIONS, preference.transportation) }}</DescriptionsItem>
          <DescriptionsItem label="住宿偏好">{{ labelOf(ACCOMMODATION_OPTIONS, preference.accommodation) }}</DescriptionsItem>
          <DescriptionsItem label="饮食忌口">{{ preference.dietary_restrictions || '无' }}</DescriptionsItem>
          <DescriptionsItem label="兴趣标签">
            <template v-if="preference.favorite_tags && preference.favorite_tags.length">
              <Tag v-for="t in preference.favorite_tags" :key="t" color="blue">{{ t }}</Tag>
            </template>
            <span v-else style="color: #999;">暂无</span>
          </DescriptionsItem>
          <DescriptionsItem label="不感兴趣">
            <template v-if="preference.disliked_tags && preference.disliked_tags.length">
              <Tag v-for="t in preference.disliked_tags" :key="t">{{ t }}</Tag>
            </template>
            <span v-else style="color: #999;">暂无</span>
          </DescriptionsItem>
          <DescriptionsItem label="去过的城市">
            <template v-if="preference.visited_cities && preference.visited_cities.length">
              <Tag v-for="c in preference.visited_cities" :key="c" color="green">{{ c }}</Tag>
            </template>
            <span v-else style="color: #999;">暂无</span>
          </DescriptionsItem>
        </Descriptions>
        <p style="font-size: 12px; color: #999; margin-top: 10px;">
          这些偏好由系统根据你的规划历史与反馈自动学习，也可以手动修改；下次生成行程时会自动应用。
        </p>
      </div>
    </div>

    <Empty v-else-if="!loading" description="暂无偏好数据" />

    <!-- 编辑弹窗 -->
    <Modal v-model:visible="editVisible" title="编辑旅行偏好" @ok="handleSave" :confirm-loading="saving">
      <Form layout="vertical">
        <Form.Item label="预算档位">
          <Select v-model:value="editForm.budget_level" :options="BUDGET_OPTIONS" />
        </Form.Item>
        <Form.Item label="出行方式">
          <Select v-model:value="editForm.transportation" :options="TRANSPORT_OPTIONS" />
        </Form.Item>
        <Form.Item label="住宿偏好">
          <Select v-model:value="editForm.accommodation" :options="ACCOMMODATION_OPTIONS" />
        </Form.Item>
        <Form.Item label="兴趣标签">
          <Select v-model:value="editForm.favorite_tags" mode="multiple" :options="TAG_OPTIONS.map(t => ({ value: t, label: t }))" placeholder="选择你喜欢的旅行主题" />
        </Form.Item>
        <Form.Item label="不感兴趣的主题">
          <Select v-model:value="editForm.disliked_tags" mode="multiple" :options="TAG_OPTIONS.map(t => ({ value: t, label: t }))" placeholder="选择你不感兴趣的主题" />
        </Form.Item>
        <Form.Item label="饮食忌口">
          <Input.TextArea v-model:value="editForm.dietary_restrictions" :rows="2" placeholder="例如：不吃辣、素食" />
        </Form.Item>
      </Form>
    </Modal>
  </Card>
</template>
