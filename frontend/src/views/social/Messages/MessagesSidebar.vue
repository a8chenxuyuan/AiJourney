<!--
  MessagesSidebar.vue：消息中心左栏——新朋友申请、互动通知、好友与会话列表（未读置顶高亮）
-->
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Button, Spin, Tag } from 'ant-design-vue'
import type { FriendRequest, FriendItem, NotificationItem } from '@/api/social'

defineProps<{
  requests: FriendRequest[]
  notifications: NotificationItem[]
  friends: FriendItem[]
  leftLoading: boolean
  activePeerId?: number | null
}>()

const emit = defineEmits<{
  accept: [r: FriendRequest]
  reject: [r: FriendRequest]
  'read-all': []
  'open-chat': [peer: { id: number; name: string; online: boolean }]
}>()

const router = useRouter()

const goUserHome = (uid: number) => router.push(`/user/${uid}`)

/** 通知点击跳转（帖子类跳详情） */
const goNotification = (n: NotificationItem) => {
  if (n.payload?.post_id) router.push(`/community/${n.payload.post_id}`)
}

/** 通知文案中的类型徽标 */
const ntypeMeta: Record<string, { text: string; color: string }> = {
  like: { text: '赞', color: 'orange' },
  comment: { text: '评', color: 'blue' },
  reply: { text: '回复', color: 'cyan' },
  friend_request: { text: '好友', color: 'green' },
  friend_accepted: { text: '好友', color: 'green' },
  system: { text: '公告', color: 'purple' }
}
</script>

<template>
  <div class="msg-left">
    <Spin :spinning="leftLoading">
      <div class="msg-section">
        <div class="msg-section-head">
          <span>👥 新朋友</span>
          <Tag v-if="requests.length" color="red">{{ requests.length }}</Tag>
        </div>
        <div v-if="!requests.length" class="msg-empty-line">暂无好友申请</div>
        <div v-for="r in requests" :key="r.friendship_id" class="msg-request">
          <div class="msg-avatar">{{ r.username.charAt(0).toUpperCase() }}</div>
          <div class="msg-request-main">
            <b>{{ r.username }}</b>
            <p>{{ r.verify_message || '请求加你为好友' }}</p>
          </div>
          <div class="msg-request-btns">
            <Button size="small" type="primary" @click="emit('accept', r)">同意</Button>
            <Button size="small" @click="emit('reject', r)">拒绝</Button>
          </div>
        </div>
      </div>

      <div class="msg-section">
        <div class="msg-section-head">
          <span>🔔 互动通知</span>
          <a v-if="notifications.length" class="msg-link" @click="emit('read-all')">全部已读</a>
        </div>
        <div v-if="!notifications.length" class="msg-empty-line">暂无互动通知</div>
        <div
          v-for="n in notifications"
          :key="n.id"
          class="msg-notice"
          :class="{ unread: !n.is_read }"
          @click="goNotification(n)"
        >
          <Tag :color="ntypeMeta[n.ntype]?.color || 'default'">
            {{ ntypeMeta[n.ntype]?.text || '通知' }}
          </Tag>
          <span class="msg-notice-text">
            {{ n.text }}<template v-if="n.payload?.post_title">「{{ n.payload.post_title }}」</template>
          </span>
        </div>
      </div>

      <div class="msg-section">
        <div class="msg-section-head"><span>🧑‍🤝‍🧑 好友</span></div>
        <div v-if="!friends.length" class="msg-empty-line">
          还没有好友，去
          <router-link to="/circle">旅行圈</router-link>
          结识旅行者吧
        </div>
        <div
          v-for="f in friends"
          :key="f.user_id"
          class="msg-friend"
          :class="{ active: activePeerId === f.user_id }"
          @click="emit('open-chat', { id: f.user_id, name: f.username, online: f.is_online })"
        >
          <div
            class="msg-avatar"
            :class="{ online: f.is_online, clickable: true }"
            title="查看主页"
            @click.stop="goUserHome(f.user_id)"
          >
            {{ f.username.charAt(0).toUpperCase() }}
          </div>
          <span class="msg-friend-name">{{ f.username }}</span>
          <span class="msg-online-dot" :class="{ on: f.is_online }"></span>
        </div>
      </div>
    </Spin>
  </div>
</template>

<style scoped>
/* .msg-left 外壳（padding/overflow）由主文件统一下发，根节点继承父级 scope */
.msg-section {
  margin-bottom: 16px;
}
.msg-section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
  margin: 8px 0;
}
.msg-link {
  margin-left: auto;
  font-size: 12px;
  color: var(--brand, #2e7d32);
}
.msg-empty-line {
  color: #bbb;
  font-size: 12px;
  padding: 6px 4px;
}
.msg-request {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 10px;
  background: #fafafa;
  margin-bottom: 8px;
}
.msg-request-main {
  flex: 1;
  min-width: 0;
}
.msg-request-main b {
  font-size: 13px;
}
.msg-request-main p {
  margin: 2px 0 0;
  color: #999;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.msg-request-btns {
  display: flex;
  gap: 6px;
}
.msg-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 6px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.msg-notice:hover {
  background: #fafafa;
}
.msg-notice.unread {
  background: #f6faf6;
}
.msg-notice-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.msg-friend {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 10px;
  cursor: pointer;
}
.msg-friend:hover,
.msg-friend.active {
  background: #f2f8f2;
}
.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e6f2e7;
  color: #2e7d32;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  flex-shrink: 0;
}
.msg-avatar.clickable {
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s;
}
.msg-avatar.clickable:hover {
  box-shadow: 0 0 0 3px rgba(46, 125, 50, 0.15);
  transform: scale(1.06);
}
.msg-friend-name {
  flex: 1;
  font-size: 14px;
}
.msg-online-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ddd;
}
.msg-online-dot.on {
  background: #52c41a;
}
</style>
