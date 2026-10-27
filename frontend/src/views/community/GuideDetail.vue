<!--
  src/views/GuideDetail.vue：攻略详情页
  作用：展示攻略正文与同城相关攻略；核心转化入口为
       「照着走」——AI 把攻略复刻为我的行程（无原行程可拷，走 LLM 生成），
       或携带城市跳首页重新规划。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 按路由参数加载攻略详情；
 * 2. 正文按空行/换行拆段渲染；
 * 3. 「照着走」调用 replicate 接口（LLM 单次生成，10-20s），成功跳结果页；
 * 4. 相关攻略与「重新规划」按钮提供跳转出口。
 */
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Button, Card, Empty, Spin, Tag, message } from 'ant-design-vue'
import { getGuideDetail, replicateGuide, type GuideDetailData } from '@/api/community/guides'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
// prevPath：上一页路径（有历史就原路返回，无历史回落攻略灵感列表）
const prevPath = window.history.state?.back as string | null
const route = useRoute()
const authStore = useAuthStore()

const loading = ref(true)
const guide = ref<GuideDetailData | null>(null)

// 照着走：出发日期（默认一周后）与生成中状态
const replicateDate = ref(new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10))
const replicating = ref(false)

/**
 * fetchGuide：加载攻略详情（含相关推荐）
 */
const fetchGuide = async () => {
  loading.value = true
  try {
    const res = await getGuideDetail(Number(route.params.id))
    if (res.success && res.data) {
      guide.value = res.data
    }
  } finally {
    loading.value = false
  }
}

/**
 * paragraphs：正文拆段渲染（兼容 \n\n 与单 \n）
 */
const paragraphs = () =>
  (guide.value?.content || '')
    .split(/\n+/)
    .map((p) => p.trim())
    .filter(Boolean)

/**
 * planSameTrip：用 AI 重新规划同款行程 → 首页带城市预填
 */
const planSameTrip = () => {
  if (guide.value?.city) {
    router.push({ path: '/', query: { city: guide.value.city } })
  } else {
    router.push('/')
  }
}

/**
 * handleReplicate：照着走——AI 把攻略复刻为我的行程
 * 未登录先去登录；生成约 10-20s，成功后直接跳新行程结果页
 */
const handleReplicate = async () => {
  if (!guide.value) return
  if (!authStore.user) {
    message.info('登录后即可照着走')
    router.push('/login')
    return
  }
  replicating.value = true
  try {
    const res = await replicateGuide(String(guide.value.id), { start_date: replicateDate.value })
    if (res.success && res.data) {
      message.success(`已复刻「${res.data.city}」${res.data.travel_days} 天行程`)
      router.push(`/result/${res.data.plan_id}`)
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    replicating.value = false
  }
}

onMounted(fetchGuide)
</script>

<template>
  <div class="page-fade" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
    <Spin :spinning="loading">
      <Empty v-if="!loading && !guide" description="攻略不存在">
        <Button type="primary" @click="router.push('/guides')">返回攻略灵感</Button>
      </Empty>

      <template v-else-if="guide">
        <!-- 页头：返回 + 城市 -->
        <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0 16px;">
          <Button @click="prevPath ? router.back() : router.push('/guides')">← {{ prevPath ? '返回' : '攻略灵感' }}</Button>
          <Tag v-if="guide.city" color="blue" style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
               @click="router.push(`/destination/${guide.city}`)">
            📍 {{ guide.city }} · 目的地页
          </Tag>
        </div>

        <!-- 标题区 -->
        <div style="margin-bottom: 20px;">
          <h1 style="font-size: 26px; margin: 0 0 10px;">{{ guide.title }}</h1>
          <div style="display: flex; gap: 12px; color: #999; font-size: 13px; align-items: center;">
            <Tag>{{ guide.source === 'crawler' ? '爬虫采集' : '人工整理' }}</Tag>
            <span v-if="guide.crawled_at">收录时间 {{ guide.crawled_at.replace('T', ' ').slice(0, 10) }}</span>
          </div>
        </div>

        <!-- 正文 -->
        <Card style="border-radius: 14px;">
          <p
            v-for="(p, idx) in paragraphs()"
            :key="idx"
            style="line-height: 2; font-size: 15px; color: #333; margin: 0 0 14px;"
          >{{ p }}</p>
        </Card>

        <!-- 核心转化：照着走（AI 复刻成我的行程） -->
        <Card style="border-radius: 14px; margin: 28px 0; background: linear-gradient(135deg, rgba(46, 107, 94, 0.07), rgba(255, 255, 255, 0) 70%);">
          <div style="text-align: center;">
            <h2 style="margin: 0 0 6px; font-size: 20px;">🧳 照着走 · 复刻成我的行程</h2>
            <p style="color: var(--ink-3); font-size: 13px; margin: 0 0 16px;">
              AI 将把这篇攻略转成你的行程：每日景点、美食、住宿与预算，生成后可随时调整
            </p>
            <div style="display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap;">
              <input
                v-model="replicateDate"
                type="date"
                style="height: 44px; border: 1px solid rgba(14, 34, 57, 0.18); border-radius: 999px; padding: 0 16px; font-size: 14px; background: #fff; color: var(--ink);"
              />
              <Button
                type="primary"
                size="large"
                style="height: 44px; padding: 0 30px; border-radius: 999px; font-size: 15px;"
                :loading="replicating"
                @click="handleReplicate"
              >
                {{ replicating ? 'AI 正在生成行程…' : '开始复刻' }}
              </Button>
            </div>
            <p style="margin: 14px 0 0;">
              <a style="color: var(--brand); font-size: 13px; cursor: pointer;" @click="planSameTrip">
                或用 AI 重新规划同款行程 →
              </a>
            </p>
          </div>
        </Card>

        <!-- 相关攻略 -->
        <Card v-if="guide.related.length" style="border-radius: 14px; margin-bottom: 32px;">
          <template #title>同城相关攻略</template>
          <div
            v-for="rel in guide.related"
            :key="rel.id"
            style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f0f0f0; cursor: pointer;"
            @click="router.push(`/guides/${rel.id}`)"
          >
            <span style="font-size: 15px;">📄 {{ rel.title }}</span>
            <span style="color: var(--brand); font-size: 13px;">查看 →</span>
          </div>
        </Card>
      </template>
    </Spin>
  </div>
</template>
