<!--
  src/views/Circle.vue：旅行圈（朋友圈式晒旅行生活，zone=circle 分区）
  作用：双列瀑布流 MomentCard（作者头 + 4 行文字展开 + 照片九宫格 + 标签/互动行）
       + 晒一晒精简弹窗（照片 + 一句话 + 标签）+ 右栏 CommunityRail
  设计：暖色渐变 Hero 与旅行笔记的蓝色系区分；照片 1 张大图 / 2 张两列 / ≥3 张三列
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted, onUnmounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Modal, Upload, Spin, Input, Select, message } from 'ant-design-vue'
// 引入社区 API 与类型
import {
  getFeed,
  createPost,
  forkPost,
  uploadImage,
  resolveImageUrl,
  type PostItem,
  type CreatePostParams
} from '@/api/community'
// 引入共享右栏（玩法引导 / 活跃旅行者 / 热门标签）
import CommunityRail from '@/components/CommunityRail.vue'

const router = useRouter()

// ==================== feed 列表 ====================

// sort：排序方式；posts：已加载动态；total/hasMore/loading：滚动分页状态
const sort = ref<'latest' | 'hot'>('latest')
const posts = ref<PostItem[]>([])
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)

// activeTag：热门标签点击后的客户端筛选（仅作用于已加载内容）
const activeTag = ref<string | null>(null)

// expandedIds：已展开全文的动态 ID（文字超 4 行时显示「展开」）
const expandedIds = ref(new Set<string>())

/**
 * relTime：created_at → 相对时间（刚刚/N分钟前/N小时前/N天前，超一周退化为日期）
 */
const relTime = (s: string) => {
  if (!s) return ''
  const diff = Date.now() - new Date(s).getTime()
  const m = 60_000
  const h = 60 * m
  const d = 24 * h
  if (diff < m) return '刚刚'
  if (diff < h) return `${Math.floor(diff / m)} 分钟前`
  if (diff < d) return `${Math.floor(diff / h)} 小时前`
  if (diff < 7 * d) return `${Math.floor(diff / d)} 天前`
  const dt = new Date(s)
  const sameYear = dt.getFullYear() === new Date().getFullYear()
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  const dd = String(dt.getDate()).padStart(2, '0')
  return sameYear ? `${mm}-${dd}` : s.slice(0, 10)
}

// filteredPosts：应用标签筛选后的动态（无筛选时与 posts 相同）
const filteredPosts = computed(() =>
  activeTag.value ? posts.value.filter((p) => p.tags.includes(activeTag.value!)) : posts.value
)

// topTags：聚合已加载动态的标签计数，取前 8
const topTags = computed(() => {
  const m = new Map<string, number>()
  posts.value.forEach((p) => p.tags.forEach((t) => m.set(t, (m.get(t) || 0) + 1)))
  return [...m.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, count]) => ({ name, count }))
})

// topUsers：从已加载动态按作者聚合发帖数与获赞，取前 5
const topUsers = computed(() => {
  const m = new Map<string, { name: string; posts: number; likes: number }>()
  posts.value.forEach((p) => {
    const u = m.get(p.author) || { name: p.author, posts: 0, likes: 0 }
    u.posts += 1
    u.likes += p.like_count
    m.set(p.author, u)
  })
  return [...m.values()].sort((a, b) => b.posts - a.posts || b.likes - a.likes).slice(0, 5)
})

/**
 * toggleTag：切换标签筛选
 */
const toggleTag = (name: string) => {
  activeTag.value = activeTag.value === name ? null : name
}

/**
 * loadFeed：拉取旅行圈 feed（reset=true 换排序/发布后回到第一页）
 */
const loadFeed = async (reset = false) => {
  if (loading.value) return
  loading.value = true
  try {
    const page = reset ? 1 : posts.value.length / 10 + 1
    const res = await getFeed('circle', sort.value, page, 10)
    if (res.success && res.data) {
      posts.value = reset ? res.data.posts : [...posts.value, ...res.data.posts]
      total.value = res.data.total
      hasMore.value = res.data.has_more
    }
  } catch {
    // 请求层已统一提示
  } finally {
    loading.value = false
  }
}

/**
 * onScroll：滚动到接近底部时加载下一页
 */
const onScroll = () => {
  if (!hasMore.value || loading.value || !posts.value.length) return
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 400) loadFeed()
}

/**
 * changeSort：切换排序，重置列表与标签筛选
 */
const changeSort = () => {
  activeTag.value = null
  loadFeed(true)
}

/**
 * goDetail：进入帖子详情（详情页两区共用）
 */
const goDetail = (id: string) => router.push(`/community/${id}`)

/**
 * toggleExpand：展开/收起长文
 */
const toggleExpand = (id: string) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

// ==================== 照着走（动态快捷入口） ====================

/**
 * handleFork：确认后复制关联行程，成功跳转新行程详情
 */
const handleFork = async (post: PostItem) => {
  Modal.confirm({
    title: '照着走这条路线？',
    content: `将把「${post.title}」关联的行程复制到我的账户（若原行程日期已过去，会自动平移到明天开始）。`,
    okText: '复制行程',
    cancelText: '再想想',
    onOk: async () => {
      try {
        const res = await forkPost(post.id)
        if (res.success && res.data) {
          message.success('行程已复制到我的账户')
          router.push(`/result/${res.data.plan_id}`)
        }
      } catch {
        // 请求层已统一提示
      }
    }
  })
}

// ==================== 晒一晒弹窗 ====================

// shareVisible：弹窗显隐；shareText/shareTags/sharePhotos：晒一晒草稿
const shareVisible = ref(false)
const shareText = ref('')
const shareTags = ref<string[]>([])
const sharePhotos = ref<string[]>([])
const shareSubmitting = ref(false)
const shareUploading = ref(false)

/**
 * openShare：打开发布弹窗（草稿为空）
 */
const openShare = () => {
  shareVisible.value = true
}

/**
 * closeShare：关闭弹窗并清空草稿
 */
const closeShare = () => {
  shareVisible.value = false
  shareText.value = ''
  shareTags.value = []
  sharePhotos.value = []
}

/**
 * uploadPhoto：照片多选上传（customRequest 逐个触发），成功记录相对 URL
 */
const uploadPhoto = async (options: {
  file: unknown
  onSuccess?: (body?: unknown) => void
  onError?: (e: Error) => void
}) => {
  shareUploading.value = true
  try {
    const res = await uploadImage(options.file as File)
    if (res.success && res.data) {
      sharePhotos.value.push(res.data.url)
      options.onSuccess?.(res.data)
    } else {
      options.onError?.(new Error(res.message || '上传失败'))
    }
  } catch (e) {
    options.onError?.(e as Error)
  } finally {
    shareUploading.value = false
  }
}

/**
 * removePhoto：移除已上传照片
 */
const removePhoto = (url: string) => {
  sharePhotos.value = sharePhotos.value.filter((p) => p !== url)
}

/**
 * share：提交晒一晒（zone=circle；朋友圈无标题概念，正文截断作为标题兜底）
 */
const share = async () => {
  const text = shareText.value.trim()
  if (!text && sharePhotos.value.length === 0) {
    message.warning('写一句话或上传至少一张照片')
    return
  }
  shareSubmitting.value = true
  try {
    const title = text ? text.slice(0, 80) : '分享了一组旅行照片'
    const params: CreatePostParams = {
      title,
      zone: 'circle',
      tags: shareTags.value
    }
    if (sharePhotos.value.length) {
      params.sections = [{ day_index: null, title, text, photos: [...sharePhotos.value] }]
      params.cover_url = sharePhotos.value[0]
    } else {
      params.text = text
    }
    const res = await createPost(params)
    if (res.success) {
      message.success('已晒进旅行圈')
      closeShare()
      loadFeed(true)
    }
  } catch {
    // 请求层已统一提示
  } finally {
    shareSubmitting.value = false
  }
}

onMounted(() => {
  loadFeed(true)
  window.addEventListener('scroll', onScroll)
})
onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<template>
  <div class="page-fade circle-page">
    <div class="cl-inner">
      <!-- 顶部 Hero：暖色渐变横幅 + 排序 + 晒一晒 -->
      <section class="cl-hero">
        <div class="cl-hero-copy">
          <h2>旅行圈</h2>
          <p>像发朋友圈一样，晒出你的旅行瞬间</p>
        </div>
        <div class="cl-hero-actions">
          <div class="cl-seg">
            <button :class="{ on: sort === 'latest' }" @click="((sort = 'latest'), changeSort())">最新</button>
            <button :class="{ on: sort === 'hot' }" @click="((sort = 'hot'), changeSort())">热门</button>
          </div>
          <button class="cl-share" @click="openShare">📷 晒一晒</button>
        </div>
        <span class="cl-hero-emoji cl-hero-emoji-1">📸</span>
        <span class="cl-hero-emoji cl-hero-emoji-2">🌅</span>
      </section>

      <!-- 主体两栏：左瀑布流 + 右信息栏 -->
      <div class="cl-layout">
        <div class="cl-feed-col">
          <!-- 标签筛选提示条 -->
          <div v-if="activeTag" class="cl-filter-hint">
            按标签「<b>{{ activeTag }}</b>」筛选 · 匹配 {{ filteredPosts.length }} 条
            <button @click="activeTag = null">清除</button>
          </div>

          <!-- 双列瀑布流：CSS columns 自动按卡片高度错落排布 -->
          <div class="cl-waterfall">
            <article v-for="post in filteredPosts" :key="post.id" class="moment" @click="goDetail(post.id)">
              <!-- 头部：作者 + 相对时间 -->
              <header class="mm-head">
                <span class="mm-avatar">{{ (post.author || '旅').charAt(0).toUpperCase() }}</span>
                <div class="mm-head-main">
                  <b>{{ post.author }}</b>
                  <span>{{ relTime(post.created_at) }}</span>
                </div>
              </header>

              <!-- 文字：最多 4 行，超出可展开 -->
              <p
                v-if="post.text"
                class="mm-text"
                :class="{ expanded: expandedIds.has(post.id) }"
              >{{ post.text }}</p>
              <button v-if="post.text.length > 120" class="mm-expand" @click.stop="toggleExpand(post.id)">
                {{ expandedIds.has(post.id) ? '收起' : '展开' }}
              </button>

              <!-- 照片九宫格：1 张大图 / 2 张两列 / ≥3 张三列（最多展示 9 张） -->
              <div
                v-if="post.photos.length"
                class="mm-photos"
                :class="post.photos.length === 1 ? 'is-1' : post.photos.length === 2 ? 'is-2' : 'is-3'"
              >
                <img
                  v-for="url in post.photos.slice(0, 9)"
                  :key="url"
                  :src="resolveImageUrl(url) || ''"
                  :alt="post.title"
                  loading="lazy"
                />
              </div>
              <!-- 无照片纯文字卡：类型角标补位说明 -->
              <span v-else class="mm-textonly-badge">📝 纯文字</span>

              <!-- 标签行 -->
              <div v-if="post.tags.length" class="mm-tags">
                <span v-for="t in post.tags.slice(0, 4)" :key="t" class="mm-tag"># {{ t }}</span>
              </div>

              <!-- 互动行 -->
              <footer class="mm-meta">
                <span>👁 {{ post.view_count }}</span>
                <span class="mm-like">♥ {{ post.like_count }}</span>
                <span>💬 {{ post.comment_count }}</span>
                <button v-if="post.plan_id" class="mm-fork" @click.stop="handleFork(post)">🧭 照着走</button>
              </footer>
            </article>
          </div>

          <!-- 空状态 -->
          <div v-if="!loading && filteredPosts.length === 0" class="cl-empty">
            <span class="cl-empty-icon">📷</span>
            <p class="cl-empty-title">{{ activeTag ? '该标签下还没有动态' : '还没有人晒旅行' }}</p>
            <p class="cl-empty-sub">{{ activeTag ? '换个标签看看' : '来发第一张照片，让旅行圈热闹起来' }}</p>
            <button class="cl-share cl-share-plain" @click="openShare">📷 发第一张照片</button>
          </div>
        </div>

        <!-- 右栏：玩法引导 / 活跃旅行者 / 热门标签 -->
        <CommunityRail zone="circle" :users="topUsers" :tags="topTags" :active-tag="activeTag" @toggle-tag="toggleTag" />
      </div>

      <!-- 加载 / 到底提示 -->
      <div v-if="loading" class="cl-loading"><Spin /></div>
      <div v-else-if="!hasMore && posts.length > 0" class="cl-end">
        <span></span>到底啦 · 共 {{ total }} 条动态<span></span>
      </div>

      <!-- 晒一晒弹窗（精简版：照片 + 一句话 + 标签） -->
      <Modal
        :open="shareVisible"
        title="晒一晒"
        :confirm-loading="shareSubmitting"
        ok-text="晒出来"
        cancel-text="取消"
        :width="520"
        @ok="share"
        @cancel="closeShare"
      >
        <p class="share-label">照片（最多 9 张，jpg/png/webp/gif，单张 ≤ 5MB）</p>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">
          <div v-for="url in sharePhotos" :key="url" style="position: relative;">
            <img :src="resolveImageUrl(url) || ''" class="share-thumb" />
            <a
              style="position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; line-height: 18px; text-align: center; background: rgba(0,0,0,0.6); color: #fff; border-radius: 50%; font-size: 12px;"
              @click.prevent="removePhoto(url)"
            >×</a>
          </div>
          <Upload
            v-if="sharePhotos.length < 9"
            :show-upload-list="false"
            accept="image/jpeg,image/png,image/webp,image/gif"
            :custom-request="uploadPhoto"
          >
            <div class="share-add">+</div>
          </Upload>
        </div>
        <p class="share-label">说点什么（可选）</p>
        <Input.TextArea v-model:value="shareText" :rows="3" :maxlength="500" placeholder="一句话记录此刻的心情…" />
        <p class="share-label">标签（最多 5 个）</p>
        <Select
          v-model:value="shareTags"
          mode="tags"
          style="width: 100%"
          placeholder="如：海岛、美食、自驾，回车添加"
          :options="[]"
        />
      </Modal>
    </div>
  </div>
</template>

<style scoped>
/* ===== 页面容器：暖色底铺满内容区 ===== */
.circle-page {
  /* 负 margin 抵消 .app-content 的 padding，让底色铺满整个内容区 */
  margin: -28px -24px -56px;
  padding: 28px 24px 48px;
  background:
    radial-gradient(1000px 420px at 12% 4%, rgba(255, 111, 145, 0.1), transparent 60%),
    linear-gradient(180deg, #fdf0ec 0%, #f7f2ef 100%);
  min-height: calc(100vh - 60px);
}
.cl-inner {
  max-width: 1280px;
  margin: 0 auto;
}

/* ===== Hero 暖色渐变横幅 ===== */
.cl-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 24px 28px;
  border-radius: 20px;
  background: linear-gradient(120deg, #ff9a56 0%, #ff6f91 100%);
  box-shadow: 0 12px 32px rgba(255, 111, 145, 0.3);
  margin-bottom: 20px;
}
.cl-hero-copy h2 {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 800;
  color: #fff;
  letter-spacing: 1px;
}
.cl-hero-copy p {
  margin: 0;
  color: rgba(255, 255, 255, 0.88);
  font-size: 13.5px;
}
.cl-hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 1;
}
.cl-seg {
  display: flex;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.38);
  border-radius: 999px;
  padding: 4px;
  backdrop-filter: blur(6px);
}
.cl-seg button {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.88);
  font-size: 13.5px;
  font-weight: 600;
  padding: 6px 18px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.cl-seg button.on {
  background: #fff;
  color: #ff6f91;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}
.cl-share {
  border: none;
  background: #fff;
  color: #ff6f91;
  font-size: 14px;
  font-weight: 700;
  padding: 9px 20px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
}
.cl-share:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
}
.cl-share-plain {
  background: linear-gradient(120deg, #ff9a56, #ff6f91);
  color: #fff;
  box-shadow: 0 8px 20px rgba(255, 111, 145, 0.4);
}
.cl-hero-emoji {
  position: absolute;
  font-size: 64px;
  opacity: 0.22;
  user-select: none;
  pointer-events: none;
}
.cl-hero-emoji-1 {
  right: 220px;
  top: -12px;
  transform: rotate(-12deg);
}
.cl-hero-emoji-2 {
  left: 40%;
  bottom: -16px;
  transform: rotate(14deg);
}

/* ===== 主体两栏布局 ===== */
.cl-layout {
  display: flex;
  align-items: flex-start;
  gap: 20px;
}
.cl-feed-col {
  flex: 1;
  min-width: 0;
}

/* ===== 标签筛选提示条 ===== */
.cl-filter-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff1f0;
  border: 1px solid #ffd9d4;
  color: #b04a3a;
  font-size: 13px;
  border-radius: 12px;
  padding: 9px 14px;
  margin-bottom: 12px;
}
.cl-filter-hint button {
  margin-left: auto;
  border: none;
  background: #fff;
  color: #ff6f91;
  font-size: 12.5px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
}

/* ===== 双列瀑布流：columns 错落排布 ===== */
.cl-waterfall {
  columns: 2;
  column-gap: 16px;
}
@media (max-width: 720px) {
  .cl-waterfall {
    columns: 1;
  }
}

/* ===== MomentCard 朋友圈式卡片 ===== */
.moment {
  break-inside: avoid;
  background: #fff;
  border-radius: 16px;
  padding: 18px;
  margin-bottom: 16px;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(120, 60, 50, 0.06);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.moment:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 26px rgba(120, 60, 50, 0.14);
}

/* 头部：头像 + 昵称 + 时间 */
.mm-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.mm-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffc46b 0%, #ff6f91 100%);
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.mm-head-main {
  min-width: 0;
}
.mm-head-main b {
  display: block;
  font-size: 14.5px;
  color: #1f2a37;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mm-head-main span {
  display: block;
  font-size: 12px;
  color: #b3bdc9;
}

/* 文字：最多 4 行，展开后不限 */
.mm-text {
  margin: 0 0 8px;
  font-size: 14px;
  color: #333f4e;
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-line;
}
.mm-text.expanded {
  display: block;
  -webkit-line-clamp: unset;
}
.mm-expand {
  border: none;
  background: transparent;
  color: #ff6f91;
  font-size: 13px;
  font-weight: 600;
  padding: 0;
  margin: -4px 0 8px;
  cursor: pointer;
}

/* 照片九宫格 */
.mm-photos {
  display: grid;
  gap: 4px;
  border-radius: 12px;
  overflow: hidden;
}
.mm-photos img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  background: #f3ece9;
  transition: transform 0.25s ease;
}
.mm-photos img:hover {
  transform: scale(1.03);
}
/* 1 张：大图，限高 320px */
.mm-photos.is-1 {
  grid-template-columns: 1fr;
}
.mm-photos.is-1 img {
  max-height: 320px;
  border-radius: 12px;
}
/* 2 张：两列方图 */
.mm-photos.is-2 {
  grid-template-columns: repeat(2, 1fr);
}
.mm-photos.is-2 img {
  aspect-ratio: 1 / 1;
}
/* ≥3 张：三列方图 */
.mm-photos.is-3 {
  grid-template-columns: repeat(3, 1fr);
}
.mm-photos.is-3 img {
  aspect-ratio: 1 / 1;
}
/* 纯文字卡角标 */
.mm-textonly-badge {
  display: inline-block;
  font-size: 12px;
  color: #b3bdc9;
  background: #f6f4f2;
  border-radius: 999px;
  padding: 3px 10px;
  margin-bottom: 4px;
}

/* 标签行 */
.mm-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.mm-tag {
  font-size: 12px;
  color: #ff6f91;
  background: #fff1f0;
  padding: 1px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

/* 互动行 */
.mm-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #f4efec;
  font-size: 12.5px;
  color: #a8b3c4;
  white-space: nowrap;
}
.mm-like {
  color: #f0627d;
}
.mm-fork {
  margin-left: auto;
  border: 1px solid #ffd0c4;
  background: #fff7f4;
  color: #ff6f91;
  font-size: 12.5px;
  font-weight: 700;
  padding: 5px 13px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}
.mm-fork:hover {
  background: #ff6f91;
  border-color: #ff6f91;
  color: #fff;
}

/* ===== 空状态 ===== */
.cl-empty {
  text-align: center;
  padding: 64px 0 52px;
}
.cl-empty-icon {
  display: inline-block;
  font-size: 64px;
  margin-bottom: 12px;
  animation: cl-float 3s ease-in-out infinite;
}
@keyframes cl-float {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-8px);
  }
}
.cl-empty-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #1f2a37;
}
.cl-empty-sub {
  margin: 6px 0 20px;
  font-size: 13.5px;
  color: #98a3b3;
}

/* ===== 加载 / 到底 ===== */
.cl-loading {
  text-align: center;
  padding: 28px 0;
}
.cl-end {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #c4aea6;
  font-size: 12.5px;
  padding: 20px 0 4px;
}
.cl-end span {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #ecdfd9, transparent);
}

/* ===== 晒一晒弹窗内样式 ===== */
.share-label {
  font-weight: 600;
  margin: 12px 0 6px;
}
.share-label:first-child {
  margin-top: 0;
}
.share-thumb {
  width: 88px;
  height: 88px;
  object-fit: cover;
  border-radius: 8px;
  display: block;
}
.share-add {
  width: 88px;
  height: 88px;
  border: 1px dashed #d9d9d9;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #999;
  cursor: pointer;
}

/* ===== 窄屏适配 ===== */
@media (max-width: 640px) {
  .circle-page {
    margin: -16px -12px -40px;
    padding: 16px 12px 40px;
  }
  .cl-hero {
    padding: 20px;
  }
  .cl-hero-emoji {
    display: none;
  }
}
</style>
