<!--
  src/views/JournalShare.vue：公开游记分享页（免登录可看）
  作用：按 token 展示公开游记全文与原行程概要；
       「复刻这条线路」一键把原行程复制到自己账户（未登录先去登录）。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 按路由 token 加载公开游记（后端校验 is_public，无效 token 404）；
 * 2. 展示作者、行程概要、分节图文；
 * 3. 复刻：已登录直接 forkSharedJournal → 跳新行程结果页；未登录跳登录页。
 */
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Button, Card, Empty, Spin, Tag, message } from 'ant-design-vue'
import { getSharedJournal, forkSharedJournal, type SharedJournalData } from '@/api/community/guides'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loading = ref(true)
const notFound = ref(false)
const journal = ref<SharedJournalData | null>(null)

// forking：复刻按钮防重复点击
const forking = ref(false)

/**
 * fetchJournal：按 token 加载公开游记
 */
const fetchJournal = async () => {
  loading.value = true
  notFound.value = false
  try {
    const res = await getSharedJournal(String(route.params.token || ''))
    if (res.success && res.data) {
      journal.value = res.data
    } else {
      notFound.value = true
    }
  } catch {
    notFound.value = true
  } finally {
    loading.value = false
  }
}

/**
 * forkTrip：复刻这条线路 → 原行程复制到我的账户
 */
const forkTrip = async () => {
  if (!authStore.isAuthenticated) {
    message.info('登录后即可复刻这条线路')
    router.push('/login')
    return
  }
  forking.value = true
  try {
    const res = await forkSharedJournal(String(route.params.token || ''))
    if (res.success && res.data) {
      message.success('线路已复刻到我的账户')
      router.push(`/result/${res.data.plan_id}`)
    }
  } finally {
    forking.value = false
  }
}

onMounted(fetchJournal)
</script>

<template>
  <div class="page-fade" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
    <Spin :spinning="loading">
      <!-- 无效/取消公开的 token -->
      <Empty v-if="!loading && notFound" description="游记不存在或未公开">
        <Button type="primary" @click="router.push('/guides')">去逛攻略灵感</Button>
      </Empty>

      <template v-else-if="journal">
        <!-- 标题区 -->
        <div style="text-align: center; margin: 28px 0 20px;">
          <h1 style="font-size: 28px; margin: 0 0 12px;">{{ journal.title || '旅行游记' }}</h1>
          <div style="display: flex; justify-content: center; gap: 10px; align-items: center; color: #888; font-size: 14px; flex-wrap: wrap;">
            <Tag color="orange">真实游记</Tag>
            <span>✍️ {{ journal.author }}</span>
            <template v-if="journal.plan">
              <span>📍 {{ journal.plan.city }}</span>
              <span>· {{ journal.plan.travel_days }} 天</span>
              <span>（{{ journal.plan.start_date }} ~ {{ journal.plan.end_date }}）</span>
            </template>
          </div>
        </div>

        <!-- 分节图文 -->
        <Card
          v-for="(sec, idx) in journal.sections"
          :key="idx"
          style="border-radius: 14px; margin-bottom: 16px;"
        >
          <template #title>
            <span style="font-size: 16px;">
              {{ sec.day_index ? `第 ${sec.day_index} 天 · ` : '' }}{{ sec.title }}
            </span>
          </template>
          <p style="white-space: pre-wrap; line-height: 2; font-size: 15px; color: #333; margin: 0;">{{ sec.text }}</p>
          <div v-if="sec.photos?.length" style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap;">
            <img
              v-for="(p, pi) in sec.photos"
              :key="pi"
              :src="p"
              style="width: 160px; height: 112px; object-fit: cover; border-radius: 8px;"
            />
          </div>
        </Card>

        <!-- 转化区：复刻线路 -->
        <div class="share-cta">
          <p style="font-size: 17px; font-weight: 600; margin: 0 0 6px; color: #fff;">
            想走同款线路？
          </p>
          <p style="color: rgba(255,255,255,0.85); font-size: 13px; margin: 0 0 16px;">
            一键复制这条线路到你的账户，日期自动顺延，可再按偏好调整
          </p>
          <Button size="large" style="height: 46px; padding: 0 32px; border-radius: 999px; font-weight: 600;"
                  :loading="forking"
                  @click="forkTrip">
            🧭 复刻这条线路
          </Button>
        </div>
      </template>
    </Spin>
  </div>
</template>

<style scoped>
/* 底部转化横幅：品牌渐变，突出复刻动作 */
.share-cta {
  text-align: center;
  padding: 30px 20px;
  border-radius: 16px;
  background: var(--grad-primary);
  margin-bottom: 36px;
}
</style>
