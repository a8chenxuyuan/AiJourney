<!--
  src/views/PostDetail.vue：帖子详情
  作用：分节图文展示、点赞、两级评论、作者删帖、照着走（复制关联行程）
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted } from 'vue'
// 引入路由
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Spin, Input, Modal, Popconfirm, Image as AImage, message } from 'ant-design-vue'
// 引入社区 API 与类型
import {
  getPost,
  deletePost,
  likePost,
  unlikePost,
  getComments,
  addComment,
  forkPost,
  resolveImageUrl,
  type PostDetail as PostDetailData,
  type CommentItem
} from '@/api/community'
// 引入用户认证 store（判断是否作者本人）
import { useAuthStore } from '@/stores/auth'
// 引入社交 API：侧栏作者卡复用用户主页接口
import { getUserProfile, type UserProfileData } from '@/api/social'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// postId：帖子 ID
const postId = route.params.id as string

// post：帖子详情；comments：评论列表；loading：首次加载
const post = ref<PostDetailData | null>(null)
const comments = ref<CommentItem[]>([])
const loading = ref(true)

/**
 * fmtTime：created_at → "YYYY-MM-DD HH:mm"
 */
const fmtTime = (s: string) => (s ? s.replace('T', ' ').slice(0, 16) : '')

/**
 * fetchPost：拉取帖子详情
 */
const fetchPost = async () => {
  try {
    const res = await getPost(postId)
    if (res.success && res.data) {
      post.value = res.data
      heroFailed.value = false
      loadProfile(res.data.user_id)
    }
  } catch {
    // 请求层已统一提示
  } finally {
    loading.value = false
  }
}

/**
 * fetchComments：拉取评论列表
 */
const fetchComments = async () => {
  try {
    const res = await getComments(postId)
    if (res.success && res.data) comments.value = res.data.comments
  } catch {
    // 请求层已统一提示
  }
}

// ==================== 点赞 ====================

/**
 * toggleLike：未赞点赞 / 已赞取消，用后端返回值同步状态
 */
const toggleLike = async () => {
  if (!post.value) return
  try {
    const res = post.value.liked ? await unlikePost(postId) : await likePost(postId)
    if (res.success && res.data) {
      post.value.liked = res.data.liked
      post.value.like_count = res.data.like_count
    }
  } catch {
    // 请求层已统一提示
  }
}

// ==================== 评论 ====================

// commentText：顶级评论输入；replyTo/replyText：楼中楼回复目标与输入
const commentText = ref('')
const replyTo = ref<CommentItem | null>(null)
const replyText = ref('')
const commentSubmitting = ref(false)

/**
 * startReply / cancelReply：进入/退出回复某条顶级评论
 */
const startReply = (c: CommentItem) => {
  replyTo.value = c
  replyText.value = ''
}
const cancelReply = () => {
  replyTo.value = null
  replyText.value = ''
}

/**
 * sendComment：提交顶级评论或回复，成功后重拉列表并本地 +1 计数
 */
const sendComment = async () => {
  const content = (replyTo.value ? replyText.value : commentText.value).trim()
  if (!content) return
  commentSubmitting.value = true
  try {
    const res = replyTo.value
      ? await addComment(postId, content, replyTo.value.id)
      : await addComment(postId, content)
    if (res.success) {
      if (replyTo.value) cancelReply()
      else commentText.value = ''
      if (post.value) post.value.comment_count += 1
      await fetchComments()
    }
  } catch {
    // 请求层已统一提示
  } finally {
    commentSubmitting.value = false
  }
}

// ==================== 删帖（仅作者） ====================

/**
 * 智能返回：按浏览来源回上一页。
 * 管理后台审核进入 → 返回内容审核 Tab；其余来源统一「返回」回上一页；
 * 无浏览历史（直接输链接进入）时回落到旅行圈照片墙。
 */
const prevPath = window.history.state?.back as string | null
const backText = prevPath?.startsWith('/admin') ? '返回内容审核' : '返回'
const goBack = () =>
  prevPath?.startsWith('/admin')
    ? router.push('/admin?tab=posts')
    : prevPath
      ? router.back()
      : router.push('/circle')

/**
 * handleDelete：删除后返回所属分区列表
 */
const handleDelete = async () => {
  try {
    const res = await deletePost(postId)
    if (res.success) {
      message.success('帖子已删除')
      goBack()
    }
  } catch {
    // 请求层已统一提示
  }
}

// ==================== 照着走 ====================

/**
 * handleFork：确认后复制关联行程，成功跳转新行程详情
 */
const handleFork = () => {
  if (!post.value?.plan_id) return
  Modal.confirm({
    title: '照着走这条路线？',
    content: '将把该帖关联的行程复制到我的账户（若原行程日期已过去，会自动平移到明天开始）。',
    okText: '复制行程',
    cancelText: '再想想',
    onOk: async () => {
      try {
        const res = await forkPost(postId)
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

onMounted(() => {
  fetchPost()
  fetchComments()
})

// ==================== 视觉辅助 ====================

/**
 * onImgErr：图片加载失败时隐藏 img，露出容器渐变占位（避免破图图标）
 * 兼容原生 img（Event）与 AImage（string | Event）两种 error 签名
 */
const onImgErr = (e: string | Event) => {
  const target = (e as Event)?.target as HTMLImageElement | undefined
  target?.classList.add('pd-img-broken')
}

// heroImgs：封面优先，无封面用分节图片兜底
const heroImgs = computed(() => {
  const p = post.value
  if (!p) return []
  if (p.cover_url) return [p.cover_url]
  return (p.sections || []).flatMap((s) => s.photos || []).slice(0, 1)
})
const heroUrl = computed(() => resolveImageUrl(heroImgs.value[0] || '') || '')
// hero 加载失败时回落到渐变占位（否则露出灰底很突兀）
const heroFailed = ref(false)

// 侧栏作者卡数据（复用用户主页接口）
const profile = ref<UserProfileData | null>(null)
const loadProfile = async (uid: number) => {
  try {
    const res = await getUserProfile(uid)
    profile.value = res.data ?? null
  } catch {
    profile.value = null
  }
}

// 渐变占位（无图/破图时显示，低饱和旅行色系，按帖子 id 稳定取色）
const gradients = [
  'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
  'linear-gradient(135deg, #fbc2eb 0%, #a6c1ee 100%)',
  'linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%)',
  'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)',
  'linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)'
]
const heroGradient = gradients[(postId.charCodeAt(postId.length - 1) || 0) % gradients.length]

// 类型徽标文案
const typeText = computed(() => {
  const t = post.value?.post_type
  return t === 'journal' ? 'AI 游记' : t === 'route' ? '路线' : '图文'
})
</script>

<template>
  <div class="page-fade pd-page">
    <!-- 顶栏：返回 + 删帖 -->
    <div class="pd-topbar">
      <button class="pd-back" @click="goBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        {{ backText }}
      </button>
      <Popconfirm
        v-if="post && post.user_id === auth.user?.id"
        title="确定删除这篇帖子？点赞与评论会一并删除"
        ok-text="删除"
        cancel-text="取消"
        @confirm="handleDelete"
      >
        <Button danger type="text" size="small">删除</Button>
      </Popconfirm>
    </div>

    <Spin :spinning="loading">
      <template v-if="post">
        <div class="pd-cols">
          <div class="pd-col-main">
            <!-- 主卡：封面 hero + 标题区 + 正文 + 互动条 -->
            <article class="pd-main">
              <!-- 封面：有图用图（失败回落渐变），无图用柔和渐变 + emoji -->
              <div class="pd-hero" :style="heroUrl && !heroFailed ? undefined : { background: heroGradient }">
                <img v-if="heroUrl && !heroFailed" :src="heroUrl" alt="" @error="heroFailed = true" />
                <span v-else class="pd-hero-emoji">🌄</span>
                <span class="pd-hero-type">{{ typeText }}</span>
              </div>

          <!-- 标题区：标签行 + 标题 + 作者条 -->
          <header class="pd-head">
            <div v-if="post.tags?.length" class="pd-tags">
              <span v-for="t in post.tags" :key="t" class="pd-tag"># {{ t }}</span>
            </div>
            <h1 class="pd-title">{{ post.title }}</h1>
            <div class="pd-author-row">
              <span class="pd-avatar" @click="router.push(`/user/${post.user_id}`)">{{ (post.author || '旅').charAt(0).toUpperCase() }}</span>
              <a class="pd-author-name" @click="router.push(`/user/${post.user_id}`)">{{ post.author }}</a>
              <span class="pd-dot">·</span>
              <span class="pd-time">{{ fmtTime(post.created_at) }}</span>
              <span class="pd-views">👀 {{ post.view_count }}</span>
            </div>
          </header>

          <!-- 正文：分节渲染（Day 徽标 + 段落 + 九宫格图） -->
          <div class="pd-body">
            <section v-for="(sec, idx) in post.sections" :key="idx" class="pd-section">
              <h3 v-if="sec.title || sec.day_index" class="pd-section-title">
                <span v-if="sec.day_index" class="pd-day">Day {{ sec.day_index }}</span>
                {{ sec.title }}
              </h3>
              <p v-if="sec.text" class="pd-text">{{ sec.text }}</p>
              <div v-if="sec.photos?.length" class="pd-grid" :class="`pd-grid-${Math.min(sec.photos.length, 3)}`">
                <div
                  v-for="(p, pi) in sec.photos"
                  :key="pi"
                  class="pd-ph"
                  :style="{ background: gradients[(idx + pi) % gradients.length] }"
                >
                  <AImage
                    :src="resolveImageUrl(p) || ''"
                    :alt="p"
                    :preview="true"
                    class="pd-grid-img"
                    @error="onImgErr"
                  />
                </div>
              </div>
            </section>
          </div>

          <!-- 互动条：点赞 / 评论 / 照着走 -->
          <footer class="pd-actions">
            <button class="pd-act" :class="{ liked: post.liked }" @click="toggleLike">
              <span class="pd-act-icon">{{ post.liked ? '❤️' : '🤍' }}</span>
              点赞 <b>{{ post.like_count }}</b>
            </button>
            <span class="pd-act pd-act-static">💬 评论 <b>{{ post.comment_count }}</b></span>
            <Button v-if="post.plan_id" type="primary" class="pd-fork" @click="handleFork">
              🗺️ 照着走这条路线
            </Button>
          </footer>
        </article>

        <!-- 评论卡：输入框置顶（公众号式） -->
        <section class="pd-comments">
          <h3 class="pd-cm-title">全部评论 <span>{{ post.comment_count }}</span></h3>

          <div class="pd-cm-editor">
            <span class="pd-avatar pd-avatar-sm">{{ (auth.user?.username || '我').charAt(0).toUpperCase() }}</span>
            <Input v-model:value="commentText" :maxlength="500" placeholder="写下你的评论，鼓励一下作者吧…" @press-enter="sendComment" />
            <Button type="primary" :loading="commentSubmitting" @click="sendComment">发布</Button>
          </div>

          <!-- 顶级评论 + 楼中楼 -->
          <div v-if="comments.length" class="pd-cm-list">
            <div v-for="c in comments" :key="c.id" class="pd-cm">
              <span class="pd-avatar pd-avatar-sm" @click="router.push(`/user/${c.user_id}`)">{{ (c.author || '旅').charAt(0).toUpperCase() }}</span>
              <div class="pd-cm-main">
                <div class="pd-cm-head">
                  <a class="pd-cm-author" @click="router.push(`/user/${c.user_id}`)">{{ c.author }}</a>
                  <span class="pd-cm-time">{{ fmtTime(c.created_at) }}</span>
                </div>
                <p class="pd-cm-text">{{ c.content }}</p>
                <button class="pd-cm-reply-btn" @click="startReply(c)">回复</button>

                <!-- 楼中楼回复 -->
                <div v-if="c.replies.length" class="pd-sub">
                  <div v-for="r in c.replies" :key="r.id" class="pd-cm pd-cm-nested">
                    <span class="pd-avatar pd-avatar-xs" @click="router.push(`/user/${r.user_id}`)">{{ (r.author || '旅').charAt(0).toUpperCase() }}</span>
                    <div class="pd-cm-main">
                      <div class="pd-cm-head">
                        <a class="pd-cm-author" @click="router.push(`/user/${r.user_id}`)">{{ r.author }}</a>
                        <span class="pd-cm-time">{{ fmtTime(r.created_at) }}</span>
                      </div>
                      <p class="pd-cm-text">{{ r.content }}</p>
                    </div>
                  </div>
                </div>

                <!-- 回复输入框 -->
                <div v-if="replyTo?.id === c.id" class="pd-cm-editor pd-cm-editor-sm">
                  <Input v-model:value="replyText" size="small" :maxlength="500" :placeholder="`回复 ${c.author}`" @press-enter="sendComment" />
                  <Button size="small" type="primary" :loading="commentSubmitting" @click="sendComment">回复</Button>
                  <Button size="small" @click="cancelReply">取消</Button>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="pd-cm-empty">
            <span class="pd-cm-empty-emoji">💬</span>
            <p>还没有评论，来抢沙发～</p>
          </div>
        </section>
          </div>

          <!-- 侧栏：作者卡 + 帖子信息卡（宽屏显示，窄屏隐藏） -->
          <aside class="pd-col-side">
            <div class="pd-side-card pd-author-card">
              <span class="pd-avatar pd-avatar-lg">{{ (post.author || '旅').charAt(0).toUpperCase() }}</span>
              <div class="pd-author-name2">{{ post.author }}</div>
              <div class="pd-author-stats">
                <div class="pd-stat"><b>{{ profile?.stats.posts_count ?? '—' }}</b><span>旅行圈</span></div>
                <div class="pd-stat"><b>{{ profile?.stats.journals_count ?? '—' }}</b><span>游记</span></div>
                <div class="pd-stat"><b>{{ profile?.stats.friends_count ?? '—' }}</b><span>好友</span></div>
              </div>
              <Button block @click="router.push(`/user/${post.user_id}`)">
                查看 TA 的主页
              </Button>
            </div>
            <div class="pd-side-card pd-info-card">
              <h4 class="pd-side-title">帖子信息</h4>
              <div class="pd-info-row"><span>发布时间</span><b>{{ fmtTime(post.created_at) }}</b></div>
              <div class="pd-info-row"><span>浏览</span><b>{{ post.view_count }}</b></div>
              <div class="pd-info-row"><span>点赞</span><b>{{ post.like_count }}</b></div>
              <div class="pd-info-row"><span>评论</span><b>{{ post.comment_count }}</b></div>
              <div v-if="post.tags?.length" class="pd-info-tags">
                <span v-for="t in post.tags" :key="t">#{{ t }}</span>
              </div>
            </div>
          </aside>
        </div>
      </template>
    </Spin>
  </div>
</template>

<style scoped>
/* ===== 页面骨架：宽屏双栏（主内容 + 侧栏），窄屏单栏 ===== */
.pd-page {
  max-width: 1160px;
  margin: 0 auto;
  padding: 16px 16px 48px;
}
.pd-cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 20px;
  align-items: start;
}
.pd-col-side {
  position: sticky;
  top: 76px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.pd-side-card {
  background: #fff;
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 4px 24px rgba(30, 41, 59, 0.07);
}
@media (max-width: 1024px) {
  .pd-cols {
    grid-template-columns: 1fr;
  }
  .pd-col-side {
    display: none;
  }
}

/* 顶栏返回按钮：胶囊 hover */
.pd-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.pd-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: #666;
  font-size: 14px;
  padding: 8px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s;
}
.pd-back:hover {
  background: #fff;
  color: var(--brand);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

/* ===== 主卡 ===== */
.pd-main {
  background: #fff;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 4px 24px rgba(30, 41, 59, 0.07);
}

/* 封面 hero：大图 / 柔和渐变占位，类型徽标浮层 */
.pd-hero {
  position: relative;
  height: 300px;
  background: #eef2f7;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pd-hero img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.pd-hero-emoji {
  font-size: 64px;
  opacity: 0.9;
}
.pd-hero-type {
  position: absolute;
  top: 16px;
  left: 16px;
  padding: 4px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(4px);
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
}

/* 标题区 */
.pd-head {
  padding: 24px 32px 0;
}
.pd-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.pd-tag {
  font-size: 13px;
  color: #2563eb;
  background: #eff6ff;
  padding: 3px 12px;
  border-radius: 999px;
}
.pd-title {
  margin: 0 0 16px;
  font-size: 26px;
  line-height: 1.4;
  color: #1e293b;
}

/* 作者条：头像可点 → 用户主页 */
.pd-author-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 20px;
  border-bottom: 1px solid #f1f5f9;
}
.pd-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  color: #fff;
  font-weight: 700;
  font-size: 17px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.pd-avatar-sm {
  width: 34px;
  height: 34px;
  font-size: 14px;
}
.pd-avatar-xs {
  width: 26px;
  height: 26px;
  font-size: 11px;
}
.pd-avatar-lg {
  width: 56px;
  height: 56px;
  font-size: 22px;
}
.pd-author-name {
  font-weight: 600;
  color: #334155;
  font-size: 15px;
}
.pd-author-name:hover {
  color: var(--brand);
}
.pd-dot,
.pd-time,
.pd-views {
  color: #94a3b8;
  font-size: 13px;
}
.pd-views {
  margin-left: auto;
}

/* ===== 正文 ===== */
.pd-body {
  padding: 8px 32px;
}
.pd-section {
  padding: 16px 0;
}
.pd-section + .pd-section {
  border-top: 1px dashed #eef2f7;
}
.pd-section-title {
  margin: 0 0 10px;
  font-size: 17px;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}
.pd-day {
  font-size: 12px;
  font-weight: 700;
  color: #d97706;
  background: #fef3c7;
  padding: 2px 10px;
  border-radius: 999px;
}
.pd-text {
  margin: 0 0 14px;
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: 15px;
  color: #475569;
}

/* 九宫格：1 张全宽 16:9，2 张对半，≥3 张三列 4:3 */
.pd-grid {
  display: grid;
  gap: 10px;
}
.pd-grid-1 {
  grid-template-columns: 1fr;
}
.pd-grid-1 .pd-ph {
  aspect-ratio: 16 / 9;
}
.pd-grid-2 {
  grid-template-columns: 1fr 1fr;
}
.pd-grid-3 {
  grid-template-columns: repeat(3, 1fr);
}
.pd-grid-2 .pd-ph,
.pd-grid-3 .pd-ph {
  aspect-ratio: 4 / 3;
}
.pd-ph {
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100px;
}
/* AImage 穿透：直接命中 ant-image 内部结构，保证图铺满格子 */
.pd-ph :deep(.ant-image) {
  width: 100%;
  height: 100%;
}
.pd-ph :deep(.ant-image-img) {
  width: 100% !important;
  height: 100% !important;
  object-fit: cover;
  display: block;
}
/* 破图兜底：隐藏 img 露出渐变底 */
:deep(.pd-img-broken),
.pd-img-broken {
  display: none !important;
}

/* ===== 互动条 ===== */
.pd-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 32px 20px;
  border-top: 1px solid #f1f5f9;
  margin-top: 8px;
}
.pd-act {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #475569;
  font-size: 14px;
  padding: 8px 18px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s;
}
.pd-act b {
  color: #1e293b;
}
.pd-act:hover {
  border-color: #f87171;
  transform: translateY(-1px);
}
.pd-act-static {
  cursor: default;
}
.pd-act-static:hover {
  border-color: #e2e8f0;
  transform: none;
}
.pd-act.liked {
  border-color: #fca5a5;
  background: #fef2f2;
  color: #dc2626;
}
.pd-fork {
  margin-left: auto;
  border-radius: 999px;
}

/* ===== 评论区 ===== */
.pd-comments {
  background: #fff;
  border-radius: 20px;
  margin-top: 20px;
  padding: 24px 32px;
  box-shadow: 0 4px 24px rgba(30, 41, 59, 0.07);
  min-height: 320px;
}
.pd-cm-title {
  margin: 0 0 18px;
  font-size: 17px;
  color: #1e293b;
}
.pd-cm-title span {
  color: #94a3b8;
  font-weight: 400;
  margin-left: 4px;
}

/* 评论输入框置顶 */
.pd-cm-editor {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
}
.pd-cm-editor-sm {
  border-bottom: none;
  padding: 10px 0 0;
  margin-top: 6px;
}

/* 评论列表 */
.pd-cm-list {
  margin-top: 6px;
}
.pd-cm {
  display: flex;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px solid #f8fafc;
}
.pd-cm:last-child {
  border-bottom: none;
}
.pd-cm-main {
  flex: 1;
  min-width: 0;
}
.pd-cm-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.pd-cm-author {
  font-weight: 600;
  font-size: 14px;
  color: #334155;
}
.pd-cm-author:hover {
  color: var(--brand);
}
.pd-cm-time {
  color: #94a3b8;
  font-size: 12px;
}
.pd-cm-text {
  margin: 5px 0 6px;
  line-height: 1.75;
  font-size: 14px;
  color: #475569;
}
.pd-cm-reply-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 12px;
  padding: 0;
  cursor: pointer;
}
.pd-cm-reply-btn:hover {
  color: var(--brand);
}

/* 楼中楼：浅灰底缩进 */
.pd-sub {
  margin-top: 10px;
  background: #f8fafc;
  border-radius: 12px;
  padding: 4px 14px;
}
.pd-cm-nested {
  padding: 10px 0;
  border-bottom: none;
}

/* 空态 */
.pd-cm-empty {
  text-align: center;
  padding: 48px 0 32px;
  color: #94a3b8;
}
.pd-cm-empty-emoji {
  font-size: 40px;
  display: block;
  margin-bottom: 10px;
}
.pd-cm-empty p {
  margin: 0;
  font-size: 14px;
}

/* 小屏适配 */
@media (max-width: 640px) {
  .pd-head,
  .pd-body,
  .pd-actions,
  .pd-comments {
    padding-left: 18px;
    padding-right: 18px;
  }
  .pd-hero {
    height: 200px;
  }
  .pd-title {
    font-size: 21px;
  }
}

/* ===== 侧栏卡 ===== */
.pd-author-card {
  text-align: center;
}
.pd-author-name2 {
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
  margin: 12px 0 16px;
}
.pd-author-stats {
  display: flex;
  justify-content: space-around;
  padding: 14px 0;
  margin-bottom: 16px;
  background: #f8fafc;
  border-radius: 14px;
}
.pd-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pd-stat b {
  font-size: 17px;
  color: #1e293b;
}
.pd-stat span {
  font-size: 12px;
  color: #94a3b8;
}
.pd-side-title {
  margin: 0 0 12px;
  font-size: 15px;
  color: #1e293b;
}
.pd-info-row {
  display: flex;
  justify-content: space-between;
  padding: 7px 0;
  font-size: 13px;
}
.pd-info-row span {
  color: #94a3b8;
}
.pd-info-row b {
  color: #475569;
  font-weight: 500;
}
.pd-info-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}
.pd-info-tags span {
  font-size: 12px;
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 10px;
  border-radius: 999px;
}
</style>
