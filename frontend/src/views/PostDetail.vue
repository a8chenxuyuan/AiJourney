<!--
  src/views/PostDetail.vue：帖子详情
  作用：分节图文展示、点赞、两级评论、作者删帖、照着走（复制关联行程）
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, onMounted } from 'vue'
// 引入路由
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Card, Tag, Spin, Input, Modal, Popconfirm, Image as AImage, message } from 'ant-design-vue'
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
    if (res.success && res.data) post.value = res.data
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
 * backZone：按帖子分区返回对应列表页（旅行圈 / 旅行笔记）
 */
const backZone = () => router.push(post.value?.zone === 'circle' ? '/circle' : '/notes')

/**
 * handleDelete：删除后返回所属分区列表
 */
const handleDelete = async () => {
  try {
    const res = await deletePost(postId)
    if (res.success) {
      message.success('帖子已删除')
      backZone()
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
</script>

<template>
  <div class="page-fade" style="max-width: 820px; margin: 0 auto; padding: 0 16px;">
    <!-- 返回 + 删帖 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0 8px;">
      <Button type="link" style="padding: 0;" @click="backZone()">
        ← {{ post?.zone === 'circle' ? '返回旅行圈' : '返回旅行笔记' }}
      </Button>
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
        <!-- 头部：标题 / 作者 / 标签 -->
        <div style="margin-bottom: 20px;">
          <h1 style="font-size: 26px; margin: 8px 0;">{{ post.title }}</h1>
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; color: #999; font-size: 13px;">
            <span style="font-weight: 600; color: #666;">{{ post.author }}</span>
            <span>{{ fmtTime(post.created_at) }}</span>
            <Tag
              color="geekblue"
              style="margin: 0; border-radius: 999px;"
            >{{ post.post_type === 'journal' ? 'AI 游记' : post.post_type === 'route' ? '路线' : '图文' }}</Tag>
            <Tag v-for="t in post.tags" :key="t" color="blue" style="margin: 0; border-radius: 999px;">{{ t }}</Tag>
          </div>
        </div>

        <!-- 正文：分节渲染（Day N 徽标 + 图片预览） -->
        <Card
          v-for="(sec, idx) in post.sections"
          :key="idx"
          style="border-radius: 12px; margin-bottom: 16px;"
        >
          <template #title>
            <span style="font-size: 15px;">
              <Tag v-if="sec.day_index" color="orange" style="margin-right: 8px;">Day {{ sec.day_index }}</Tag>
              {{ sec.title }}
            </span>
          </template>
          <p style="white-space: pre-wrap; line-height: 1.9; margin: 0;">{{ sec.text }}</p>
          <div v-if="sec.photos?.length" style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap;">
            <AImage
              v-for="(p, pi) in sec.photos"
              :key="pi"
              :src="resolveImageUrl(p) || ''"
              :width="140"
              :height="100"
              style="object-fit: cover; border-radius: 8px;"
            />
          </div>
        </Card>

        <!-- 操作条：点赞 / 照着走 -->
        <div style="display: flex; align-items: center; gap: 12px; margin: 20px 0;">
          <Button :type="post.liked ? 'primary' : 'default'" @click="toggleLike">
            {{ post.liked ? '❤️' : '🤍' }} 点赞 {{ post.like_count }}
          </Button>
          <span style="color: #999;">💬 {{ post.comment_count }} 条评论</span>
          <span style="color: #999;">👀 {{ post.view_count }} 浏览</span>
          <Button v-if="post.plan_id" type="primary" ghost style="margin-left: auto;" @click="handleFork">
            🗺️ 照着走
          </Button>
        </div>

        <!-- 评论区 -->
        <Card style="border-radius: 12px;">
          <template #title>评论（{{ post.comment_count }}）</template>

          <!-- 顶级评论 + 楼中楼 -->
          <div v-if="comments.length">
            <div v-for="c in comments" :key="c.id" style="padding: 12px 0; border-bottom: 1px solid #f0f0f0;">
              <p style="margin: 0 0 4px;">
                <span style="font-weight: 600; margin-right: 8px;">{{ c.author }}</span>
                <span style="color: #999; font-size: 12px;">{{ fmtTime(c.created_at) }}</span>
              </p>
              <p style="margin: 0 0 6px; line-height: 1.7;">{{ c.content }}</p>
              <Button type="link" size="small" style="padding: 0;" @click="startReply(c)">回复</Button>

              <!-- 楼中楼回复 -->
              <div
                v-if="c.replies.length"
                style="margin-top: 8px; padding-left: 16px; border-left: 2px solid #f0f0f0;"
              >
                <div v-for="r in c.replies" :key="r.id" style="padding: 6px 0;">
                  <p style="margin: 0 0 2px;">
                    <span style="font-weight: 600; margin-right: 8px;">{{ r.author }}</span>
                    <span style="color: #999; font-size: 12px;">{{ fmtTime(r.created_at) }}</span>
                  </p>
                  <p style="margin: 0; line-height: 1.7;">{{ r.content }}</p>
                </div>
              </div>

              <!-- 回复输入框 -->
              <div v-if="replyTo?.id === c.id" style="display: flex; gap: 8px; margin-top: 8px;">
                <Input v-model:value="replyText" size="small" :maxlength="500" :placeholder="`回复 ${c.author}`" @press-enter="sendComment" />
                <Button size="small" type="primary" :loading="commentSubmitting" @click="sendComment">回复</Button>
                <Button size="small" @click="cancelReply">取消</Button>
              </div>
            </div>
          </div>
          <p v-else style="color: #999; text-align: center; padding: 16px 0;">还没有评论，来抢沙发～</p>

          <!-- 顶级评论输入框 -->
          <div style="display: flex; gap: 8px; margin-top: 16px;">
            <Input v-model:value="commentText" :maxlength="500" placeholder="写下你的评论…" @press-enter="sendComment" />
            <Button type="primary" :loading="commentSubmitting" @click="sendComment">发布</Button>
          </div>
        </Card>
      </template>
    </Spin>
  </div>
</template>
