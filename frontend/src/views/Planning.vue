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
// 引入 SSE 获取 Agent 日志的 API
import { streamAgentLogs, type AgentLog } from '@/api/agent'
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
})

/**
 * 组件卸载时关闭 SSE 连接，防止内存泄漏
 */
onUnmounted(() => {
  closeStream()
})
</script>

<template>
  <div class="page-fade" style="max-width: 900px; margin: 0 auto;">
    <Card title="规划进度" style="border-radius: 8px;">
      <!-- 当前状态提示 -->
      <div style="margin-bottom: 16px;">
        <Spin v-if="loading" size="small" style="margin-right: 8px;" />
        <span v-if="!completed">正在为您规划行程，请稍候……</span>
        <span v-else-if="completed && logs[logs.length - 1]?.status === 'success'">规划完成！</span>
        <span v-else>规划结束</span>
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
