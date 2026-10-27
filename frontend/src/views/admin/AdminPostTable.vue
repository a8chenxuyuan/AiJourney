<!--
  AdminPostTable.vue：管理后台内容审核——帖子状态筛选、下架与恢复操作
-->
<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { listAdminPosts, hidePost, restorePost, type AdminPostRow } from '@/api/admin'

const posts = ref<AdminPostRow[]>([])
const postTotal = ref(0)
const postPage = ref(1)
const postSize = 10
const statusFilter = ref<'all' | 'published' | 'hidden'>('all')
const postsLoading = ref(false)

/** load：拉取帖子审核列表 */
async function load() {
  postsLoading.value = true
  try {
    const res = await listAdminPosts(statusFilter.value, postPage.value, postSize)
    if (res.success) {
      posts.value = res.data.posts
      postTotal.value = res.data.total
    }
  } finally {
    postsLoading.value = false
  }
}

/** onFilterChange：切换状态筛选（重置回第一页） */
function onFilterChange() {
  postPage.value = 1
  load()
}

/** toggleHide：下架/恢复帖子 */
async function toggleHide(row: AdminPostRow) {
  const res = row.status === 'hidden' ? await restorePost(row.id) : await hidePost(row.id)
  if (res.success) {
    message.success(res.message)
    load()
  }
}

const postColumns = [
  { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
  { title: '作者', dataIndex: 'author', key: 'author', width: 110 },
  { title: '分区', key: 'zone', width: 90 },
  { title: '状态', key: 'status', width: 90 },
  { title: '赞/评', key: 'counts', width: 80 },
  { title: '发布时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'actions', width: 150 }
]

// 分区/状态中文映射
const zoneText: Record<string, string> = { circle: '旅行圈', note: '笔记' }
const statusMeta: Record<string, { text: string; color: string }> = {
  published: { text: '已发布', color: 'green' },
  hidden: { text: '已下架', color: 'red' }
}

/** fmtTime：时间格式化（YYYY-MM-DD HH:mm） */
function fmtTime(iso: string | null | undefined) {
  if (!iso) return '-'
  return iso.slice(0, 16).replace('T', ' ')
}

defineExpose({ load })
</script>

<template>
  <div class="ad-toolbar">
    <a-segmented
      v-model:value="statusFilter"
      :options="[
        { label: '全部', value: 'all' },
        { label: '已发布', value: 'published' },
        { label: '已下架', value: 'hidden' }
      ]"
      @change="onFilterChange"
    />
  </div>
  <a-table
    :columns="postColumns"
    :data-source="posts"
    :loading="postsLoading"
    :pagination="{ current: postPage, pageSize: postSize, total: postTotal, onChange: (p: number) => { postPage = p; load() } }"
    row-key="id"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'zone'">
        {{ zoneText[record.zone] || record.zone }}
      </template>
      <template v-else-if="column.key === 'status'">
        <a-tag :color="statusMeta[record.status]?.color || 'default'">
          {{ statusMeta[record.status]?.text || record.status }}
        </a-tag>
      </template>
      <template v-else-if="column.key === 'counts'">
        {{ record.like_count }} / {{ record.comment_count }}
      </template>
      <template v-else-if="column.key === 'created_at'">
        {{ fmtTime(record.created_at) }}
      </template>
      <template v-else-if="column.key === 'actions'">
        <a-button size="small" :danger="record.status !== 'hidden'" @click="toggleHide(record)">
          {{ record.status === 'hidden' ? '恢复' : '下架' }}
        </a-button>
        <a-button size="small" style="margin-left: 8px" @click="$router.push(`/community/${record.id}`)">查看</a-button>
      </template>
    </template>
  </a-table>
</template>

<style scoped>
.ad-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: center;
}
</style>
