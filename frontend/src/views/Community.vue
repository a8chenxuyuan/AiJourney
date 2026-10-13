<!--
  src/views/Community.vue：社区广场
  作用：最新/热门双排序 feed（滚动加载）+ 发布弹窗（手动图文/关联行程/图片上传）
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, onMounted, onUnmounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import {
  Button,
  Card,
  Tag,
  Input,
  Select,
  Modal,
  Upload,
  Radio,
  Spin,
  Empty,
  message
} from 'ant-design-vue'
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

// sort：排序方式；posts：已加载卡片；page/hasMore/loading：分页滚动加载状态
const sort = ref<'latest' | 'hot'>('latest')
const posts = ref<PostItem[]>([])
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)

/**
 * fmtTime：created_at → "YYYY-MM-DD HH:mm"
 */
const fmtTime = (s: string) => (s ? s.replace('T', ' ').slice(0, 16) : '')

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

// ==================== 照着走（卡片快捷入口） ====================

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
  <div class="page-fade" style="max-width: 820px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头：标题 + 排序 + 发布 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
      <h2 style="margin: 0; font-size: 24px;">旅行社区</h2>
      <div style="display: flex; gap: 12px; align-items: center;">
        <Radio.Group v-model:value="sort" button-style="solid" @change="changeSort">
          <Radio.Button value="latest">最新</Radio.Button>
          <Radio.Button value="hot">热门</Radio.Button>
        </Radio.Group>
        <Button type="primary" @click="openPublish">✏️ 发布</Button>
      </div>
    </div>

    <!-- 帖子卡片流 -->
    <Card
      v-for="post in posts"
      :key="post.id"
      hoverable
      style="border-radius: 12px; margin-bottom: 16px; overflow: hidden;"
      @click="goDetail(post.id)"
    >
      <div style="display: flex; gap: 16px;">
        <!-- 封面：无封面用渐变占位块 -->
        <img
          v-if="post.cover_url"
          :src="resolveImageUrl(post.cover_url) || ''"
          style="width: 150px; height: 112px; object-fit: cover; border-radius: 8px; flex-shrink: 0;"
        />
        <div
          v-else
          style="width: 150px; height: 112px; border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 40px; background: linear-gradient(135deg, #e6f4ff 0%, #d6f5e6 100%);"
        >
          {{ post.post_type === 'journal' ? '📖' : post.post_type === 'route' ? '🗺️' : '📝' }}
        </div>

        <!-- 右侧信息 -->
        <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
          <p style="font-size: 16px; font-weight: 600; margin: 0 0 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {{ post.title }}
          </p>
          <p
            v-if="post.summary"
            style="color: #666; font-size: 13px; margin: 0 0 8px; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;"
          >
            {{ post.summary }}
          </p>
          <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px;">
            <Tag v-for="t in post.tags.slice(0, 3)" :key="t" color="blue" style="margin: 0; border-radius: 999px;">{{ t }}</Tag>
          </div>
          <div style="margin-top: auto; display: flex; align-items: center; gap: 12px; color: #999; font-size: 13px;">
            <span>{{ post.author }}</span>
            <span>{{ fmtTime(post.created_at) }}</span>
            <span style="margin-left: auto;">❤️ {{ post.like_count }} · 💬 {{ post.comment_count }}</span>
            <Button
              v-if="post.plan_id"
              size="small"
              type="primary"
              ghost
              @click.stop="handleFork(post)"
            >照着走</Button>
          </div>
        </div>
      </div>
    </Card>

    <!-- 空状态 / 加载状态 -->
    <Empty
      v-if="!loading && posts.length === 0"
      description="还没有帖子，点右上角「发布」分享你的旅行故事"
      style="margin: 80px 0;"
    />
    <div v-if="loading" style="text-align: center; padding: 24px 0;">
      <Spin />
    </div>
    <p v-else-if="!hasMore && posts.length > 0" style="text-align: center; color: #999; padding: 16px 0;">
      到底啦 · 共 {{ total }} 篇
    </p>

    <!-- 发布弹窗 -->
    <Modal
      :open="pubVisible"
      title="发布帖子"
      :confirm-loading="pubSubmitting"
      ok-text="发布"
      cancel-text="取消"
      :width="560"
      @ok="publish"
      @cancel="closePublish"
    >
      <p style="margin-bottom: 6px; font-weight: 600;">标题</p>
      <Input v-model:value="pubTitle" :maxlength="100" placeholder="给帖子起个吸引人的标题" />
      <p style="margin: 12px 0 6px; font-weight: 600;">正文</p>
      <Input.TextArea v-model:value="pubText" :rows="4" :maxlength="5000" placeholder="分享你的旅行故事、攻略心得…" />
      <p style="margin: 12px 0 6px; font-weight: 600;">标签（最多 5 个）</p>
      <Select
        v-model:value="pubTags"
        mode="tags"
        style="width: 100%"
        placeholder="如：美食、亲子、西湖，回车添加"
        :options="[]"
      />
      <p style="margin: 12px 0 6px; font-weight: 600;">照片（jpg/png/webp/gif，单张 ≤ 5MB）</p>
      <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">
        <div v-for="url in pubPhotos" :key="url" style="position: relative;">
          <img :src="resolveImageUrl(url) || ''" style="width: 88px; height: 88px; object-fit: cover; border-radius: 8px;" />
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
          <div
            style="width: 88px; height: 88px; border: 1px dashed #d9d9d9; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #999; cursor: pointer;"
          >+</div>
        </Upload>
      </div>
      <p style="margin: 12px 0 6px; font-weight: 600;">封面（可选，默认第一张照片）</p>
      <div style="display: flex; gap: 8px; align-items: center;">
        <img v-if="pubCover" :src="resolveImageUrl(pubCover) || ''" style="width: 88px; height: 88px; object-fit: cover; border-radius: 8px;" />
        <Upload
          v-else
          :show-upload-list="false"
          accept="image/jpeg,image/png,image/webp,image/gif"
          :custom-request="uploadCover"
        >
          <div
            style="width: 88px; height: 88px; border: 1px dashed #d9d9d9; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #999; cursor: pointer;"
          >+</div>
        </Upload>
        <Button v-if="pubCover" size="small" @click="pubCover = ''">移除封面</Button>
      </div>
      <p style="margin: 12px 0 6px; font-weight: 600;">关联行程（可选，供他人「照着走」）</p>
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
