<!--
  src/views/Archive.vue：旅行档案
  作用：汇总当前用户的全部行程与打卡统计（去过 N 城 / M 次打卡 / 足迹跨度），
       以卡片流展示历史行程，每张卡可跳转行程详情 / 足迹 / 游记。
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Card, Tag, Empty, Spin, message } from 'ant-design-vue'
// 引入档案 API 与类型
import { getArchive, type ArchiveData } from '@/api/companion'

const router = useRouter()

// archive：档案数据；loading：加载状态
const archive = ref<ArchiveData | null>(null)
const loading = ref(true)

/**
 * tripSpan：足迹跨度文案（最早 ~ 最晚打卡日期）
 */
const tripSpan = computed(() => {
  const stats = archive.value?.stats
  if (!stats?.first_checkin_at) return '暂无打卡记录'
  const fmt = (iso: string) => iso.slice(0, 10)
  const first = fmt(stats.first_checkin_at)
  const last = fmt(stats.last_checkin_at ?? stats.first_checkin_at)
  return first === last ? first : `${first} ~ ${last}`
})

/**
 * citiesText：行程目的地文案（多城联游用 →，单城直接显示）
 */
const citiesText = (plan: ArchiveData['plans'][number]) => {
  if (plan.cities?.length) return plan.cities.map((c) => c.city).join(' → ')
  return plan.city
}

/**
 * statusTag：行程状态 → 标签颜色与文案
 */
const statusTag = (status: string) => {
  const map: Record<string, { color: string; text: string }> = {
    completed: { color: 'success', text: '已完成' },
    planning: { color: 'processing', text: '规划中' },
    failed: { color: 'error', text: '失败' },
    revising: { color: 'processing', text: '修订中' }
  }
  return map[status] ?? { color: 'default', text: status }
}

/**
 * fetchArchive：拉取档案数据
 */
const fetchArchive = async () => {
  try {
    const res = await getArchive()
    if (res.success) {
      archive.value = res.data
    }
  } catch {
    message.error('加载档案失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchArchive)
</script>

<template>
  <div class="page-fade" style="max-width: 1080px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
      <h2 style="margin: 0; font-size: 24px;">旅行档案</h2>
      <Button type="default" @click="router.push('/profile')">个人中心</Button>
    </div>

    <Spin :spinning="loading">
      <!-- 顶部统计条 -->
      <Card v-if="archive" style="border-radius: 12px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-around; text-align: center; flex-wrap: wrap; gap: 12px;">
          <div>
            <p style="font-size: 26px; font-weight: 700; margin: 0; color: #1677ff;">{{ archive.stats.city_count }}</p>
            <p style="color: #888; margin: 4px 0 0; font-size: 13px;">去过城市</p>
          </div>
          <div>
            <p style="font-size: 26px; font-weight: 700; margin: 0; color: #1677ff;">{{ archive.stats.plan_count }}</p>
            <p style="color: #888; margin: 4px 0 0; font-size: 13px;">旅行次数</p>
          </div>
          <div>
            <p style="font-size: 26px; font-weight: 700; margin: 0; color: #1677ff;">{{ archive.stats.checkin_total }}</p>
            <p style="color: #888; margin: 4px 0 0; font-size: 13px;">打卡记录</p>
          </div>
          <div>
            <p style="font-size: 26px; font-weight: 700; margin: 0; color: #1677ff;">{{ archive.stats.photo_total }}</p>
            <p style="color: #888; margin: 4px 0 0; font-size: 13px;">照片</p>
          </div>
          <div>
            <p style="font-size: 15px; font-weight: 600; margin: 6px 0;">{{ tripSpan }}</p>
            <p style="color: #888; margin: 4px 0 0; font-size: 13px;">足迹跨度</p>
          </div>
        </div>
        <!-- 城市标签墙 -->
        <div v-if="archive.stats.cities.length" style="margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;">
          <Tag v-for="city in archive.stats.cities" :key="city" color="blue">🏙️ {{ city }}</Tag>
        </div>
      </Card>

      <!-- 行程卡片流 -->
      <Empty
        v-if="!loading && (!archive || archive.plans.length === 0)"
        description="还没有旅行记录，去首页规划第一次旅行吧"
      >
        <Button type="primary" @click="router.push('/')">去规划</Button>
      </Empty>

      <div v-else style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px;">
        <Card v-for="plan in archive?.plans ?? []" :key="plan.plan_id" hoverable style="border-radius: 12px;">
          <template #title>
            <span style="font-size: 16px;">{{ citiesText(plan) }}</span>
          </template>
          <template #extra>
            <Tag :color="statusTag(plan.status).color">{{ statusTag(plan.status).text }}</Tag>
          </template>
          <p style="color: #666; margin: 0;">
            🗓 {{ plan.start_date }} ~ {{ plan.end_date }}（{{ plan.travel_days }} 天）
          </p>
          <p style="color: #666; margin: 6px 0 0;">
            👣 {{ plan.checkin_count }} 次打卡
            <span v-if="plan.budget_total"> · 💰 预算 ¥{{ plan.budget_total }}</span>
          </p>
          <div style="display: flex; gap: 8px; margin-top: 14px;">
            <Button size="small" type="primary" @click="router.push(`/result/${plan.plan_id}`)">行程</Button>
            <Button size="small" @click="router.push(`/trip/${plan.plan_id}/today`)">今天</Button>
            <Button size="small" @click="router.push(`/trip/${plan.plan_id}/footprints`)">足迹</Button>
            <Button size="small" @click="router.push(`/trip/${plan.plan_id}/journal`)">游记</Button>
          </div>
        </Card>
      </div>
    </Spin>
  </div>
</template>
