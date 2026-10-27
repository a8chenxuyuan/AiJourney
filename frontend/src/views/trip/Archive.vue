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
import { Button, Tag, Spin, message } from 'ant-design-vue'
// 引入档案 API 与类型
import { getArchive, type ArchiveData } from '@/api/trip/companion'

const router = useRouter()
// prevPath：上一页路径（有历史原路返回，无历史兜底回个人中心）
const prevPath = window.history.state?.back as string | null

// archive：档案数据；loading：加载状态
const archive = ref<ArchiveData | null>(null)
const loading = ref(true)

// cityGradients：城市徽章渐变色池（按索引循环取色）
const cityGradients = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)'
]

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
  <div class="page-fade ar-page">
    <!-- 顶部返回：原路返回上一页，无历史时兜底回个人中心 -->
    <div class="ar-topbar">
      <button class="ar-back" @click="prevPath ? router.back() : router.push('/profile')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        {{ prevPath ? '返回' : '返回个人中心' }}
      </button>
    </div>

    <Spin :spinning="loading">
      <template v-if="archive">
        <!-- Hero：暮色渐变 banner + 大标题 + 玻璃统计卡 -->
        <section class="ar-hero">
          <div class="ar-hero-text">
            <h2>我的旅行档案</h2>
            <p>每一段旅程都值得被珍藏 · {{ tripSpan }}</p>
          </div>
          <div class="ar-hero-stats">
            <div class="ar-hstat"><b>{{ archive.stats.city_count }}</b><span>去过城市</span></div>
            <div class="ar-hstat"><b>{{ archive.stats.plan_count }}</b><span>旅行次数</span></div>
            <div class="ar-hstat"><b>{{ archive.stats.checkin_total }}</b><span>打卡记录</span></div>
            <div class="ar-hstat"><b>{{ archive.stats.photo_total }}</b><span>照片</span></div>
            <div class="ar-hstat"><b>{{ archive.stats.post_total ?? 0 }}</b><span>旅行圈发布</span></div>
          </div>
        </section>

        <!-- 城市徽章墙 -->
        <section v-if="archive.stats.cities.length" class="ar-block">
          <h3 class="ar-title">🌍 我的足迹版图</h3>
          <div class="ar-cities">
            <div
              v-for="(city, i) in archive.stats.cities"
              :key="city"
              class="ar-city"
              :style="{ background: cityGradients[i % cityGradients.length] }"
            >
              <span class="ar-city-ico">✈️</span>
              <span class="ar-city-name">{{ city }}</span>
            </div>
          </div>
        </section>

        <!-- 旅行时间线 -->
        <section v-if="archive.plans.length" class="ar-block">
          <h3 class="ar-title">🕘 旅行时间线</h3>
          <div class="ar-timeline">
            <div v-for="plan in archive.plans" :key="plan.plan_id" class="ar-tl-item">
              <span class="ar-dot" />
              <div class="ar-tl-card">
                <div class="ar-tl-head">
                  <h4>{{ citiesText(plan) }}</h4>
                  <Tag :color="statusTag(plan.status).color">{{ statusTag(plan.status).text }}</Tag>
                </div>
                <p class="ar-tl-meta">
                  <span>🗓 {{ plan.start_date }} ~ {{ plan.end_date }}（{{ plan.travel_days }} 天）</span>
                  <span class="ar-sep">·</span>
                  <span>👣 {{ plan.checkin_count }} 次打卡</span>
                  <template v-if="plan.budget_total">
                    <span class="ar-sep">·</span>
                    <span>💰 预算 ¥{{ plan.budget_total }}</span>
                  </template>
                </p>
                <div class="ar-tl-actions">
                  <Button size="small" type="primary" @click="router.push(`/result/${plan.plan_id}`)">行程</Button>
                  <Button size="small" @click="router.push(`/trip/${plan.plan_id}/today`)">今天</Button>
                  <Button size="small" @click="router.push(`/trip/${plan.plan_id}/footprints`)">足迹</Button>
                  <Button size="small" @click="router.push(`/trip/${plan.plan_id}/journal`)">游记</Button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 空态 -->
        <div v-if="!archive.plans.length && !archive.stats.cities.length" class="ar-empty">
          <span class="ar-empty-ico">🧳</span>
          <p>还没有旅行记录</p>
          <Button type="primary" size="large" @click="router.push('/')">去规划第一次旅行</Button>
        </div>
      </template>
    </Spin>
  </div>
</template>

<style scoped>
/* ===== 页面骨架 ===== */
.ar-page {
  max-width: 1900px;
  margin: 0 auto;
  padding: 0 16px 48px;
}
.ar-topbar {
  display: flex;
  justify-content: flex-end;
  margin: 20px 0 12px;
}
.ar-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 14px;
  padding: 8px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s;
}
.ar-back:hover {
  background: #fff;
  color: var(--brand);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

/* ===== Hero：夜空→日落暖色渐变 banner ===== */
.ar-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  padding: 44px 40px;
  border-radius: 24px;
  background:
    radial-gradient(circle at 86% 80%, rgba(255, 196, 112, 0.4) 0%, transparent 46%),
    radial-gradient(circle at 14% 12%, rgba(255, 255, 255, 0.14) 0%, transparent 40%),
    linear-gradient(115deg, #141a3d 0%, #33306b 38%, #8a4a7d 70%, #e8815a 100%);
  color: #fff;
  box-shadow: 0 12px 36px rgba(51, 48, 107, 0.35);
}
.ar-hero-text h2 {
  margin: 0 0 8px;
  font-size: 32px;
  letter-spacing: 1px;
  color: #fff;
}
.ar-hero-text p {
  margin: 0;
  color: rgba(255, 255, 255, 0.88);
  font-size: 15px;
}
/* 玻璃统计卡 */
.ar-hero-stats {
  display: flex;
  gap: 6px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 18px;
  padding: 18px 22px;
}
.ar-hstat {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 76px;
  gap: 3px;
}
.ar-hstat + .ar-hstat {
  border-left: 1px solid rgba(255, 255, 255, 0.16);
  padding-left: 6px;
}
.ar-hstat b {
  font-size: 26px;
}
.ar-hstat span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

/* ===== 区块标题 ===== */
.ar-block {
  margin-top: 32px;
}
.ar-title {
  margin: 0 0 16px;
  font-size: 18px;
  color: #1e293b;
}

/* ===== 城市徽章墙 ===== */
.ar-cities {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
}
.ar-city {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 22px;
  border-radius: 16px;
  color: #fff;
  box-shadow: 0 6px 18px rgba(30, 41, 59, 0.15);
  transition: transform 0.2s;
  cursor: default;
}
.ar-city:hover {
  transform: translateY(-3px);
}
.ar-city-ico {
  font-size: 24px;
}
.ar-city-name {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
}

/* ===== 旅行时间线 ===== */
.ar-timeline {
  position: relative;
  padding-left: 26px;
}
/* 竖线 */
.ar-timeline::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: linear-gradient(#c7d2fe, #ddd6fe);
  border-radius: 2px;
}
.ar-tl-item {
  position: relative;
  margin-bottom: 18px;
}
/* 节点圆点 */
.ar-dot {
  position: absolute;
  left: -26px;
  top: 26px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #6366f1;
  box-shadow: 0 0 0 4px #e0e7ff;
}
.ar-tl-card {
  background: #fff;
  border-radius: 18px;
  padding: 22px 28px;
  box-shadow: 0 4px 20px rgba(30, 41, 59, 0.07);
  transition: transform 0.2s, box-shadow 0.2s;
}
.ar-tl-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(30, 41, 59, 0.12);
}
.ar-tl-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.ar-tl-head h4 {
  margin: 0;
  font-size: 20px;
  color: #1e293b;
}
.ar-tl-meta {
  margin: 10px 0 14px;
  color: #64748b;
  font-size: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.ar-sep {
  color: #cbd5e1;
}
.ar-tl-actions {
  display: flex;
  gap: 8px;
}

/* ===== 空态 ===== */
.ar-empty {
  text-align: center;
  padding: 72px 0 40px;
}
.ar-empty-ico {
  font-size: 56px;
  display: block;
  margin-bottom: 12px;
}
.ar-empty p {
  color: #94a3b8;
  font-size: 15px;
  margin: 0 0 20px;
}

/* ===== 小屏适配 ===== */
@media (max-width: 640px) {
  .ar-hero {
    padding: 30px 24px;
  }
  .ar-hero-text h2 {
    font-size: 24px;
  }
  .ar-hero-stats {
    width: 100%;
    justify-content: space-between;
  }
  .ar-hstat {
    min-width: 0;
    flex: 1;
  }
}
</style>
