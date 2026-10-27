<!-- ResultPayModal.vue：预订行程沙箱支付弹窗——选支付方式、创建订单、模拟支付 -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { Modal, Button, Radio, RadioGroup, message } from 'ant-design-vue'
import { createPayment, payOrder, type OrderSummary } from '@/api/trip/payment'

const props = defineProps<{
  planId: string
  amount?: number
}>()

const visible = defineModel<boolean>('visible', { default: false })

const emit = defineEmits<{
  (e: 'paid'): void
}>()

const payMethod = ref<'alipay' | 'wechat' | 'bank_card'>('alipay')
const payCreating = ref(false)
const paying = ref(false)
// currentOrder：本次弹窗内正在操作的订单（创建后填充）
const currentOrder = ref<OrderSummary | null>(null)

const payMethodOptions = [
  { label: '支付宝', value: 'alipay' },
  { label: '微信支付', value: 'wechat' },
  { label: '银行卡', value: 'bank_card' }
]

// 打开弹窗时重置为选择支付方式步骤（与原 openPayModal 行为一致）
watch(visible, (v) => {
  if (v) currentOrder.value = null
})

/**
 * handleCreateOrder：创建支付订单（沙箱）
 */
const handleCreateOrder = async () => {
  const amount = props.amount || 0
  if (!amount) {
    message.warning('行程还没有预算信息，无法创建订单')
    return
  }
  payCreating.value = true
  try {
    const res = await createPayment({ plan_id: props.planId, amount, payment_method: payMethod.value })
    if (res.success && res.data) {
      currentOrder.value = {
        order_id: res.data.order_id,
        plan_id: props.planId,
        amount: res.data.amount,
        status: res.data.status,
        payment_method: payMethod.value,
        created_at: null,
        paid_at: null
      }
      message.success('订单已创建，请确认支付')
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    payCreating.value = false
  }
}

/**
 * handleSandboxPay：收银台确认支付，更新订单状态
 */
const handleSandboxPay = async () => {
  if (!currentOrder.value) return
  paying.value = true
  try {
    const res = await payOrder(currentOrder.value.order_id)
    if (res.success) {
      currentOrder.value.status = 'paid'
      message.success('支付成功，行程已预订！')
      emit('paid')
    }
  } catch {
    // 错误提示由 request 拦截器统一处理
  } finally {
    paying.value = false
  }
}
</script>

<template>
  <Modal v-model:open="visible" title="预订行程（沙箱支付）" :footer="null" style="border-radius: 12px;">
    <!-- 步骤一：创建订单 -->
    <template v-if="!currentOrder">
      <p style="color: #666; margin-bottom: 12px;">
        根据行程预算创建预订订单：预估总额
        <strong style="color: #fa541c; font-size: 18px;">¥{{ amount ?? '-' }}</strong>
        <span style="color: #999; font-size: 12px;">（沙箱环境，不涉及真实资金）</span>
      </p>
      <p style="margin-bottom: 8px; font-weight: 600;">选择支付方式</p>
      <RadioGroup v-model:value="payMethod" style="margin-bottom: 16px;">
        <Radio v-for="m in payMethodOptions" :key="m.value" :value="m.value">{{ m.label }}</Radio>
      </RadioGroup>
      <Button type="primary" block :loading="payCreating" @click="handleCreateOrder">创建订单</Button>
    </template>
    <!-- 步骤二：沙箱支付 / 支付完成 -->
    <template v-else>
      <div style="text-align: center; padding: 8px 0 16px;">
        <template v-if="currentOrder.status !== 'paid'">
          <p style="font-size: 28px; color: #fa541c; margin: 8px 0;">¥{{ currentOrder.amount }}</p>
          <p style="color: #999; font-size: 13px; margin-bottom: 16px;">订单号：{{ currentOrder.order_id }}</p>
          <Button type="primary" size="large" block :loading="paying" @click="handleSandboxPay">
            模拟支付成功（沙箱）
          </Button>
        </template>
        <template v-else>
          <p style="font-size: 40px; margin: 8px 0;">✅</p>
          <p style="font-size: 16px; font-weight: 600; color: #52c41a;">支付成功，行程已预订</p>
          <p style="color: #999; font-size: 13px;">订单号：{{ currentOrder.order_id }}</p>
        </template>
      </div>
    </template>
  </Modal>
</template>
