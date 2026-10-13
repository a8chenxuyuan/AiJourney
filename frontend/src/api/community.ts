/**
 * src/api/community.ts：旅行社区 API 封装
 * 作用：封装帖子发布/广场 feed/帖子详情/点赞/评论/照着走/图片上传等接口调用
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, httpDelete, type StandardResponse } from './request'

/**
 * PostSection：帖子分节图文（与游记 JournalSection 结构一致）
 */
export interface PostSection {
  day_index: number | null
  title: string
  text: string
  photos?: string[]
}

/**
 * PostItem：帖子 feed 卡片（不含分节内容 JSON）
 */
export interface PostItem {
  id: string
  user_id: number
  author: string
  post_type: 'journal' | 'manual' | 'route' | string
  zone: 'circle' | 'note' | string
  title: string
  summary: string
  cover_url: string | null
  tags: string[]
  plan_id: string | null
  like_count: number
  comment_count: number
  view_count: number
  created_at: string
}

/**
 * PostDetail：帖子详情（含分节内容与当前用户点赞状态）
 */
export interface PostDetail extends PostItem {
  sections: PostSection[]
  liked: boolean
}

/**
 * FeedData：广场 feed 分页响应
 */
export interface FeedData {
  posts: PostItem[]
  total: number
  page: number
  size: number
  has_more: boolean
}

/**
 * CommentItem：单条评论（replies 为楼中楼回复，仅一级）
 */
export interface CommentItem {
  id: string
  user_id: number
  author: string
  content: string
  created_at: string
  replies: CommentItem[]
}

/**
 * CreatePostParams：发布帖子参数
 * journal_id 有值为游记转发；text/sections 为手动图文；仅 plan_id 为路线帖
 */
export interface CreatePostParams {
  title: string
  zone?: 'circle' | 'note' | string
  tags?: string[]
  cover_url?: string | null
  sections?: PostSection[]
  text?: string
  journal_id?: string
  plan_id?: string
}

/**
 * createPost：发布帖子
 */
export function createPost(params: CreatePostParams): Promise<StandardResponse<PostItem>> {
  return httpPost<PostItem>('/community/posts', params)
}

/**
 * getFeed：广场 feed（zone 过滤分区：circle 旅行圈 | note 旅行笔记，不传=全部；
 * sort=latest 最新 | hot 热门）
 */
export function getFeed(
  zone: 'circle' | 'note' | null,
  sort: 'latest' | 'hot' = 'latest',
  page = 1,
  size = 10
): Promise<StandardResponse<FeedData>> {
  return httpGet<FeedData>('/community/feed', {
    params: { ...(zone ? { zone } : {}), sort, page, size }
  })
}

/**
 * getPost：帖子详情
 */
export function getPost(postId: string): Promise<StandardResponse<PostDetail>> {
  return httpGet<PostDetail>(`/community/posts/${postId}`)
}

/**
 * deletePost：删除帖子（仅作者本人）
 */
export function deletePost(postId: string): Promise<StandardResponse<any>> {
  return httpDelete(`/community/posts/${postId}`)
}

/**
 * likePost：点赞（重复点赞幂等返回）
 */
export function likePost(
  postId: string
): Promise<StandardResponse<{ liked: boolean; like_count: number }>> {
  return httpPost<{ liked: boolean; like_count: number }>(`/community/posts/${postId}/like`)
}

/**
 * unlikePost：取消点赞（未点赞幂等返回）
 */
export function unlikePost(
  postId: string
): Promise<StandardResponse<{ liked: boolean; like_count: number }>> {
  return httpDelete<{ liked: boolean; like_count: number }>(`/community/posts/${postId}/like`)
}

/**
 * getComments：评论列表（顶级评论 + replies 楼中楼）
 */
export function getComments(
  postId: string
): Promise<StandardResponse<{ comments: CommentItem[] }>> {
  return httpGet<{ comments: CommentItem[] }>(`/community/posts/${postId}/comments`)
}

/**
 * addComment：发评论（parentId 有值为回复某条顶级评论）
 */
export function addComment(
  postId: string,
  content: string,
  parentId?: string
): Promise<StandardResponse<CommentItem>> {
  return httpPost<CommentItem>(`/community/posts/${postId}/comments`, {
    content,
    parent_id: parentId ?? null
  })
}

/**
 * ForkResult：照着走返回的新行程信息
 */
export interface ForkResult {
  plan_id: string
  start_date: string
  end_date: string
}

/**
 * forkPost：照着走（复制关联行程到我的账户，过去的行程自动平移到明天开始）
 */
export function forkPost(postId: string): Promise<StandardResponse<ForkResult>> {
  return httpPost<ForkResult>(`/community/posts/${postId}/fork`)
}

/**
 * uploadImage：上传图片，返回相对 URL（/uploads/IMG_x.jpg）
 */
export function uploadImage(file: File): Promise<StandardResponse<{ url: string }>> {
  const formData = new FormData()
  formData.append('file', file)
  return httpPost<{ url: string }>('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// API_ORIGIN：后端站点 origin（基地址去掉尾部 /api），用于拼接图片静态地址
const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(
  /\/api\/?$/,
  ''
)

/**
 * resolveImageUrl：把后端返回的相对图片 URL 拼成完整地址（已是 http(s) 开头则原样返回）
 */
export function resolveImageUrl(url?: string | null): string | null {
  if (!url) return null
  if (/^https?:\/\//.test(url)) return url
  return `${API_ORIGIN}${url}`
}
