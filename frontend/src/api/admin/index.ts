/**
 * src/api/admin.ts：管理后台 API 封装
 * 作用：数据看板、用户管理（封禁/授权）、内容审核、系统公告
 */

// 导入请求方法与统一响应类型
import { httpGet, httpPost, httpDelete, httpPatch } from '../request'
import type { StandardResponse } from '../request'

// ==================== 类型定义 ====================

/** AdminStats：数据看板统计 */
export interface AdminStats {
  users: number
  users_today: number
  plans: number
  posts: number
  posts_today: number
  journals: number
  admins: number
  posts_published: number
  posts_hidden: number
  posts_circle: number
  posts_note: number
  top_users: { user_id: number; username: string; count: number }[]
  plans_today: number
  journals_today: number
  like_total: number
  comment_total: number
  friend_pairs: number
  pending_requests: number
  journals_public: number
  orders_paid: number
  revenue_paid: number
  trends_7d: { date: string; users: number; posts: number }[]
}

/** AdminUserRow：用户管理列表行 */
export interface AdminUserRow {
  id: number
  username: string
  email: string
  role: 'user' | 'admin'
  is_banned: boolean
  plans_count: number
  posts_count: number
  created_at: string
}

/** AdminPostRow：内容审核列表行 */
export interface AdminPostRow {
  id: string
  author: string
  title: string
  zone: string
  post_type: string
  status: string
  like_count: number
  comment_count: number
  created_at: string
}

/** 分页包装 */
export interface Paged {
  total: number
  page: number
  size: number
}

// ==================== 看板 ====================

/** getAdminStats：数据看板统计 */
export function getAdminStats(): Promise<StandardResponse<AdminStats>> {
  return httpGet<AdminStats>('/admin/stats')
}

// ==================== 用户管理 ====================

/** listAdminUsers：用户列表（搜索 + 分页） */
export function listAdminUsers(
  search: string,
  page: number,
  size: number
): Promise<StandardResponse<Paged & { users: AdminUserRow[] }>> {
  return httpGet('/admin/users', { params: { search, page, size } })
}

/** banUser：封禁用户 */
export function banUser(userId: number): Promise<StandardResponse> {
  return httpPost(`/admin/users/${userId}/ban`)
}

/** unbanUser：解封用户 */
export function unbanUser(userId: number): Promise<StandardResponse> {
  return httpPost(`/admin/users/${userId}/unban`)
}

/** setUserRole：授权/收权 */
export function setUserRole(userId: number, role: 'admin' | 'user'): Promise<StandardResponse> {
  return httpPost(`/admin/users/${userId}/role`, { role })
}

/** updateUserProfile：编辑用户资料（用户名/邮箱，均可选） */
export function updateUserProfile(
  userId: number,
  data: { username?: string; email?: string }
): Promise<StandardResponse> {
  return httpPatch(`/admin/users/${userId}`, data)
}

/** resetUserPassword：重置用户密码（管理员直设新密码） */
export function resetUserPassword(userId: number, newPassword: string): Promise<StandardResponse> {
  return httpPost(`/admin/users/${userId}/password`, { new_password: newPassword })
}

// ==================== 内容审核 ====================

/** listAdminPosts：全量帖子列表（含隐藏帖） */
export function listAdminPosts(
  statusFilter: 'all' | 'published' | 'hidden',
  page: number,
  size: number
): Promise<StandardResponse<Paged & { posts: AdminPostRow[] }>> {
  return httpGet('/admin/posts', { params: { status: statusFilter, page, size } })
}

/** hidePost：下架帖子 */
export function hidePost(postId: string): Promise<StandardResponse> {
  return httpPost(`/admin/posts/${postId}/hide`)
}

/** restorePost：恢复帖子 */
export function restorePost(postId: string): Promise<StandardResponse> {
  return httpPost(`/admin/posts/${postId}/restore`)
}

// ==================== 系统公告 ====================

/** AdminAnnouncement：历史公告（同内容聚合去重后的一条） */
export interface AdminAnnouncement {
  title: string
  content: string
  sent_at: string | null
  receivers: number
}

/** listAnnouncements：历史公告列表（按发送时间倒序） */
export function listAnnouncements(): Promise<StandardResponse<AdminAnnouncement[]>> {
  return httpGet('/admin/announcements')
}

/** createAnnouncement：发系统公告 */
export function createAnnouncement(title: string, content: string): Promise<StandardResponse> {
  return httpPost('/admin/announcements', { title, content })
}

/** clearAnnouncements：清空全部系统公告 */
export function clearAnnouncements(): Promise<StandardResponse> {
  return httpDelete('/admin/announcements')
}
