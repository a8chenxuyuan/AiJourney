<!--
  src/views/Journal.vue：游记页
  作用：行程结束后一键生成 LLM 图文游记（生成中轮询进度），
       生成后分节展示，支持编辑标题与正文后保存。
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, onMounted, onUnmounted } from 'vue'
// 引入路由
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Card, Tag, Spin, Input, message } from 'ant-design-vue'
// 引入游记 API 与类型
import { generateJournal, getJournal, updateJournal, type JournalData, type JournalSection } from '@/api/trip/companion'
// 引入游记公开分享 API（内容中心回流）
import { publishJournal, unpublishJournal } from '@/api/community/guides'
// 引入发布到社区弹窗（游记一键转发）
import PublishCommunityModal from '@/components/PublishCommunityModal.vue'

const route = useRoute()
const router = useRouter()

// planId：行程 ID
const planId = route.params.id as string

// journal：游记数据；loading：首次加载；pollTimer：生成轮询定时器
const journal = ref<JournalData | null>(null)
const loading = ref(true)
let pollTimer: number | null = null

// ==================== 编辑 ====================

// editing：编辑模式；editTitle：标题草稿；editSections：分节草稿；saving：保存中
const editing = ref(false)
const editTitle = ref('')
const editSections = ref<JournalSection[]>([])
const saving = ref(false)

// publishVisible：发布到社区弹窗（携带当前游记一键转发）
const publishVisible = ref(false)

// ==================== 公开分享（内容中心回流） ====================

// publishing：公开/取消公开请求中
const publishing = ref(false)

/**
 * togglePublic：设为公开 / 取消公开；公开成功后提示可复制分享链接
 */
const togglePublic = async () => {
  if (!journal.value || publishing.value) return
  publishing.value = true
  try {
    const res = journal.value.is_public
      ? await unpublishJournal(planId)
      : await publishJournal(planId)
    if (res.success && res.data && journal.value) {
      journal.value.is_public = res.data.is_public
      journal.value.public_token = res.data.public_token
      if (res.data.is_public && res.data.public_token) {
        const link = `${window.location.origin}/journal/${res.data.public_token}`
        await navigator.clipboard.writeText(link).catch(() => undefined)
        message.success('游记已公开，分享链接已复制')
      } else {
        message.success('游记已取消公开')
      }
    }
  } finally {
    publishing.value = false
  }
}

/**
 * copyShareLink：再次复制公开分享链接
 */
const copyShareLink = async () => {
  if (journal.value?.public_token) {
    const link = `${window.location.origin}/journal/${journal.value.public_token}`
    await navigator.clipboard.writeText(link).catch(() => undefined)
    message.success('分享链接已复制')
  }
}

/**
 * fetchJournal：拉取游记（生成中自动启动轮询）
 */
const fetchJournal = async () => {
  try {
    const res = await getJournal(planId)
    if (res.success) {
      journal.value = res.data
      if (res.data?.status === 'generating') startPolling()
      else stopPolling()
    }
  } catch {
    // 首次查询失败静默（页面显示"尚未生成"）
  } finally {
    loading.value = false
  }
}

/**
 * startPolling / stopPolling：生成中的 3 秒轮询
 */
const startPolling = () => {
  if (pollTimer) return
  pollTimer = window.setInterval(fetchJournal, 3000)
}
const stopPolling = () => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

/**
 * handleGenerate：触发游记生成
 */
const handleGenerate = async () => {
  try {
    const res = await generateJournal(planId)
    if (res.success && res.data) {
      journal.value = res.data
      if (res.data.status === 'generating') {
        message.success('游记生成已开始，预计需要几十秒')
        startPolling()
      }
    } else {
      message.error(res.message || '触发生成失败')
    }
  } catch {
    message.error('触发生成失败')
  }
}

/**
 * startEdit：进入编辑模式（草稿 = 当前内容）
 */
const startEdit = () => {
  if (!journal.value) return
  editTitle.value = journal.value.title
  editSections.value = journal.value.sections.map((s) => ({ ...s }))
  editing.value = true
}

/**
 * saveEdit：保存编辑（photos 原样回传避免丢失）
 */
const saveEdit = async () => {
  saving.value = true
  try {
    const res = await updateJournal(planId, {
      title: editTitle.value,
      sections: editSections.value
    })
    if (res.success && res.data) {
      journal.value = res.data
      editing.value = false
      message.success('游记已保存')
    } else {
      message.error(res.message || '保存失败')
    }
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(fetchJournal)
onUnmounted(stopPolling)
</script>

<template>
  <div class="page-fade" style="max-width: 960px; margin: 0 auto; padding: 0 16px;">
    <!-- 页头 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
      <h2 style="margin: 0; font-size: 24px;">旅行游记</h2>
      <Button type="default" @click="router.push(`/result/${planId}`)">查看行程</Button>
    </div>

    <Spin :spinning="loading">
      <!-- 尚未生成：引导生成 -->
      <Card v-if="!loading && !journal" style="border-radius: 12px; text-align: center; padding: 32px 0;">
        <p style="font-size: 40px; margin: 8px 0;">📖</p>
        <p style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">还没有游记</p>
        <p style="color: #999; margin-bottom: 16px;">
          AI 会根据行程安排与你的打卡感想，自动写一篇图文游记
        </p>
        <Button type="primary" size="large" @click="handleGenerate">生成游记</Button>
      </Card>

      <template v-else-if="journal">
        <!-- 生成中 -->
        <Card v-if="journal.status === 'generating'" style="border-radius: 12px; text-align: center; padding: 32px 0;">
          <Spin size="large" />
          <p style="font-size: 16px; font-weight: 600; margin-top: 16px;">游记生成中…</p>
          <p style="color: #999;">AI 正在整理行程与打卡记录，预计需要几十秒，完成后自动刷新</p>
        </Card>

        <!-- 生成失败 -->
        <Card v-else-if="journal.status === 'failed'" style="border-radius: 12px; text-align: center; padding: 32px 0;">
          <p style="font-size: 40px; margin: 8px 0;">😵</p>
          <p style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">游记生成失败</p>
          <Button type="primary" @click="handleGenerate">重新生成</Button>
        </Card>

        <!-- 完成：展示 / 编辑 -->
        <template v-else>
          <!-- 查看模式 -->
          <template v-if="!editing">
            <div style="text-align: center; margin-bottom: 24px;">
              <h1 style="font-size: 26px; margin: 8px 0;">{{ journal.title || '我的旅行游记' }}</h1>
              <Tag color="blue">AI 生成 · 可编辑</Tag>
              <span v-if="journal.generated_at" style="color: #999; font-size: 13px; margin-left: 8px;">
                {{ journal.generated_at.replace('T', ' ').slice(0, 16) }}
              </span>
            </div>

            <Card v-for="(sec, idx) in journal.sections" :key="idx" style="border-radius: 12px; margin-bottom: 16px;">
              <template #title>
                <span style="font-size: 16px;">{{ sec.day_index ? `第 ${sec.day_index} 天 · ` : '' }}{{ sec.title }}</span>
              </template>
              <p style="white-space: pre-wrap; line-height: 1.9; margin: 0;">{{ sec.text }}</p>
              <div v-if="sec.photos?.length" style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap;">
                <img v-for="(p, pi) in sec.photos" :key="pi" :src="p" style="width: 140px; height: 100px; object-fit: cover; border-radius: 8px;" />
              </div>
            </Card>

            <div style="display: flex; justify-content: center; gap: 12px; margin: 20px 0; flex-wrap: wrap;">
              <Button type="primary" @click="startEdit">编辑游记</Button>
              <Button @click="publishVisible = true">发布到社区</Button>
              <!-- 公开分享：公开后游记进入攻略灵感流，可复制免登录链接 -->
              <Button :loading="publishing" @click="togglePublic">
                {{ journal.is_public ? '取消公开' : '设为公开分享' }}
              </Button>
              <Button v-if="journal.is_public" @click="copyShareLink">复制分享链接</Button>
              <Button @click="router.push(`/trip/${planId}/footprints`)">查看足迹地图</Button>
            </div>

            <!-- 发布到社区弹窗（游记转发） -->
            <PublishCommunityModal
              v-model:visible="publishVisible"
              :journal-id="journal.id"
              :default-title="journal.title"
            />
          </template>

          <!-- 编辑模式 -->
          <template v-else>
            <Card style="border-radius: 12px; margin-bottom: 16px;">
              <p style="font-weight: 600; margin-bottom: 8px;">游记标题</p>
              <Input v-model:value="editTitle" :maxlength="80" placeholder="游记标题" />
            </Card>

            <Card
              v-for="(sec, idx) in editSections"
              :key="idx"
              style="border-radius: 12px; margin-bottom: 16px;"
            >
              <template #title>
                <Input v-model:value="sec.title" size="small" style="max-width: 400px;" placeholder="节标题" />
              </template>
              <Input.TextArea v-model:value="sec.text" :rows="5" placeholder="节正文" />
              <p v-if="sec.photos?.length" style="color: #999; font-size: 12px; margin-top: 8px;">
                📷 本节含 {{ sec.photos.length }} 张打卡配图（编辑时自动保留）
              </p>
            </Card>

            <div style="display: flex; justify-content: center; gap: 12px; margin: 20px 0;">
              <Button type="primary" :loading="saving" @click="saveEdit">保存</Button>
              <Button @click="editing = false">取消</Button>
            </div>
          </template>
        </template>
      </template>
    </Spin>
  </div>
</template>
