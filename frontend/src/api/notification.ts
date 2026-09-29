/**
 * src/api/notification.ts：站内通知相关 API 封装
 * 作用：拉取当前用户的通知列表与未读数、一键全部已读
 */

// 导入统一响应类型与 GET/POST 请求方法
import { httpGet, httpPost, type StandardResponse } from './request'

/**
 * NotificationItem：单条站内通知
 */
export interface NotificationItem {
  id: number
  type: string
  title: string
  content: string
  is_read: boolean
  created_at: string
}

/**
 * getNotifications：获取当前用户的通知列表与未读数（需登录）
 * @returns Promise<StandardResponse<{ notifications: NotificationItem[]; unread_count: number }>> 通知数据
 */
export function getNotifications(): Promise<StandardResponse<{ notifications: NotificationItem[]; unread_count: number }>> {
  return httpGet('/trip/notifications')
}

/**
 * markAllNotificationsRead：一键标记所有通知为已读（需登录）
 * @returns Promise<StandardResponse<{ marked: number }>> 本次标记的条数
 */
export function markAllNotificationsRead(): Promise<StandardResponse<{ marked: number }>> {
  return httpPost('/trip/notifications/read-all')
}
