<!--
  src/views/Join.vue：邀请加入协作页
  作用：已登录用户通过邀请链接（/join/{token}）加入他人行程的协作。
  流程：onMounted 取路由参数 token → 调用 joinByToken → 成功后跳转对应行程结果页；
        失败（链接无效/已撤销/已过期）时展示错误提示与返回入口。
  说明：本页需登录（路由未标记 public），未登录用户会被守卫重定向到登录页，
        登录后回跳本页即可完成加入。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从路由参数取出邀请令牌 token；
 * 2. 组件挂载时调用 joinByToken 凭令牌加入协作；
 * 3. 成功跳转行程结果页，失败展示错误信息。
 */

// 引入 Vue 组合式 API
import { ref, onMounted } from 'vue'
// 引入 Vue Router 的 useRoute（读取 token 参数）与 useRouter（成功后跳转结果页）
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 展示组件
import { Spin, Result as AResult, Button, Tag } from 'ant-design-vue'

// 引入协作 API
import { joinByToken, type JoinCollabResult } from '@/api/collab'

// 路由与路由器实例
const route = useRoute()
const router = useRouter()

// 加入结果、加载与错误状态
const joined = ref<JoinCollabResult | null>(null)
// 加入成功的提示语（后端对"已是所有者/已加入过"返回幂等成功，文案直接透传）
const successMsg = ref('')
const loading = ref(true)
// 错误信息：非空时展示错误页（404 无效 / 410 撤销或过期）
const errorMsg = ref('')

/**
 * join：凭邀请令牌加入行程协作
 */
const join = async () => {
  loading.value = true
  errorMsg.value = ''
  try {
    const token = String(route.params.token || '')
    const res = await joinByToken(token)
    if (res.success && res.data) {
      joined.value = res.data
      successMsg.value = res.message || '已加入行程协作'
      // 加入成功后稍作停留再跳转结果页，让用户看到加入成功的反馈
      setTimeout(() => {
        router.replace(`/result/${res.data!.plan_id}`)
      }, 1200)
    } else {
      errorMsg.value = res.message || '加入协作失败'
    }
  } catch (err: any) {
    // 后端 404（令牌无效/行程已删除）与 410（已撤销/已过期）返回 detail 字段
    errorMsg.value = err?.response?.data?.detail || err?.message || '加入协作失败'
  } finally {
    loading.value = false
  }
}

// 组件挂载时立即加入
onMounted(join)
</script>

<template>
  <div class="page-fade" style="max-width: 720px; margin: 0 auto; padding: 0 16px;">
    <div style="padding: 64px 0;">
      <!-- 加载中 -->
      <div v-if="loading" style="text-align: center; padding: 48px 0;">
        <Spin size="large" tip="正在加入协作..." />
      </div>

      <!-- 加入成功：展示行程信息并自动跳转结果页 -->
      <AResult
        v-else-if="joined"
        status="success"
        title="加入成功"
        :sub-title="successMsg"
      >
        <template #extra>
          <p style="margin: 0 0 16px; color: #666;">
            即将进入行程：
            <Tag color="blue">{{ joined.city || '旅行行程' }}</Tag>
          </p>
          <Button type="primary" @click="router.replace(`/result/${joined.plan_id}`)">立即查看行程</Button>
        </template>
      </AResult>

      <!-- 加入失败：链接无效 / 已撤销 / 已过期 -->
      <AResult
        v-else
        status="404"
        title="无法加入该行程"
        :sub-title="errorMsg"
      >
        <template #extra>
          <Button type="primary" @click="router.push('/')">去规划我的行程</Button>
        </template>
      </AResult>
    </div>
  </div>
</template>
