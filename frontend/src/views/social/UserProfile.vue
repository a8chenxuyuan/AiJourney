<!--
  src/views/UserProfile.vue：用户主页（QQ 式资料卡 + 内容流）
  作用：全站头像点击的统一落地页——资料卡（头像/昵称/加入时间/统计）、
       关系按钮（＋添加好友 / 等待验证 / 同意·拒绝 / 💬发消息，随关系态切换）、
       「TA 的旅行圈」与「TA 的游记」两个 Tab 的公开内容流。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 路由参数 user_id 变化时并行拉取资料、动态与游记；
 * 2. 添加好友弹出验证消息弹窗，提交后按钮切「等待验证」；
 * 3. pending_in 状态可直接同意/拒绝；accepted 直接发消息跳聊天。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Card, Empty, Input, Modal, Spin, TabPane, Tabs, Tag, message } from 'ant-design-vue'
import {
  acceptFriend,
  applyFriend,
  getFriendRequests,
  getUserJournals,
  getUserPosts,
  getUserProfile,
  rejectFriend,
  type ProfileJournalItem,
  type ProfilePostItem,
  type UserProfileData
} from '@/api/social'
import { resolveImageUrl } from '@/api/community'

const route = useRoute()
const router = useRouter()

// 核心状态：资料 / 两个 Tab 的内容流
const profile = ref<UserProfileData | null>(null)
const posts = ref<ProfilePostItem[]>([])
const journals = ref<ProfileJournalItem[]>([])
const loading = ref(true)
const activeTab = ref('posts')

// 加好友弹窗（验证消息）
const applyOpen = ref(false)
const verifyText = ref('')
const applySubmitting = ref(false)

// 展示昵称与统计
const username = computed(() => profile.value?.username || '旅行者')
const initial = computed(() => username.value.charAt(0).toUpperCase())
const stats = computed(() => profile.value?.stats)

/**
 * loadAll：按路由 user_id 拉取主页数据
 */
const loadAll = async () => {
  const userId = Number(route.params.id)
  if (!userId) return
  loading.value = true
  try {
    const [profileRes, postsRes, journalsRes] = await Promise.all([
      getUserProfile(userId),
      getUserPosts(userId),
      getUserJournals(userId)
    ])
    if (profileRes.success && profileRes.data) profile.value = profileRes.data
    posts.value = postsRes.data?.items || []
    journals.value = journalsRes.data?.items || []
  } finally {
    loading.value = false
  }
}

/**
 * submitApply：提交好友申请（空验证消息由后端默认文案兜底）
 */
const submitApply = async () => {
  const userId = profile.value?.user_id
  if (!userId) return
  applySubmitting.value = true
  try {
    const res = await applyFriend(userId, verifyText.value.trim())
    if (res.success) {
      message.success('好友申请已发送')
      applyOpen.value = false
      verifyText.value = ''
      loadAll() // 刷新关系态 → 等待验证
    } else if (res.message) {
      message.warning(res.message)
    }
  } finally {
    applySubmitting.value = false
  }
}

/**
 * handleAccept / handleReject：处理对方发来的申请（pending_in 按钮态）
 */
const handleAccept = async () => {
  const fid = profile.value?.friendship_id
  if (!fid) return
  const res = await acceptFriend(fid)
  if (res.success) {
    message.success('已添加好友')
    loadAll()
  }
}

const handleReject = async () => {
  const fid = profile.value?.friendship_id
  if (!fid) return
  const res = await rejectFriend(fid)
  if (res.success) {
    message.info('已拒绝')
    loadAll()
  }
}

/**
 * goChat：已好友 → 跳消息页并打开与该好友的会话
 */
const goChat = () => {
  if (profile.value?.user_id) router.push(`/messages?peer=${profile.value.user_id}`)
}

/**
 * goBack：返回上一页（无浏览历史时兜底回消息页）
 */
const goBack = () => {
  if (window.history.state?.back) router.back()
  else router.push('/messages')
}

/**
 * goPost / goJournal：内容卡片跳转
 */
const goPost = (p: ProfilePostItem) => router.push(`/community/${p.id}`)
const goJournal = (j: ProfileJournalItem) => router.push(`/journal/${j.public_token}`)

// 兜底：他人发来申请后，主页也可直接拉取申请详情（verify_message 展示在按钮旁提示）
const incomingVerify = ref<string | null>(null)
const loadIncomingVerify = async () => {
  if (profile.value?.relation !== 'pending_in') {
    incomingVerify.value = null
    return
  }
  const res = await getFriendRequests()
  const match = (res.data?.requests || []).find((r) => r.user_id === profile.value?.user_id)
  incomingVerify.value = match?.verify_message || null
}

watch(
  () => route.params.id,
  () => loadAll()
)
onMounted(loadAll)
// 资料加载后若为 pending_in，补拉验证消息文案
watch(profile, () => loadIncomingVerify())

</script>

<template>
  <div class="up-page page-fade">
    <!-- 返回键：从消息页/旅行圈等来源原路返回 -->
    <div class="up-topbar">
      <Button type="text" class="up-back" @click="goBack">← 返回</Button>
    </div>
    <Spin :spinning="loading">
      <!-- 资料卡 -->
      <Card style="border-radius: 16px; overflow: hidden;">
        <template #cover>
          <div class="up-banner"></div>
        </template>
        <div class="up-head">
          <div class="up-avatar">{{ initial }}</div>
          <div class="up-meta">
            <h2 style="margin: 0; font-size: 20px;">{{ username }}</h2>
            <p style="margin: 4px 0 0; color: #999; font-size: 13px;">
              {{ profile?.created_at ? `${profile.created_at.slice(0, 10)} 加入` : '' }}
            </p>
          </div>
          <!-- 关系按钮区：随 relation 切换 -->
          <div class="up-actions">
            <template v-if="profile?.relation === 'self'">
              <Button @click="router.push('/profile')">编辑资料</Button>
            </template>
            <template v-else-if="profile?.relation === 'none'">
              <Button type="primary" @click="applyOpen = true">＋ 添加好友</Button>
            </template>
            <template v-else-if="profile?.relation === 'pending_out'">
              <Button disabled>⏳ 等待验证</Button>
            </template>
            <template v-else-if="profile?.relation === 'pending_in'">
              <span v-if="incomingVerify" class="up-verify">「{{ incomingVerify }}」</span>
              <Button type="primary" @click="handleAccept">✓ 同意</Button>
              <Button danger style="margin-left: 8px;" @click="handleReject">✕ 拒绝</Button>
            </template>
            <template v-else-if="profile?.relation === 'accepted'">
              <Button type="primary" @click="goChat">💬 发消息</Button>
            </template>
          </div>
        </div>

        <!-- 统计行 -->
        <div v-if="stats" class="up-stats">
          <span><b>{{ stats.posts_count }}</b> 旅行圈动态</span>
          <span><b>{{ stats.likes_received }}</b> 获赞</span>
          <span><b>{{ stats.journals_count }}</b> 公开游记</span>
          <span><b>{{ stats.friends_count }}</b> 好友</span>
        </div>
      </Card>

      <!-- 内容 Tabs -->
      <Card style="border-radius: 16px; margin-top: 16px;">
        <Tabs v-model:activeKey="activeTab">
          <TabPane key="posts" tab="TA 的旅行圈">
            <Spin :spinning="loading">
              <Empty v-if="!posts.length" description="TA 还没有发布动态" />
              <div v-else class="up-list">
                <div
                  v-for="p in posts"
                  :key="p.id"
                  class="up-item"
                  @click="goPost(p)"
                >
                  <img
                    v-if="p.cover_url"
                    :src="resolveImageUrl(p.cover_url) || ''"
                    class="up-item-cover"
                  />
                  <div v-else class="up-item-cover up-item-placeholder">📝</div>
                  <div class="up-item-main">
                    <Tag :color="p.zone === 'circle' ? 'orange' : 'green'">
                      {{ p.zone === 'circle' ? '晒图' : '笔记' }}
                    </Tag>
                    <span class="up-item-title">{{ p.title || '（无标题）' }}</span>
                    <p class="up-item-sub">{{ p.summary || '' }}</p>
                    <span class="up-item-meta">❤️ {{ p.like_count }} · 💬 {{ p.comment_count }}</span>
                  </div>
                </div>
              </div>
            </Spin>
          </TabPane>
          <TabPane key="journals" tab="TA 的游记">
            <Empty v-if="!journals.length" description="TA 还没有公开游记" />
            <div v-else class="up-list">
              <div v-for="j in journals" :key="j.id" class="up-item" @click="goJournal(j)">
                <img v-if="j.cover_url" :src="resolveImageUrl(j.cover_url) || ''" class="up-item-cover" />
                <div v-else class="up-item-cover up-item-placeholder">📔</div>
                <div class="up-item-main">
                  <Tag color="blue">游记</Tag>
                  <span class="up-item-title">{{ j.title }}</span>
                  <p class="up-item-sub">{{ j.travel_days ? `${j.travel_days} 天行程` : '' }}</p>
                  <span class="up-item-meta">{{ j.created_at?.slice(0, 10) }}</span>
                </div>
              </div>
            </div>
          </TabPane>
        </Tabs>
      </Card>
    </Spin>

    <!-- 添加好友弹窗（验证消息） -->
    <Modal
      v-model:open="applyOpen"
      title="添加好友"
      :confirm-loading="applySubmitting"
      ok-text="发送申请"
      cancel-text="取消"
      @ok="submitApply"
    >
      <p style="color: #999; margin: 0 0 8px;">发送验证消息，对方同意后即可聊天</p>
      <Input.TextArea
        v-model:value="verifyText"
        :rows="3"
        :maxlength="200"
        :placeholder="`我是${username}的粉丝，想和你交流旅行~`"
      />
    </Modal>
  </div>
</template>

<style scoped>
.up-page {
  max-width: 1900px;
  margin: 0 auto;
  padding: 24px 0;
}
.up-topbar {
  padding: 0 4px 10px;
}
.up-back {
  color: #64748b;
  font-size: 14px;
  padding-left: 0;
}
.up-back:hover {
  color: var(--brand);
}
.up-banner {
  height: 88px;
  background: linear-gradient(120deg, #e8f5e9 0%, #f1f8e9 60%, #e3f2fd 100%);
}
.up-head {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-top: -46px;
  flex-wrap: wrap;
}
.up-avatar {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  background: var(--brand-soft, #e6f2e7);
  border: 4px solid #fff;
  color: var(--brand, #2e7d32);
  font-size: 34px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.up-meta {
  flex: 1;
  min-width: 160px;
}
.up-actions {
  display: flex;
  align-items: center;
  padding-bottom: 4px;
}
.up-verify {
  color: #b45309;
  font-size: 13px;
  margin-right: 10px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.up-stats {
  display: flex;
  gap: 28px;
  margin-top: 16px;
  color: #666;
  font-size: 14px;
}
.up-stats b {
  color: #222;
  font-size: 17px;
  margin-right: 4px;
}
.up-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  /* 固定高度框：内容多时框内滚动（与个人中心「我的发布」一致） */
  max-height: 520px;
  overflow-y: auto;
  padding-right: 8px;
}
.up-list::-webkit-scrollbar {
  width: 6px;
}
.up-list::-webkit-scrollbar-thumb {
  background: #dbe3ec;
  border-radius: 999px;
}
.up-item {
  display: flex;
  gap: 12px;
  padding: 10px;
  border: 1px solid #f0f0f0;
  border-radius: 12px;
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.up-item:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
.up-item-cover {
  width: 96px;
  height: 72px;
  object-fit: cover;
  border-radius: 8px;
  flex-shrink: 0;
}
.up-item-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  background: #f5f5f5;
}
.up-item-main {
  flex: 1;
  min-width: 0;
}
.up-item-title {
  font-size: 15px;
  font-weight: 600;
  margin-left: 6px;
}
.up-item-sub {
  color: #888;
  font-size: 13px;
  margin: 4px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.up-item-meta {
  color: #aaa;
  font-size: 12px;
}
</style>
