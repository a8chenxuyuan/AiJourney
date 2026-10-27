/**
 * src/api/knowledge.ts：知识库（RAG）与爬虫相关 API 封装
 * 作用：封装攻略文档上传/检索、爬虫任务触发/状态查询等接口调用
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, type StandardResponse } from '../request'

// ==================== 知识库（RAG） ====================

/**
 * RagUploadParams：上传攻略文档请求参数
 */
export interface RagUploadParams {
  title: string
  content: string
  city?: string
}

/**
 * RagSearchResult：单条知识库检索结果
 */
export interface RagSearchResult {
  title?: string
  content?: string
  city?: string
  score?: number
  [key: string]: any
}

/**
 * uploadDocument：上传攻略文档到知识库（切分 + Embedding 入库）
 * @param params 文档参数（标题、正文、所属城市）
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function uploadDocument(params: RagUploadParams): Promise<StandardResponse<any>> {
  return httpPost<any>('/rag/upload', params)
}

/**
 * searchKnowledge：检索知识库
 * @param params 查询参数（查询文本、城市过滤、条数）
 * @returns Promise<StandardResponse<{ query: string; results: RagSearchResult[] }>> 检索结果
 */
export function searchKnowledge(params: {
  query: string
  city?: string
  top_k?: number
}): Promise<StandardResponse<{ query: string; results: RagSearchResult[] }>> {
  return httpPost<{ query: string; results: RagSearchResult[] }>('/rag/search', params)
}

// ==================== 爬虫任务 ====================

/**
 * CrawlerTriggerParams：触发爬虫任务请求参数
 */
export interface CrawlerTriggerParams {
  cities?: string[]
  max_pages?: number
}

/**
 * CrawlerJobStatus：爬虫任务状态信息
 */
export interface CrawlerJobStatus {
  job_id: string
  status: 'deferred' | 'queued' | 'in_progress' | 'complete' | 'not_found'
  result: {
    task_id?: string
    cities?: string[]
    documents_added?: number
    status?: string
    timestamp?: string
  } | null
}

/**
 * triggerCrawler：触发爬虫任务（异步入队，立即返回任务 ID）
 * @param params 抓取参数（城市列表、最大页数）
 * @returns Promise<StandardResponse<{ job_id: string; status: string }>> 任务信息
 */
export function triggerCrawler(params: CrawlerTriggerParams): Promise<StandardResponse<{ job_id: string; status: string }>> {
  return httpPost<{ job_id: string; status: string }>('/crawler/trigger', params)
}

/**
 * getCrawlerStatus：查询爬虫任务状态与结果
 * @param jobId 触发时返回的任务 ID
 * @returns Promise<StandardResponse<CrawlerJobStatus>> 任务状态
 */
export function getCrawlerStatus(jobId: string): Promise<StandardResponse<CrawlerJobStatus>> {
  return httpGet<CrawlerJobStatus>(`/crawler/status/${jobId}`)
}
