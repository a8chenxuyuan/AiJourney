/**
 * src/api/recommend.ts：个性化推荐相关 API 封装
 * 作用：拉取"为你推荐"目的地列表（来源：收藏/记忆/历史/知识库）
 */

// 导入统一响应类型与 GET 请求方法
import { httpGet, type StandardResponse } from './request'

/**
 * RecommendationItem：单条目的地推荐
 * source：推荐来源（favorites 收藏 / memory 偏好记忆 / history 历史 / knowledge 知识库）
 */
export interface RecommendationItem {
  city: string
  reason: string
  source: 'favorites' | 'memory' | 'history' | 'knowledge'
  spots?: string[]
}

/**
 * getRecommendations：获取当前用户的个性化目的地推荐（需登录）
 * @returns Promise<StandardResponse<{ items: RecommendationItem[] }>> 推荐列表
 */
export function getRecommendations(): Promise<StandardResponse<{ items: RecommendationItem[] }>> {
  return httpGet('/trip/recommendations')
}
