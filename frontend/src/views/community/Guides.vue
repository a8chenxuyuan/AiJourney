<!--
  src/views/Guides.vue：攻略灵感页（图文内容中心，全站唯一图文流入口）
  作用：真实游记 + 社区笔记帖 + 爬虫攻略三源智能合流的卡片流，
       支持类型/城市筛选与关键词搜索；游记跳公开分享页、笔记跳帖子详情（点赞/评论/照着走）、
       攻略跳详情页；页头「发布笔记」复用 NoteComposerModal 发布社区笔记帖。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 挂载时拉取攻略流（后端智能排序：源权重 × 热度 × 时间衰减）；
 * 2. 类型/城市 chips 与搜索框触发重新查询（页码重置）；
 * 3. 「加载更多」按页码追加数据；发布笔记成功后刷新列表。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Drawer, Empty, Input, Spin, Tag } from 'ant-design-vue'
import { getGuides, type ContentItem } from '@/api/community/guides'
import NoteComposerModal from '@/components/NoteComposerModal.vue'

const router = useRouter()

// loading：首屏加载；loadingMore：加载更多；cities：城市筛选 chips
const loading = ref(true)
const loadingMore = ref(false)
const cities = ref<string[]>([])

// items：当前列表；keyword：搜索词；activeCity：选中城市；activeType：类型筛选；activeDays：天数上限（0=不限）
const items = ref<ContentItem[]>([])
const keyword = ref('')
const activeCity = ref('')
const activeType = ref<'' | 'journal' | 'note' | 'guide'>('')
const activeDays = ref(0)

// previewItem：快速预览抽屉当前条目（点卡片先预览，不离开列表）
const previewItem = ref<ContentItem | null>(null)

// page / hasMore：分页状态；noteVisible：发布笔记弹窗
const page = ref(1)
const hasMore = ref(false)
const noteVisible = ref(false)

/**
 * fetchGuides：按当前筛选条件查询攻略流（重置分页）
 */
const fetchGuides = async () => {
  loading.value = true
  try {
    const res = await getGuides({
      city: activeCity.value || undefined,
      q: keyword.value.trim() || undefined,
      type: activeType.value || undefined,
      max_days: activeDays.value || undefined,
      page: 1,
      size: 10
    })
    if (res.success && res.data) {
      items.value = res.data.items || []
      cities.value = res.data.cities || []
      page.value = 1
      hasMore.value = res.data.has_more
    }
  } finally {
    loading.value = false
  }
}

/**
 * loadMore：追加下一页数据
 */
const loadMore = async () => {
  loadingMore.value = true
  try {
    const res = await getGuides({
      city: activeCity.value || undefined,
      q: keyword.value.trim() || undefined,
      type: activeType.value || undefined,
      max_days: activeDays.value || undefined,
      page: page.value + 1,
      size: 10
    })
    if (res.success && res.data) {
      items.value.push(...(res.data.items || []))
      page.value += 1
      hasMore.value = res.data.has_more
    }
  } finally {
    loadingMore.value = false
  }
}

/**
 * selectCity：切换城市筛选（同城市点击取消）
 */
const selectCity = (city: string) => {
  activeCity.value = activeCity.value === city ? '' : city
  fetchGuides()
}

/**
 * selectType：切换类型筛选（同类型点击取消）
 */
const selectType = (t: '' | 'journal' | 'note' | 'guide') => {
  activeType.value = activeType.value === t ? '' : t
  fetchGuides()
}

/**
 * selectDays：切换天数上限筛选（0=不限）
 */
const selectDays = (d: number) => {
  activeDays.value = activeDays.value === d ? 0 : d
  fetchGuides()
}

/**
 * onSearch：搜索词回车/按钮触发
 */
const onSearch = () => fetchGuides()

/**
 * goItem：卡片跳转（游记 → 公开分享页；笔记 → 帖子详情；攻略 → 详情页）
 */
const goItem = (item: ContentItem) => {
  if (item.item_type === 'journal') {
    if (item.public_token) router.push(`/journal/${item.public_token}`)
  } else if (item.item_type === 'note') {
    router.push(`/community/${item.id}`)
  } else {
    router.push(`/guides/${item.id}`)
  }
}

/**
 * openFull：从预览抽屉进入全文（先捕获条目再关闭抽屉，避免置空后拿不到数据）
 */
const openFull = (item: ContentItem) => {
  previewItem.value = null
  goItem(item)
}

/**
 * goAuthor：从预览抽屉跳作者主页（同样先捕获再关闭）
 */
const goAuthor = (item: ContentItem) => {
  previewItem.value = null
  if (item.user_id) router.push(`/user/${item.user_id}`)
}

// 渐变占位背景（无封面图卡片使用，按序号稳定取色）
const gradients = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)'
]
const gradientOf = (idx: number) => gradients[idx % gradients.length]

// 卡片类型徽标文案与配色
const typeMeta: Record<ContentItem['item_type'], { text: string; color: string }> = {
  journal: { text: '真实游记', color: 'orange' },
  note: { text: '社区笔记', color: 'green' },
  guide: { text: '攻略', color: 'blue' }
}

onMounted(fetchGuides)
</script>

<template>
  <div class="page-fade" style="max-width: 1900px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0 16px;">
      <div>
        <h2 style="margin: 0; font-size: 24px;">攻略灵感</h2>
        <p style="color: #888; margin: 6px 0 0; font-size: 14px;">
          真实游记、社区笔记与精选攻略，看中的线路可以一键复刻成自己的行程
        </p>
      </div>
      <div style="display: flex; gap: 10px;">
        <Button type="primary" @click="noteVisible = true">✏️ 发布笔记</Button>
        <Button @click="router.push('/')">去规划行程</Button>
      </div>
    </div>

    <!-- 筛选区：搜索框 + 类型 chips + 城市 chips -->
    <div style="display: flex; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; align-items: center;">
      <Input.Search
        v-model:value="keyword"
        placeholder="搜索标题或内容"
        style="max-width: 300px;"
        allow-clear
        @search="onSearch"
      />
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <Tag
          :color="activeType === '' ? 'blue' : 'default'"
          style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
          @click="selectType('')"
        >全部</Tag>
        <Tag
          v-for="(meta, t) in typeMeta"
          :key="t"
          :color="activeType === t ? meta.color : 'default'"
          style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
          @click="selectType(t)"
        >{{ meta.text }}</Tag>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <Tag
          :color="activeDays === 0 ? 'blue' : 'default'"
          style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
          @click="selectDays(0)"
        >⏱ 全部天数</Tag>
        <Tag
          v-for="d in [3, 5, 7]"
          :key="d"
          :color="activeDays === d ? 'blue' : 'default'"
          style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
          @click="selectDays(d)"
        >≤ {{ d }} 天</Tag>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <Tag
          :color="activeCity === '' ? 'blue' : 'default'"
          style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
          @click="activeCity = ''; fetchGuides()"
        >📍全部城市</Tag>
        <Tag
          v-for="city in cities"
          :key="city"
          :color="activeCity === city ? 'blue' : 'default'"
          style="cursor: pointer; font-size: 14px; padding: 4px 12px;"
          @click="selectCity(city)"
        >📍 {{ city }}</Tag>
      </div>
    </div>

    <Spin :spinning="loading">
      <Empty
        v-if="!loading && items.length === 0"
        description="暂无相关内容，换个关键词或城市试试"
      />

      <!-- 合流卡片列表：智能排序（游记/笔记/攻略混合） -->
      <div v-else style="display: flex; flex-direction: column; gap: 16px; margin-top: 12px;">
        <Card
          v-for="(item, idx) in items"
          :key="`${item.item_type}-${item.id}`"
          hoverable
          style="border-radius: 14px; overflow: hidden;"
          @click="previewItem = item"
        >
          <div style="display: flex; gap: 16px; align-items: stretch;">
            <!-- 封面：游记/笔记用封面图，攻略用渐变占位 -->
            <img
              v-if="item.cover_url"
              :src="item.cover_url"
              style="width: 180px; height: 128px; object-fit: cover; border-radius: 10px; flex-shrink: 0;"
            />
            <div
              v-else
              :style="{
                width: '180px', height: '128px', borderRadius: '10px', flexShrink: 0,
                background: gradientOf(idx), display: 'flex', alignItems: 'center', justifyContent: 'center'
              }"
            >
              <span style="font-size: 40px;">{{ item.item_type === 'journal' ? '📔' : item.item_type === 'note' ? '📝' : '🧳' }}</span>
            </div>

            <!-- 信息区 -->
            <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <Tag :color="typeMeta[item.item_type].color">{{ typeMeta[item.item_type].text }}</Tag>
                <span v-if="item.city" style="color: var(--brand); font-size: 13px;">📍 {{ item.city }}</span>
                <span v-if="item.travel_days" style="color: #888; font-size: 13px;">· {{ item.travel_days }} 天</span>
              </div>
              <h3 style="margin: 8px 0 6px; font-size: 17px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                {{ item.title }}
              </h3>
              <p style="color: #666; margin: 0; font-size: 14px; line-height: 1.7; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">
                {{ item.excerpt || '（暂无摘要）' }}
              </p>
              <div style="margin-top: auto; color: #999; font-size: 13px; display: flex; gap: 12px; align-items: center;">
                <a v-if="item.author && item.user_id" style="color: inherit;" @click.stop="router.push(`/user/${item.user_id}`)">✍️ {{ item.author }}</a>
                <span v-else-if="item.author">✍️ {{ item.author }}</span>
                <span v-if="item.created_at">{{ item.created_at.replace('T', ' ').slice(0, 10) }}</span>
                <!-- 社区笔记专属互动数 -->
                <template v-if="item.item_type === 'note'">
                  <span>❤️ {{ item.like_count || 0 }}</span>
                  <span>💬 {{ item.comment_count || 0 }}</span>
                  <span>👁 {{ item.view_count || 0 }}</span>
                </template>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <!-- 加载更多 -->
      <div v-if="hasMore" style="text-align: center; margin: 20px 0;">
        <Button :loading="loadingMore" @click="loadMore">加载更多</Button>
      </div>
    </Spin>

    <!-- 发布笔记弹窗（复用抽取组件） -->
    <NoteComposerModal v-model:open="noteVisible" @success="fetchGuides" />

    <!-- 快速预览抽屉：不离开列表先看摘要，再决定是否进入全文 -->
    <Drawer
      :open="!!previewItem"
      width="520"
      title="内容预览"
      @close="previewItem = null"
    >
      <template v-if="previewItem">
        <!-- 头图：封面图或渐变占位 -->
        <img
          v-if="previewItem.cover_url"
          :src="previewItem.cover_url"
          style="width: 100%; height: 220px; object-fit: cover; border-radius: 12px; display: block;"
        />
        <div
          v-else
          style="width: 100%; height: 160px; border-radius: 12px; display: flex; align-items: center; justify-content: center; background: var(--grad-primary-soft);"
        >
          <span style="font-size: 52px;">{{ previewItem.item_type === 'journal' ? '📔' : previewItem.item_type === 'note' ? '📝' : '🧳' }}</span>
        </div>

        <div style="margin-top: 16px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <Tag :color="typeMeta[previewItem.item_type].color">{{ typeMeta[previewItem.item_type].text }}</Tag>
          <span v-if="previewItem.city" style="color: var(--brand); font-size: 13px;">📍 {{ previewItem.city }}</span>
          <span v-if="previewItem.travel_days" style="color: #888; font-size: 13px;">· {{ previewItem.travel_days }} 天</span>
        </div>

        <h2 style="margin: 10px 0 8px; font-size: 20px; line-height: 1.4;">{{ previewItem.title }}</h2>
        <p style="color: #999; font-size: 13px; margin: 0 0 14px;">
          <a v-if="previewItem.author && previewItem.user_id" style="color: var(--brand);" @click="goAuthor(previewItem!)">✍️ {{ previewItem.author }}</a>
          <span v-else-if="previewItem.author">✍️ {{ previewItem.author }}</span>
          <span v-if="previewItem.created_at"> · {{ previewItem.created_at.replace('T', ' ').slice(0, 10) }}</span>
        </p>

        <p style="color: #555; font-size: 14.5px; line-height: 1.9; white-space: pre-wrap;">
          {{ previewItem.excerpt || '（暂无摘要，点击下方按钮查看全文）' }}
        </p>

        <!-- 社区笔记互动数 -->
        <div v-if="previewItem.item_type === 'note'" style="display: flex; gap: 16px; color: #999; font-size: 13px; margin: 12px 0;">
          <span>❤️ {{ previewItem.like_count || 0 }}</span>
          <span>💬 {{ previewItem.comment_count || 0 }}</span>
          <span>👁 {{ previewItem.view_count || 0 }}</span>
        </div>

        <div style="display: flex; gap: 10px; margin-top: 20px;">
          <Button type="primary" style="flex: 1;" @click="openFull(previewItem!)">查看全文 →</Button>
          <Button @click="previewItem = null">关闭</Button>
        </div>
      </template>
    </Drawer>
  </div>
</template>
