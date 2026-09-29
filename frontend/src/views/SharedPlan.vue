<!--
  src/views/SharedPlan.vue：行程只读分享页
  作用：通过分享令牌（路由参数 token）公开查看他人分享的行程，无需登录。
  流程：onMounted 调用 getSharedPlan(token) 拉取只读数据 → 渲染概览 + 每日行程。
  失败场景：链接不存在/已关闭（404）、已过期（410）时展示对应提示。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从路由参数取出 token；
 * 2. 组件挂载时调用 getSharedPlan 拉取只读行程数据；
 * 3. 根据加载状态渲染行程内容或错误提示。
 */

// 引入 Vue 组合式 API
import { ref, onMounted } from 'vue'
// 引入 Vue Router 的 useRoute（读取 token 参数）与 useRouter（提供"去首页"入口）
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 展示组件
import { Card, Tag, Spin, Result as AResult, Button, Collapse, Timeline } from 'ant-design-vue'

// 引入分享数据 API
import { getSharedPlan, type SharedPlanData } from '@/api/trip'

// 路由与路由器实例
const route = useRoute()
const router = useRouter()

// 分享数据、加载与错误状态
const shared = ref<SharedPlanData | null>(null)
const loading = ref(true)
// 错误信息：非空时展示错误页（含 404/410 场景）
const errorMsg = ref('')

/**
 * fetchShared：拉取分享行程数据
 */
const fetchShared = async () => {
  loading.value = true
  errorMsg.value = ''
  try {
    const token = String(route.params.token || '')
    const res = await getSharedPlan(token)
    if (res.success && res.data) {
      shared.value = res.data
    } else {
      errorMsg.value = res.message || '分享内容加载失败'
    }
  } catch (err: any) {
    // 后端 404（链接不存在/已关闭）与 410（已过期）返回 detail 字段
    errorMsg.value = err?.response?.data?.detail || err?.message || '分享内容加载失败'
  } finally {
    loading.value = false
  }
}

// 组件挂载时拉取数据
onMounted(fetchShared)
</script>

<template>
  <div class="page-fade" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
    <!-- 加载中 -->
    <Spin :spinning="loading" tip="正在加载分享行程...">
      <div style="min-height: 300px;">
        <!-- 错误状态：链接无效或已过期 -->
        <div v-if="errorMsg" style="padding: 48px 0;">
          <AResult
            status="404"
            title="无法查看该分享"
            :sub-title="errorMsg"
          >
            <template #extra>
              <Button type="primary" @click="router.push('/')">去规划我的行程</Button>
            </template>
          </AResult>
        </div>

        <!-- 分享内容 -->
        <template v-else-if="shared && shared.plan">
          <!-- 顶部标题 -->
          <div style="display: flex; justify-content: space-between; align-items: center; margin: 24px 0;">
            <h2 style="margin: 0; font-size: 24px;">
              {{ shared.plan.city }} 旅行行程
              <Tag v-if="shared.version" color="purple" style="margin-left: 8px;">v{{ shared.version }}</Tag>
            </h2>
            <Tag color="blue">只读分享</Tag>
          </div>

          <!-- 概览卡片 -->
          <Card title="行程概览" style="margin-bottom: 24px; border-radius: 12px;">
            <p style="margin: 8px 0;"><strong>目的地：</strong>{{ shared.plan.city }}</p>
            <p style="margin: 8px 0;">
              <strong>出行日期：</strong>{{ shared.plan.start_date }} 至 {{ shared.plan.end_date }}
              （共 {{ shared.plan.travel_days }} 天）
            </p>
            <p v-if="shared.plan.budget" style="margin: 8px 0;">
              <strong>预算估算：</strong>总计 {{ shared.plan.budget.total }} 元
            </p>
            <p v-if="shared.plan.overall_suggestions"
              style="color: #555; margin-top: 12px; background: #f6f6f6; padding: 12px; border-radius: 8px;">
              <strong>整体建议：</strong>{{ shared.plan.overall_suggestions }}
            </p>
          </Card>

          <!-- 每日行程（折叠面板，默认展开第一天） -->
          <Card title="每日行程" style="border-radius: 12px;">
            <Collapse :default-active-key="[0]">
              <Collapse.Panel v-for="(day, dayIdx) in shared.plan.day_plans" :key="dayIdx" :header="`第 ${day.day_index} 天 · ${day.date}`">
                <p v-if="day.description" style="color: #666; margin-bottom: 12px;">{{ day.description }}</p>

                <!-- 当日景点 -->
                <template v-if="day.attractions && day.attractions.length > 0">
                  <p style="font-weight: 600; margin-bottom: 8px;">景点安排</p>
                  <Timeline style="margin-bottom: 16px;">
                    <Timeline.Item v-for="(spot, idx) in day.attractions" :key="idx">
                      <strong>{{ spot.name }}</strong>
                      <Tag v-if="spot.duration" color="orange" style="margin-left: 6px;">{{ spot.duration }}</Tag>
                      <Tag v-if="spot.ticket_price" color="green" style="margin-left: 6px;">¥{{ spot.ticket_price }}</Tag>
                      <p v-if="spot.description" style="color: #666; font-size: 13px; margin: 4px 0 0;">{{ spot.description }}</p>
                    </Timeline.Item>
                  </Timeline>
                </template>

                <!-- 当日餐饮 -->
                <template v-if="day.meals && day.meals.length > 0">
                  <p style="font-weight: 600; margin-bottom: 8px;">餐饮安排</p>
                  <p style="color: #555; margin: 0 0 12px; font-size: 13px;">
                    <span v-for="(meal, idx) in day.meals" :key="idx" style="margin-right: 16px;">
                      {{ meal.type }}：{{ meal.name || '待定' }}
                      <span v-if="meal.estimated_cost">（约 {{ meal.estimated_cost }} 元）</span>
                    </span>
                  </p>
                </template>

                <!-- 当日住宿 -->
                <p v-if="day.hotel" style="color: #555; font-size: 13px;">
                  <strong>住宿：</strong>{{ day.hotel.name }}
                  <span v-if="day.hotel.price_per_night">（{{ day.hotel.price_per_night }} 元/晚）</span>
                </p>
                <p v-if="day.transportation" style="color: #555; font-size: 13px; margin: 8px 0 0;">
                  <strong>当日交通：</strong>{{ day.transportation }}
                </p>
              </Collapse.Panel>
            </Collapse>
          </Card>

          <!-- 底部推广入口 -->
          <p style="text-align: center; color: #999; margin: 32px 0;">
            这份行程由 agent1旅行 AI 规划生成
            <a style="color: #1890ff; margin-left: 8px;" @click="router.push('/')">我也想规划一次 →</a>
          </p>
        </template>
      </div>
    </Spin>
  </div>
</template>
