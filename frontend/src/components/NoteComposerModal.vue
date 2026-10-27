<!--
  src/components/NoteComposerModal.vue：发布笔记弹窗（攻略灵感页用）
  作用：手动发布社区笔记帖（zone=note），支持标题/正文/标签/照片/封面/关联行程；
       从旅行圈拆 Tab 时抽出复用，发布成功后 emit success 由父页面刷新列表。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. open 变为 true 时拉取可关联的已完成行程下拉；
 * 2. 照片/封面走 uploadImage，封面的相对 URL 经 resolveImageUrl 展示；
 * 3. publish 校验标题与内容后调 createPost(zone=note)，成功即关闭并通知父页面。
 */
import { ref, watch } from 'vue'
import { Modal, Input, Select, Upload, Button, message } from 'ant-design-vue'
import {
  createPost,
  uploadImage,
  resolveImageUrl,
  type CreatePostParams
} from '@/api/community'
import { getMyPlans } from '@/api/trip'

// open：弹窗显隐（v-model:open）；success：发布成功回调
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', v: boolean): void; (e: 'success'): void }>()

// 发布草稿字段
const pubTitle = ref('')
const pubText = ref('')
const pubTags = ref<string[]>([])
const pubPhotos = ref<string[]>([])
const pubCover = ref('')
const pubPlanId = ref<string | undefined>(undefined)
const pubSubmitting = ref(false)

// planOptions：可关联的已完成行程下拉
const planOptions = ref<Array<{ label: string; value: string }>>([])

// 弹窗打开时拉取可关联行程
watch(
  () => props.open,
  async (open) => {
    if (!open) return
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
)

/**
 * closePublish：关闭弹窗并清空草稿
 */
const closePublish = () => {
  emit('update:open', false)
  pubTitle.value = ''
  pubText.value = ''
  pubTags.value = []
  pubPhotos.value = []
  pubCover.value = ''
  pubPlanId.value = undefined
}

/**
 * uploadCommon：上传公共逻辑（成功返回相对 URL）
 */
const uploadCommon = async (options: {
  file: unknown
  onSuccess?: (body?: unknown) => void
  onError?: (e: Error) => void
}) => {
  try {
    const res = await uploadImage(options.file as File)
    if (res.success && res.data) {
      options.onSuccess?.(res.data)
      return res.data.url
    }
    options.onError?.(new Error(res.message || '上传失败'))
  } catch (e) {
    options.onError?.(e as Error)
  }
  return null
}

/**
 * uploadPubPhoto：笔记照片多选上传
 */
const uploadPubPhoto = async (options: {
  file: unknown
  onSuccess?: (body?: unknown) => void
  onError?: (e: Error) => void
}) => {
  const url = await uploadCommon(options)
  if (url) pubPhotos.value.push(url)
}

/**
 * uploadPubCover：笔记封面上传（覆盖旧值）
 */
const uploadPubCover = async (options: {
  file: unknown
  onSuccess?: (body?: unknown) => void
  onError?: (e: Error) => void
}) => {
  const url = await uploadCommon(options)
  if (url) pubCover.value = url
}

/**
 * removePubPhoto：移除已上传照片（同时清掉引用它的封面）
 */
const removePubPhoto = (url: string) => {
  pubPhotos.value = pubPhotos.value.filter((p) => p !== url)
  if (pubCover.value === url) pubCover.value = ''
}

/**
 * publish：提交发布（有照片用 sections 携带图片，否则纯文本）
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
      zone: 'note',
      tags: pubTags.value,
      plan_id: pubPlanId.value
    }
    if (pubPhotos.value.length) {
      params.sections = [{ day_index: null, title, text, photos: [...pubPhotos.value] }]
      params.cover_url = pubCover.value || pubPhotos.value[0]
    } else {
      params.text = text
      params.cover_url = pubCover.value || null
    }
    const res = await createPost(params)
    if (res.success) {
      message.success('发布成功')
      closePublish()
      emit('success')
    }
  } catch {
    // 请求层已统一提示
  } finally {
    pubSubmitting.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
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
          @click.prevent="removePubPhoto(url)"
        >×</a>
      </div>
      <Upload
        v-if="pubPhotos.length < 9"
        :show-upload-list="false"
        accept="image/jpeg,image/png,image/webp,image/gif"
        :custom-request="uploadPubPhoto"
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
        :custom-request="uploadPubCover"
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
</template>

<style scoped>
.pub-label {
  margin: 12px 0 6px;
  font-size: 13px;
  color: #666;
}
.pub-thumb {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 8px;
  display: block;
}
.pub-add {
  width: 72px;
  height: 72px;
  border: 1px dashed #d9d9d9;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #999;
  cursor: pointer;
}
</style>
