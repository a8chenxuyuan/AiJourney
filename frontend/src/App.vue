<!--
  src/App.vue：应用根组件
  作用：提供全局布局、玻璃拟态顶部导航栏以及路由出口（router-view），
       控制登录/未登录状态下的导航展示。
  设计说明：导航栏采用毛玻璃（backdrop-filter）效果 + 胶囊式导航链接，
           内容区带页面进入动画，整体风格由 design-system.css 统一约束。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 引入路由相关 Hook 与 Auth Store
 * 2. 从 store 读取登录状态与用户信息
 * 3. 点击退出登录时清除状态并跳转登录页
 */

// 引入 Vue 的 computed，用于计算当前激活导航
import { computed } from 'vue'
// 引入 Vue Router 的 useRouter / useRoute Hook
import { useRouter, useRoute } from 'vue-router'
// 引入 Ant Design Vue 的 message 提示与 Button 组件
import { message, Button } from 'ant-design-vue'
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

/**
 * isActive：判断指定导航是否为当前路由
 */
const isActive = (path: string) => route.path === path

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
  <!-- 全局布局容器 -->
  <div style="min-height: 100vh; display: flex; flex-direction: column;">
    <!-- 顶部玻璃拟态导航栏 -->
    <header class="app-navbar">
      <!-- Logo / 品牌名 -->
      <div class="app-logo" @click="router.push('/')">
        <div class="app-logo-icon">✈️</div>
        <div class="app-logo-name">agent1<span style="color: var(--brand);">旅行</span></div>
      </div>

      <!-- 中部导航胶囊 -->
      <nav class="app-nav-links">
        <button class="app-nav-link" :class="{ active: isActive('/') }" @click="router.push('/')">首页</button>
        <button
          v-if="authStore.isAuthenticated"
          class="app-nav-link"
          :class="{ active: isActive('/profile') }"
          @click="router.push('/profile')"
        >
          个人中心
        </button>
      </nav>

      <!-- 右侧用户信息 / 登录注册按钮 -->
      <div class="app-user-chip">
        <template v-if="authStore.isAuthenticated">
          <div class="app-user-avatar">{{ userInitial }}</div>
          <span style="font-size: 14px; color: var(--ink-2);">{{ authStore.user?.username || '旅行者' }}</span>
          <button class="app-logout-btn" @click="handleLogout">退出</button>
        </template>
        <template v-else>
          <button class="app-logout-btn" @click="router.push('/login')">登录</button>
          <Button type="primary" style="border-radius: 999px; padding: 0 22px;" @click="router.push('/register')">
            注册
          </Button>
        </template>
      </div>
    </header>

    <!-- 页面主内容区域：各页面根节点自带 page-fade 挂载动画 -->
    <main class="app-content">
      <router-view />
    </main>

    <!-- 页脚 -->
    <footer class="app-footer">
      © {{ currentYear }} <strong>agent1旅行</strong> · 让 AI 为你规划每一次出发 ✈️
    </footer>
  </div>
</template>
