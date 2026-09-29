/**
 * src/api/auth.ts：用户认证相关 API 封装
 * 作用：封装登录、注册、获取当前用户等接口调用，统一使用 request 模块的 httpGet/httpPost
 */

// 导入统一响应类型与 GET/POST 请求方法
import { httpGet, httpPost, type StandardResponse } from './request'

/**
 * LoginData：登录接口响应 data 结构
 * 包含 access_token 字符串
 */
export interface LoginData {
  access_token: string
}

/**
 * UserData：获取当前用户接口响应 data 结构
 */
export interface UserData {
  id: number
  username: string
  email: string
}

/**
 * login：用户登录
 * @param username 用户名
 * @param password 密码
 * @returns Promise<StandardResponse<LoginData>> 后端响应，data 包含 access_token
 */
export function login(username: string, password: string): Promise<StandardResponse<LoginData>> {
  return httpPost<LoginData>('/auth/login', { username, password })
}

/**
 * register：用户注册
 * @param username 用户名
 * @param email 邮箱
 * @param password 密码
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function register(username: string, email: string, password: string): Promise<StandardResponse<any>> {
  return httpPost('/auth/register', { username, email, password })
}

/**
 * getCurrentUser：获取当前登录用户信息
 * @returns Promise<StandardResponse<UserData>> 后端响应，data 包含用户信息
 */
export function getCurrentUser(): Promise<StandardResponse<UserData>> {
  return httpGet<UserData>('/auth/me')
}
