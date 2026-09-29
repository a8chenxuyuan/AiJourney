/**
 * src/api/memory.ts：用户记忆/偏好相关 API
 * 对应后端路由：/api/memory/{user_id}
 */

// 导入 HTTP 请求封装与统一响应类型
import { httpGet, httpPost, type StandardResponse } from './request'

/**
 * UserPreference：用户偏好画像数据结构（与后端 memory 路由返回字段一致）
 */
export interface UserPreference {
  budget_level: string | null
  favorite_tags: string[]
  disliked_tags: string[]
  transportation: string | null
  accommodation: string | null
  dietary_restrictions: string | null
  visited_cities: string[]
}

/**
 * getMyPreference：获取指定用户的偏好画像
 * @param userId 用户 ID（须为当前登录用户）
 */
export function getMyPreference(userId: number): Promise<StandardResponse<UserPreference>> {
  return httpGet(`/memory/${userId}`)
}

/**
 * updateMyPreference：更新指定用户的偏好画像（只传需要更新的字段）
 * @param userId 用户 ID（须为当前登录用户）
 * @param updates 偏好字段更新字典
 */
export function updateMyPreference(
  userId: number,
  updates: Partial<UserPreference>
): Promise<StandardResponse<UserPreference>> {
  return httpPost<UserPreference>(`/memory/${userId}`, updates)
}
