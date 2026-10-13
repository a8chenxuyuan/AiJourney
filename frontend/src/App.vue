<!--
  src/App.vue：应用根组件
  作用：提供全局布局（左侧毛玻璃侧边栏 + 右侧内容区）与路由出口（router-view），
       控制登录/未登录状态下的导航展示；登录/注册页使用无侧边栏的裸布局。
  设计说明：侧边栏集中品牌、导航（首页/旅行圈/旅行笔记/个人中心）与用户卡片，
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
import { computed } from 'vue'
// 引入 Vue Router 的 useRouter / useRoute Hook
import { useRouter, useRoute } from 'vue-router'
// 引入 Ant Design Vue 的 message 提示
import { message } from 'ant-design-vue'
// 引入用户状态管理 store
import { useAuthStore } from '@/stores/auth'

// 获取路由实例
const router = useRouter()
// 获取当前路由（用于导航高亮）
const route = useRoute()
// 获取用户认证状态管理 store
const authStore = useAuthStore()

// currentYear：用于页脚版权年份
const currentYear = new Date().getFullYear()

// userInitial：用户名首字（头像展示用）
const userInitial = computed(() => (authStore.user?.username || '旅').charAt(0).toUpperCase())

// isBareLayout：登录/注册页不渲染侧边栏，内容全宽
const isBareLayout = computed(() => ['/login', '/register'].includes(route.path))

/**
 * isActive：判断指定导航是否为当前路由（首页精确匹配，其余按前缀匹配）
 */
const isActive = (path: string) =>
  path === '/' ? route.path === '/' : route.path.startsWith(path)

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
        <div class="app-logo-name">agent1<span style="color: var(--brand);">旅行</span></div>
      </div>

      <!-- 导航：首页 / 旅行圈 / 旅行笔记 / 个人中心 -->
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
          :class="{ active: isActive('/notes') }"
          @click="router.push('/notes')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" /></svg>
          <span>旅行笔记</span>
        </button>
        <button
          v-if="authStore.isAuthenticated"
          class="app-side-link"
          :class="{ active: isActive('/profile') }"
          @click="router.push('/profile')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
          <span>个人中心</span>
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
        © {{ currentYear }} <strong>agent1旅行</strong> · 让 AI 为你规划每一次出发 ✈️
      </footer>
    </div>
  </div>
</template>
