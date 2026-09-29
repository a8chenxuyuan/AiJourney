<!--
  src/views/Register.vue：注册页面
  作用：提供用户名、邮箱、密码输入表单，调用注册 API 完成用户注册
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 定义注册表单响应式数据
 * 2. 前端校验两次输入的密码是否一致
 * 3. 调用 auth store 的 register 方法，成功后跳转登录页
 */

// 引入 Vue 的响应式 API
import { reactive, ref } from 'vue'
// 引入 Vue Router 的 useRouter Hook
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 表单、输入框、按钮、消息提示组件
import { Form, Input, Button, Card, message } from 'ant-design-vue'
// 引入用户认证状态管理 store
import { useAuthStore } from '@/stores/auth'

// 获取路由实例，用于注册成功后跳转
const router = useRouter()
// 获取用户认证状态管理 store
const authStore = useAuthStore()

// registerForm：注册表单响应式数据
const registerForm = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

// loading：控制注册按钮的加载状态
const loading = ref(false)

/**
 * handleRegister：注册表单提交处理函数
 * 作用：校验表单、调用注册接口、成功后跳转登录页
 */
const handleRegister = async () => {
  // 简单的前端非空校验
  if (!registerForm.username || !registerForm.email || !registerForm.password) {
    message.warning('请填写完整注册信息')
    return
  }
  // 校验两次密码是否一致
  if (registerForm.password !== registerForm.confirmPassword) {
    message.error('两次输入的密码不一致')
    return
  }

  loading.value = true
  try {
    // 调用 auth store 的 register 方法
    const res = await authStore.register(registerForm.username, registerForm.email, registerForm.password)
    if (res.success) {
      message.success('注册成功，请登录')
      // 注册成功后跳转登录页
      router.push('/login')
    } else {
      message.error(res.message || '注册失败')
    }
  } catch (error) {
    console.error('注册异常', error)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <!-- 页面容器：居中显示注册卡片 -->
  <div class="auth-shell page-fade">
    <Card class="auth-card">
      <!-- 品牌区 -->
      <div class="auth-brand">
        <div class="app-logo-icon">✈️</div>
        <div class="auth-brand-title">创建账号</div>
        <div class="auth-brand-sub">注册 agent1旅行，开启 AI 行程规划之旅</div>
      </div>

      <!-- 注册表单 -->
      <Form layout="vertical">
        <Form.Item label="用户名">
          <Input v-model:value="registerForm.username" size="large" placeholder="请输入用户名" />
        </Form.Item>
        <Form.Item label="邮箱">
          <Input v-model:value="registerForm.email" size="large" placeholder="请输入邮箱" />
        </Form.Item>
        <Form.Item label="密码">
          <Input.Password v-model:value="registerForm.password" size="large" placeholder="请输入密码" />
        </Form.Item>
        <Form.Item label="确认密码">
          <Input.Password v-model:value="registerForm.confirmPassword" size="large" placeholder="请再次输入密码" @pressEnter="handleRegister" />
        </Form.Item>
        <Form.Item style="margin-bottom: 12px;">
          <Button type="primary" block size="large" :loading="loading" @click="handleRegister">注册</Button>
        </Form.Item>
        <div style="text-align: center; color: var(--ink-3); font-size: 13px;">
          已有账号？<a style="color: var(--brand); font-weight: 600;" @click="router.push('/login')">立即登录</a>
        </div>
      </Form>
    </Card>
  </div>
</template>
