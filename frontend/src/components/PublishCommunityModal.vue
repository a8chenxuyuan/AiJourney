<!--
  src/components/PublishCommunityModal.vue：发布到社区弹窗（游记转发）
  作用：Journal 页与 Result 页共用，填标题/标签后携带 journal_id 一键发布到旅行笔记分区
-->

<script setup lang="ts">
// 引入 Vue 组合式 API 与路由
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Modal, Input, Select, message } from 'ant-design-vue'
// 引入社区发布 API
import { createPost } from '@/api/community'

// 路由：发布成功后跳转旅行笔记列表
const router = useRouter()

// 组件入参：visible 控制显隐，journalId 来源游记，defaultTitle/defaultTags 作为草稿初值
const props = defineProps<{
  visible: boolean
  journalId: string
  defaultTitle?: string
  defaultTags?: string[]
}>()

// emit：关闭弹窗（update:visible）与发布成功通知
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'success'): void
}>()

// title/tags：发布草稿；submitting：提交中
const title = ref('')
const tags = ref<string[]>([])
const submitting = ref(false)

// 弹窗打开时用默认值初始化草稿
watch(
  () => props.visible,
  (v) => {
    if (v) {
      title.value = props.defaultTitle || ''
      tags.value = props.defaultTags ? [...props.defaultTags] : []
    }
  }
)

// close：关闭弹窗
const close = () => emit('update:visible', false)

/**
 * submit：提交发布（游记 sections/封面/关联行程由后端从游记缺省补全）
 */
const submit = async () => {
  if (!title.value.trim()) {
    message.warning('请填写帖子标题')
    return
  }
  submitting.value = true
  try {
    const res = await createPost({
      title: title.value.trim(),
      zone: 'note',
      tags: tags.value,
      journal_id: props.journalId
    })
    if (res.success) {
      message.success('已发布到旅行笔记')
      close()
      emit('success')
      router.push('/circle?tab=note')
    }
  } catch {
    // 请求层已统一提示错误
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Modal
    :open="visible"
    title="发布到社区"
    :confirm-loading="submitting"
    ok-text="发布"
    cancel-text="取消"
    @ok="submit"
    @cancel="close"
  >
    <p style="color: #888; margin-bottom: 12px;">
      将这篇游记一键发布到旅行社区，其他人可以浏览、点赞，还能「照着走」复制你的路线
    </p>
    <p style="margin-bottom: 6px; font-weight: 600;">标题</p>
    <Input v-model:value="title" :maxlength="100" placeholder="给帖子起个吸引人的标题" />
    <p style="margin: 12px 0 6px; font-weight: 600;">标签（最多 5 个）</p>
    <Select
      v-model:value="tags"
      mode="tags"
      style="width: 100%"
      placeholder="如：美食、亲子、西湖，回车添加"
      :options="[]"
    />
  </Modal>
</template>
