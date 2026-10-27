<!--
  AdminStatsPanel.vue：管理后台数据看板——统计卡、今日动态、7 天趋势与可视化四联
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { getAdminStats, type AdminStats } from '@/api/admin'

const stats = ref<AdminStats | null>(null)
const statsLoading = ref(true)

/** load：拉取数据看板 */
async function load() {
  statsLoading.value = true
  try {
    const res = await getAdminStats()
    if (res.success) stats.value = res.data
  } finally {
    statsLoading.value = false
  }
}

// 看板统计卡（全部并列等权，icon + 数字 + 标签 + 可选今日增量）
const statCards = computed(() => [
  { key: 'users', icon: '👥', label: '注册用户', value: stats.value?.users ?? '-', today: `今日 +${stats.value?.users_today ?? 0}`, cls: 'ad-s-blue' },
  { key: 'plans', icon: '🧭', label: '行程总数', value: stats.value?.plans ?? '-', today: '', cls: 'ad-s-teal' },
  { key: 'posts', icon: '💬', label: '社区帖子', value: stats.value?.posts ?? '-', today: `今日 +${stats.value?.posts_today ?? 0}`, cls: 'ad-s-violet' },
  { key: 'posts_circle', icon: '📸', label: '旅行圈', value: stats.value?.posts_circle ?? '-', today: '', cls: 'ad-s-sky' },
  { key: 'posts_note', icon: '📝', label: '笔记', value: stats.value?.posts_note ?? '-', today: '', cls: 'ad-s-fuchsia' },
  { key: 'journals', icon: '📔', label: '游记', value: stats.value?.journals ?? '-', today: '', cls: 'ad-s-amber' },
  { key: 'admins', icon: '🛡️', label: '管理员', value: stats.value?.admins ?? '-', today: '', cls: 'ad-s-rose' }
])

// composeBars：内容构成对比（行程/帖子/游记，按最大值归一化宽度）
const composeBars = computed(() => {
  if (!stats.value) return []
  const items = [
    { label: '行程计划', value: stats.value.plans, color: 'linear-gradient(90deg, #4facfe, #00f2fe)' },
    { label: '社区帖子', value: stats.value.posts, color: 'linear-gradient(90deg, #667eea, #764ba2)' },
    { label: '旅行游记', value: stats.value.journals, color: 'linear-gradient(90deg, #fa709a, #fee140)' }
  ]
  const max = Math.max(...items.map((i) => i.value), 1)
  return items.map((i) => ({ ...i, pct: Math.max(Math.round((i.value / max) * 100), 5) }))
})

// donut：帖子状态环形图（conic-gradient 纯 CSS 实现）
const donut = computed(() => {
  const p = stats.value?.posts_published ?? 0
  const h = stats.value?.posts_hidden ?? 0
  const total = p + h
  const pct = total ? (p / total) * 100 : 0
  return {
    conic: `conic-gradient(#22c55e 0turn ${(pct / 100).toFixed(3)}turn, #f87171 ${(pct / 100).toFixed(3)}turn 1turn)`,
    publishedPct: Math.round(pct),
    published: p,
    hidden: h,
    total
  }
})

// topUsers / topMax：活跃作者 TOP5
const topUsers = computed(() => stats.value?.top_users ?? [])
const topMax = computed(() => Math.max(...topUsers.value.map((u) => u.count), 1))

// todayCards：今日动态（渐变横条四项）
const todayCards = computed(() => [
  { icon: '👤', label: '今日新增用户', value: stats.value?.users_today ?? 0 },
  { icon: '📝', label: '今日新增帖子', value: stats.value?.posts_today ?? 0 },
  { icon: '🧭', label: '今日新增行程', value: stats.value?.plans_today ?? 0 },
  { icon: '📔', label: '今日新增游记', value: stats.value?.journals_today ?? 0 }
])

// trendBars：近 7 天趋势柱状图（用户/帖子双柱，按最大值归一化高度）
const trendMax = computed(() =>
  Math.max(1, ...(stats.value?.trends_7d ?? []).flatMap((t) => [t.users, t.posts]))
)
const trendBars = computed(() =>
  (stats.value?.trends_7d ?? []).map((t) => ({
    ...t,
    label: t.date.slice(5).replace('-', '/'),
    userPct: Math.max(Math.round((t.users / trendMax.value) * 100), t.users > 0 ? 6 : 2),
    postPct: Math.max(Math.round((t.posts / trendMax.value) * 100), t.posts > 0 ? 6 : 2)
  }))
)

// metricRows：运营指标（互动/社交/公开内容/支付）
const metricRows = computed(() => [
  {
    label: '累计点赞',
    value: stats.value?.like_total ?? 0,
    icon: '❤️',
    color: 'linear-gradient(90deg, #f43f5e, #fb923c)'
  },
  {
    label: '累计评论',
    value: stats.value?.comment_total ?? 0,
    icon: '💬',
    color: 'linear-gradient(90deg, #2e6b5e, #5aa287)'
  },
  {
    label: '好友关系',
    value: `${stats.value?.friend_pairs ?? 0} 对`,
    icon: '🤝',
    color: 'linear-gradient(90deg, #22c55e, #a3e635)'
  },
  {
    label: '待处理好友申请',
    value: `${stats.value?.pending_requests ?? 0} 条`,
    icon: '⏳',
    color: 'linear-gradient(90deg, #f59e0b, #fde047)'
  },
  {
    label: '公开游记',
    value: `${stats.value?.journals_public ?? 0} 篇`,
    icon: '🌍',
    color: 'linear-gradient(90deg, #8b5cf6, #ec4899)'
  },
  {
    label: '支付订单',
    value: `${stats.value?.orders_paid ?? 0} 单 / ¥${(stats.value?.revenue_paid ?? 0).toFixed(2)}`,
    icon: '💰',
    color: 'linear-gradient(90deg, #10b981, #34d399)'
  }
])

defineExpose({ load })
</script>

<template>
  <a-spin :spinning="statsLoading">
    <!-- 统计卡：全部并列等权 -->
    <div class="ad-cards">
      <div v-for="c in statCards" :key="c.key" class="ad-card" :class="c.cls">
        <span class="ad-card-icon">{{ c.icon }}</span>
        <b>{{ c.value }}</b>
        <span class="ad-card-label">{{ c.label }}</span>
      </div>
    </div>

    <!-- 今日动态横条 -->
    <div class="ad-today">
      <div v-for="t in todayCards" :key="t.label" class="ad-today-item">
        <span class="ad-today-icon">{{ t.icon }}</span>
        <div>
          <b>{{ t.value }}</b>
          <span>{{ t.label }}</span>
        </div>
      </div>
    </div>

    <!-- 近 7 天趋势柱状图 -->
    <div class="ad-viz-card ad-trend">
      <div class="ad-trend-head">
        <h4>📈 近 7 天新增趋势</h4>
        <div class="ad-legend-row">
          <span class="ad-legend-item"><i style="background: #2e6b5e" />新增用户</span>
          <span class="ad-legend-item"><i style="background: #a855f7" />新增帖子</span>
        </div>
      </div>
      <div class="ad-trend-chart">
        <div v-for="t in trendBars" :key="t.date" class="ad-trend-col">
          <div class="ad-trend-pair">
            <div class="ad-trend-bar" :style="{ height: t.userPct + '%', background: 'linear-gradient(180deg, #60a5fa, #2563eb)' }" :title="`用户 ${t.users}`" />
            <div class="ad-trend-bar" :style="{ height: t.postPct + '%', background: 'linear-gradient(180deg, #c084fc, #9333ea)' }" :title="`帖子 ${t.posts}`" />
          </div>
          <span class="ad-trend-nums">{{ t.users }}/{{ t.posts }}</span>
          <span class="ad-trend-date">{{ t.label }}</span>
        </div>
      </div>
    </div>

    <!-- 可视化四联 -->
    <div class="ad-viz">
      <!-- 内容构成对比 -->
      <div class="ad-viz-card">
        <h4>📊 内容构成对比</h4>
        <div class="ad-bar-row" v-for="b in composeBars" :key="b.label">
          <span class="ad-bar-label">{{ b.label }}</span>
          <div class="ad-bar-track">
            <div class="ad-bar-fill" :style="{ width: b.pct + '%', background: b.color }" />
          </div>
          <b class="ad-bar-val">{{ b.value }}</b>
        </div>
        <!-- 帖子分区细分：旅行圈 vs 笔记 -->
        <div class="ad-bar-row" style="margin-top: 18px;">
          <span class="ad-bar-label">分区细分</span>
          <div class="ad-bar-track ad-zone-track">
            <div class="ad-zone-seg" style="background: linear-gradient(90deg, #38bdf8, #0ea5e9)" :style="{ flex: stats?.posts_circle ?? 0 }" />
            <div class="ad-zone-seg" style="background: linear-gradient(90deg, #a78bfa, #7c3aed)" :style="{ flex: stats?.posts_note ?? 0 }" />
          </div>
          <b class="ad-bar-val">{{ stats?.posts ?? 0 }}</b>
        </div>
        <p class="ad-viz-tip">
          旅行圈 {{ stats?.posts_circle ?? 0 }} 篇 · 笔记 {{ stats?.posts_note ?? 0 }} 篇（行程/帖子/游记总量对比）
        </p>
      </div>

      <!-- 帖子状态环形 -->
      <div class="ad-viz-card ad-viz-center">
        <h4>🍩 帖子状态分布</h4>
        <div class="ad-donut" :style="{ background: donut.conic }">
          <div class="ad-donut-hole">
            <b>{{ donut.total }}</b>
            <span>总帖子</span>
          </div>
        </div>
        <div class="ad-legend">
          <span class="ad-legend-item"><i style="background: #22c55e" />已发布 {{ donut.published }}（{{ donut.publishedPct }}%）</span>
          <span class="ad-legend-item"><i style="background: #f87171" />已下架 {{ donut.hidden }}（{{ 100 - donut.publishedPct }}%）</span>
        </div>
      </div>

      <!-- 活跃作者 TOP5 -->
      <div class="ad-viz-card">
        <h4>🔥 活跃作者 TOP5</h4>
        <div class="ad-top-row" v-for="(u, i) in topUsers" :key="u.user_id">
          <span class="ad-top-rank" :class="{ top1: i === 0, top2: i === 1, top3: i === 2 }">{{ i + 1 }}</span>
          <span class="ad-top-name">{{ u.username }}</span>
          <div class="ad-top-track">
            <div class="ad-top-fill" :style="{ width: Math.max(Math.round((u.count / topMax) * 100), 8) + '%' }" />
          </div>
          <b class="ad-top-val">{{ u.count }}</b>
        </div>
        <p v-if="!topUsers.length" class="ad-viz-tip">还没有帖子数据</p>
      </div>

      <!-- 运营指标 -->
      <div class="ad-viz-card">
        <h4>🚀 运营指标</h4>
        <div class="ad-metric-row" v-for="m in metricRows" :key="m.label">
          <span class="ad-metric-icon">{{ m.icon }}</span>
          <span class="ad-metric-label">{{ m.label }}</span>
          <b class="ad-metric-val">{{ m.value }}</b>
          <div class="ad-metric-bar"><i :style="{ background: m.color }" /></div>
        </div>
      </div>
    </div>
  </a-spin>
</template>

<style scoped>
/* ===== 看板统计卡：并列等权浅色渐变 ===== */
.ad-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 14px;
  padding-top: 8px;
}
.ad-card {
  border-radius: 18px;
  padding: 20px 22px;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid rgba(30, 41, 59, 0.05);
  transition: transform 0.25s, box-shadow 0.25s;
}
.ad-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 26px rgba(30, 41, 59, 0.12);
}
.ad-card-icon {
  font-size: 22px;
  margin-bottom: 4px;
}
.ad-card b {
  font-size: 32px;
  line-height: 1.1;
  color: #1e293b;
}
.ad-card-label {
  color: #64748b;
  font-size: 13px;
}
.ad-card-today {
  position: absolute;
  right: 12px;
  top: 14px;
  font-size: 11px;
  color: #fff;
  background: rgba(30, 41, 59, 0.28);
  border-radius: 999px;
  padding: 2px 10px;
  backdrop-filter: blur(4px);
}
/* 七色浅渐变池（并列卡轮换，低饱和不刺眼） */
.ad-s-blue {
  background: linear-gradient(150deg, #eff6ff, #dbeafe);
}
.ad-s-teal {
  background: linear-gradient(150deg, #f0fdfa, #ccfbf1);
}
.ad-s-violet {
  background: linear-gradient(150deg, #f5f3ff, #ede9fe);
}
.ad-s-sky {
  background: linear-gradient(150deg, #f0f9ff, #e0f2fe);
}
.ad-s-fuchsia {
  background: linear-gradient(150deg, #fdf4ff, #fae8ff);
}
.ad-s-amber {
  background: linear-gradient(150deg, #fffbeb, #fef3c7);
}
.ad-s-rose {
  background: linear-gradient(150deg, #fff1f2, #ffe4e6);
}

/* ===== 可视化四联 ===== */
.ad-viz {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr 1.1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}
@media (max-width: 1100px) {
  .ad-viz {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 720px) {
  .ad-viz {
    grid-template-columns: 1fr;
  }
}

/* ===== 今日动态横条 ===== */
.ad-today {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  margin-top: 14px;
  border-radius: 18px;
  padding: 20px 10px;
  background: linear-gradient(120deg, #1e3a8a, #6d28d9 55%, #be185d);
  box-shadow: 0 8px 24px rgba(109, 40, 217, 0.25);
}
@media (max-width: 720px) {
  .ad-today {
    grid-template-columns: repeat(2, 1fr);
    gap: 16px 0;
  }
}
.ad-today-item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #fff;
}
.ad-today-item + .ad-today-item {
  border-left: 1px solid rgba(255, 255, 255, 0.18);
}
.ad-today-icon {
  font-size: 26px;
}
.ad-today-item b {
  display: block;
  font-size: 26px;
  line-height: 1.1;
}
.ad-today-item span {
  font-size: 12px;
  opacity: 0.82;
}

/* ===== 近 7 天趋势柱状图 ===== */
.ad-trend {
  margin-top: 14px;
}
.ad-trend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.ad-trend-head h4 {
  margin: 0;
  font-size: 15px;
  color: #1e293b;
}
.ad-legend-row {
  display: flex;
  gap: 14px;
}
.ad-trend-chart {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 10px;
  align-items: end;
}
.ad-trend-col {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.ad-trend-pair {
  height: 150px;
  display: flex;
  align-items: flex-end;
  gap: 5px;
}
.ad-trend-bar {
  width: 18px;
  min-height: 3px;
  border-radius: 6px 6px 2px 2px;
  transition: height 0.6s ease;
}
.ad-trend-nums {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #475569;
}
.ad-trend-date {
  font-size: 11px;
  color: #94a3b8;
}

/* ===== 运营指标 ===== */
.ad-metric-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  column-gap: 8px;
  padding: 8px 0;
  border-bottom: 1px dashed #f1f5f9;
}
.ad-metric-row:last-child {
  border-bottom: none;
}
.ad-metric-icon {
  font-size: 15px;
}
.ad-metric-label {
  color: #64748b;
  font-size: 13px;
  flex: 1;
}
.ad-metric-val {
  color: #1e293b;
  font-size: 13px;
}
.ad-metric-bar {
  width: 100%;
  height: 4px;
  background: #f1f5f9;
  border-radius: 999px;
  overflow: hidden;
}
.ad-metric-bar i {
  display: block;
  height: 100%;
  width: 100%;
  border-radius: 999px;
  opacity: 0.85;
}
.ad-viz-card {
  background: #fff;
  border-radius: 16px;
  padding: 20px 22px;
  box-shadow: 0 4px 18px rgba(30, 41, 59, 0.06);
}
.ad-viz-card h4 {
  margin: 0 0 16px;
  font-size: 15px;
  color: #1e293b;
}
.ad-viz-tip {
  margin: 14px 0 0;
  color: #cbd5e1;
  font-size: 12px;
}
.ad-viz-center {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.ad-viz-center h4 {
  align-self: flex-start;
}

/* 内容构成条形 */
.ad-bar-row {
  display: grid;
  grid-template-columns: 64px 1fr 40px;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.ad-bar-label {
  color: #475569;
  font-size: 13px;
}
.ad-bar-track {
  height: 14px;
  background: #f1f5f9;
  border-radius: 999px;
  overflow: hidden;
}
.ad-bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.6s ease;
}
.ad-bar-val {
  font-size: 14px;
  color: #1e293b;
  text-align: right;
}

/* 帖子分区分段条 */
.ad-zone-track {
  display: flex;
  gap: 3px;
  background: transparent;
}
.ad-zone-seg {
  height: 100%;
  border-radius: 999px;
  min-width: 4px;
  transition: flex 0.6s ease;
}

/* 帖子状态环形图 */
.ad-donut {
  width: 132px;
  height: 132px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 4px 0 12px;
}
.ad-donut-hole {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.ad-donut-hole b {
  font-size: 24px;
  color: #1e293b;
}
.ad-donut-hole span {
  font-size: 11px;
  color: #94a3b8;
}
.ad-legend {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ad-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #475569;
}
.ad-legend-item i {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
}

/* 活跃作者 TOP5 */
.ad-top-row {
  display: grid;
  grid-template-columns: 24px 90px 1fr 32px;
  align-items: center;
  gap: 10px;
  margin-bottom: 13px;
}
.ad-top-rank {
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ad-top-rank.top1 {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  color: #fff;
}
.ad-top-rank.top2 {
  background: linear-gradient(135deg, #94a3b8, #64748b);
  color: #fff;
}
.ad-top-rank.top3 {
  background: linear-gradient(135deg, #fdba74, #ea580c);
  color: #fff;
}
.ad-top-name {
  color: #334155;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-top-track {
  height: 10px;
  background: #f1f5f9;
  border-radius: 999px;
  overflow: hidden;
}
.ad-top-fill {
  height: 100%;
  background: linear-gradient(90deg, #fb923c, #f43f5e);
  border-radius: 999px;
  transition: width 0.6s ease;
}
.ad-top-val {
  font-size: 13px;
  color: #1e293b;
  text-align: right;
}
</style>
