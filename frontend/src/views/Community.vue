<!--
  src/views/Community.vue：社区广场
  作用：最新/热门双排序 feed（滚动加载）+ 发布弹窗（手动图文/关联行程/图片上传）
  设计：参考小红书双列瀑布流范式——大封面卡片（游记/路线/图文角标）、
       标题两行截断、作者+相对时间+互动数四要素，浅灰蓝底衬托白卡
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, onMounted, onUnmounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Input, Select, Modal, Upload, Spin, message } from 'ant-design-vue'
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
// 引入行程 API（发布弹窗关联行程下拉）
import { getMyPlans } from '@/api/trip'

const router = useRouter()

// ==================== feed 列表 ====================

// sort：排序方式；posts：已加载卡片；total/hasMore/loading：分页滚动加载状态
const sort = ref<'latest' | 'hot'>('latest')
const posts = ref<PostItem[]>([])
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)

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

/**
 * typeMeta：帖子类型 → 角标文案 / 占位图配色 / 占位 emoji
 */
const typeMeta: Record<string, { label: string; cls: string; emoji: string }> = {
  journal: { label: '游记', cls: 'is-journal', emoji: '📖' },
  route: { label: '路线', cls: 'is-route', emoji: '🗺️' },
  manual: { label: '图文', cls: 'is-manual', emoji: '📸' }
}

/**
 * loadFeed：拉取 feed（reset=true 换排序/发布后回到第一页）
 */
const loadFeed = async (reset = false) => {
  if (loading.value) return
  loading.value = true
  try {
    const page = reset ? 1 : posts.value.length / 10 + 1
    const res = await getFeed(sort.value, page, 10)
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
 * changeSort：切换排序，重置列表
 */
const changeSort = () => loadFeed(true)

/**
 * goDetail：进入帖子详情
 */
const goDetail = (id: string) => router.push(`/community/${id}`)

// ==================== 照着走（封面角标快捷入口） ====================

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

// ==================== 发布弹窗 ====================

// pubVisible：弹窗显隐；其余为发布草稿字段
const pubVisible = ref(false)
const pubTitle = ref('')
const pubText = ref('')
const pubTags = ref<string[]>([])
const pubPhotos = ref<string[]>([])
const pubCover = ref('')
const pubPlanId = ref<string | undefined>(undefined)
const pubSubmitting = ref(false)
const pubUploading = ref(false)

// planOptions：可关联的已完成行程下拉
const planOptions = ref<Array<{ label: string; value: string }>>([])

/**
 * openPublish：打开发布弹窗，并拉取可关联的已完成行程
 */
const openPublish = async () => {
  pubVisible.value = true
  try {
    const res = await getMyPlans()
    if (res.success && res.data) {
      planOptions.value = (res.data.plans || [])
        .filter((p) => p.status === 'completed')
        .map((p) => ({ label: `${p.city} · ${p.start_date} ~ ${p.end_date}`, value: p.plan_id }))
    }
  } catch {
    // 关联行程拉取失败不阻塞发帖
  }
}

/**
 * closePublish：关闭弹窗并清空草稿
 */
const closePublish = () => {
  pubVisible.value = false
  pubTitle.value = ''
  pubText.value = ''
  pubTags.value = []
  pubPhotos.value = []
  pubCover.value = ''
  pubPlanId.value = undefined
}

/**
 * uploadPhoto：照片多选上传（customRequest 逐个触发），成功记录相对 URL
 */
const uploadPhoto = async (options: {
  file: unknown
  onSuccess?: (body?: unknown) => void
  onError?: (e: Error) => void
}) => {
  pubUploading.value = true
  try {
    const res = await uploadImage(options.file as File)
    if (res.success && res.data) {
      pubPhotos.value.push(res.data.url)
      options.onSuccess?.(res.data)
    } else {
      options.onError?.(new Error(res.message || '上传失败'))
    }
  } catch (e) {
    options.onError?.(e as Error)
  } finally {
    pubUploading.value = false
  }
}

/**
 * uploadCover：封面单选上传（覆盖旧值）
 */
const uploadCover = async (options: {
  file: unknown
  onSuccess?: (body?: unknown) => void
  onError?: (e: Error) => void
}) => {
  try {
    const res = await uploadImage(options.file as File)
    if (res.success && res.data) {
      pubCover.value = res.data.url
      options.onSuccess?.(res.data)
    } else {
      options.onError?.(new Error(res.message || '上传失败'))
    }
  } catch (e) {
    options.onError?.(e as Error)
  }
}

/**
 * removePhoto：移除已上传照片（同时清掉引用它的封面）
 */
const removePhoto = (url: string) => {
  pubPhotos.value = pubPhotos.value.filter((p) => p !== url)
  if (pubCover.value === url) pubCover.value = ''
}

/**
 * publish：提交发布（有照片用 sections 携带图片，否则走纯文本；未选封面默认第一张照片）
 */
const publish = async () => {
  const title = pubTitle.value.trim()
  if (!title) {
    message.warning('请填写帖子标题')
    return
  }
  const text = pubText.value.trim()
  if (!text && pubPhotos.value.length === 0) {
    message.warning('写点正文或上传至少一张图片')
    return
  }
  pubSubmitting.value = true
  try {
    const params: CreatePostParams = {
      title,
      tags: pubTags.value,
      plan_id: pubPlanId.value
    }
    if (pubPhotos.value.length) {
      params.sections = [
        { day_index: null, title, text, photos: [...pubPhotos.value] }
      ]
      params.cover_url = pubCover.value || pubPhotos.value[0]
    } else {
      params.text = text
      params.cover_url = pubCover.value || null
    }
    const res = await createPost(params)
    if (res.success) {
      message.success('发布成功')
      closePublish()
      loadFeed(true)
    }
  } catch {
    // 请求层已统一提示
  } finally {
    pubSubmitting.value = false
  }
}

onMounted(() => {
  loadFeed(true)
  window.addEventListener('scroll', onScroll)
})
onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<template>
  <div class="page-fade community-page">
    <!-- 顶部 Hero：渐变横幅 + 排序 + 发布 -->
    <section class="cm-hero">
      <div class="cm-hero-copy">
        <h2>旅行社区</h2>
        <p>看看别人怎么玩 · 把好路线一键抄回家</p>
      </div>
      <div class="cm-hero-actions">
        <div class="cm-seg">
          <button :class="{ on: sort === 'latest' }" @click="((sort = 'latest'), changeSort())">最新</button>
          <button :class="{ on: sort === 'hot' }" @click="((sort = 'hot'), changeSort())">热门</button>
        </div>
        <button class="cm-publish" @click="openPublish">✏️ 发布笔记</button>
      </div>
      <span class="cm-hero-emoji cm-hero-emoji-1">🌏</span>
      <span class="cm-hero-emoji cm-hero-emoji-2">🧭</span>
    </section>

    <!-- 双列瀑布流卡片 -->
    <div class="cm-masonry">
      <article v-for="post in posts" :key="post.id" class="cm-card" @click="goDetail(post.id)">
        <!-- 封面：真实图按原比例展示，无封面用类型渐变占位 -->
        <div class="cm-cover" :class="!post.cover_url ? typeMeta[post.post_type]?.cls || 'is-manual' : ''">
          <img
            v-if="post.cover_url"
            :src="resolveImageUrl(post.cover_url) || ''"
            :alt="post.title"
            loading="lazy"
          />
          <span v-else class="cm-cover-ph">{{ typeMeta[post.post_type]?.emoji || '📸' }}</span>
          <span class="cm-badge">{{ typeMeta[post.post_type]?.label || '图文' }}</span>
          <button v-if="post.plan_id" class="cm-fork" @click.stop="handleFork(post)">🧭 照着走</button>
        </div>

        <!-- 卡片信息：标题 / 摘要 / 标签 / 作者与互动 -->
        <div class="cm-body">
          <h3 class="cm-title">{{ post.title }}</h3>
          <p v-if="post.summary" class="cm-summary">{{ post.summary }}</p>
          <div v-if="post.tags.length" class="cm-tags">
            <span v-for="t in post.tags.slice(0, 3)" :key="t" class="cm-tag"># {{ t }}</span>
          </div>
          <div class="cm-foot">
            <span class="cm-avatar">{{ (post.author || '旅').charAt(0).toUpperCase() }}</span>
            <span class="cm-author">{{ post.author }}</span>
            <span class="cm-time">{{ relTime(post.created_at) }}</span>
            <span class="cm-stat">♥ {{ post.like_count }}</span>
            <span class="cm-stat">💬 {{ post.comment_count }}</span>
          </div>
        </div>
      </article>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && posts.length === 0" class="cm-empty">
      <span class="cm-empty-icon">🧳</span>
      <p class="cm-empty-title">社区还空着</p>
      <p class="cm-empty-sub">发布第一篇旅行笔记，让别人照着你的路线走</p>
      <button class="cm-publish" @click="openPublish">✏️ 发布第一篇</button>
    </div>

    <!-- 加载 / 到底提示 -->
    <div v-if="loading" class="cm-loading"><Spin /></div>
    <div v-else-if="!hasMore && posts.length > 0" class="cm-end">
      <span></span>到底啦 · 共 {{ total }} 篇<span></span>
    </div>

    <!-- 发布弹窗 -->
    <Modal
      :open="pubVisible"
      title="发布笔记"
      :confirm-loading="pubSubmitting"
      ok-text="发布"
      cancel-text="取消"
      :width="560"
      @ok="publish"
      @cancel="closePublish"
    >
      <p class="pub-label">标题</p>
      <Input v-model:value="pubTitle" :maxlength="100" placeholder="给笔记起个吸引人的标题" />
      <p class="pub-label">正文</p>
      <Input.TextArea v-model:value="pubText" :rows="4" :maxlength="5000" placeholder="分享你的旅行故事、攻略心得…" />
      <p class="pub-label">标签（最多 5 个）</p>
      <Select
        v-model:value="pubTags"
        mode="tags"
        style="width: 100%"
        placeholder="如：美食、亲子、西湖，回车添加"
        :options="[]"
      />
      <p class="pub-label">照片（jpg/png/webp/gif，单张 ≤ 5MB）</p>
      <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">
        <div v-for="url in pubPhotos" :key="url" style="position: relative;">
          <img :src="resolveImageUrl(url) || ''" class="pub-thumb" />
          <a
            style="position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; line-height: 18px; text-align: center; background: rgba(0,0,0,0.6); color: #fff; border-radius: 50%; font-size: 12px;"
            @click.prevent="removePhoto(url)"
          >×</a>
        </div>
        <Upload
          v-if="pubPhotos.length < 9"
          :show-upload-list="false"
          accept="image/jpeg,image/png,image/webp,image/gif"
          :custom-request="uploadPhoto"
        >
          <div class="pub-add">+</div>
        </Upload>
      </div>
      <p class="pub-label">封面（可选，默认第一张照片）</p>
      <div style="display: flex; gap: 8px; align-items: center;">
        <img v-if="pubCover" :src="resolveImageUrl(pubCover) || ''" class="pub-thumb" />
        <Upload
          v-else
          :show-upload-list="false"
          accept="image/jpeg,image/png,image/webp,image/gif"
          :custom-request="uploadCover"
        >
          <div class="pub-add">+</div>
        </Upload>
        <Button v-if="pubCover" size="small" @click="pubCover = ''">移除封面</Button>
      </div>
      <p class="pub-label">关联行程（可选，供他人「照着走」）</p>
      <Select
        v-model:value="pubPlanId"
        style="width: 100%"
        placeholder="选择一份已完成的行程"
        allow-clear
        :options="planOptions"
      />
    </Modal>
  </div>
</template>

<style scoped>
/* ===== 页面容器：浅灰蓝底衬托白卡 ===== */
.community-page {
  max-width: 960px;
  margin: 0 auto;
  background: #f4f7fb;
  border-radius: 24px;
  padding: 20px 20px 28px;
}

/* ===== Hero 渐变横幅 ===== */
.cm-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 26px 28px;
  border-radius: 20px;
  background: linear-gradient(120deg, #1677ff 0%, #0aa5c2 100%);
  box-shadow: 0 12px 32px rgba(22, 119, 255, 0.28);
  margin-bottom: 20px;
}
.cm-hero-copy h2 {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 800;
  color: #fff;
  letter-spacing: 1px;
}
.cm-hero-copy p {
  margin: 0;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13.5px;
}
.cm-hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 1;
}
/* 排序分段控件（白底胶囊） */
.cm-seg {
  display: flex;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  padding: 4px;
  backdrop-filter: blur(6px);
}
.cm-seg button {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13.5px;
  font-weight: 600;
  padding: 6px 18px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.cm-seg button.on {
  background: #fff;
  color: #1677ff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}
/* 发布按钮（白色高对比 CTA） */
.cm-publish {
  border: none;
  background: #fff;
  color: #1677ff;
  font-size: 14px;
  font-weight: 700;
  padding: 9px 20px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
}
.cm-publish:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
}
/* Hero 装饰 emoji */
.cm-hero-emoji {
  position: absolute;
  font-size: 64px;
  opacity: 0.22;
  user-select: none;
  pointer-events: none;
}
.cm-hero-emoji-1 {
  right: 220px;
  top: -12px;
  transform: rotate(-12deg);
}
.cm-hero-emoji-2 {
  left: 40%;
  bottom: -16px;
  transform: rotate(14deg);
}

/* ===== 双列瀑布流 ===== */
.cm-masonry {
  columns: 3 300px;
  column-gap: 16px;
}
.cm-card {
  break-inside: avoid;
  margin-bottom: 16px;
  background: #fff;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.06);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.cm-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 28px rgba(31, 56, 88, 0.14);
}

/* 封面区：真实图自然高度，占位图 4:3 渐变 */
.cm-cover {
  position: relative;
  overflow: hidden;
  background: #eef2f7;
}
.cm-cover img {
  display: block;
  width: 100%;
  max-height: 320px;
  object-fit: cover;
  transition: transform 0.25s ease;
}
.cm-card:hover .cm-cover img {
  transform: scale(1.04);
}
.cm-cover-ph {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 4 / 3;
  font-size: 52px;
}
/* 类型专属渐变占位底色 */
.cm-cover.is-journal {
  background: linear-gradient(135deg, #ffe8e0 0%, #ffd6e8 100%);
}
.cm-cover.is-route {
  background: linear-gradient(135deg, #dceeff 0%, #c9f0f7 100%);
}
.cm-cover.is-manual {
  background: linear-gradient(135deg, #e2f7e9 0%, #d3f1f0 100%);
}
/* 类型角标（左上） */
.cm-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: rgba(31, 56, 88, 0.45);
  backdrop-filter: blur(6px);
}
/* 照着走角标（右下，毛玻璃） */
.cm-fork {
  position: absolute;
  right: 10px;
  bottom: 10px;
  border: none;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 700;
  color: #1677ff;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(6px);
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
}
.cm-fork:hover {
  background: #1677ff;
  color: #fff;
}

/* 卡片信息区 */
.cm-body {
  padding: 12px 14px 12px;
}
.cm-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #1f2a37;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cm-summary {
  margin: 6px 0 0;
  font-size: 13px;
  color: #7a8699;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cm-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.cm-tag {
  font-size: 12px;
  color: #1677ff;
  background: #eaf3ff;
  padding: 2px 9px;
  border-radius: 999px;
  white-space: nowrap;
}
/* 作者 + 互动行 */
.cm-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-size: 12.5px;
  color: #98a3b3;
}
.cm-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb199 0%, #ff6f91 100%);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.cm-author {
  color: #4b5768;
  font-weight: 600;
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cm-time {
  flex: 1;
  min-width: 0;
}
.cm-stat {
  white-space: nowrap;
}

/* ===== 空状态 ===== */
.cm-empty {
  text-align: center;
  padding: 72px 0 60px;
}
.cm-empty-icon {
  display: inline-block;
  font-size: 64px;
  margin-bottom: 12px;
  animation: cm-float 3s ease-in-out infinite;
}
@keyframes cm-float {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-8px);
  }
}
.cm-empty-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #1f2a37;
}
.cm-empty-sub {
  margin: 6px 0 20px;
  font-size: 13.5px;
  color: #98a3b3;
}

/* ===== 加载 / 到底 ===== */
.cm-loading {
  text-align: center;
  padding: 28px 0;
}
.cm-end {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #a8b3c4;
  font-size: 12.5px;
  padding: 20px 0 4px;
}
.cm-end span {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #dde5ef, transparent);
}

/* ===== 发布弹窗内复用样式 ===== */
.pub-label {
  font-weight: 600;
  margin: 12px 0 6px;
}
.pub-label:first-child {
  margin-top: 0;
}
.pub-thumb {
  width: 88px;
  height: 88px;
  object-fit: cover;
  border-radius: 8px;
  display: block;
}
.pub-add {
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
  .community-page {
    padding: 12px 12px 20px;
    border-radius: 16px;
  }
  .cm-hero {
    padding: 20px;
  }
  .cm-hero-emoji {
    display: none;
  }
}
</style>
