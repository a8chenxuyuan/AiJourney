<!--
  src/views/Creators.vue：同路人 · 达人发现页
  作用：按获赞/发帖排序的创作者卡片墙；点击卡片进用户主页（可加好友/发消息）。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 挂载时拉取 /users/creators 达人榜（免登录）；
 * 2. 顶部排序切换（按获赞 / 按发帖，前端排序）；
 * 3. 达人卡：头像 + 昵称 + 加入时间 + 三项统计 + 最近封面条 + 查看主页。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Empty, Spin } from 'ant-design-vue'
import { listCreators, type CreatorItem } from '@/api/social'

const router = useRouter()

// creators：达人列表；sortBy：排序维度（likes/posts）；loading：加载态
const creators = ref<CreatorItem[]>([])
const sortBy = ref<'likes' | 'posts'>('likes')
const loading = ref(true)

// sorted：按当前维度排序（获赞相同时发帖多者靠前，反之亦然）
const sorted = computed(() =>
  [...creators.value].sort((a, b) =>
    sortBy.value === 'likes'
      ? b.likes_total - a.likes_total || b.posts_count - a.posts_count
      : b.posts_count - a.posts_count || b.likes_total - a.likes_total
  )
)

/**
 * joinedAt：加入时间格式化为 YYYY-MM
 */
const joinedAt = (t: string | null) =>
  t ? new Date(t).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' }) : ''

onMounted(async () => {
  try {
    const res = await listCreators()
    if (res.success && res.data) creators.value = res.data.items || []
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page-fade creators-page">
    <!-- 页头 -->
    <div style="max-width: 1900px; margin: 0 auto; padding: 32px 16px 0;">
      <p class="section-overline">同路人</p>
      <div style="display: flex; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
        <div>
          <h2 style="margin: 4px 0 6px; font-size: 26px;">旅行达人，值得跟玩</h2>
          <p style="margin: 0; color: var(--ink-3); font-size: 14px;">
            按获赞与发帖数排序的活跃创作者，点进主页看 TA 的旅行圈与游记
          </p>
        </div>
        <!-- 排序切换 -->
        <div class="cr-sort">
          <button :class="{ on: sortBy === 'likes' }" @click="sortBy = 'likes'">🔥 按获赞</button>
          <button :class="{ on: sortBy === 'posts' }" @click="sortBy = 'posts'">📝 按发帖</button>
        </div>
      </div>
    </div>

    <!-- 达人卡网格 -->
    <div style="max-width: 1900px; margin: 0 auto; padding: 22px 16px 56px;">
      <Spin :spinning="loading">
        <Empty v-if="!loading && creators.length === 0" description="还没有活跃的创作者，去旅行圈发第一帖吧" />
        <div v-else class="cr-grid">
          <div
            v-for="(c, i) in sorted"
            :key="c.user_id"
            class="cr-card"
            @click="router.push(`/user/${c.user_id}`)"
          >
            <!-- 排名徽标（前三名高亮） -->
            <span class="cr-rank" :class="`top-${i + 1}`" v-if="i < 3">{{ i + 1 }}</span>

            <!-- 头部：头像 + 昵称 + 加入时间 -->
            <div style="display: flex; align-items: center; gap: 12px;">
              <span class="cr-avatar">{{ c.username.charAt(0).toUpperCase() }}</span>
              <div style="min-width: 0;">
                <h3 style="margin: 0; font-size: 15.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                  {{ c.username }}
                </h3>
                <p style="margin: 3px 0 0; color: var(--ink-3); font-size: 12px;">{{ joinedAt(c.joined_at) }} 加入</p>
              </div>
            </div>

            <!-- 统计三项 -->
            <div class="cr-stats">
              <div><b>{{ c.likes_total }}</b><span>获赞</span></div>
              <div><b>{{ c.posts_count }}</b><span>发帖</span></div>
              <div><b>{{ c.journals_count }}</b><span>游记</span></div>
            </div>

            <!-- 最近封面条（无封面用渐变块） -->
            <div class="cr-covers">
              <template v-if="c.covers.length">
                <img v-for="(cv, ci) in c.covers" :key="ci" :src="cv" />
              </template>
              <template v-else>
                <span class="cr-cover-empty">🌍</span>
                <span class="cr-cover-empty">📷</span>
                <span class="cr-cover-empty">✨</span>
              </template>
            </div>

            <Button type="primary" block style="margin-top: 12px;">查看 TA 的主页 →</Button>
          </div>
        </div>
      </Spin>
    </div>
  </div>
</template>

<style scoped>
/* 排序胶囊组 */
.cr-sort {
  display: flex;
  gap: 6px;
  background: #fff;
  border: 1px solid rgba(34, 48, 43, 0.09);
  border-radius: 999px;
  padding: 4px;
}
.cr-sort button {
  border: none;
  background: transparent;
  padding: 7px 16px;
  border-radius: 999px;
  font-size: 13.5px;
  color: var(--ink-2);
  cursor: pointer;
  transition: all 0.2s ease;
}
.cr-sort button.on {
  background: var(--brand);
  color: #fff;
  font-weight: 600;
}

/* 达人卡网格：自适应三列起 */
.cr-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 18px;
}
.cr-card {
  position: relative;
  background: #fff;
  border: 1px solid rgba(34, 48, 43, 0.07);
  border-radius: 16px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.cr-card:hover {
  transform: translateY(-3px);
  border-color: rgba(46, 107, 94, 0.35);
  box-shadow: 0 14px 34px rgba(46, 107, 94, 0.12);
}

/* 前三名排名徽标 */
.cr-rank {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0ede4;
  color: var(--ink-3);
}
.cr-rank.top-1 {
  background: linear-gradient(135deg, #f7b733, #fc4a1a);
  color: #fff;
}
.cr-rank.top-2 {
  background: linear-gradient(135deg, #b7c4d0, #8e9eab);
  color: #fff;
}
.cr-rank.top-3 {
  background: linear-gradient(135deg, #d5a06b, #b0763c);
  color: #fff;
}

/* 头像（首字母，绿色渐变） */
.cr-avatar {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: var(--grad-primary);
  color: #fff;
  font-size: 19px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* 统计三项 */
.cr-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 16px 0 12px;
  padding: 10px 0;
  border-top: 1px solid rgba(34, 48, 43, 0.07);
  border-bottom: 1px solid rgba(34, 48, 43, 0.07);
}
.cr-stats > div {
  text-align: center;
}
.cr-stats b {
  display: block;
  font-size: 17px;
  color: var(--ink);
}
.cr-stats span {
  font-size: 12px;
  color: var(--ink-3);
}

/* 最近封面条：三等分横滑缩略图 */
.cr-covers {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  height: 74px;
}
.cr-covers img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 9px;
}
.cr-cover-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  font-size: 22px;
  background: var(--grad-primary-soft);
}
</style>
