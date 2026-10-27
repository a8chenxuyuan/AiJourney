/**
 * src/api/companion.ts：行中伴侣与旅行档案 API 封装
 * 作用：封装打卡、当日视图、附近推荐、游记生成/查询/编辑、旅行档案等接口调用
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, httpPatch, httpDelete, type StandardResponse } from '../request'

/**
 * CheckinRecord：单条打卡记录
 */
export interface CheckinRecord {
  id: string
  plan_id: string
  day_index: number
  spot_type: 'attraction' | 'meal' | 'hotel' | string
  spot_name: string
  longitude: number
  latitude: number
  checkin_at: string | null
  photo_urls: string[]
  note: string | null
}

/**
 * CheckinListData：GET /trip/{id}/checkins 返回数据
 */
export interface CheckinListData {
  checkins: CheckinRecord[]
  by_day: Record<string, CheckinRecord[]>
  total: number
}

/**
 * createCheckin：创建打卡（坐标可用浏览器定位或行程内地点坐标）
 */
export function createCheckin(
  planId: string,
  params: {
    day_index: number
    spot_type?: string
    spot_name: string
    longitude?: number
    latitude?: number
    note?: string
    photo_urls?: string[]
  }
): Promise<StandardResponse<CheckinRecord>> {
  return httpPost<CheckinRecord>(`/trip/${planId}/checkins`, params)
}

/**
 * getCheckins：查询行程全部打卡记录（按天分组）
 */
export function getCheckins(planId: string): Promise<StandardResponse<CheckinListData>> {
  return httpGet<CheckinListData>(`/trip/${planId}/checkins`)
}

/**
 * deleteCheckin：删除打卡（仅打卡人本人）
 */
export function deleteCheckin(checkinId: string): Promise<StandardResponse<any>> {
  return httpDelete(`/trip/checkins/${checkinId}`)
}

/**
 * TodayViewData：GET /trip/{id}/today 返回数据
 * in_trip=false 时 today_plan 为 null，另含行前/行后天数提示
 */
export interface TodaySpot {
  name: string
  checked_in: boolean
  location?: { longitude: number; latitude: number; address?: string }
  [key: string]: any
}

export interface TodayViewData {
  in_trip: boolean
  today_plan: {
    day_index: number
    date: string
    city?: string | null
    description?: string
    intercity_note?: string | null
    attractions: TodaySpot[]
    meals: TodaySpot[]
    hotel: TodaySpot | null
  } | null
  weather: { date: string; day_weather?: string; night_weather?: string; day_temp?: string; night_temp?: string } | null
  days_until_start?: number | null
  days_after_end?: number | null
  plan_city: string
  start_date: string
  end_date: string
}

/**
 * getTodayView：当日视图聚合
 */
export function getTodayView(planId: string): Promise<StandardResponse<TodayViewData>> {
  return httpGet<TodayViewData>(`/trip/${planId}/today`)
}

/**
 * NearbyPoi：附近推荐 POI
 */
export interface NearbyPoi {
  id: string
  name: string
  address: string | null
  location: { longitude: number; latitude: number }
  distance: number
  tel: string | null
  rating: number | null
  image_url: string | null
}

/**
 * getNearby：附近推荐（type: restaurant/cafe/toilet 或自定义关键词）
 */
export function getNearby(
  planId: string,
  longitude: number,
  latitude: number,
  type = 'restaurant',
  radius = 1000
): Promise<StandardResponse<{ type: string; pois: NearbyPoi[] }>> {
  return httpGet(`/trip/${planId}/nearby`, {
    params: { longitude, latitude, type, radius }
  })
}

/**
 * JournalSection：游记分节
 */
export interface JournalSection {
  day_index: number | null
  title: string
  text: string
  photos?: string[]
}

/**
 * JournalData：游记数据（生成中 status=generating，sections 为空）
 */
export interface JournalData {
  id: string
  plan_id: string
  title: string
  status: 'generating' | 'done' | 'failed'
  sections: JournalSection[]
  is_public: boolean
  public_token: string | null
  generated_at: string | null
}

/**
 * generateJournal：触发游记生成（幂等，返回当前状态供轮询）
 */
export function generateJournal(planId: string): Promise<StandardResponse<JournalData>> {
  return httpPost<JournalData>(`/trip/${planId}/journal/generate`, {})
}

/**
 * getJournal：查询游记（轮询 status）
 */
export function getJournal(planId: string): Promise<StandardResponse<JournalData | null>> {
  return httpGet<JournalData | null>(`/trip/${planId}/journal`)
}

/**
 * updateJournal：编辑游记标题与分节内容
 */
export function updateJournal(
  planId: string,
  payload: { title?: string; sections?: JournalSection[] }
): Promise<StandardResponse<JournalData>> {
  return httpPatch<JournalData>(`/trip/${planId}/journal`, payload)
}

/**
 * ArchivePlanItem：档案中的单条行程摘要
 */
export interface ArchivePlanItem {
  plan_id: string
  city: string
  cities: Array<{ city: string; days: number }> | null
  start_date: string
  end_date: string
  travel_days: number
  status: string
  budget_total: number | null
  checkin_count: number
}

/**
 * ArchiveData：旅行档案汇总
 */
export interface ArchiveData {
  stats: {
    plan_count: number
    city_count: number
    cities: string[]
    checkin_total: number
    photo_total: number
    /** 旅行圈发布数（旅行圈+笔记，仅已发布） */
    post_total: number
    first_checkin_at: string | null
    last_checkin_at: string | null
  }
  plans: ArchivePlanItem[]
}

/**
 * getArchive：旅行档案（历史行程 + 打卡统计）
 */
export function getArchive(): Promise<StandardResponse<ArchiveData>> {
  return httpGet<ArchiveData>('/trip/archive')
}
