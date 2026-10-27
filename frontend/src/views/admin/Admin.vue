<!--
  src/views/Admin.vue：管理后台
  作用：数据看板 / 用户管理（封禁+授权）/ 内容审核（帖子下架恢复）/ 系统公告
  权限：仅 admin 角色可见（路由守卫 + 侧边栏入口 + 后端 get_current_admin 三重校验）
  子组件：Admin/（StatsPanel 看板、UserTable 用户、PostTable 审核、AnnouncementPanel 公告）
-->

<script setup lang="ts">
import { onMounted, ref } from 'vue'
// 引入路由（读取 ?tab= 指定激活页签）
import { useRoute } from 'vue-router'
import AdminStatsPanel from './AdminStatsPanel.vue'
import AdminUserTable from './AdminUserTable.vue'
import AdminPostTable from './AdminPostTable.vue'
import AdminAnnouncementPanel from './AdminAnnouncementPanel.vue'

// activeTab：当前激活的 Tab（stats/users/posts/ann），支持 /admin?tab=posts 深链
const route = useRoute()
const activeTab = ref((route.query.tab as string) || 'stats')

const statsRef = ref<InstanceType<typeof AdminStatsPanel> | null>(null)
const usersRef = ref<InstanceType<typeof AdminUserTable> | null>(null)
const postsRef = ref<InstanceType<typeof AdminPostTable> | null>(null)
const annRef = ref<InstanceType<typeof AdminAnnouncementPanel> | null>(null)

// 四个面板经 force-render 预挂载，路由进入时在主文件统一触发各 Tab 数据加载
onMounted(() => {
  statsRef.value?.load()
  usersRef.value?.load()
  postsRef.value?.load()
  annRef.value?.load()
})
</script>

<template>
  <div class="page-fade ad-page">
    <!-- 页头 -->
    <div class="ad-head">
      <h2>🛡️ 管理后台</h2>
      <span class="ad-sub">仅管理员可见 · 操作实时生效</span>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="stats" tab="数据看板" force-render>
        <AdminStatsPanel ref="statsRef" />
      </a-tab-pane>
      <a-tab-pane key="users" tab="用户管理" force-render>
        <AdminUserTable ref="usersRef" />
      </a-tab-pane>
      <a-tab-pane key="posts" tab="内容审核" force-render>
        <AdminPostTable ref="postsRef" />
      </a-tab-pane>
      <a-tab-pane key="ann" tab="系统公告" force-render>
        <AdminAnnouncementPanel ref="annRef" />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<style scoped>
/* ===== 页面骨架 ===== */
.ad-page {
  max-width: 1900px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}
.ad-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
}
.ad-head h2 {
  margin: 0;
  font-size: 24px;
}
.ad-sub {
  color: #94a3b8;
  font-size: 13px;
}
.ad-page :deep(.ant-tabs-tab) {
  font-size: 15px;
}
</style>
