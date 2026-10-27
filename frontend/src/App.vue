<!--
  src/App.vue：应用根组件
  作用：提供全局布局（左侧毛玻璃侧边栏 + 右侧内容区）与路由出口（router-view），
       控制登录/未登录状态下的导航展示；登录/注册页使用无侧边栏的裸布局。
  设计说明：侧边栏集中品牌、导航（首页/旅行圈/个人中心）与用户卡片，
           激活项用品牌渐变高亮，整体风格由 design-system.css 统一约束。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 引入路由相关 Hook 与 Auth Store
 * 2. 从 store 读取登录状态与用户信息
 * 3. 侧边栏按当前路由高亮导航项；退出登录清空状态并跳转登录页
 */

// 引入 Vue 的 computed，用于计算派生状态
import { computed, ref, watch } from 'vue'
// 引入 Vue Router 的 useRouter / useRoute Hook
import { useRouter, useRoute } from 'vue-router'
// 引入 Ant Design Vue 的 message 提示
import { message } from 'ant-design-vue'
// 引入用户状态管理 store
import { useAuthStore } from '@/stores/auth'
// 引入消息通知 store（红点 + WS 长连）
import { useNotifyStore } from '@/stores/notify'

// 获取路由实例
const router = useRouter()
// 获取当前路由（用于导航高亮）
const route = useRoute()
// 获取用户认证状态管理 store
const authStore = useAuthStore()
// 获取消息通知 store：登录后建立 WS 长连并拉红点，登出时断开
const notifyStore = useNotifyStore()

// currentYear：用于页脚版权年份
const currentYear = new Date().getFullYear()

// searchDraft：侧栏搜索框草稿（回车跳 /search）
const searchDraft = ref('')

// 登录态变化驱动 WS 连接与红点
watch(
  () => authStore.isAuthenticated,
  (authed) => {
    if (authed) notifyStore.connect()
    else notifyStore.disconnect()
  },
  { immediate: true }
)

// userInitial：用户名首字（头像展示用）
const userInitial = computed(() => (authStore.user?.username || '旅').charAt(0).toUpperCase())

// isBareLayout：登录/注册页不渲染侧边栏，内容全宽
const isBareLayout = computed(() => ['/login', '/register'].includes(route.path))

/**
 * isActive：侧栏按钮高亮判断
 * exact 为 true 时精确匹配（用于 /profile，避免 /profile/archive 误点亮个人中心）
 */
const isActive = (path: string, exact = false) =>
  exact ? route.path === path : path === '/' ? route.path === '/' : route.path.startsWith(path)

/**
 * handleLogout：退出登录处理函数
 * 作用：调用 auth store 的 logout 方法，清空 token 与用户信息，并跳转登录页
 */
const handleLogout = () => {
  authStore.logout()
  message.success('已退出登录')
  router.push('/login')
}
</script>

<template>
  <!-- 全局布局：左侧栏 + 主内容区 -->
  <div class="app-shell">
    <!-- 左侧毛玻璃侧边栏：品牌 / 导航 / 用户区 -->
    <aside v-if="!isBareLayout" class="app-sidebar">
      <!-- Logo / 品牌名 -->
      <div class="app-logo" @click="router.push('/')">
        <div class="app-logo-icon">✈️</div>
        <div class="app-logo-name">旅<span style="color: var(--brand);">程</span></div>
      </div>

      <!-- 全站搜索入口：回车跳搜索页 -->
      <div class="app-side-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
        <input
          v-model="searchDraft"
          placeholder="搜索帖子 / 游记 / 攻略…"
          @keydown.enter.prevent="searchDraft.trim() && router.push(`/search?q=${encodeURIComponent(searchDraft.trim())}`)"
        />
      </div>

      <!-- 导航：首页 / 旅行圈（内含照片墙/攻略笔记双 Tab）/ 攻略灵感 / 个人中心 -->
      <nav class="app-side-nav">
        <button class="app-side-link" :class="{ active: isActive('/') }" @click="router.push('/')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg>
          <span>首页</span>
        </button>
        <button
          class="app-side-link"
          :class="{ active: isActive('/circle') }"
          @click="router.push('/circle')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" /></svg>
          <span>旅行圈</span>
        </button>
        <button
          class="app-side-link"
          :class="{ active: isActive('/guides') || isActive('/destination') }"
          @click="router.push('/guides')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" /></svg>
          <span>攻略灵感</span>
        </button>
        <!-- 同路人：达人发现页（免登录可看） -->
        <button
          class="app-side-link"
          :class="{ active: isActive('/creators') }"
          @click="router.push('/creators')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
          <span>同路人</span>
        </button>
        <button
          class="app-side-link"
          :class="{ active: isActive('/messages') }"
          @click="router.push('/messages')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
          <span>消息</span>
          <span v-if="notifyStore.totalBadge > 0" class="app-side-badge">{{ notifyStore.totalBadge > 99 ? '99+' : notifyStore.totalBadge }}</span>
        </button>
        <button
          class="app-side-link"
          :class="{ active: isActive('/orders') }"
          @click="router.push('/orders')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" /><line x1="1" y1="10" x2="23" y2="10" /></svg>
          <span>我的订单</span>
        </button>
        <button
          v-if="authStore.isAuthenticated"
          class="app-side-link"
          :class="{ active: isActive('/profile/archive') }"
          @click="router.push('/profile/archive')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 21V8a4 4 0 0 1 4-4h0a4 4 0 0 1 4 4v13" /><path d="M4 21h16" /><path d="M8 12h8" /></svg>
          <span>旅行档案</span>
        </button>
        <!-- 我的行囊：收藏独立页 -->
        <button
          v-if="authStore.isAuthenticated"
          class="app-side-link"
          :class="{ active: isActive('/favorites') }"
          @click="router.push('/favorites')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" /><path d="M3 6h18" /><path d="M16 10a4 4 0 0 1-8 0" /></svg>
          <span>我的行囊</span>
        </button>
        <button
          v-if="authStore.isAuthenticated"
          class="app-side-link"
          :class="{ active: isActive('/profile', true) }"
          @click="router.push('/profile')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
          <span>个人中心</span>
        </button>
        <!-- 管理后台入口：仅管理员可见 -->
        <button
          v-if="authStore.isAdmin"
          class="app-side-link"
          :class="{ active: isActive('/admin') }"
          @click="router.push('/admin')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
          <span>管理后台</span>
        </button>
      </nav>

      <!-- 底部：用户卡片或登录/注册入口 -->
      <div class="app-side-foot">
        <template v-if="authStore.isAuthenticated">
          <div class="app-side-user">
            <div class="app-user-avatar">{{ userInitial }}</div>
            <div class="app-side-user-meta">
              <span class="app-side-user-name">{{ authStore.user?.username || '旅行者' }}</span>
              <span class="app-side-user-tag">旅行者</span>
            </div>
            <button class="app-side-logout" title="退出登录" @click="handleLogout">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" x2="9" y1="12" y2="12" /></svg>
            </button>
          </div>
        </template>
        <template v-else>
          <button class="app-side-login" @click="router.push('/login')">登录</button>
          <button class="app-side-register" @click="router.push('/register')">注册</button>
        </template>
      </div>
    </aside>

    <!-- 右侧主区：页面内容 + 页脚 -->
    <div class="app-main">
      <!-- 页面主内容区域：各页面根节点自带 page-fade 挂载动画 -->
      <main class="app-content">
        <router-view />
      </main>

      <!-- 页脚 -->
      <footer class="app-footer">
        © {{ currentYear }} <strong>旅程</strong> · 让 AI 为你规划每一次出发 ✈️
      </footer>
    </div>
  </div>
</template>
