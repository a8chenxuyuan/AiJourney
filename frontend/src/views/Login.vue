<!--
  src/views/Login.vue：登录页面
  作用：提供用户名、密码输入表单，调用 auth store 完成登录并跳转首页
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 定义表单响应式数据
 * 2. 调用 auth store 的 login 方法
 * 3. 登录成功后通过 Vue Router 跳转首页
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { reactive, ref } from 'vue'
// 引入 Vue Router 的 useRouter Hook
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 表单、输入框、按钮、消息提示组件
import { Form, Input, Button, Card, message } from 'ant-design-vue'
// 引入用户认证状态管理 store
import { useAuthStore } from '@/stores/auth'

// 获取路由实例，用于登录成功后跳转
const router = useRouter()
// 获取用户认证状态管理 store
const authStore = useAuthStore()

// loginForm：登录表单响应式数据
const loginForm = reactive({
  username: '',
  password: ''
})

// loading：控制登录按钮的加载状态
const loading = ref(false)

/**
 * handleLogin：登录表单提交处理函数
 * 作用：校验表单、调用登录接口、成功后跳转首页
 */
const handleLogin = async () => {
  // 简单的前端非空校验
  if (!loginForm.username || !loginForm.password) {
    message.warning('请输入用户名和密码')
    return
  }

  loading.value = true
  try {
    // 调用 auth store 的 login 方法，内部会保存 token 并获取用户信息
    const res = await authStore.login(loginForm.username, loginForm.password)
    if (res.success) {
      message.success('登录成功')
      // 登录成功后跳转首页
      router.push('/')
    } else {
      message.error(res.message || '登录失败')
    }
  } catch (error) {
    // request.ts 已统一处理错误提示，此处可记录日志
    console.error('登录异常', error)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <!-- 页面容器：居中显示登录卡片 -->
  <div class="auth-shell page-fade">
    <Card class="auth-card">
      <!-- 品牌区 -->
      <div class="auth-brand">
        <div class="app-logo-icon">✈️</div>
        <div class="auth-brand-title">欢迎回来</div>
        <div class="auth-brand-sub">登录 agent1旅行，继续你的下一段旅程</div>
      </div>

      <!-- 登录表单 -->
      <Form layout="vertical">
        <Form.Item label="用户名">
          <Input v-model:value="loginForm.username" size="large" placeholder="请输入用户名" @pressEnter="handleLogin" />
        </Form.Item>
        <Form.Item label="密码">
          <Input.Password v-model:value="loginForm.password" size="large" placeholder="请输入密码" @pressEnter="handleLogin" />
        </Form.Item>
        <Form.Item style="margin-bottom: 12px;">
          <Button type="primary" block size="large" :loading="loading" @click="handleLogin">登录</Button>
        </Form.Item>
        <div style="text-align: center; color: var(--ink-3); font-size: 13px;">
          还没有账号？<a style="color: var(--brand); font-weight: 600;" @click="router.push('/register')">立即注册</a>
        </div>
      </Form>
    </Card>
  </div>
</template>
