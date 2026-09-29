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
import { ref, onMounted, onUnmounted } from 'vue'
// 引入 Ant Design Vue 组件
import { Card, Empty, Spin, Tag, List, Button, message, Collapse, CollapsePanel, Input, Textarea } from 'ant-design-vue'
// 引入用户认证状态管理 store
import { useAuthStore } from '@/stores/auth'
// 引入行程卡片组件
import PlanCard from '@/components/PlanCard.vue'
// 引入偏好画像卡片组件
import PreferenceCard from '@/components/PreferenceCard.vue'
// 引入历史行程与收藏 API 及类型
import { getMyPlans, getFavorites, removeFavorite, type MyPlanSummary, type FavoriteRecord } from '@/api/trip'
// 引入知识库（RAG）与爬虫 API 及类型
import {
  uploadDocument,
  searchKnowledge,
  triggerCrawler,
  getCrawlerStatus,
  type RagSearchResult,
  type CrawlerJobStatus
} from '@/api/knowledge'

// 获取用户认证状态管理 store
const authStore = useAuthStore()

// plans：历史行程摘要列表（真实数据）
const plans = ref<MyPlanSummary[]>([])
// loading：列表加载状态
const loading = ref(false)
// loaded：是否已至少加载过一次（区分"加载中"与"确实没有数据"）
const loaded = ref(false)

// favorites：我的收藏记录列表
const favorites = ref<FavoriteRecord[]>([])
// favLoading：收藏列表加载状态
const favLoading = ref(false)

/**
 * itemTypeLabel：收藏类型的中文标签与颜色
 */
const itemTypeLabel = (t: string): { label: string; color: string } => {
  switch (t) {
    case 'attraction':
      return { label: '景点', color: 'blue' }
    case 'hotel':
      return { label: '酒店', color: 'purple' }
    case 'restaurant':
      return { label: '餐厅', color: 'orange' }
    default:
      return { label: t, color: 'default' }
  }
}

/**
 * fetchFavorites：拉取当前用户的收藏列表
 */
const fetchFavorites = async () => {
  favLoading.value = true
  try {
    const res = await getFavorites()
    if (res.success && res.data) {
      favorites.value = res.data.favorites
    }
  } catch (error) {
    console.error('获取收藏列表失败', error)
  } finally {
    favLoading.value = false
  }
}

/**
 * handleRemoveFavorite：取消收藏
 * @param record 被取消的收藏记录
 */
const handleRemoveFavorite = async (record: FavoriteRecord) => {
  try {
    await removeFavorite(record.id)
    favorites.value = favorites.value.filter((f) => f.id !== record.id)
    message.success(`已取消收藏「${record.item_name}」`)
  } catch {
    message.error('取消收藏失败')
  }
}

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

// 组件挂载时拉取历史行程与收藏列表
onMounted(() => {
  fetchPlans()
  fetchFavorites()
})

/**
 * formatPlan：把后端摘要转成 PlanCard 需要的字段结构
 */
const formatPlan = (p: MyPlanSummary) => ({
  plan_id: p.plan_id,
  city: p.city,
  start_date: p.start_date,
  end_date: p.end_date,
  budget: { total: p.budget_total },
  status: p.status
})

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
  <div class="page-fade" style="max-width: 1000px; margin: 0 auto;">
    <!-- 用户信息卡片 -->
    <Card title="个人信息" style="margin-bottom: 16px; border-radius: 12px;">
      <p style="margin: 4px 0;"><strong>用户名：</strong>{{ authStore.user?.username || '未登录' }}</p>
      <p style="margin: 4px 0;"><strong>邮箱：</strong>{{ authStore.user?.email || '-' }}</p>
    </Card>

    <!-- 偏好画像卡片（雷达图 + 明细 + 编辑） -->
    <div style="margin-bottom: 16px;">
      <PreferenceCard :user-id="authStore.user?.id" />
    </div>

    <!-- 我的收藏列表 -->
    <h3 style="margin: 24px 0 16px;">我的收藏</h3>
    <Card style="border-radius: 12px;">
      <Spin :spinning="favLoading">
        <List v-if="favorites.length > 0" :data-source="favorites" item-layout="horizontal">
          <template #renderItem="{ item }">
            <List.Item>
              <List.Item.Meta>
                <template #title>
                  <span>
                    <Tag :color="itemTypeLabel(item.item_type).color">{{ itemTypeLabel(item.item_type).label }}</Tag>
                    <strong>{{ item.item_name }}</strong>
                    <Tag v-if="item.city" style="margin-left: 8px;">{{ item.city }}</Tag>
                  </span>
                </template>
                <template #description>
                  <span style="color: #999; font-size: 12px;">
                    收藏于 {{ item.created_at ? new Date(item.created_at).toLocaleString() : '-' }}
                  </span>
                </template>
              </List.Item.Meta>
              <template #actions>
                <Button size="small" danger @click="handleRemoveFavorite(item)">取消收藏</Button>
              </template>
            </List.Item>
          </template>
        </List>
        <div v-else-if="!favLoading" style="padding: 16px 0;">
          <Empty description="还没有收藏，去行程结果页收藏感兴趣的景点吧" />
        </div>
      </Spin>
    </Card>

    <!-- 历史行程列表（真实数据） -->
    <h3 style="margin: 24px 0 16px;">历史行程</h3>
    <Spin :spinning="loading">
      <div
        v-if="plans.length > 0"
        style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px;"
      >
        <PlanCard v-for="p in plans" :key="p.plan_id" :plan="formatPlan(p)" />
      </div>
      <div v-else-if="loaded && !loading" style="padding: 24px 0;">
        <Empty description="还没有行程记录，去首页发起一次旅行规划吧" />
      </div>
    </Spin>

    <!-- 知识库管理（攻略上传/检索 + 爬虫任务） -->
    <h3 style="margin: 24px 0 16px;">知识库管理</h3>
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
  </div>
</template>
