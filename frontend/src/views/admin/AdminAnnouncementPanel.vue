<!--
  AdminAnnouncementPanel.vue：管理后台系统公告——历史公告列表、发布与清空操作
-->
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { message, Popconfirm } from 'ant-design-vue'
import {
  createAnnouncement,
  clearAnnouncements,
  listAnnouncements,
  type AdminAnnouncement
} from '@/api/admin'

// annForm：公告表单；sending：发送中；anns：历史公告列表
const annForm = reactive({ title: '', content: '' })
const sending = ref(false)
const anns = ref<AdminAnnouncement[]>([])
const annsLoading = ref(false)

/** load：拉取历史公告（发送时间倒序） */
async function load() {
  annsLoading.value = true
  try {
    const res = await listAnnouncements()
    if (res.success) anns.value = res.data
  } finally {
    annsLoading.value = false
  }
}

/** sendAnnouncement：发送系统公告（全站用户），成功后刷新历史列表 */
async function sendAnnouncement() {
  if (!annForm.title.trim() || !annForm.content.trim()) {
    message.warning('请填写公告标题和内容')
    return
  }
  sending.value = true
  try {
    const res = await createAnnouncement(annForm.title.trim(), annForm.content.trim())
    if (res.success) {
      message.success(res.message)
      annForm.title = ''
      annForm.content = ''
      load()
    }
  } finally {
    sending.value = false
  }
}

/** clearAllAnnouncements：清空全部系统公告 */
async function clearAllAnnouncements() {
  const res = await clearAnnouncements()
  if (res.success) {
    message.success(res.message)
    load()
  }
}

defineExpose({ load })
</script>

<template>
  <!-- 历史公告列表 -->
  <div class="ad-ann-form">
    <div class="ad-ann-head">
      <h3>🗂️ 历史公告（{{ anns.length }}）</h3>
      <a-button size="small" @click="load">刷新</a-button>
    </div>
    <a-spin :spinning="annsLoading">
      <div v-if="anns.length" class="ad-ann-list">
        <div v-for="(a, i) in anns" :key="i" class="ad-ann-item">
          <span class="ad-ann-horn">📢</span>
          <div class="ad-ann-body">
            <p class="ad-ann-title">{{ a.title }}</p>
            <p class="ad-ann-content">{{ a.content }}</p>
            <span class="ad-ann-meta">
              {{ a.sent_at ? a.sent_at.slice(0, 16).replace('T', ' ') : '-' }} · 触达 {{ a.receivers }} 名用户
            </span>
          </div>
        </div>
      </div>
      <div v-else-if="!annsLoading" class="ad-ann-empty">还没有发布过公告</div>
    </a-spin>
  </div>

  <!-- 发布表单 -->
  <div class="ad-ann-form" style="margin-top: 14px;">
    <h3>📢 发布系统公告</h3>
    <p class="ad-ann-tip">公告会推送给全站用户：在线用户实时弹提醒，全部用户可在「消息 → 互动通知」查看。</p>
    <div class="ad-ann-inputs">
      <a-input v-model:value="annForm.title" placeholder="公告标题（50 字内）" :maxlength="50" show-count style="margin: 14px 0 12px" />
      <a-textarea v-model:value="annForm.content" placeholder="公告内容（500 字内）" :maxlength="500" :rows="5" show-count />
      <div class="ad-ann-actions">
        <a-button type="primary" :loading="sending" @click="sendAnnouncement">发送公告</a-button>
        <Popconfirm title="确认清空全部系统公告？此操作不可恢复。" @confirm="clearAllAnnouncements">
          <a-button danger>清空全部公告</a-button>
        </Popconfirm>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== 公告表单 ===== */
.ad-ann-form {
  background: #fff;
  border-radius: 18px;
  padding: 28px 32px;
  box-shadow: 0 4px 18px rgba(30, 41, 59, 0.06);
}

/* 发布表单输入区与其他卡统一的全宽排版 */
.ad-ann-form .ad-ann-inputs {
  max-width: 720px;
}

/* 历史公告列表 */
.ad-ann-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.ad-ann-head h3 {
  margin: 0;
}
.ad-ann-list {
  max-height: 420px;
  overflow-y: auto;
  padding-right: 8px;
  margin-top: 8px;
}
.ad-ann-list::-webkit-scrollbar {
  width: 6px;
}
.ad-ann-list::-webkit-scrollbar-thumb {
  background: #dbe3ec;
  border-radius: 999px;
}
.ad-ann-item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid #f1f5f9;
  background: #f8fafc;
  margin-bottom: 10px;
}
.ad-ann-horn {
  font-size: 20px;
  flex-shrink: 0;
}
.ad-ann-body {
  min-width: 0;
  flex: 1;
}
.ad-ann-title {
  margin: 0 0 4px;
  font-weight: 700;
  color: #1e293b;
  font-size: 14px;
}
.ad-ann-content {
  margin: 0 0 6px;
  color: #475569;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ad-ann-meta {
  color: #94a3b8;
  font-size: 12px;
}
.ad-ann-empty {
  text-align: center;
  color: #cbd5e1;
  padding: 26px 0;
  font-size: 13px;
}
.ad-ann-form h3 {
  margin: 0;
  font-size: 17px;
}
.ad-ann-tip {
  color: #94a3b8;
  font-size: 13px;
  margin: 8px 0 0;
}
.ad-ann-actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}
</style>
