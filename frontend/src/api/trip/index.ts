/**
 * src/api/trip.ts：旅行规划相关 API 封装
 * 作用：封装创建规划、查询规划、重算规划、提交反馈等接口调用
 */

// 导入统一响应类型与 GET/POST/PUT/DELETE 请求方法
import { httpGet, httpPost, httpPut, httpDelete, type StandardResponse } from '../request'

/**
 * CityStay：多城市联游时单个城市的停留信息（按出发顺序）
 */
export interface CityStay {
  city: string
  days: number
}

/**
 * TripRequest：创建旅行规划的请求参数
 * 字段与后端 Pydantic TripRequest 保持一致，包含城市、起止日期、交通、住宿、偏好等
 */
export interface TripRequest {
  city: string
  // cities：多城市联游的城市与停留天数列表；单城传 null/不传，仍用 city 字段
  cities?: CityStay[] | null
  start_date: string
  end_date: string
  transportation?: string
  accommodation?: string
  preferences?: string[]
  must_visit?: string[]
  budget_level?: string
  free_text_input?: string
}

/**
 * PlanBrief：创建规划接口返回的简要信息
 */
export interface PlanBrief {
  plan_id: string
  status: string
}

/**
 * TripPlan：完整的旅行规划结果结构
 * 与后端 Pydantic TripPlan 保持一致，包含概览、每日行程、天气、预算等字段
 */
export interface TripPlan {
  plan_id?: string
  user_id?: number
  city: string
  // cities：多城市联游的行程城市列表（单城为 null/缺失）
  cities?: CityStay[] | null
  start_date: string
  end_date: string
  travel_days: number
  overall_suggestions?: string
  day_plans: DayPlan[]
  budget: BudgetInfo
  weather: WeatherInfo[]
  style?: string
}

/**
 * DayPlan：单日行程
 * 与后端 DayPlan 保持一致，包含当日景点、餐饮、酒店、交通建议等
 */
export interface LocationInfo {
  longitude: number
  latitude: number
  address?: string
}

export interface DayPlan {
  day_index: number
  date: string
  // city：当日所在城市（多城市联游时返回；单城为 null/缺失）
  city?: string | null
  // intercity_note：城际交通说明，如"上午高铁 杭州→苏州（约1.5小时）"
  intercity_note?: string | null
  description?: string
  attractions: AttractionInfo[]
  meals: MealInfo[]
  hotel?: HotelInfo
  transportation?: string
  route_polyline?: string
  map_center?: LocationInfo
}

/**
 * AttractionInfo：景点信息
 */
export interface AttractionInfo {
  name: string
  description?: string
  duration?: string
  ticket_price?: number
  rating?: number
  tags?: string[]
  image_url?: string
  photos?: string[]
  business_hours?: string
  phone?: string
  detail_url?: string
  location?: LocationInfo
}

/**
 * MealInfo：餐饮安排信息
 */
export interface MealInfo {
  type: string
  name?: string
  cuisine?: string
  estimated_cost?: number
  location_name?: string
  detail_url?: string
  location?: LocationInfo
  image_url?: string
  photos?: string[]
  rating?: number
  phone?: string
  business_hours?: string
  address?: string
}

/**
 * HotelInfo：酒店信息
 */
export interface HotelInfo {
  name: string
  price_per_night?: number
  rating?: number
  image_url?: string
  business_hours?: string
  phone?: string
  detail_url?: string
  location?: LocationInfo
}

/**
 * WeatherInfo：天气信息
 * 与后端 WeatherInfo 保持一致
 */
export interface WeatherInfo {
  date: string
  weather: string
  temperature?: string
  wind?: string
}

/**
 * BudgetInfo：预算信息
 * 与后端 Budget 保持一致
 */
export interface BudgetInfo {
  attractions: number
  meals: number
  hotels: number
  transportation: number
  total: number
  currency?: string
  notes?: string
}

/**
 * createPlan：创建旅行规划
 * @param params TripRequest 旅行规划请求参数
 * @returns Promise<StandardResponse<PlanBrief>> 后端响应，data 包含 plan_id 与 status
 */
export function createPlan(params: TripRequest): Promise<StandardResponse<PlanBrief>> {
  return httpPost<PlanBrief>('/trip/plan', params)
}

/**
 * getPlan：查询指定旅行规划的当前状态与结果
 * @param planId 规划任务 ID
 * @returns Promise<StandardResponse<PlanDetailData>> 后端响应
 *          plan：行程结果；version：当前版本号；diff_summary：相对上一版的差异摘要
 */
export function getPlan(planId: string): Promise<StandardResponse<PlanDetailData>> {
  return httpGet(`/trip/${planId}`)
}

/**
 * PlanDetailData：GET /trip/{id} 返回的数据结构
 */
export interface PlanDetailData {
  plan_id: string
  status: string
  plan: TripPlan
  version?: number | null
  /** 当前登录用户是否为行程所有者（决定能否使用分享/邀请管理等 owner 操作） */
  is_owner?: boolean
  diff_summary?: {
    total_changes: number
    days: Array<{
      day_index: number
      change_count: number
      attractions: { added: string[]; removed: string[] }
      meals: { changed: Array<{ meal_type: string; from: string; to: string }> }
      hotel: { from: string; to: string } | null
    }>
  } | null
}

/**
 * recalculatePlan：对指定规划任务进行重算
 * @param planId 规划任务 ID
 * @param params 可选的重算参数，例如调整偏好
 * @returns Promise<StandardResponse<PlanBrief>> 后端响应
 */
export function recalculatePlan(planId: string, params?: Partial<TripRequest>): Promise<StandardResponse<PlanBrief>> {
  return httpPost<PlanBrief>(`/trip/${planId}/recalculate`, params || {})
}

/**
 * PlanFeedbackRequest：行程修改反馈请求
 */
export interface PlanFeedbackRequest {
  day_index?: number | null
  tags: string[]
  raw_text: string
}

/**
 * PlanFeedbackResponse：行程修改反馈提交响应
 */
export interface PlanFeedbackResponse {
  feedback_id: number
  revision_id: number
  revision_type: string
  status: string
}

/**
 * submitPlanFeedback：提交对某天行程的修改反馈
 * @param planId 规划任务 ID
 * @param feedback 反馈内容
 * @returns Promise<StandardResponse<PlanFeedbackResponse>> 后端响应
 */
export function submitPlanFeedback(planId: string, feedback: PlanFeedbackRequest): Promise<StandardResponse<PlanFeedbackResponse>> {
  return httpPost<PlanFeedbackResponse>(`/trip/${planId}/feedback`, feedback)
}

/**
 * editPlanFeedback：编辑已有的行程反馈
 * @param planId 规划任务 ID
 * @param feedbackId 反馈 ID
 * @param feedback 新的反馈内容
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function editPlanFeedback(planId: string, feedbackId: number, feedback: PlanFeedbackRequest): Promise<StandardResponse<any>> {
  return httpPut(`/trip/${planId}/feedback/${feedbackId}`, feedback)
}

/**
 * withdrawPlanFeedback：撤回行程反馈
 * @param planId 规划任务 ID
 * @param feedbackId 反馈 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function withdrawPlanFeedback(planId: string, feedbackId: number): Promise<StandardResponse<any>> {
  return httpPost(`/trip/${planId}/feedback/${feedbackId}/withdraw`, {})
}

/**
 * getPlanRevisions：获取行程版本历史
 * @param planId 规划任务 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function getPlanRevisions(planId: string): Promise<StandardResponse<any>> {
  return httpGet(`/trip/${planId}/revisions`)
}

/**
 * regeneratePlan：基于所有有效反馈重新生成完整行程
 * @param planId 规划任务 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function regeneratePlan(planId: string): Promise<StandardResponse<any>> {
  return httpPost(`/trip/${planId}/regenerate`, {})
}

/**
 * getPlanFeedbacks：获取行程反馈列表
 * @param planId 规划任务 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function getPlanFeedbacks(planId: string): Promise<StandardResponse<any>> {
  return httpGet(`/trip/${planId}/feedback`)
}

/**
 * submitFeedback：对规划结果提交总体评分反馈（旧版兼容）
 * @param planId 规划任务 ID
 * @param feedback 反馈内容对象
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function submitFeedback(planId: string, feedback: { rating: number; comment: string }): Promise<StandardResponse<any>> {
  return httpPost(`/trip/${planId}/feedback_legacy`, feedback)
}

/**
 * sendPlanChat：对话式修改行程助手
 * 后端通过 LLM 判断意图：feedback（提取结构化反馈入库）/ question（直接回答）
 * @param planId 规划任务 ID
 * @param message 用户本轮输入
 * @param history 最近几轮对话历史（可空）
 * @returns Promise<StandardResponse<PlanChatData>> 后端响应
 */
export function sendPlanChat(
  planId: string,
  message: string,
  history: Array<{ role: string; content: string }> = []
): Promise<StandardResponse<PlanChatData>> {
  return httpPost<PlanChatData>(`/trip/${planId}/chat`, { message, history })
}

/**
 * PlanChatData：POST /trip/{id}/chat 返回的数据结构
 */
export interface PlanChatData {
  reply: string
  intent: 'feedback' | 'question'
  day_index: number | null
  tags: string[]
  feedback_id: number | null
  pending_count: number
}

/**
 * MyPlanSummary：历史行程摘要（个人中心列表用）
 */
export interface MyPlanSummary {
  plan_id: string
  city: string
  start_date: string
  end_date: string
  travel_days: number
  status: string
  budget_total: number
  created_at: string | null
}

/**
 * getMyPlans：获取当前用户的历史行程列表（摘要）
 * @returns Promise<StandardResponse<{ plans: MyPlanSummary[] }>> 后端响应
 */
export function getMyPlans(): Promise<StandardResponse<{ plans: MyPlanSummary[] }>> {
  return httpGet('/trip/my/list')
}

// ==================== 行程分享 ====================

/**
 * ShareInfo：开启分享接口返回的分享信息
 */
export interface ShareInfo {
  plan_id: string
  share_token: string
  share_path: string
  expires_at: string | null
  share_view_count: number
}

/**
 * SharedPlanData：GET /trip/share/{token} 返回的只读行程数据
 */
export interface SharedPlanData {
  plan_id: string
  status: string
  city: string
  version?: number | null
  plan: TripPlan
}

/**
 * createShare：开启行程分享（已有未过期令牌会被复用）
 * @param planId 行程计划 ID
 * @param expiresDays 分享有效天数，默认 7 天
 * @returns Promise<StandardResponse<ShareInfo>> 分享信息
 */
export function createShare(planId: string, expiresDays = 7): Promise<StandardResponse<ShareInfo>> {
  return httpPost<ShareInfo>(`/trip/${planId}/share`, { expires_days: expiresDays })
}

/**
 * closeShare：关闭行程分享，原链接立即失效
 * @param planId 行程计划 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function closeShare(planId: string): Promise<StandardResponse<any>> {
  return httpDelete(`/trip/${planId}/share`)
}

/**
 * getSharedPlan：通过分享令牌公开查看行程（无需登录）
 * @param token 分享令牌
 * @returns Promise<StandardResponse<SharedPlanData>> 只读行程数据
 */
export function getSharedPlan(token: string): Promise<StandardResponse<SharedPlanData>> {
  return httpGet<SharedPlanData>(`/trip/share/${token}`)
}

// ==================== 收藏与复购 ====================

/**
 * FavoriteCreateParams：添加收藏请求参数
 */
export interface FavoriteCreateParams {
  item_type: 'attraction' | 'hotel' | 'restaurant'
  item_id: string
  item_name: string
  city?: string
  item_data?: Record<string, any>
}

/**
 * FavoriteRecord：单条收藏记录
 */
export interface FavoriteRecord {
  id: number
  item_type: string
  item_id: string
  item_name: string
  city: string | null
  item_data: Record<string, any> | null
  created_at: string | null
}

/**
 * addFavorite：收藏行程中的景点/酒店/餐厅（重复收藏幂等）
 * @param params 收藏内容
 * @returns Promise<StandardResponse<FavoriteRecord>> 收藏记录
 */
export function addFavorite(params: FavoriteCreateParams): Promise<StandardResponse<FavoriteRecord>> {
  return httpPost<FavoriteRecord>('/trip/favorites', params)
}

/**
 * getFavorites：查询当前用户收藏列表，支持按城市过滤
 * @param city 可选的城市过滤条件
 * @returns Promise<StandardResponse<{ favorites: FavoriteRecord[] }>> 收藏列表
 */
export function getFavorites(city?: string): Promise<StandardResponse<{ favorites: FavoriteRecord[] }>> {
  return httpGet<{ favorites: FavoriteRecord[] }>('/trip/favorites', { params: city ? { city } : undefined })
}

/**
 * getFavoriteCities：查询当前用户收藏内容涉及的城市列表（去重，最近收藏优先）
 * @returns Promise<StandardResponse<{ cities: string[] }>> 城市名数组
 */
export function getFavoriteCities(): Promise<StandardResponse<{ cities: string[] }>> {
  return httpGet<{ cities: string[] }>('/trip/favorites/cities')
}

/**
 * removeFavorite：取消收藏
 * @param favoriteId 收藏记录 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function removeFavorite(favoriteId: number): Promise<StandardResponse<any>> {
  return httpDelete(`/trip/favorites/${favoriteId}`)
}
