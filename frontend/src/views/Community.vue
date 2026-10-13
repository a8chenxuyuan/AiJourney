<!--
  src/views/Community.vue：社区广场
  作用：最新/热门双排序 feed（滚动加载）+ 发布弹窗（手动图文/关联行程/图片上传）
  设计：列表流布局（一条一条，适合文字为主的沉浸阅读）+ 右侧信息栏（玩法引导/
       热门标签/社区数据）填充版面；帖子卡完整七要素：类型角标、标题、摘要、
       标签、作者、相对时间、浏览/点赞/评论数 + 封面缩略图
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted, onUnmounted } from 'vue'
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

// activeTag：热门标签点击后的客户端筛选（仅作用于已加载内容，提示条中明确说明）
const activeTag = ref<string | null>(null)

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
 * typeMeta：帖子类型 → 角标文案与配色 class
 */
const typeMeta: Record<string, { label: string; cls: string }> = {
  journal: { label: '游记', cls: 'is-journal' },
  route: { label: '路线', cls: 'is-route' },
  manual: { label: '图文', cls: 'is-manual' }
}

// filteredPosts：应用标签筛选后的列表（无筛选时与 posts 相同）
const filteredPosts = computed(() =>
  activeTag.value ? posts.value.filter((p) => p.tags.includes(activeTag.value!)) : posts.value
)

// topTags：聚合已加载帖子的标签计数，取前 8
const topTags = computed(() => {
  const m = new Map<string, number>()
  posts.value.forEach((p) => p.tags.forEach((t) => m.set(t, (m.get(t) || 0) + 1)))
  return [...m.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, count]) => ({ name, count }))
})

// 社区数据卡：笔记用服务端 total；浏览/点赞/可照着走基于已加载内容聚合
const sumViews = computed(() => posts.value.reduce((s, p) => s + p.view_count, 0))
const sumLikes = computed(() => posts.value.reduce((s, p) => s + p.like_count, 0))
const forkableCount = computed(() => posts.value.filter((p) => p.plan_id).length)

/**
 * toggleTag：切换标签筛选
 */
const toggleTag = (name: string) => {
  activeTag.value = activeTag.value === name ? null : name
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
 * changeSort：切换排序，重置列表与标签筛选
 */
const changeSort = () => {
  activeTag.value = null
  loadFeed(true)
}

/**
 * goDetail：进入帖子详情
 */
const goDetail = (id: string) => router.push(`/community/${id}`)

// ==================== 照着走（列表快捷入口） ====================

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

    <!-- 主体两栏：左列表 + 右信息栏 -->
    <div class="cm-layout">
      <!-- 左列：帖子列表（一条一条） -->
      <div class="cm-list-col">
        <!-- 标签筛选提示条 -->
        <div v-if="activeTag" class="cm-filter-hint">
          按标签「<b>{{ activeTag }}</b>」筛选 · 匹配 {{ filteredPosts.length }} 条
          <button @click="activeTag = null">清除</button>
        </div>

        <article
          v-for="post in filteredPosts"
          :key="post.id"
          class="cm-item"
          @click="goDetail(post.id)"
        >
          <!-- 作者头像 -->
          <span class="ci-avatar">{{ (post.author || '旅').charAt(0).toUpperCase() }}</span>

          <!-- 中部内容区 -->
          <div class="ci-main">
            <div class="ci-title-row">
              <span class="ci-type" :class="typeMeta[post.post_type]?.cls || 'is-manual'">
                {{ typeMeta[post.post_type]?.label || '图文' }}
              </span>
              <h3 class="ci-title">{{ post.title }}</h3>
            </div>
            <p v-if="post.summary" class="ci-summary">{{ post.summary }}</p>
            <div v-if="post.tags.length" class="ci-tags">
              <span v-for="t in post.tags.slice(0, 4)" :key="t" class="ci-tag"># {{ t }}</span>
            </div>
            <div class="ci-meta">
              <span class="ci-author">{{ post.author }}</span>
              <span class="ci-sep">·</span>
              <span>{{ relTime(post.created_at) }}</span>
              <span class="ci-stat">👁 {{ post.view_count }}</span>
              <span class="ci-stat ci-stat-like">♥ {{ post.like_count }}</span>
              <span class="ci-stat">💬 {{ post.comment_count }}</span>
              <button v-if="post.plan_id" class="ci-fork" @click.stop="handleFork(post)">
                🧭 照着走
              </button>
            </div>
          </div>

          <!-- 右侧封面缩略图（无封面不占位） -->
          <img
            v-if="post.cover_url"
            class="ci-cover"
            :src="resolveImageUrl(post.cover_url) || ''"
            :alt="post.title"
            loading="lazy"
          />
        </article>

        <!-- 空状态 -->
        <div v-if="!loading && filteredPosts.length === 0" class="cm-empty">
          <span class="cm-empty-icon">🧳</span>
          <p class="cm-empty-title">{{ activeTag ? '该标签下还没有内容' : '社区还空着' }}</p>
          <p class="cm-empty-sub">{{ activeTag ? '换个标签看看，或发布第一篇' : '发布第一篇旅行笔记，让别人照着你的路线走' }}</p>
          <button class="cm-publish cm-publish-plain" @click="openPublish">✏️ 发布第一篇</button>
        </div>
      </div>

      <!-- 右列：信息栏 -->
      <aside class="cm-rail">
        <!-- 社区玩法引导 -->
        <section class="rail-card">
          <h4>社区怎么玩</h4>
          <ol class="rail-steps">
            <li><i>1</i><div><b>规划行程</b><span>AI 帮你定制路线</span></div></li>
            <li><i>2</i><div><b>行中打卡</b><span>记录足迹与照片</span></div></li>
            <li><i>3</i><div><b>生成游记</b><span>AI 一键写好图文</span></div></li>
            <li><i>4</i><div><b>发布 · 照着走</b><span>把路线分享给他人</span></div></li>
          </ol>
        </section>

        <!-- 热门标签 -->
        <section class="rail-card">
          <h4>热门标签</h4>
          <div v-if="topTags.length" class="rail-tags">
            <button
              v-for="t in topTags"
              :key="t.name"
              :class="{ on: activeTag === t.name }"
              @click="toggleTag(t.name)"
            ># {{ t.name }}<i>{{ t.count }}</i></button>
          </div>
          <p v-else class="rail-empty">发帖时添加标签，就会出现在这里</p>
        </section>

        <!-- 社区数据 -->
        <section class="rail-card">
          <h4>社区数据</h4>
          <div class="rail-stats">
            <div><b>{{ total }}</b><span>笔记</span></div>
            <div><b>{{ sumViews }}</b><span>浏览</span></div>
            <div><b>{{ sumLikes }}</b><span>点赞</span></div>
            <div><b>{{ forkableCount }}</b><span>可照着走</span></div>
          </div>
          <p class="rail-note">浏览 / 点赞基于当前已加载内容统计</p>
        </section>
      </aside>
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
  max-width: 1100px;
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
  padding: 24px 28px;
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
.cm-publish-plain {
  background: var(--grad-primary, #1677ff);
  color: #fff;
  box-shadow: 0 8px 20px rgba(22, 119, 255, 0.35);
}
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

/* ===== 主体两栏布局 ===== */
.cm-layout {
  display: flex;
  align-items: flex-start;
  gap: 20px;
}
.cm-list-col {
  flex: 1;
  min-width: 0;
}
.cm-rail {
  width: 292px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 16px;
}
@media (max-width: 1080px) {
  .cm-rail {
    display: none;
  }
}

/* ===== 标签筛选提示条 ===== */
.cm-filter-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #e8f3ff;
  border: 1px solid #cfe5ff;
  color: #2f5c8f;
  font-size: 13px;
  border-radius: 12px;
  padding: 9px 14px;
  margin-bottom: 12px;
}
.cm-filter-hint button {
  margin-left: auto;
  border: none;
  background: #fff;
  color: #1677ff;
  font-size: 12.5px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
}

/* ===== 列表流帖子卡（一条一条） ===== */
.cm-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  background: #fff;
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 12px;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.05);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.cm-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 26px rgba(31, 56, 88, 0.12);
}
/* 作者头像（渐变圆） */
.ci-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb199 0%, #ff6f91 100%);
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
/* 中部内容 */
.ci-main {
  flex: 1;
  min-width: 0;
}
.ci-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
/* 类型角标配色 */
.ci-type {
  flex-shrink: 0;
  font-size: 11.5px;
  font-weight: 700;
  padding: 2px 9px;
  border-radius: 999px;
}
.ci-type.is-journal {
  color: #e0447c;
  background: #ffe8ef;
}
.ci-type.is-route {
  color: #1677ff;
  background: #e6f3ff;
}
.ci-type.is-manual {
  color: #0f9d58;
  background: #e5f7ec;
}
.ci-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #1f2a37;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s ease;
}
.cm-item:hover .ci-title {
  color: #1677ff;
}
.ci-summary {
  margin: 6px 0 0;
  font-size: 13px;
  color: #7a8699;
  line-height: 1.65;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ci-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.ci-tag {
  font-size: 12px;
  color: #1677ff;
  background: #f0f6ff;
  padding: 1px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
/* 底部元信息行 */
.ci-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 10px;
  font-size: 12.5px;
  color: #98a3b3;
  white-space: nowrap;
}
.ci-author {
  color: #4b5768;
  font-weight: 600;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ci-sep {
  color: #c9d2dd;
}
.ci-stat {
  flex-shrink: 0;
}
.ci-stat-like {
  color: #f0627d;
}
.ci-fork {
  margin-left: auto;
  border: 1px solid #cfe0ff;
  background: #f5f9ff;
  color: #1677ff;
  font-size: 12.5px;
  font-weight: 700;
  padding: 5px 13px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}
.ci-fork:hover {
  background: #1677ff;
  border-color: #1677ff;
  color: #fff;
}
/* 右侧封面缩略图 */
.ci-cover {
  width: 172px;
  height: 116px;
  object-fit: cover;
  border-radius: 10px;
  flex-shrink: 0;
  background: #eef2f7;
}

/* ===== 右侧信息栏 ===== */
.rail-card {
  background: #fff;
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.05);
}
.rail-card h4 {
  margin: 0 0 14px;
  font-size: 14.5px;
  font-weight: 700;
  color: #1f2a37;
}
/* 玩法步骤 */
.rail-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rail-steps li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rail-steps i {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1677ff, #0aa5c2);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  font-style: normal;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.rail-steps b {
  display: block;
  font-size: 13.5px;
  color: #1f2a37;
}
.rail-steps span {
  display: block;
  font-size: 12px;
  color: #98a3b3;
}
/* 热门标签 */
.rail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.rail-tags button {
  border: 1px solid #e3ecf5;
  background: #f7fafd;
  color: #4b5768;
  font-size: 12.5px;
  padding: 5px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.rail-tags button i {
  font-style: normal;
  color: #b3bdc9;
  margin-left: 4px;
  font-size: 11.5px;
}
.rail-tags button:hover {
  border-color: #9dc6ff;
  color: #1677ff;
}
.rail-tags button.on {
  background: #1677ff;
  border-color: #1677ff;
  color: #fff;
}
.rail-tags button.on i {
  color: rgba(255, 255, 255, 0.7);
}
.rail-empty {
  margin: 0;
  font-size: 12.5px;
  color: #b3bdc9;
  line-height: 1.6;
}
/* 社区数据 */
.rail-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.rail-stats b {
  display: block;
  font-size: 17px;
  font-weight: 800;
  color: #1f2a37;
}
.rail-stats span {
  display: block;
  font-size: 11.5px;
  color: #98a3b3;
  margin-top: 2px;
}
.rail-note {
  margin: 12px 0 0;
  font-size: 11.5px;
  color: #c0c9d4;
}

/* ===== 空状态 ===== */
.cm-empty {
  text-align: center;
  padding: 64px 0 52px;
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
  .ci-cover {
    width: 116px;
    height: 84px;
  }
  .ci-summary {
    -webkit-line-clamp: 1;
  }
}
</style>
