/**
 * src/api/social.ts：社交体系 API 封装（好友 / 用户主页 / 私聊 / 互动通知）
 * 作用：封装好友申请与处理、用户主页资料与内容流、私聊会话与消息、
 *      红点徽标与通知列表；WS 连接不在此处（见 stores/notify.ts）。
 */
import { httpGet, httpPost, type StandardResponse } from '../request'

// ============ 同路人达人榜 ============

/**
 * CreatorItem：达人卡数据（按获赞/发帖排序）
 */
export interface CreatorItem {
  user_id: number
  username: string
  posts_count: number
  likes_total: number
  journals_count: number
  joined_at: string | null
  /** 最近 3 张已发布帖子封面 */
  covers: string[]
}

/**
 * listCreators：达人榜（免登录可看）
 */
export function listCreators(): Promise<StandardResponse<{ items: CreatorItem[] }>> {
  return httpGet<{ items: CreatorItem[] }>('/users/creators')
}

// ============ 好友 ============

/**
 * applyFriend：发起好友申请（附验证消息，微信式）
 * @param userId 目标用户 ID
 * @param verifyMessage 验证消息（≤200 字）
 */
export function applyFriend(userId: number, verifyMessage: string): Promise<StandardResponse> {
  return httpPost('/friends/apply', { user_id: userId, verify_message: verifyMessage })
}

/**
 * FriendRequest：待处理好友申请（新朋友卡）
 */
export interface FriendRequest {
  friendship_id: number
  user_id: number
  username: string
  verify_message: string | null
  created_at: string | null
}

/**
 * getFriendRequests：我收到的待处理好友申请列表
 */
export function getFriendRequests(): Promise<StandardResponse<{ requests: FriendRequest[] }>> {
  return httpGet('/friends/requests')
}

/**
 * acceptFriend：同意好友申请
 */
export function acceptFriend(friendshipId: number): Promise<StandardResponse> {
  return httpPost(`/friends/${friendshipId}/accept`)
}

/**
 * rejectFriend：拒绝好友申请
 */
export function rejectFriend(friendshipId: number): Promise<StandardResponse> {
  return httpPost(`/friends/${friendshipId}/reject`)
}

/**
 * FriendItem：好友列表项（含在线状态）
 */
export interface FriendItem {
  user_id: number
  username: string
  is_online: boolean
}

/**
 * getFriends：好友列表
 */
export function getFriends(): Promise<StandardResponse<{ friends: FriendItem[] }>> {
  return httpGet('/friends')
}

export type RelationState = 'self' | 'none' | 'pending_out' | 'pending_in' | 'accepted'

/**
 * getFriendStatus：与指定用户的关系态（主页按钮态驱动）
 */
export function getFriendStatus(
  userId: number
): Promise<StandardResponse<{ relation: RelationState; friendship_id: number | null }>> {
  return httpGet(`/friends/status/${userId}`)
}

// ============ 用户主页 ============

/**
 * UserProfileData：用户资料卡（含统计与关系态）
 */
export interface UserProfileData {
  user_id: number
  username: string
  created_at: string | null
  stats: {
    posts_count: number
    /** 发帖分区细分（旅行圈） */
    posts_circle: number
    /** 发帖分区细分（笔记） */
    posts_note: number
    likes_received: number
    journals_count: number
    friends_count: number
  }
  relation: RelationState
  friendship_id: number | null
}

/**
 * getUserProfile：用户主页资料
 */
export function getUserProfile(userId: number): Promise<StandardResponse<UserProfileData>> {
  return httpGet(`/users/${userId}/profile`)
}

/**
 * ProfilePostItem：TA 的旅行圈动态（摘要卡片）
 */
export interface ProfilePostItem {
  id: string
  zone: 'circle' | 'note'
  title: string
  summary: string | null
  cover_url: string | null
  /** 帖子状态：本人查看时可能为 hidden（被下架，前端打标签） */
  status: string
  like_count: number
  comment_count: number
  created_at: string | null
}

/**
 * getUserPosts：TA 的旅行圈动态列表
 */
export function getUserPosts(
  userId: number,
  page = 1,
  size = 10
): Promise<StandardResponse<{ items: ProfilePostItem[]; total: number; has_more: boolean }>> {
  return httpGet(`/users/${userId}/posts`, { params: { page, size } })
}

/**
 * ProfileJournalItem：TA 的公开游记
 */
export interface ProfileJournalItem {
  id: string
  title: string
  cover_url: string | null
  travel_days: number | null
  public_token: string
  created_at: string | null
}

/**
 * getUserJournals：TA 的公开游记列表
 */
export function getUserJournals(
  userId: number
): Promise<StandardResponse<{ items: ProfileJournalItem[] }>> {
  return httpGet(`/users/${userId}/journals`)
}

// ============ 私聊 ============

/**
 * Conversation：会话列表项
 */
export interface Conversation {
  peer_id: number
  peer_name: string
  is_online: boolean
  last_content: string
  /** 最后一条消息类型：text/image/video/call（会话列表显示 [图片] 等摘要用） */
  last_type?: string
  last_time: string | null
  unread: number
}

/**
 * getConversations：会话列表（未读置顶）
 */
export function getConversations(): Promise<StandardResponse<{ conversations: Conversation[] }>> {
  return httpGet('/chat/conversations')
}

/**
 * ChatMessageItem：单条私聊消息
 */
export interface ChatMessageItem {
  id: number
  sender_id: number
  receiver_id: number
  content: string
  content_type: string
  created_at: string | null
  /** WS 推送事件附带作者名（HTTP 列表无此字段） */
  sender_name?: string
}

/**
 * getMessages：与某好友的历史消息（游标分页，升序返回）
 */
export function getMessages(
  peerId: number,
  beforeId?: number,
  limit = 20
): Promise<StandardResponse<{ messages: ChatMessageItem[]; has_more: boolean }>> {
  return httpGet(`/chat/${peerId}/messages`, {
    params: beforeId ? { before_id: beforeId, limit } : { limit }
  })
}

/**
 * sendMessage：发送私聊消息（仅好友）
 * @param contentType text=文本 / image|video=媒体 URL / call=通话卡片（content 为 voice|video）
 */
export function sendMessage(
  receiverId: number,
  content: string,
  contentType = 'text'
): Promise<StandardResponse<{ message: ChatMessageItem; delivered_realtime: boolean }>> {
  return httpPost('/chat', { receiver_id: receiverId, content, content_type: contentType })
}

/**
 * uploadChatMedia：上传聊天图片/视频，返回相对 URL（/uploads/IMG_x.jpg、VID_x.mp4）
 */
export function uploadChatMedia(file: File): Promise<StandardResponse<{ url: string; media_type: string }>> {
  const formData = new FormData()
  formData.append('file', file)
  return httpPost<{ url: string; media_type: string }>('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** sendCallSignal：发送 WebRTC 通话信令（后端经 WS 实时中继给对端） */
export function sendCallSignal(
  toUserId: number,
  signal: Record<string, any>
): Promise<StandardResponse<{ delivered: boolean }>> {
  return httpPost('/chat/call/signal', { to_user_id: toUserId, signal })
}

// 说明：后端「拉取历史消息」时自动将对方发来的消息置为已读，
// 因此打开会话即已读，无需单独的已读端点。

// ============ 通知 ============

/**
 * BadgeData：侧边栏红点聚合
 */
export interface BadgeData {
  chat_unread: number
  request_count: number
  notification_unread: number
  total: number
}

/**
 * getBadge：红点聚合查询
 */
export function getBadge(): Promise<StandardResponse<BadgeData>> {
  return httpGet('/chat/badge')
}

/**
 * NotificationItem：互动通知（赞/评/回复/好友事件）
 */
export interface NotificationItem {
  id: number
  ntype: 'like' | 'comment' | 'reply' | 'friend_request' | 'friend_accepted' | string
  text: string
  payload: { post_id?: string; post_title?: string; excerpt?: string; verify_message?: string }
  actor_id: number | null
  actor_name: string | null
  is_read: boolean
  created_at: string | null
}

/**
 * getNotifications：互动通知列表
 */
export function getNotifications(params?: {
  only_unread?: boolean
  page?: number
  size?: number
}): Promise<StandardResponse<{ items: NotificationItem[]; total: number; has_more: boolean }>> {
  return httpGet('/chat/notifications', { params })
}

/**
 * readNotifications：标记通知已读（不传 ids 全读）
 */
export function readNotifications(ids?: number[]): Promise<StandardResponse<{ marked: number }>> {
  return httpPost('/chat/notifications/read', ids ? { ids } : {})
}
