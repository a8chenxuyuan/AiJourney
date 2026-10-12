/**
 * src/api/collab.ts：多人协作行程相关 API 封装
 * 作用：行程所有者生成邀请链接、查看/移除协作者；用户凭邀请令牌加入协作
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, httpDelete, type StandardResponse } from './request'

/**
 * CollaboratorItem：行程成员（所有者或协作者）
 * role 为 owner（所有者）或 editor（协作者，可查看行程并提交反馈）
 */
export interface CollaboratorItem {
  user_id: number
  username: string
  role: string
  joined_at: string | null
}

/**
 * InviteInfo：所有者生成的邀请信息
 * invite_path 为前端路由路径（如 /join/xxx），配合站点 origin 拼成完整链接
 */
export interface InviteInfo {
  plan_id: string
  token: string
  invite_path: string
  expires_at: string | null
}

/**
 * JoinCollabResult：凭邀请令牌加入协作的返回
 * plan_id 用于加入成功后跳转到对应行程结果页
 */
export interface JoinCollabResult {
  plan_id: string
  city: string | null
  role: string
}

/**
 * inviteCollaborator：为行程生成邀请链接（仅所有者）
 * @param planId 行程计划 ID
 * @returns Promise<StandardResponse<InviteInfo>> 邀请令牌与前端路由路径
 */
export function inviteCollaborator(planId: string): Promise<StandardResponse<InviteInfo>> {
  return httpPost<InviteInfo>(`/trip/${planId}/collaborators/invite`, {})
}

/**
 * listCollaborators：查询行程成员列表（所有者或协作者均可）
 * @param planId 行程计划 ID
 * @returns Promise<StandardResponse<{ plan_id: string; collaborators: CollaboratorItem[] }>> 成员列表
 */
export function listCollaborators(planId: string): Promise<StandardResponse<{ plan_id: string; collaborators: CollaboratorItem[] }>> {
  return httpGet(`/trip/${planId}/collaborators`)
}

/**
 * removeCollaborator：所有者移除协作者
 * @param planId 行程计划 ID
 * @param userId 待移除的协作者用户 ID
 * @returns Promise<StandardResponse<any>> 操作结果
 */
export function removeCollaborator(planId: string, userId: number): Promise<StandardResponse<any>> {
  return httpDelete(`/trip/${planId}/collaborators/${userId}`)
}

/**
 * joinByToken：登录用户凭邀请令牌加入行程协作（重复加入幂等成功）
 * @param token 邀请令牌
 * @returns Promise<StandardResponse<JoinCollabResult>> 加入的行程信息
 */
export function joinByToken(token: string): Promise<StandardResponse<JoinCollabResult>> {
  return httpPost<JoinCollabResult>(`/trip/collab/join/${token}`, {})
}
