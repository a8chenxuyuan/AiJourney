/**
 * src/api/request.ts：Axios 请求封装模块
 * 作用：创建统一的 axios 实例，配置基地址、请求/响应拦截器，实现 token 自动附加与统一错误处理
 */

// 导入 axios 核心与类型
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
// 导入 Ant Design Vue 的消息提示组件，用于错误提示
import { message } from 'ant-design-vue'

/**
 * StandardResponse：后端统一响应结构类型
 * 所有接口均返回 { success: boolean, message: string, data: any }
 */
export interface StandardResponse<T = any> {
  success: boolean
  message: string
  data: T
}

// API_BASE_URL：后端 API 基地址，优先读取环境变量，默认值为 http://localhost:8000/api
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

/**
 * request：统一封装的 axios 实例
 * 基地址已配置为 API_BASE_URL，超时时间 10 秒
 */
const request: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  // headers：默认请求头，声明发送 JSON 数据
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * 请求拦截器
 * 作用：在每次请求发送前，从 localStorage 读取 token 并附加到 Authorization 请求头
 */
request.interceptors.request.use(
  (config) => {
    // 尝试读取本地存储的 token
    const token = localStorage.getItem('agent1_travel_token')
    // 若 token 存在，则设置 Bearer Token
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    // 请求发送失败时，将错误继续向下传递
    return Promise.reject(error)
  }
)

/**
 * 响应拦截器
 * 作用：统一处理后端响应，对 success=false 或 HTTP 错误进行提示
 */
request.interceptors.response.use(
  (response: AxiosResponse<StandardResponse>) => {
    // 提取后端业务数据
    const res = response.data
    // 若后端返回 success 为 false，则提示错误信息
    if (!res.success) {
      message.error(res.message || '请求失败')
    }
    return response
  },
  (error) => {
    // 统一处理 HTTP 错误，例如 401、500 等
    let errorMsg = '网络请求异常'
    if (error.response) {
      const status = error.response.status
      const requestUrl = error.config?.url || ''
      // FastAPI 的 HTTPException 返回 detail 字段，统一响应则是 message 字段
      const backendMsg = error.response.data?.message || error.response.data?.detail
      if (status === 401) {
        // 登录接口的 401 是“用户名或密码错误”，不要显示成登录过期
        if (requestUrl.includes('/auth/login')) {
          errorMsg = backendMsg || '用户名或密码错误'
        } else {
          errorMsg = '登录已过期，请重新登录'
          localStorage.removeItem('agent1_travel_token')
        }
      } else if (status === 500) {
        errorMsg = '服务器内部错误'
      } else {
        errorMsg = backendMsg || `请求错误 (${status})`
      }
    } else if (error.request) {
      errorMsg = '无法连接到服务器，请检查网络'
    }
    message.error(errorMsg)
    return Promise.reject(error)
  }
)

/**
 * httpGet：封装 GET 请求
 * @param url 请求地址
 * @param config 可选的 axios 请求配置
 * @returns Promise<StandardResponse<T>> 统一响应结构
 */
export function httpGet<T = any>(url: string, config?: AxiosRequestConfig): Promise<StandardResponse<T>> {
  return request.get<StandardResponse<T>>(url, config).then((res) => res.data)
}

/**
 * httpPost：封装 POST 请求
 * @param url 请求地址
 * @param data 请求体数据
 * @param config 可选的 axios 请求配置
 * @returns Promise<StandardResponse<T>> 统一响应结构
 */
export function httpPost<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<StandardResponse<T>> {
  return request.post<StandardResponse<T>>(url, data, config).then((res) => res.data)
}

/**
 * httpPut：封装 PUT 请求
 * @param url 请求地址
 * @param data 请求体数据
 * @param config 可选的 axios 请求配置
 * @returns Promise<StandardResponse<T>> 统一响应结构
 */
export function httpPut<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<StandardResponse<T>> {
  return request.put<StandardResponse<T>>(url, data, config).then((res) => res.data)
}

/**
 * httpPatch：封装 PATCH 请求
 * @param url 请求地址
 * @param data 请求体数据
 * @param config 可选的 axios 请求配置
 * @returns Promise<StandardResponse<T>> 统一响应结构
 */
export function httpPatch<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<StandardResponse<T>> {
  return request.patch<StandardResponse<T>>(url, data, config).then((res) => res.data)
}

/**
 * httpDelete：封装 DELETE 请求
 * @param url 请求地址
 * @param config 可选的 axios 请求配置
 * @returns Promise<StandardResponse<T>> 统一响应结构
 */
export function httpDelete<T = any>(url: string, config?: AxiosRequestConfig): Promise<StandardResponse<T>> {
  return request.delete<StandardResponse<T>>(url, config).then((res) => res.data)
}

// 导出 axios 实例，供需要自定义处理的模块使用（如 SSE）
export default request
