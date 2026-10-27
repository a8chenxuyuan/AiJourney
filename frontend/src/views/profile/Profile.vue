<!--
  src/views/Profile.vue：个人中心页
  作用：展示当前登录用户信息、AI 偏好画像（雷达图 + 可编辑）、历史行程列表（真实数据）
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从 auth store 读取当前用户信息
 * 2. 渲染偏好画像卡片（PreferenceCard 组件，内部自取数据）
 * 3. 调用 getMyPlans 获取真实历史行程列表，点击卡片跳转结果页
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, computed, onMounted, onUnmounted } from 'vue'
// 引入 Vue Router（快捷入口跳转）
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Card, Spin, Tag, List, Button, message, Collapse, CollapsePanel, Input, Textarea } from 'ant-design-vue'
// 引入用户认证状态管理 store
import { useAuthStore } from '@/stores/auth'
// 引入社交 API（用户统计 + 我的发布列表）
import { getUserProfile, getUserPosts, type UserProfileData, type ProfilePostItem } from '@/api/social'
// 引入偏好画像卡片组件
import PreferenceCard from '@/components/PreferenceCard.vue'
// 引入历史行程 API 及类型
import { getMyPlans, type MyPlanSummary } from '@/api/trip'
// 引入知识库（RAG）与爬虫 API 及类型
import {
  uploadDocument,
  searchKnowledge,
  triggerCrawler,
  getCrawlerStatus,
  type RagSearchResult,
  type CrawlerJobStatus
} from '@/api/trip/knowledge'

// 获取用户认证状态管理 store
const authStore = useAuthStore()
const router = useRouter()

// profileStats：社交统计（发帖/游记/好友/收赞 + 注册时间），复用用户主页接口
const profileStats = ref<UserProfileData | null>(null)

// pfTab：当前激活的内容 Tab（历史行程/收藏/我的发布/偏好画像/知识库）
const pfTab = ref('plans')

// myPosts：我的发布列表；myZone：分区分段筛选（all/circle/note）
const myPosts = ref<ProfilePostItem[]>([])
const myZone = ref<'all' | 'circle' | 'note'>('all')
const myPostsLoading = ref(false)

// filteredMyPosts：按分区筛选后的我的发布
const filteredMyPosts = computed(() =>
  myZone.value === 'all' ? myPosts.value : myPosts.value.filter((p) => p.zone === myZone.value)
)

/**
 * fetchMyPosts：拉取本人全部发布（含被下架帖，列表里打「已下架」标签）
 */
const fetchMyPosts = async () => {
  if (!authStore.user?.id) return
  myPostsLoading.value = true
  try {
    const res = await getUserPosts(authStore.user.id, 1, 50)
    if (res.success) myPosts.value = res.data.items
  } catch {
    // 静默失败：发布列表非核心数据
  } finally {
    myPostsLoading.value = false
  }
}

/** goPost：跳转帖子详情 */
const goPost = (id: string) => router.push(`/community/${id}`)
// joinedAt：注册时间格式化为 YYYY-MM
const joinedAt = computed(() => {
  const t = profileStats.value?.created_at
  return t ? new Date(t).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' }) : ''
})

// plans：历史行程摘要列表（真实数据）
const plans = ref<MyPlanSummary[]>([])
// loading：列表加载状态
const loading = ref(false)
// loaded：是否已至少加载过一次（区分"加载中"与"确实没有数据"）
const loaded = ref(false)

/**
 * fetchPlans：拉取当前用户的历史行程列表
 */
const fetchPlans = async () => {
  loading.value = true
  try {
    const res = await getMyPlans()
    if (res.success && res.data?.plans) {
      plans.value = res.data.plans
    }
  } catch (error) {
    console.error('获取历史行程失败', error)
  } finally {
    loading.value = false
    loaded.value = true
  }
}

// 组件挂载时拉取历史行程、社交统计与我的发布
onMounted(async () => {
  fetchPlans()
  fetchMyPosts()
  if (authStore.user?.id) {
    try {
      const res = await getUserProfile(authStore.user.id)
      profileStats.value = res.data ?? null
    } catch {
      profileStats.value = null
    }
  }
})

/**
 * planStatus：行程状态的中文标签与颜色
 */
const planStatus = (status: string): { label: string; color: string } => {
  switch (status) {
    case 'completed':
      return { label: '已完成', color: 'green' }
    case 'planning':
      return { label: '规划中', color: 'blue' }
    case 'failed':
      return { label: '生成失败', color: 'red' }
    default:
      return { label: status, color: 'default' }
  }
}

// ==================== 知识库（RAG）：攻略上传与检索 ====================

// 攻略上传表单状态
const ragTitle = ref('')
const ragCity = ref('')
const ragContent = ref('')
const ragUploading = ref(false)
// 检索状态
const ragQuery = ref('')
const ragSearching = ref(false)
const ragResults = ref<RagSearchResult[]>([])

/**
 * handleUploadDoc：上传攻略文档到知识库
 */
const handleUploadDoc = async () => {
  if (!ragTitle.value.trim() || !ragContent.value.trim()) {
    message.warning('请填写攻略标题与正文')
    return
  }
  ragUploading.value = true
  try {
    const res = await uploadDocument({
      title: ragTitle.value.trim(),
      content: ragContent.value.trim(),
      city: ragCity.value.trim() || undefined
    })
    if (res.success) {
      message.success('攻略已入库，规划时会自动检索引用')
      ragTitle.value = ''
      ragCity.value = ''
      ragContent.value = ''
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    ragUploading.value = false
  }
}

/**
 * handleSearchKb：检索知识库
 */
const handleSearchKb = async () => {
  if (!ragQuery.value.trim()) {
    message.warning('请输入检索内容')
    return
  }
  ragSearching.value = true
  try {
    const res = await searchKnowledge({ query: ragQuery.value.trim(), top_k: 5 })
    if (res.success && res.data) {
      ragResults.value = res.data.results || []
      if (!ragResults.value.length) message.info('没有检索到相关攻略')
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    ragSearching.value = false
  }
}

// ==================== 爬虫抓取任务 ====================

// crawlerCities：用户输入的城市（逗号/空格分隔），为空则抓取默认热门城市
const crawlerCities = ref('')
const crawlerTriggering = ref(false)
// crawlerJob：最近一次任务的状态（含轮询结果）
const crawlerJob = ref<CrawlerJobStatus | null>(null)
// crawlerTimer：轮询定时器句柄
let crawlerTimer: number | null = null

/**
 * pollCrawler：轮询爬虫任务状态，直到完成
 * @param jobId 任务 ID
 */
const pollCrawler = (jobId: string) => {
  if (crawlerTimer) window.clearTimeout(crawlerTimer)
  crawlerTimer = window.setTimeout(async () => {
    try {
      const res = await getCrawlerStatus(jobId)
      if (res.success && res.data) {
        crawlerJob.value = res.data
        if (res.data.status === 'complete') {
          message.success(`抓取完成：新增 ${res.data.result?.documents_added ?? 0} 篇攻略文档`)
          return
        }
        if (res.data.status !== 'not_found') {
          pollCrawler(jobId)
          return
        }
      }
    } catch {
      // 查询失败时停止轮询，保留当前状态
    }
  }, 2000)
}

/**
 * handleTriggerCrawler：触发爬虫任务并入队
 */
const handleTriggerCrawler = async () => {
  crawlerTriggering.value = true
  try {
    const cities = crawlerCities.value.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
    const res = await triggerCrawler({ cities: cities.length ? cities : undefined })
    if (res.success && res.data) {
      message.success('爬虫任务已入队，由后台 Worker 执行')
      crawlerJob.value = { job_id: res.data.job_id, status: 'queued', result: null }
      pollCrawler(res.data.job_id)
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    crawlerTriggering.value = false
  }
}

// 组件卸载时清理轮询定时器
onUnmounted(() => {
  if (crawlerTimer) window.clearTimeout(crawlerTimer)
})
</script>

<template>
  <div class="page-fade pf-page">
    <!-- 资料头卡：渐变 banner + 头像 + 基本信息 + 统计 -->
    <section class="pf-hero">
      <span class="pf-avatar">{{ (authStore.user?.username || '旅').charAt(0).toUpperCase() }}</span>
      <div class="pf-id">
        <h2 class="pf-name">{{ authStore.user?.username || '未登录' }}</h2>
        <p class="pf-mail">{{ authStore.user?.email || '-' }}</p>
        <p class="pf-join">
          <template v-if="joinedAt">{{ joinedAt }} 加入 · </template>每一段旅程都值得被记录
        </p>
      </div>
      <div class="pf-stats">
        <div class="pf-stat"><b>{{ plans.length }}</b><span>历史行程</span></div>
        <div class="pf-stat"><b>{{ profileStats?.stats.posts_count ?? '—' }}</b><span>发帖</span></div>
        <div class="pf-stat"><b>{{ profileStats?.stats.journals_count ?? '—' }}</b><span>游记</span></div>
        <div class="pf-stat"><b>{{ profileStats?.stats.friends_count ?? '—' }}</b><span>好友</span></div>
        <div class="pf-stat"><b>{{ profileStats?.stats.likes_received ?? '—' }}</b><span>收到的赞</span></div>
      </div>
    </section>

    <!-- 内容 Tab：点击标签切换历史行程/收藏/我的发布/偏好画像 -->
    <a-tabs v-model:activeKey="pfTab" class="pf-tabs" size="large">
      <!-- Tab：历史行程 -->
      <a-tab-pane key="plans" tab="🧭 历史行程">
        <Card style="border-radius: 16px;">
          <Spin :spinning="loading">
            <div v-if="plans.length > 0" class="pf-plan-list">
              <div
                v-for="p in plans"
                :key="p.plan_id"
                class="pf-plan-item"
                @click="router.push(`/result/${p.plan_id}`)"
              >
                <div class="pf-plan-city">{{ (p.city || '旅').charAt(0) }}</div>
                <div class="pf-plan-info">
                  <p class="pf-plan-title">{{ p.city }}</p>
                  <p class="pf-plan-sub">{{ p.start_date }} 至 {{ p.end_date }}</p>
                  <div class="pf-plan-meta">
                    <Tag :color="planStatus(p.status).color">{{ planStatus(p.status).label }}</Tag>
                    <span>⏱ {{ p.travel_days }} 天</span>
                    <span v-if="p.budget_total != null">💰 预算 {{ p.budget_total }} 元</span>
                  </div>
                </div>
                <span class="pf-plan-go">查看行程 →</span>
              </div>
            </div>
            <div v-else-if="loaded && !loading" class="pf-empty">
              <span class="pf-empty-ico">🧭</span>
              <p>还没有行程记录</p>
              <Button @click="router.push('/')">去首页发起旅行规划</Button>
            </div>
          </Spin>
        </Card>
      </a-tab-pane>

      <!-- Tab：我的发布 -->
      <a-tab-pane key="posts" tab="📝 我的发布">
        <Card style="border-radius: 16px;">
          <div class="pf-mine-head">
            <a-segmented
              v-model:value="myZone"
              :options="[
                { label: `全部 ${myPosts.length}`, value: 'all' },
                { label: `旅行圈 ${myPosts.filter((p) => p.zone === 'circle').length}`, value: 'circle' },
                { label: `笔记 ${myPosts.filter((p) => p.zone === 'note').length}`, value: 'note' }
              ]"
            />
            <span class="pf-mine-tip">共收到 {{ profileStats?.stats.likes_received ?? 0 }} 个赞</span>
          </div>
          <Spin :spinning="myPostsLoading">
            <div v-if="filteredMyPosts.length > 0" class="pf-mine-list">
              <div v-for="p in filteredMyPosts" :key="p.id" class="pf-mine-item" @click="goPost(p.id)">
                <img v-if="p.cover_url" :src="p.cover_url" class="pf-mine-cover" alt="" />
                <div v-else class="pf-mine-cover pf-mine-cover-ph">🖼️</div>
                <div class="pf-mine-info">
                  <p class="pf-mine-title">{{ p.title || '未命名发布' }}</p>
                  <p class="pf-mine-sub">{{ p.summary || '暂无摘要' }}</p>
                  <div class="pf-mine-meta">
                    <Tag :color="p.zone === 'circle' ? 'blue' : 'purple'">
                      {{ p.zone === 'circle' ? '旅行圈' : '笔记' }}
                    </Tag>
                    <Tag v-if="p.status === 'hidden'" color="red">已下架</Tag>
                    <span>❤️ {{ p.like_count }}</span>
                    <span>💬 {{ p.comment_count }}</span>
                    <span class="pf-mine-time">{{ p.created_at ? p.created_at.slice(0, 10) : '' }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else-if="!myPostsLoading" class="pf-empty">
              <span class="pf-empty-ico">📷</span>
              <p>还没有发布过内容</p>
              <Button @click="router.push('/circle')">去旅行圈晒一晒</Button>
            </div>
          </Spin>
        </Card>
      </a-tab-pane>

      <!-- Tab：偏好画像 -->
      <a-tab-pane key="pref" tab="✨ 偏好画像">
        <PreferenceCard :user-id="authStore.user?.id" />
      </a-tab-pane>

      <!-- Tab：知识库管理（攻略上传/检索 + 爬虫任务） -->
      <a-tab-pane key="kb" tab="📚 知识库">
        <Card style="border-radius: 12px;">
          <Collapse>
        <!-- 攻略上传与检索 -->
        <CollapsePanel key="rag" header="攻略上传与检索（喂给 AI 的旅行知识）">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
            <!-- 上传 -->
            <div>
              <p style="font-weight: 600; margin-bottom: 8px;">上传攻略文档</p>
              <Input v-model:value="ragTitle" placeholder="攻略标题，如：成都 3 日美食攻略" style="margin-bottom: 8px;" />
              <Input v-model:value="ragCity" placeholder="所属城市（可选，如：成都）" style="margin-bottom: 8px;" />
              <Textarea v-model:value="ragContent" placeholder="攻略正文内容…" :rows="4" style="margin-bottom: 8px;" />
              <Button type="primary" :loading="ragUploading" @click="handleUploadDoc">上传入库</Button>
            </div>
            <!-- 检索 -->
            <div>
              <p style="font-weight: 600; margin-bottom: 8px;">检索测试</p>
              <Input.Search
                v-model:value="ragQuery"
                placeholder="输入问题，如：成都有哪些必吃火锅"
                enter-button="检索"
                :loading="ragSearching"
                @search="handleSearchKb"
              />
              <List v-if="ragResults.length" :data-source="ragResults" size="small" style="margin-top: 12px;">
                <template #renderItem="{ item }">
                  <List.Item>
                    <List.Item.Meta :title="item.title || item.city || '攻略片段'" :description="String(item.content || '').slice(0, 80)" />
                  </List.Item>
                </template>
              </List>
            </div>
          </div>
        </CollapsePanel>
        <!-- 爬虫任务 -->
        <CollapsePanel key="crawler" header="爬虫抓取任务（自动抓取城市攻略入库）">
          <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
            <Input
              v-model:value="crawlerCities"
              placeholder="目标城市，逗号分隔；留空抓取默认热门城市"
              style="flex: 1; min-width: 260px;"
            />
            <Button type="primary" :loading="crawlerTriggering" @click="handleTriggerCrawler">触发抓取</Button>
          </div>
          <p v-if="crawlerJob" style="margin: 12px 0 0; color: #666; font-size: 13px;">
            任务 {{ crawlerJob.job_id.slice(0, 12) }}…：
            <Tag :color="crawlerJob.status === 'complete' ? 'green' : crawlerJob.status === 'not_found' ? 'red' : 'blue'">
              {{ crawlerJob.status }}
            </Tag>
            <span v-if="crawlerJob.status === 'complete' && crawlerJob.result">
              新增 {{ crawlerJob.result.documents_added }} 篇文档（{{ crawlerJob.result.cities?.join('、') }}）
            </span>
          </p>
        </CollapsePanel>
      </Collapse>
        </Card>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<style scoped>
/* ===== 页面骨架 ===== */
.pf-page {
  max-width: 1900px;
  margin: 0 auto;
  padding: 20px 16px 48px;
}

/* ===== 内容 Tabs ===== */
.pf-tabs {
  margin-top: 18px;
}
.pf-tabs :deep(.ant-tabs-tab) {
  font-size: 15px;
  padding-top: 14px;
  padding-bottom: 14px;
}

/* ===== 资料头卡：柔和多色渐变 banner ===== */
.pf-hero {
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 30px 34px;
  border-radius: 20px;
  background:
    radial-gradient(circle at 85% 20%, rgba(255, 255, 255, 0.55) 0%, transparent 45%),
    linear-gradient(120deg, #e0f2fe 0%, #fce7f3 55%, #ede9fe 100%);
  box-shadow: 0 4px 24px rgba(30, 41, 59, 0.07);
  flex-wrap: wrap;
}
.pf-avatar {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  color: #fff;
  font-size: 32px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 18px rgba(124, 108, 245, 0.35);
  flex-shrink: 0;
}
.pf-id {
  flex: 1;
  min-width: 200px;
}
.pf-name {
  margin: 0 0 4px;
  font-size: 24px;
  color: #1e293b;
}
.pf-mail {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 14px;
}
.pf-join {
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
}
/* 统计条：半透明白底玻璃卡 */
.pf-stats {
  display: flex;
  gap: 8px;
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(6px);
  border-radius: 16px;
  padding: 14px 20px;
}
.pf-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 68px;
  gap: 2px;
}
.pf-stat + .pf-stat {
  border-left: 1px solid #eef2f7;
  padding-left: 8px;
  min-width: 76px;
}
.pf-stat b {
  font-size: 20px;
  color: #1e293b;
}
.pf-stat span {
  font-size: 12px;
  color: #94a3b8;
}

/* ===== 区块标题 ===== */
.pf-title {
  margin: 20px 0 12px;
  font-size: 16px;
  color: #1e293b;
}

/* ===== 收藏/行程双栏 ===== */
.pf-two {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 20px;
  align-items: start;
}
@media (max-width: 900px) {
  .pf-two {
    grid-template-columns: 1fr;
  }
}

/* ===== 美化空态 ===== */
.pf-empty {
  text-align: center;
  padding: 32px 0;
}
.pf-empty-ico {
  font-size: 42px;
  display: block;
  margin-bottom: 8px;
}
.pf-empty p {
  color: #94a3b8;
  font-size: 14px;
  margin: 0 0 14px;
}
/* 历史行程 */
.pf-plan-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  /* 固定高度框：行程多时框内滚动，页面不再被拉长 */
  max-height: 520px;
  overflow-y: auto;
  padding-right: 8px;
}
.pf-plan-list::-webkit-scrollbar {
  width: 6px;
}
.pf-plan-list::-webkit-scrollbar-thumb {
  background: #dbe3ec;
  border-radius: 999px;
}
.pf-plan-list::-webkit-scrollbar-thumb:hover {
  background: #c3cddd;
}
.pf-plan-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid #f1f5f9;
  cursor: pointer;
  transition: box-shadow 0.25s, transform 0.25s, border-color 0.25s;
}
.pf-plan-item:hover {
  border-color: #bfdbfe;
  box-shadow: 0 6px 18px rgba(46, 107, 94, 0.12);
  transform: translateY(-2px);
}
.pf-plan-city {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  background: var(--grad-primary);
  color: #fff;
  font-weight: 700;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 10px rgba(46, 107, 94, 0.25);
}
.pf-plan-info {
  min-width: 0;
  flex: 1;
}
.pf-plan-title {
  margin: 0 0 2px;
  font-weight: 600;
  color: #1e293b;
}
.pf-plan-sub {
  margin: 0 0 6px;
  color: #94a3b8;
  font-size: 12px;
}
.pf-plan-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font-size: 12px;
}
.pf-plan-go {
  color: var(--brand);
  font-size: 12px;
  flex-shrink: 0;
}

/* 我的发布 */
.pf-mine-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.pf-mine-tip {
  color: #94a3b8;
  font-size: 13px;
}
.pf-mine-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  /* 固定高度框：内容多时框内滚动，页面不再被拉长 */
  max-height: 520px;
  overflow-y: auto;
  padding-right: 8px;
}
.pf-mine-list::-webkit-scrollbar {
  width: 6px;
}
.pf-mine-list::-webkit-scrollbar-thumb {
  background: #dbe3ec;
  border-radius: 999px;
}
.pf-mine-list::-webkit-scrollbar-thumb:hover {
  background: #c3cddd;
}
.pf-mine-item {
  display: flex;
  gap: 14px;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid #f1f5f9;
  cursor: pointer;
  transition: box-shadow 0.25s, transform 0.25s, border-color 0.25s;
}
.pf-mine-item:hover {
  border-color: #bfdbfe;
  box-shadow: 0 6px 18px rgba(46, 107, 94, 0.12);
  transform: translateY(-2px);
}
.pf-mine-cover {
  width: 84px;
  height: 64px;
  border-radius: 10px;
  object-fit: cover;
  flex-shrink: 0;
}
.pf-mine-cover-ph {
  background: linear-gradient(135deg, #e0f2fe, #ede9fe);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}
.pf-mine-info {
  min-width: 0;
  flex: 1;
}
.pf-mine-title {
  margin: 0 0 2px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pf-mine-sub {
  margin: 0 0 6px;
  color: #94a3b8;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pf-mine-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font-size: 12px;
}
.pf-mine-time {
  margin-left: auto;
  color: #cbd5e1;
}
</style>
