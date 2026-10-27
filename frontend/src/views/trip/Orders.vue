<!--
  src/views/Orders.vue：我的订单页
  作用：全量展示当前用户的预订订单，待支付可去收银台支付或直接取消，已支付可跳回行程
-->

<script setup lang="ts">
// 引入 Vue 组合式 API
import { ref, computed, onMounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入 Ant Design Vue 组件
import { Button, Modal, Spin, message } from 'ant-design-vue'
// 引入支付 API 与类型
import { getOrders, cancelOrder, type OrderSummary } from '@/api/trip/payment'

const router = useRouter()

// orders：订单列表；loading：加载状态
const orders = ref<OrderSummary[]>([])
const loading = ref(true)

// statusMeta：订单状态 → 显示名/标签色/说明
const statusMeta: Record<string, { label: string; color: string }> = {
  pending: { label: '待支付', color: 'orange' },
  paid: { label: '已支付', color: 'green' },
  cancelled: { label: '已取消', color: 'default' },
  refunded: { label: '已退款', color: 'red' }
}

// methodLabel：支付方式显示名
const methodLabel = (m: string | null) => {
  const map: Record<string, string> = { alipay: '支付宝', wechat: '微信支付', bank_card: '银行卡' }
  return map[m || ''] || m || '-'
}

// fmtTime：ISO 时间 → YYYY-MM-DD HH:mm
const fmtTime = (s: string | null) => (s ? s.slice(0, 16).replace('T', ' ') : '-')

// pendingCount：待支付订单数（顶部提示）
const pendingCount = computed(() => orders.value.filter((o) => o.status === 'pending').length)

/**
 * load：拉取订单列表
 */
const load = async () => {
  loading.value = true
  try {
    const res = await getOrders()
    if (res.success && res.data) {
      orders.value = res.data.orders
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/**
 * handleCancel：确认后取消待支付订单
 */
const handleCancel = (order: OrderSummary) => {
  Modal.confirm({
    title: '取消这笔订单？',
    content: `订单 ${order.order_id}（¥${order.amount.toFixed(2)}）将被取消。`,
    okText: '取消订单',
    cancelText: '再想想',
    onOk: async () => {
      try {
        const res = await cancelOrder(order.order_id)
        if (res.success) {
          message.success('订单已取消')
          await load()
        }
      } catch {
        // 错误提示由 request 拦截器统一处理
      }
    }
  })
}

onMounted(load)
</script>

<template>
  <div class="page-fade orders-page">
    <div class="od-inner">
      <!-- 页头 -->
      <header class="od-head">
        <h2>我的订单</h2>
        <p v-if="pendingCount > 0">你有 {{ pendingCount }} 笔待支付订单，请尽快完成支付</p>
        <p v-else>预订与支付记录（沙箱演示，不产生真实扣款）</p>
      </header>

      <Spin v-if="loading" style="display: block; padding: 64px 0;" />

      <!-- 订单列表 -->
      <template v-else-if="orders.length">
        <article v-for="o in orders" :key="o.order_id" class="od-item">
          <div class="od-main">
            <div class="od-title-row">
              <span class="od-status" :class="`s-${o.status}`">{{ statusMeta[o.status]?.label || o.status }}</span>
              <b class="od-amount">¥{{ o.amount.toFixed(2) }}</b>
            </div>
            <p class="od-meta">
              <span>{{ o.order_id }}</span>
              <span>·</span>
              <span>{{ methodLabel(o.payment_method) }}</span>
              <span>·</span>
              <span>{{ fmtTime(o.created_at) }}</span>
              <span v-if="o.paid_at">· 支付于 {{ fmtTime(o.paid_at) }}</span>
            </p>
          </div>
          <div class="od-actions">
            <template v-if="o.status === 'pending'">
              <Button type="primary" size="small" @click="router.push(`/pay/${o.order_id}`)">去支付</Button>
              <Button size="small" @click="handleCancel(o)">取消</Button>
            </template>
            <Button v-else-if="o.status === 'paid'" size="small" @click="router.push(`/result/${o.plan_id}`)">
              查看行程
            </Button>
          </div>
        </article>
      </template>

      <!-- 空状态 -->
      <div v-else class="od-empty">
        <span class="od-empty-icon">🧾</span>
        <p class="od-empty-title">还没有订单</p>
        <p class="od-empty-sub">在行程结果页的「预订支付」中创建第一笔订单</p>
        <Button type="primary" @click="router.push('/')">去规划旅行</Button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.orders-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 16px;
}
.od-head {
  margin: 28px 0 20px;
}
.od-head h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 800;
  color: #1f2a37;
}
.od-head p {
  margin: 0;
  font-size: 13px;
  color: #98a3b3;
}
.od-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  background: #fff;
  border-radius: 14px;
  padding: 18px 22px;
  margin-bottom: 12px;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.05);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.od-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 26px rgba(31, 56, 88, 0.12);
}
.od-main {
  flex: 1;
  min-width: 240px;
}
.od-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.od-status {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
}
.od-status.s-pending {
  color: #d46b08;
  background: #fff2e8;
}
.od-status.s-paid {
  color: #237804;
  background: #f0fbe8;
}
.od-status.s-cancelled {
  color: #8c8c8c;
  background: #f5f5f5;
}
.od-status.s-refunded {
  color: #cf1322;
  background: #fff1f0;
}
.od-amount {
  font-size: 18px;
  font-weight: 800;
  color: #fa541c;
}
.od-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 8px 0 0;
  font-size: 12.5px;
  color: #98a3b3;
}
.od-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.od-empty {
  text-align: center;
  padding: 72px 0 56px;
}
.od-empty-icon {
  display: inline-block;
  font-size: 60px;
  margin-bottom: 12px;
}
.od-empty-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #1f2a37;
}
.od-empty-sub {
  margin: 6px 0 20px;
  font-size: 13.5px;
  color: #98a3b3;
}
</style>
