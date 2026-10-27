/**
 * src/api/agent.ts：Agent 执行日志与人机协同决策 API 封装
 * 作用：通过 SSE（Server-Sent Events）实时获取 Agent 节点执行日志，以及提交人机协同决策
 */

// 导入 axios 实例，用于提交人机协同决策
import request from '../request'

/**
 * AgentLog：SSE 推送的单条 Agent 执行日志
 * 字段说明：
 * - step：当前步骤名称
 * - agent_name：执行该步骤的 Agent 名称
 * - status：步骤状态，例如 running / success / failed
 */
export interface AgentLog {
  step?: string
  agent_name?: string
  status: string
}

/**
 * HumanDecision：人机协同决策请求参数
 */
export interface HumanDecision {
  decision_type: string
  decision_value: string
}

/**
 * streamAgentLogs：通过 SSE 获取 Agent 执行日志
 * @param planId 规划任务 ID
 * @param onLog 每收到一条日志时的回调函数
 * @param onError SSE 连接出错时的回调函数
 * @param onComplete SSE 连接正常结束时的回调函数
 * @returns EventSource 实例，调用方可在需要时调用 close() 关闭连接
 */
export function streamAgentLogs(
  planId: string,
  onLog: (log: AgentLog) => void,
  onError?: (event: Event) => void,
  onComplete?: () => void
): EventSource {
  // 构建 SSE 请求 URL，使用完整的后端基地址 + 路由
  const baseURL = import.meta.env.VITE_API_BASE_URL || `http://${window.location.hostname}:8000/api`
  let url = `${baseURL}/agent/trip/${planId}/stream`

  // 由于浏览器 EventSource 无法设置 Authorization 请求头，
  // 若本地存在 JWT Token，则通过 URL 查询参数 ?token= 传递给后端进行认证
  const token = localStorage.getItem('agent1_travel_token')
  if (token) {
    url += `?token=${encodeURIComponent(token)}`
  }

  // 创建 EventSource 实例，浏览器原生支持 SSE
  const es = new EventSource(url)

  // 监听消息事件，解析 JSON 数据并回调
  es.onmessage = (event) => {
    try {
      const data: AgentLog = JSON.parse(event.data)
      onLog(data)
    } catch {
      // 若数据不是 JSON，则降级为文本日志
      onLog({ step: event.data, agent_name: '', status: 'info' })
    }
  }

  // 监听错误事件
  es.onerror = (event) => {
    if (onError) onError(event)
  }

  // 监听连接关闭事件（部分浏览器支持）
  es.addEventListener('close', () => {
    if (onComplete) onComplete()
  })

  return es
}

/**
 * submitHumanDecision：提交人机协同决策
 * @param planId 规划任务 ID
 * @param decision HumanDecision 决策内容
 * @returns Promise<any> 后端响应（使用 request 实例的 post 方法）
 */
export function submitHumanDecision(planId: string, decision: HumanDecision): Promise<any> {
  return request.post(`/agent/trip/${planId}/human_decision`, decision).then((res) => res.data)
}

/**
 * ApprovalDecision：预算超支审批决策请求参数（M3 HITL）
 * decision：approved（同意超支，继续生成）/ rejected（拒绝，终止规划）
 */
export interface ApprovalDecision {
  decision: 'approved' | 'rejected'
}

/**
 * decidePlanApproval：提交预算超支审批决策
 * @param planId 规划任务 ID
 * @param decision 审批决策（approved / rejected）
 * @returns Promise<any> 后端响应（data 含行程最新状态）
 */
export function decidePlanApproval(planId: string, decision: ApprovalDecision): Promise<any> {
  return request.post(`/trip/${planId}/approve`, decision).then((res) => res.data)
}
