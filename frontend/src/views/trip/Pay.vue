<!--
  src/views/Pay.vue：沙箱收银台页
  作用：展示订单金额/方式/状态，待支付订单可确认支付或取消；已支付展示成功态并可跳行程/订单页
  说明：沙箱环境不产生真实扣款，确认支付即置为已支付（真实接入时改为跳第三方收银台）
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted } from 'vue'
// 引入路由（参数取订单 ID，成功后跳转）
import { useRoute, useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Spin, message } from 'ant-design-vue'
// 引入支付 API 与类型
import { getOrder, payOrder, cancelOrder, type PaymentInfo } from '@/api/trip/payment'

const route = useRoute()
const router = useRouter()

// orderId：路由参数中的订单 ID
const orderId = route.params.orderId as string

// order：订单详情；loading/paying/cancelling：请求中状态
const order = ref<PaymentInfo | null>(null)
const loading = ref(true)
const paying = ref(false)
const cancelling = ref(false)

// methodLabel：支付方式显示名
const methodLabel = computed(() => {
  const m: Record<string, string> = { alipay: '支付宝', wechat: '微信支付', bank_card: '银行卡' }
  return m[order.value?.payment_method || ''] || order.value?.payment_method || '-'
})

// payBtnText：收银台按钮文案（按支付方式区分）
const payBtnText = computed(() => {
  const m: Record<string, string> = { alipay: '支付宝沙箱支付', wechat: '微信沙箱支付', bank_card: '银行卡支付' }
  return m[order.value?.payment_method || ''] || '确认支付'
})

/**
 * fmtTime：ISO 时间 → 本地可读格式（YYYY-MM-DD HH:mm）
 */
const fmtTime = (s: string | null) => (s ? s.slice(0, 16).replace('T', ' ') : '-')

/**
 * load：拉取订单详情
 */
const load = async () => {
  loading.value = true
  try {
    const res = await getOrder(orderId)
    if (res.success && res.data) {
      order.value = res.data
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/**
 * handlePay：确认支付，成功后刷新订单状态
 */
const handlePay = async () => {
  paying.value = true
  try {
    const res = await payOrder(orderId)
    if (res.success && res.data) {
      order.value = res.data
      message.success('支付成功')
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    paying.value = false
  }
}

/**
 * handleCancel：取消订单，成功后刷新状态
 */
const handleCancel = async () => {
  cancelling.value = true
  try {
    const res = await cancelOrder(orderId)
    if (res.success && res.data) {
      order.value = { ...(order.value as PaymentInfo), status: res.data.status }
      message.success('订单已取消')
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    cancelling.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-fade pay-page">
    <div class="pay-card">
      <Spin v-if="loading" style="padding: 64px 0; display: block;" />
      <template v-else-if="order">
        <!-- 商户与金额 -->
        <div class="pay-merchant">
          <span class="pay-logo">✈️</span>
          <div>
            <b>旅程 · 行程预订</b>
            <span>沙箱环境 · 不产生真实扣款</span>
          </div>
        </div>
        <div class="pay-amount">¥{{ order.amount.toFixed(2) }}</div>

        <!-- 订单信息 -->
        <ul class="pay-info">
          <li><span>订单号</span><b>{{ order.order_id }}</b></li>
          <li><span>支付方式</span><b>{{ methodLabel }}</b></li>
          <li><span>创建时间</span><b>{{ fmtTime(order.created_at) }}</b></li>
          <li v-if="order.paid_at"><span>支付时间</span><b>{{ fmtTime(order.paid_at) }}</b></li>
          <li>
            <span>关联行程</span>
            <a @click="router.push(`/result/${order.plan_id}`)">查看行程 →</a>
          </li>
        </ul>

        <!-- 待支付：确认支付 / 取消 -->
        <template v-if="order.status === 'pending'">
          <Button type="primary" size="large" block :loading="paying" class="pay-btn" @click="handlePay">
            {{ payBtnText }}
          </Button>
          <Button size="large" block :loading="cancelling" @click="handleCancel">取消订单</Button>
        </template>

        <!-- 已支付：成功态 -->
        <template v-else-if="order.status === 'paid'">
          <div class="pay-result is-success">
            <span class="pay-result-icon">✅</span>
            <b>支付成功，行程已预订</b>
          </div>
          <Button type="primary" size="large" block class="pay-btn" @click="router.push(`/result/${order.plan_id}`)">
            返回行程
          </Button>
          <Button size="large" block @click="router.push('/orders')">查看我的订单</Button>
        </template>

        <!-- 已取消 -->
        <template v-else>
          <div class="pay-result is-cancelled">
            <span class="pay-result-icon">🚫</span>
            <b>订单已取消</b>
          </div>
          <Button type="primary" size="large" block class="pay-btn" @click="router.push(`/result/${order.plan_id}`)">
            返回行程重新下单
          </Button>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.pay-page {
  max-width: 480px;
  margin: 40px auto;
  padding: 0 16px;
}
.pay-card {
  background: #fff;
  border-radius: 16px;
  padding: 28px;
  box-shadow: 0 4px 20px rgba(31, 56, 88, 0.08);
}
.pay-merchant {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.pay-logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--grad-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}
.pay-merchant b {
  display: block;
  font-size: 15px;
  color: #1f2a37;
}
.pay-merchant span {
  display: block;
  font-size: 12px;
  color: #98a3b3;
  margin-top: 2px;
}
.pay-amount {
  text-align: center;
  font-size: 36px;
  font-weight: 800;
  color: #fa541c;
  padding: 8px 0 20px;
}
.pay-info {
  list-style: none;
  margin: 0 0 22px;
  padding: 14px 16px;
  background: #f7f9fc;
  border-radius: 12px;
}
.pay-info li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  padding: 5px 0;
}
.pay-info span {
  color: #98a3b3;
  flex-shrink: 0;
}
.pay-info b {
  color: #1f2a37;
  font-weight: 600;
  word-break: break-all;
  text-align: right;
}
.pay-info a {
  color: var(--brand);
  font-weight: 600;
  cursor: pointer;
}
.pay-btn {
  margin-bottom: 12px;
}
.pay-result {
  text-align: center;
  padding: 10px 0 22px;
}
.pay-result-icon {
  display: block;
  font-size: 52px;
  margin-bottom: 8px;
}
.pay-result b {
  font-size: 16px;
  color: #1f2a37;
}
</style>
