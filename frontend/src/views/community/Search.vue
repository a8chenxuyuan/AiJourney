<!--
  src/views/Search.vue：全站搜索页
  作用：按关键词统一检索社区帖子/公开游记/爬虫攻略/用户四源，
       结果按类型打标并跳转对应详情；侧边栏搜索框跳转本页。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 挂载/路由 query 变化时按 q 调用 /search 统一检索；
 * 2. 顶部结果统计（四源计数 chips）+ 横排结果卡；
 * 3. 点击结果按类型跳转：帖子/游记/攻略/用户主页。
 */
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Empty, Input, Spin, Tag } from 'ant-design-vue'
import { globalSearch, type SearchResult } from '@/api/community/search'

const route = useRoute()
const router = useRouter()

// keyword：搜索框输入；resultQ：当前已查询的关键词（防止重复请求）
const keyword = ref((route.query.q as string) || '')
const resultQ = ref('')
const loading = ref(false)
const items = ref<SearchResult[]>([])
const counts = ref<SearchDataCounts | null>(null)

interface SearchDataCounts {
  post: number
  journal: number
  guide: number
  user: number
}

/**
 * doSearch：执行搜索
 */
const doSearch = async () => {
  const q = keyword.value.trim()
  if (!q) return
  loading.value = true
  try {
    const res = await globalSearch(q)
    if (res.success && res.data) {
      items.value = res.data.items || []
      counts.value = res.data.counts
      resultQ.value = q
    }
  } finally {
    loading.value = false
  }
}

// 路由 query 变化时重新搜索（侧边栏/页头重复发起）
watch(
  () => route.query.q,
  (q) => {
    if (q && q !== resultQ.value) {
      keyword.value = String(q)
      doSearch()
    }
  }
)

/**
 * typeMeta：结果类型的中文标签与配色
 */
const typeMeta: Record<SearchResult['result_type'], { text: string; color: string }> = {
  user: { text: '用户', color: 'purple' },
  post: { text: '帖子', color: 'green' },
  journal: { text: '游记', color: 'orange' },
  guide: { text: '攻略', color: 'blue' }
}

/**
 * goResult：按类型跳转
 */
const goResult = (item: SearchResult) => {
  switch (item.result_type) {
    case 'user':
      router.push(`/user/${item.id}`)
      break
    case 'post':
      router.push(`/community/${item.id}`)
      break
    case 'journal':
      if (item.public_token) router.push(`/journal/${item.public_token}`)
      break
    case 'guide':
      router.push(`/guides/${item.id}`)
      break
  }
}
</script>

<template>
  <div class="page-fade" style="max-width: 1900px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头：搜索框 -->
    <div style="margin: 24px 0 16px;">
      <h2 style="margin: 0; font-size: 24px;">全站搜索</h2>
      <p style="color: #888; margin: 6px 0 12px; font-size: 14px;">
        一次搜全：旅行圈帖子 · 公开游记 · 攻略 · 用户
      </p>
      <Input.Search
        v-model:value="keyword"
        placeholder="搜索帖子、游记、攻略或用户"
        enter-button="搜索"
        style="max-width: 560px;"
        size="large"
        allow-clear
        @search="doSearch"
      />
    </div>

    <!-- 结果统计 chips -->
    <div v-if="counts && items.length" style="display: flex; gap: 10px; margin-bottom: 8px; flex-wrap: wrap;">
      <Tag color="purple">用户 {{ counts.user }}</Tag>
      <Tag color="green">帖子 {{ counts.post }}</Tag>
      <Tag color="orange">游记 {{ counts.journal }}</Tag>
      <Tag color="blue">攻略 {{ counts.guide }}</Tag>
      <span style="color: #999; font-size: 13px; align-self: center;">共 {{ items.length }} 条结果</span>
    </div>

    <Spin :spinning="loading">
      <Empty
        v-if="!loading && resultQ && items.length === 0"
        :description="`没有找到与「${resultQ}」相关的内容`"
      />
      <Empty v-else-if="!loading && !resultQ" description="输入关键词开始搜索" />

      <!-- 结果列表：横排卡（与攻略灵感页同构） -->
      <div v-else style="display: flex; flex-direction: column; gap: 14px; margin-top: 12px;">
        <div
          v-for="item in items"
          :key="`${item.result_type}-${item.id}`"
          style="display: flex; gap: 14px; align-items: center; padding: 12px; border-radius: 14px; background: #fff; border: 1px solid rgba(34, 48, 43, 0.07); cursor: pointer; transition: border-color 0.2s, box-shadow 0.2s;"
          @click="goResult(item)"
        >
          <!-- 封面/头像占位 -->
          <img
            v-if="item.cover_url"
            :src="item.cover_url"
            style="width: 88px; height: 66px; object-fit: cover; border-radius: 10px; flex-shrink: 0;"
          />
          <div
            v-else
            style="width: 88px; height: 66px; border-radius: 10px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; background: var(--grad-primary-soft); font-size: 28px;"
          >
            {{ item.result_type === 'user' ? '👤' : item.result_type === 'journal' ? '📔' : item.result_type === 'guide' ? '🧳' : '📝' }}
          </div>

          <!-- 信息区 -->
          <div style="flex: 1; min-width: 0;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <Tag :color="typeMeta[item.result_type].color" style="margin: 0;">{{ typeMeta[item.result_type].text }}</Tag>
              <span v-if="item.city" style="color: var(--brand); font-size: 13px;">📍 {{ item.city }}</span>
              <span v-if="item.travel_days" style="color: #888; font-size: 13px;">· {{ item.travel_days }} 天</span>
            </div>
            <h3 style="margin: 5px 0 4px; font-size: 15.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ item.title }}
            </h3>
            <p style="color: #666; margin: 0; font-size: 13px; line-height: 1.6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ item.excerpt || '（暂无摘要）' }}
            </p>
          </div>

          <!-- 右侧元信息 -->
          <div style="flex-shrink: 0; color: #999; font-size: 13px; display: flex; gap: 12px; align-items: center;">
            <a v-if="item.result_type === 'user'" style="color: var(--brand);">查看主页 →</a>
            <template v-else>
              <a v-if="item.author && item.user_id" style="color: inherit;" @click.stop="router.push(`/user/${item.user_id}`)">✍️ {{ item.author }}</a>
              <span v-else-if="item.author">✍️ {{ item.author }}</span>
              <span v-if="item.result_type === 'post'">❤️ {{ item.like_count || 0 }}</span>
              <span v-if="item.created_at">{{ item.created_at.replace('T', ' ').slice(0, 10) }}</span>
            </template>
          </div>
        </div>
      </div>
    </Spin>

    <!-- 底部返回 -->
    <div v-if="items.length" style="text-align: center; margin: 24px 0;">
      <Button @click="router.push('/guides')">去攻略灵感逛逛 →</Button>
    </div>
  </div>
</template>
