<!--
  src/views/Planning.vue：规划进度页
  作用：通过 SSE 实时展示 Agent 节点执行过程，规划完成后自动跳转 /result/:id；提供返回/取消按钮
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从路由参数中获取 plan_id
 * 2. 建立 SSE 连接，监听 Agent 执行日志
 * 3. 将日志追加到列表并展示在 AgentLogPanel 组件中
 * 4. 当收到完成状态日志时，关闭 SSE 并跳转结果页
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, onMounted, onUnmounted } from 'vue'
// 引入 Vue Router 的 useRoute 与 useRouter Hook
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 按钮、卡片、 spinning 加载组件
import { Button, Card, Spin, message } from 'ant-design-vue'
// 引入 SSE 获取 Agent 日志与审批决策的 API
import { streamAgentLogs, decidePlanApproval, type AgentLog } from '@/api/trip/agent'
// 引入行程查询 API（审批暂停态轮询）
import { getPlan } from '@/api/trip'
// 引入 Agent 日志面板组件
import AgentLogPanel from '@/components/AgentLogPanel.vue'

// 获取当前路由信息，用于读取 plan_id 参数
const route = useRoute()
// 获取路由实例，用于跳转结果页或返回首页
const router = useRouter()

// planId：当前规划任务 ID
const planId = route.params.id as string

// logs：Agent 执行日志列表
const logs = ref<AgentLog[]>([])
// eventSource：SSE 连接实例
let eventSource: EventSource | null = null
// completed：标记规划是否已完成
const completed = ref(false)
// loading：标记是否正在连接或等待中
const loading = ref(true)

/**
 * handleLog：每次收到 SSE 日志时的回调
 * @param log 单条 Agent 执行日志
 */
const handleLog = (log: AgentLog) => {
  logs.value.push(log)
  // 若日志状态为 success / completed / failed，可视为规划结束
  if (log.status === 'success' || log.status === 'completed' || log.status === 'failed') {
    completed.value = true
    stopApprovalPolling()
    closeStream()
    // 规划成功后自动跳转结果页（若失败则提示）
    if (log.status === 'success' || log.status === 'completed') {
      message.success('规划完成，正在展示结果')
      setTimeout(() => {
        // 强制 location.reload() 整页刷新，绕开 Vue Router 复用组件实例的 bug。
        // 重要：仅依赖路由 push + watch 有时不触发（特别是 /planning → /result 同 id），
        // 整页 reload 能保证 Result.vue 一定拉到最新数据。
        window.location.href = `/result/${planId}?from=regenerate&refresh=${Date.now()}`
      }, 800)
    } else {
      message.error('规划失败，请返回重试')
    }
  }
}

/**
 * closeStream：关闭 SSE 连接
 */
const closeStream = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  loading.value = false
}

/**
 * handleCancel：取消规划，关闭 SSE 并返回首页
 */
const handleCancel = () => {
  closeStream()
  router.push('/')
}

// ==================== M3 HITL：预算超支审批确认卡 ====================
// 规划暂停在 pending_approval 状态时，SSE 流没有结束标记，
// 通过轮询 GET /trip/{id} 发现暂停态并弹出超支明细确认卡。

// approvalVisible：审批确认卡是否可见
const approvalVisible = ref(false)
// approvalInfo：预算超支明细（total / daily_limit / days / ratio）
interface ApprovalInfo {
  type?: string
  budget_level?: string | null
  total?: number
  daily_limit?: number
  days?: number
  ratio?: number
}
const approvalInfo = ref<ApprovalInfo | null>(null)
// deciding：审批决策提交中（防重复点击）
const deciding = ref(false)
// pollTimer：轮询定时器句柄
let pollTimer: number | null = null

/**
 * checkApprovalStatus：轮询行程状态，发现 pending_approval 时弹出确认卡
 */
const checkApprovalStatus = async () => {
  if (completed.value || approvalVisible.value || deciding.value) return
  try {
    const res = await getPlan(planId)
    // 暂停态下 plan_data = { approval: 超支明细 }，后端 GET /trip/{id} 原样透出
    const approval = (res.data as { plan?: { approval?: ApprovalInfo } }).plan?.approval
    if (res.data?.status === 'pending_approval' && approval) {
      approvalInfo.value = approval
      approvalVisible.value = true
    }
  } catch {
    // 轮询失败静默跳过，下一轮重试
  }
}

/**
 * startApprovalPolling：启动审批状态轮询（3 秒一次）
 */
const startApprovalPolling = () => {
  stopApprovalPolling()
  pollTimer = window.setInterval(checkApprovalStatus, 3000)
}

/**
 * stopApprovalPolling：停止审批状态轮询
 */
const stopApprovalPolling = () => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

/**
 * handleApprove：同意超支预算，后端从断点续跑 finalize 批次
 */
const handleApprove = async () => {
  deciding.value = true
  try {
    await decidePlanApproval(planId, { decision: 'approved' })
    approvalVisible.value = false
    stopApprovalPolling()
    loading.value = true
    message.info('已同意超支预算，正在继续生成行程…')
    // 续跑完成/失败由 SSE 流的结束标记统一处理，无需额外跳转
  } catch {
    message.error('审批提交失败，请重试')
  } finally {
    deciding.value = false
  }
}

/**
 * handleReject：拒绝超支预算，后端终止规划并推送 failed 标记
 */
const handleReject = async () => {
  deciding.value = true
  try {
    await decidePlanApproval(planId, { decision: 'rejected' })
    approvalVisible.value = false
    stopApprovalPolling()
    message.info('已拒绝超支预算，规划终止')
    // failed 标记由 SSE 回调统一处理
  } catch {
    message.error('审批提交失败，请重试')
  } finally {
    deciding.value = false
  }
}

/**
 * 组件挂载时建立 SSE 连接
 */
onMounted(() => {
  loading.value = true
  eventSource = streamAgentLogs(
    planId,
    handleLog,
    (error) => {
      console.error('SSE 连接异常', error)
      message.error('实时日志连接异常')
      closeStream()
    },
    () => {
      // SSE 连接正常结束
      loading.value = false
    }
  )
  // 启动审批暂停态轮询（M3 HITL）
  startApprovalPolling()
})

/**
 * 组件卸载时关闭 SSE 连接与轮询定时器，防止内存泄漏
 */
onUnmounted(() => {
  closeStream()
  stopApprovalPolling()
})
</script>

<template>
  <div class="page-fade" style="max-width: 1040px; margin: 0 auto;">
    <Card title="规划进度" style="border-radius: 8px;">
      <!-- 当前状态提示 -->
      <div style="margin-bottom: 16px;">
        <Spin v-if="loading" size="small" style="margin-right: 8px;" />
        <span v-if="!completed">正在为您规划行程，请稍候……</span>
        <span v-else-if="completed && logs[logs.length - 1]?.status === 'success'">规划完成！</span>
        <span v-else>规划结束</span>
      </div>

      <!-- M3 HITL：预算超支审批确认卡 -->
      <div
        v-if="approvalVisible && approvalInfo"
        style="
          margin-bottom: 16px;
          padding: 20px 24px;
          border-radius: 8px;
          background: linear-gradient(135deg, #fff7e6 0%, #fff1d6 100%);
          border: 1px solid #ffd591;
        "
      >
        <div style="font-size: 16px; font-weight: 600; color: #ad6800; margin-bottom: 10px;">
          行程预算超出档位上限，需要您确认
        </div>
        <div style="color: #614700; line-height: 1.8; margin-bottom: 16px;">
          本次规划的预估总费用为
          <b style="color: #d46b08;">{{ approvalInfo.total }} 元</b>
          ，按「{{ approvalInfo.budget_level || 'standard' }}」档位日均上限
          {{ approvalInfo.daily_limit }} 元 × {{ approvalInfo.days }} 天计算，
          超支比率为 <b style="color: #d46b08;">{{ approvalInfo.ratio }}</b>。
          <br />
          同意后将按当前方案继续生成行程；拒绝则终止本次规划。
        </div>
        <div style="display: flex; gap: 12px;">
          <Button type="primary" :loading="deciding" @click="handleApprove">同意，继续生成</Button>
          <Button :disabled="deciding" @click="handleReject">拒绝，终止规划</Button>
        </div>
      </div>

      <!-- Agent 日志面板 -->
      <AgentLogPanel :logs="logs" />

      <!-- 操作按钮区 -->
      <div style="margin-top: 24px; display: flex; gap: 12px;">
        <Button type="default" @click="router.push('/')">返回首页</Button>
        <Button type="primary" danger :disabled="completed" @click="handleCancel">取消规划</Button>
      </div>
    </Card>
  </div>
</template>
