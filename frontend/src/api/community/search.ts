/**
 * src/api/search.ts：全站搜索 API 封装
 * 作用：统一检索社区帖子/公开游记/爬虫攻略/用户四源
 */

import { httpGet, type StandardResponse } from '../request'

/** SearchResult：搜索结果条目（result_type 区分四源） */
export interface SearchResult {
  result_type: 'post' | 'journal' | 'guide' | 'user'
  id: string | number
  title: string
  excerpt: string
  cover_url?: string | null
  /** 游记专属 */
  public_token?: string | null
  city?: string | null
  travel_days?: number | null
  /** 帖子/游记/用户通用 */
  author?: string
  user_id?: number
  like_count?: number
  comment_count?: number
  /** 攻略专属 */
  source?: string
  created_at?: string | null
}

/** SearchData：搜索响应 */
export interface SearchData {
  q: string
  total: number
  counts: { post: number; journal: number; guide: number; user: number }
  items: SearchResult[]
}

/**
 * globalSearch：全站搜索（免登录，公开内容）
 * @param q 关键词
 */
export function globalSearch(q: string): Promise<StandardResponse<SearchData>> {
  return httpGet<SearchData>('/search', { params: { q } })
}
