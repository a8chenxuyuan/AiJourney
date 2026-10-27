<!--
  src/views/Favorites.vue：我的行囊（收藏独立页）
  作用：集中浏览收藏的景点/酒店/餐厅——类型分段筛选 + 城市标签筛选 + 卡片网格，
       卡片可跳目的地聚合页、取消收藏；空状态引导去攻略灵感（借鉴 RouteBuddy 行囊设计）。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 挂载时并行拉取收藏列表与收藏城市（后端支持按城市过滤，本地也做一次联动筛选）；
 * 2. 类型 Segmented + 城市 Tag 双维筛选；
 * 3. 卡片操作：查看目的地（city → /destination/:city）、取消收藏。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Segmented, Spin, Tag, message } from 'ant-design-vue'
import { getFavoriteCities, getFavorites, removeFavorite, type FavoriteRecord } from '@/api/trip'

const router = useRouter()

// favorites：收藏全量列表；cities：收藏涉及的城市（去重）
const favorites = ref<FavoriteRecord[]>([])
const cities = ref<string[]>([])
// 筛选状态：类型（all/attraction/hotel/restaurant）+ 城市（null=全部城市）
const typeFilter = ref<'all' | 'attraction' | 'hotel' | 'restaurant'>('all')
const activeCity = ref<string | null>(null)
const loading = ref(true)

/**
 * typeMeta：收藏类型的图标/标签/颜色映射
 */
const typeMeta: Record<string, { label: string; icon: string; color: string }> = {
  attraction: { label: '景点', icon: '📍', color: 'blue' },
  hotel: { label: '酒店', icon: '🏨', color: 'purple' },
  restaurant: { label: '餐厅', icon: '🍽️', color: 'orange' }
}

/**
 * typeCount：分类型计数（头部统计用）
 */
const typeCount = (t: string) => favorites.value.filter((f) => f.item_type === t).length

// cityFiltered：城市筛选；typeFiltered：再叠加类型筛选（卡片网格最终数据源）
const cityFiltered = computed(() =>
  activeCity.value ? favorites.value.filter((f) => f.city === activeCity.value) : favorites.value
)
const typeFiltered = computed(() =>
  typeFilter.value === 'all'
    ? cityFiltered.value
    : cityFiltered.value.filter((f) => f.item_type === typeFilter.value)
)

/**
 * loadAll：并行拉取收藏列表与城市清单
 */
const loadAll = async () => {
  loading.value = true
  try {
    const [favRes, cityRes] = await Promise.all([getFavorites(), getFavoriteCities()])
    favorites.value = favRes.data?.favorites || []
    cities.value = cityRes.data?.cities || []
  } finally {
    loading.value = false
  }
}

/**
 * handleRemove：取消收藏（本地同步移除）
 */
const handleRemove = async (record: FavoriteRecord) => {
  try {
    await removeFavorite(record.id)
    favorites.value = favorites.value.filter((f) => f.id !== record.id)
    message.success(`已取消收藏「${record.item_name}」`)
  } catch {
    message.error('取消收藏失败')
  }
}

/**
 * goDestination：跳目的地聚合页
 */
const goDestination = (city?: string | null) => {
  if (city) router.push(`/destination/${encodeURIComponent(city)}`)
}

onMounted(loadAll)
</script>

<template>
  <div class="page-fade fav-page">
    <!-- 行囊头卡：柔和渐变横幅 + 统计 -->
    <section class="fav-hero">
      <span class="fav-hero-ico">🎒</span>
      <div class="fav-hero-text">
        <h2>我的行囊</h2>
        <p>旅途中种草的景点、酒店与餐厅，都收在这里等你出发</p>
      </div>
      <div class="fav-hero-stats">
        <div class="fav-stat"><b>{{ favorites.length }}</b><span>全部收藏</span></div>
        <div class="fav-stat"><b>{{ typeCount('attraction') }}</b><span>景点</span></div>
        <div class="fav-stat"><b>{{ typeCount('hotel') }}</b><span>酒店</span></div>
        <div class="fav-stat"><b>{{ typeCount('restaurant') }}</b><span>餐厅</span></div>
      </div>
    </section>

    <!-- 双维筛选：类型分段器 + 城市标签 -->
    <div class="fav-filters">
      <Segmented
        v-model:value="typeFilter"
        :options="[
          { label: '全部', value: 'all' },
          { label: '📍 景点', value: 'attraction' },
          { label: '🏨 酒店', value: 'hotel' },
          { label: '🍽️ 餐厅', value: 'restaurant' }
        ]"
      />
      <div class="fav-city-tags">
        <Tag
          :color="activeCity === null ? 'blue' : 'default'"
          style="cursor: pointer; padding: 4px 14px;"
          @click="activeCity = null"
        >
          全部城市
        </Tag>
        <Tag
          v-for="c in cities"
          :key="c"
          :color="activeCity === c ? 'blue' : 'default'"
          style="cursor: pointer; padding: 4px 14px;"
          @click="activeCity = c"
        >
          {{ c }}
        </Tag>
      </div>
    </div>

    <Spin :spinning="loading">
      <!-- 收藏卡片网格 -->
      <div v-if="typeFiltered.length" class="fav-grid">
        <div v-for="f in typeFiltered" :key="f.id" class="fav-card">
          <div class="fav-card-top">
            <span class="fav-ico">{{ typeMeta[f.item_type]?.icon || '⭐' }}</span>
            <Tag :color="typeMeta[f.item_type]?.color || 'default'">
              {{ typeMeta[f.item_type]?.label || f.item_type }}
            </Tag>
          </div>
          <h3 class="fav-name" :title="f.item_name">{{ f.item_name }}</h3>
          <p class="fav-meta">
            <span v-if="f.city">🏙 {{ f.city }}</span>
            <span>⏱ 收藏于 {{ f.created_at?.slice(0, 10) }}</span>
          </p>
          <div class="fav-actions">
            <Button v-if="f.city" size="small" @click="goDestination(f.city)">查看目的地</Button>
            <Button size="small" type="text" danger @click="handleRemove(f)">取消收藏</Button>
          </div>
        </div>
      </div>

      <!-- 空态：完全没收藏引导去逛 / 筛选后为空提供清除 -->
      <Card v-else-if="!loading" style="border-radius: 16px;">
        <div class="fav-empty">
          <span class="fav-empty-ico">{{ favorites.length === 0 ? '🎒' : '🔍' }}</span>
          <p>{{ favorites.length === 0 ? '行囊还是空的，去种草第一站吧' : '没有符合条件的收藏' }}</p>
          <Button v-if="favorites.length === 0" type="primary" @click="router.push('/guides')">
            去攻略灵感逛逛
          </Button>
          <Button v-else @click="typeFilter = 'all'; activeCity = null">清除筛选条件</Button>
        </div>
      </Card>
    </Spin>
  </div>
</template>

<style scoped>
.fav-page {
  max-width: 1900px;
  margin: 0 auto;
  padding: 0 16px 48px;
}
/* 行囊头卡：柔和渐变横幅 */
.fav-hero {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 26px 28px;
  border-radius: 20px;
  background: linear-gradient(120deg, #e0f2fe 0%, #ede9fe 55%, #fce7f3 100%);
  margin: 20px 0 18px;
}
.fav-hero-ico {
  font-size: 44px;
  filter: drop-shadow(0 4px 8px rgba(14, 34, 57, 0.12));
}
.fav-hero-text h2 {
  margin: 0;
  font-size: 22px;
  color: var(--ink);
}
.fav-hero-text p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--ink-2);
}
.fav-hero-stats {
  margin-left: auto;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.fav-stat {
  background: rgba(255, 255, 255, 0.72);
  border-radius: 14px;
  padding: 10px 18px;
  text-align: center;
  min-width: 86px;
}
.fav-stat b {
  font-size: 20px;
  display: block;
  color: #1e293b;
}
.fav-stat span {
  font-size: 12px;
  color: var(--ink-3);
}
/* 筛选行 */
.fav-filters {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.fav-city-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
/* 卡片网格 */
.fav-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.fav-card {
  background: #fff;
  border: 1px solid #f1f5f9;
  border-radius: 16px;
  padding: 18px;
  transition: box-shadow 0.25s, transform 0.25s, border-color 0.25s;
}
.fav-card:hover {
  box-shadow: 0 10px 26px rgba(46, 107, 94, 0.12);
  transform: translateY(-3px);
  border-color: #cfe3d8;
}
.fav-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.fav-ico {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #e0f2fe, #ede9fe);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}
.fav-name {
  margin: 0 0 8px;
  font-size: 16px;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fav-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: #94a3b8;
  font-size: 12px;
  margin: 0 0 14px;
}
.fav-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
/* 空态 */
.fav-empty {
  text-align: center;
  padding: 36px 0;
}
.fav-empty-ico {
  font-size: 46px;
  display: block;
  margin-bottom: 10px;
}
.fav-empty p {
  color: #94a3b8;
  margin: 0 0 16px;
}
</style>
