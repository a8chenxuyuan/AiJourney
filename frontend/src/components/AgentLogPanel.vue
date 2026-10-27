<!--
  src/components/AgentLogPanel.vue：Agent 日志面板组件
  作用：接收 logs 数组，按时间顺序展示 Agent 节点执行步骤、状态
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 通过 defineProps 接收 logs 数组
 * 2. 使用 Timeline 组件展示每条日志的 step、agent_name、status
 * 3. 根据 status 显示不同颜色标识
 */

// 引入 Ant Design Vue 时间线、标签组件
import { Timeline, Tag } from 'ant-design-vue'
// 引入 AgentLog 类型
import type { AgentLog } from '@/api/trip/agent'

/**
 * AgentLogPanelProps：组件 props 类型
 * logs：Agent 执行日志数组
 */
interface AgentLogPanelProps {
  logs: AgentLog[]
}

// 声明 props，模板中可直接使用 logs
defineProps<AgentLogPanelProps>()

/**
 * statusColor：根据日志状态返回标签颜色
 * @param status 步骤状态字符串
 * @returns Tag 组件可用的颜色字符串
 */
const statusColor = (status: string): string => {
  switch (status) {
    case 'running':
      return 'blue'
    case 'success':
      return 'green'
    case 'failed':
      return 'red'
    case 'info':
      return 'default'
    default:
      return 'default'
  }
}
</script>

<template>
  <!-- 日志面板容器 -->
  <div style="max-height: 400px; overflow-y: auto; background: #fafafa; padding: 16px; border-radius: 8px;">
    <!-- 有日志时展示时间线 -->
    <Timeline v-if="logs.length > 0">
      <Timeline.Item v-for="(log, index) in logs" :key="index">
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <strong>{{ log.step }}</strong>
          <span v-if="log.agent_name" style="color: #888; font-size: 12px;">@{{ log.agent_name }}</span>
          <Tag :color="statusColor(log.status)" size="small">{{ log.status }}</Tag>
        </div>
      </Timeline.Item>
    </Timeline>
    <!-- 无日志时展示占位提示 -->
    <div v-else style="text-align: center; color: #999; padding: 24px 0;">
      等待 Agent 执行日志……
    </div>
  </div>
</template>
