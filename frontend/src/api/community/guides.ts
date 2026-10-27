/**
 * src/api/guides.ts：内容中心（攻略库/目的地/公开游记）API 封装
 * 作用：封装攻略列表/详情、目的地聚合、AI 问答、精选游记、公开分享、复刻线路、游记公开/取消公开等接口调用
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, type StandardResponse } from '../request'

/**
 * ContentItem：攻略流条目（item_type 区分三源：游记/社区笔记/爬虫攻略）
 */
export interface ContentItem {
  item_type: 'journal' | 'note' | 'guide'
  id: string | number
  title: string
  excerpt: string
  city: string | null
  /** 游记/笔记专属字段 */
  public_token?: string | null
  author?: string
  /** 作者用户 ID（游记/笔记），用于跳转用户主页 */
  user_id?: number
  travel_days?: number
  cover_url?: string | null
  /** 社区笔记专属字段 */
  like_count?: number
  comment_count?: number
  view_count?: number
  post_type?: string
  /** 攻略专属字段 */
  source?: string
  created_at: string | null
}

/**
 * GuideListData：攻略流响应（三源智能合流，含城市筛选 chips）
 */
export interface GuideListData {
  items: ContentItem[]
  total: number
  page: number
  size: number
  has_more: boolean
  cities: string[]
}

/**
 * GuideDetailData：攻略详情
 */
export interface GuideDetailData {
  id: number
  title: string
  content: string
  city: string | null
  source: string
  url: string | null
  crawled_at: string | null
  related: { id: number; title: string; city: string | null }[]
}

/**
 * TemplateItem：目的地页"热门行程模板"（社区公开帖关联的已完成行程）
 */
export interface TemplateItem {
  post_id: string
  title: string
  author: string
  user_id?: number
  like_count: number
  travel_days: number
  start_date: string
}

/**
 * DestinationData：目的地聚合页数据
 */
export interface DestinationData {
  city: string
  summary: string
  summary_url: string
  guides: ContentItem[]
  journals: ContentItem[]
  notes: ContentItem[]
  templates: TemplateItem[]
}

/**
 * FeaturedJournal：精选公开游记条目
 */
export interface FeaturedJournal {
  id: string
  public_token: string | null
  title: string
  author: string
  city: string
  travel_days: number
  cover_url: string | null
  excerpt: string
  created_at: string | null
}

/**
 * SharedJournalData：公开游记分享页数据（免登录可读）
 */
export interface SharedJournalData {
  id: string
  title: string
  author: string
  sections: { day_index: number | null; title: string; text: string; photos: string[] }[]
  cover_url: string | null
  plan: {
    city: string
    start_date: string
    end_date: string
    travel_days: number
  } | null
  generated_at: string | null
}

/**
 * ForkPlanData：复刻线路结果
 */
export interface ForkPlanData {
  plan_id: string
  city: string
  start_date: string
  end_date: string
}

/**
 * getGuides：攻略流（游记/社区笔记/攻略三源智能合流，免登录）
 * @param params city 城市筛选 / q 关键词 / type 内容类型 / page 页码 / size 每页条数
 * @returns Promise<StandardResponse<GuideListData>>
 */
export function getGuides(params?: {
  city?: string
  q?: string
  type?: 'journal' | 'note' | 'guide'
  /** 行程天数上限（≤N 天），仅对携带天数信息的内容生效 */
  max_days?: number
  page?: number
  size?: number
}): Promise<StandardResponse<GuideListData>> {
  return httpGet<GuideListData>('/guides', { params })
}

/**
 * getGuideDetail：攻略详情（正文 + 同城相关攻略，免登录）
 * @param guideId 攻略文档 ID
 * @returns Promise<StandardResponse<GuideDetailData>>
 */
export function getGuideDetail(guideId: number): Promise<StandardResponse<GuideDetailData>> {
  return httpGet<GuideDetailData>(`/guides/${guideId}`)
}

/**
 * getDestination：目的地聚合数据（百科简介 + 攻略 + 游记 + 模板，免登录）
 * @param city 城市名
 * @returns Promise<StandardResponse<DestinationData>>
 */
export function getDestination(city: string): Promise<StandardResponse<DestinationData>> {
  // 百科外部抓取可能较慢，放宽超时
  return httpGet<DestinationData>(`/destination/${encodeURIComponent(city)}`, { timeout: 20000 })
}

/**
 * destinationAsk：目的地 AI 问答（RAG 检索 + LLM 回答，需登录）
 * @param city 城市名
 * @param question 问题
 * @returns Promise<StandardResponse<{ city: string; reply: string }>>
 */
export function destinationAsk(city: string, question: string): Promise<StandardResponse<{ city: string; reply: string }>> {
  return httpPost<{ city: string; reply: string }>(
    '/destination/ask',
    { city, question },
    { timeout: 60000 }
  )
}

/**
 * getFeaturedJournals：精选公开游记流（免登录）
 * @param limit 返回条数上限
 * @returns Promise<StandardResponse<{ items: FeaturedJournal[] }>>
 */
export function getFeaturedJournals(limit = 12): Promise<StandardResponse<{ items: FeaturedJournal[] }>> {
  return httpGet<{ items: FeaturedJournal[] }>('/journals/featured', { params: { limit } })
}

/**
 * getSharedJournal：按 token 读取公开游记（免登录）
 * @param token 公开访问令牌
 * @returns Promise<StandardResponse<SharedJournalData>>
 */
export function getSharedJournal(token: string): Promise<StandardResponse<SharedJournalData>> {
  return httpGet<SharedJournalData>(`/journals/share/${token}`)
}

/**
 * forkSharedJournal：复刻公开游记的原线路到自己的账户（需登录）
 * @param token 公开访问令牌
 * @returns Promise<StandardResponse<ForkPlanData>>
 */
export function forkSharedJournal(token: string): Promise<StandardResponse<ForkPlanData>> {
  return httpPost<ForkPlanData>(`/journals/share/${token}/fork`)
}

/**
 * ReplicateResult：攻略照着走结果
 */
export interface ReplicateResult {
  plan_id: string
  city: string
  travel_days: number
}

/**
 * replicateGuide：攻略照着走——AI 把攻略转写为我的行程（需登录，约 10-20s）
 * @param guideId 攻略文档 ID
 * @param body 出发日期（可选，默认一周后）与目标天数（可选）
 */
export function replicateGuide(
  guideId: string,
  body: { start_date?: string; travel_days?: number } = {}
): Promise<StandardResponse<ReplicateResult>> {
  return httpPost<ReplicateResult>(`/guides/${guideId}/replicate`, body)
}

/**
 * publishJournal：将游记设为公开（首次生成分享 token），返回分享链接所需 token
 * @param planId 行程计划 ID
 * @returns Promise<StandardResponse<{ is_public: boolean; public_token: string | null }>>
 */
export function publishJournal(planId: string): Promise<StandardResponse<{ is_public: boolean; public_token: string | null }>> {
  return httpPost<{ is_public: boolean; public_token: string | null }>(`/trip/${planId}/journal/publish`)
}

/**
 * unpublishJournal：取消游记公开（保留 token，分享链接随之失效）
 * @param planId 行程计划 ID
 * @returns Promise<StandardResponse<{ is_public: boolean; public_token: string | null }>>
 */
export function unpublishJournal(planId: string): Promise<StandardResponse<{ is_public: boolean; public_token: string | null }>> {
  return httpPost<{ is_public: boolean; public_token: string | null }>(`/trip/${planId}/journal/unpublish`)
}
