<!-- ResultCollabModal.vue：行程协作弹窗——成员列表、生成/复制邀请链接、移除协作者 -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { Modal, Button, Input, Tag, List, Spin, message } from 'ant-design-vue'
import {
  inviteCollaborator,
  listCollaborators,
  removeCollaborator,
  type CollaboratorItem,
  type InviteInfo
} from '@/api/trip/collab'

const props = defineProps<{
  planId: string
  isOwner: boolean
}>()

const collabVisible = ref(false)
const collabLoading = ref(false)
// collaborators：行程成员列表（所有者 + 协作者）
const collaborators = ref<CollaboratorItem[]>([])
const inviteLoading = ref(false)
// inviteInfo：最近一次生成的邀请信息（token / 有效期等）
const inviteInfo = ref<InviteInfo | null>(null)
// inviteUrl：完整邀请链接（站点 origin + 前端路由 /join/{token}）
const inviteUrl = computed(() =>
  inviteInfo.value ? `${window.location.origin}${inviteInfo.value.invite_path}` : ''
)

/**
 * fetchCollaborators：拉取行程成员列表（所有者与协作者均可查看）
 */
const fetchCollaborators = async () => {
  collabLoading.value = true
  try {
    const res = await listCollaborators(props.planId)
    if (res.success && res.data) {
      collaborators.value = res.data.collaborators
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    collabLoading.value = false
  }
}

/**
 * openCollabModal：打开协作弹窗并刷新成员列表
 */
const openCollabModal = () => {
  inviteInfo.value = null
  collabVisible.value = true
  fetchCollaborators()
}

/**
 * handleGenerateInvite：所有者生成邀请链接（有效期 7 天）
 */
const handleGenerateInvite = async () => {
  inviteLoading.value = true
  try {
    const res = await inviteCollaborator(props.planId)
    if (res.success && res.data) {
      inviteInfo.value = res.data
      message.success('邀请链接已生成，复制发给对方即可')
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '生成邀请链接失败')
  } finally {
    inviteLoading.value = false
  }
}

/**
 * handleCopyInviteLink：复制邀请链接到剪贴板
 * 与分享链接相同的降级方案：clipboard API 失败时用隐藏 textarea 兜底
 */
const handleCopyInviteLink = async () => {
  if (!inviteUrl.value) return
  try {
    await navigator.clipboard.writeText(inviteUrl.value)
    message.success('邀请链接已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = inviteUrl.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    message.success('邀请链接已复制')
  }
}

/**
 * handleRemoveCollaborator：所有者移除协作者（二次确认）
 * 移除后该用户立即失去行程访问权
 */
const handleRemoveCollaborator = (item: CollaboratorItem) => {
  Modal.confirm({
    title: '移除协作者',
    content: `确定移除协作者「${item.username}」吗？移除后其将无法再查看该行程。`,
    okText: '移除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await removeCollaborator(props.planId, item.user_id)
        message.success('已移除协作者')
        fetchCollaborators()
      } catch {
        message.error('移除协作者失败')
      }
    }
  })
}

defineExpose({ open: openCollabModal })
</script>

<template>
  <Modal v-model:open="collabVisible" title="行程协作" :footer="null" style="border-radius: 12px;">
    <p style="color: #666; margin-bottom: 12px;">
      协作者可查看这份行程并提交反馈修订，删除与邀请管理仅所有者可用。
    </p>

    <!-- 邀请区：仅所有者可见 -->
    <div v-if="isOwner" style="margin-bottom: 16px;">
      <template v-if="!inviteInfo">
        <Button type="primary" :loading="inviteLoading" @click="handleGenerateInvite">生成邀请链接（7 天有效）</Button>
      </template>
      <template v-else>
        <div style="display: flex; gap: 8px; margin-bottom: 8px;">
          <Input :value="inviteUrl" readonly />
          <Button type="primary" @click="handleCopyInviteLink">复制链接</Button>
        </div>
        <p style="color: #999; font-size: 12px; margin: 0;">
          对方打开链接并登录后即加入协作；再次生成会创建新链接，旧链接在有效期内仍可用。
        </p>
      </template>
    </div>

    <!-- 成员列表 -->
    <Spin :spinning="collabLoading">
      <List :data-source="collaborators" size="small">
        <template #renderItem="{ item }">
          <List.Item>
            <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
              <span>
                <strong>{{ item.username }}</strong>
                <Tag :color="item.role === 'owner' ? 'gold' : 'blue'" style="margin-left: 8px;">
                  {{ item.role === 'owner' ? '所有者' : '协作者' }}
                </Tag>
                <span v-if="item.joined_at" style="color: #999; font-size: 12px; margin-left: 8px;">
                  {{ item.joined_at.slice(0, 10) }} 加入
                </span>
              </span>
              <Button
                v-if="isOwner && item.role !== 'owner'"
                danger
                size="small"
                @click="handleRemoveCollaborator(item)"
              >移除</Button>
            </div>
          </List.Item>
        </template>
      </List>
    </Spin>
  </Modal>
</template>
