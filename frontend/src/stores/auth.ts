/**
 * src/stores/auth.ts：用户认证状态管理（Pinia Store）
 * 作用：集中管理用户登录状态、token、用户信息，提供 login、logout 等异步/同步方法
 */

// 从 Pinia 导入 defineStore，用于定义 store
import { defineStore } from 'pinia'
// 从 Vue 导入 ref 与 computed，分别用于响应式状态与派生状态
import { ref, computed } from 'vue'
// 导入登录、注册、获取当前用户等 API
import { login as loginApi, register as registerApi, getCurrentUser } from '@/api/auth'
// 导入后端统一响应类型
import type { StandardResponse } from '@/api/request'

/**
 * User：用户信息对象类型
 * 包含用户唯一标识、用户名、邮箱等基础字段
 */
export interface User {
  id?: number
  username: string
  email?: string
}

// 用户信息在 localStorage 中的键名（随 token 一起持久化，刷新后恢复）
const USER_STORAGE_KEY = 'agent1_travel_user'

/**
 * useAuthStore：用户认证状态管理 store
 * 返回 token、user、isAuthenticated 等状态及 login/logout/register 方法
 */
export const useAuthStore = defineStore('auth', () => {
  // token：用户登录令牌，初始值尝试从 localStorage 读取
  const token = ref<string | null>(localStorage.getItem('agent1_travel_token'))
  // user：当前登录用户信息，初始值从 localStorage 恢复（避免刷新后丢失）
  const user = ref<User | null>(restoreUserFromStorage())

  // isAuthenticated：计算属性，判断当前是否已登录（token 存在且有效）
  const isAuthenticated = computed<boolean>(() => !!token.value)

  /**
   * restoreUserFromStorage：从 localStorage 恢复用户信息（解析失败时返回 null）
   */
  function restoreUserFromStorage(): User | null {
    try {
      const raw = localStorage.getItem(USER_STORAGE_KEY)
      return raw ? (JSON.parse(raw) as User) : null
    } catch {
      return null
    }
  }

  /**
   * setToken：保存 token 到状态与本地存储
   * @param value 登录成功后返回的 JWT access_token 字符串
   */
  const setToken = (value: string) => {
    token.value = value
    localStorage.setItem('agent1_travel_token', value)
  }

  /**
   * persistUser：把用户信息写入本地存储（供刷新后恢复）
   * @param value 用户信息对象
   */
  const persistUser = (value: User) => {
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(value))
  }

  /**
   * clearAuth：清空登录状态与本地存储的 token
   */
  const clearAuth = () => {
    token.value = null
    user.value = null
    localStorage.removeItem('agent1_travel_token')
    localStorage.removeItem(USER_STORAGE_KEY)
  }

  /**
   * login：用户登录方法
   * @param username 用户名
   * @param password 密码
   * @returns Promise<StandardResponse> 后端响应结果
   * 主要流程：调用登录 API -> 成功后保存 token -> 获取当前用户信息
   */
  const login = async (username: string, password: string): Promise<StandardResponse> => {
    const res = await loginApi(username, password)
    if (res.success && res.data?.access_token) {
      setToken(res.data.access_token)
      // 登录成功后获取用户信息
      await fetchUser()
    }
    return res
  }

  /**
   * register：用户注册方法
   * @param username 用户名
   * @param email 邮箱
   * @param password 密码
   * @returns Promise<StandardResponse> 后端响应结果
   */
  const register = async (username: string, email: string, password: string): Promise<StandardResponse> => {
    return await registerApi(username, email, password)
  }

  /**
   * fetchUser：获取当前登录用户信息
   * @returns Promise<User | null> 用户信息或 null
   */
  const fetchUser = async (): Promise<User | null> => {
    if (!token.value) return null
    const res = await getCurrentUser()
    if (res.success && res.data) {
      user.value = res.data as User
      // 同步写入本地存储，刷新后可恢复
      persistUser(user.value)
      return user.value
    }
    return null
  }

  /**
   * logout：退出登录方法
   */
  const logout = () => {
    clearAuth()
  }

  // 返回 store 暴露给外部的状态与方法
  return {
    token,
    user,
    isAuthenticated,
    login,
    register,
    fetchUser,
    logout
  }
})
