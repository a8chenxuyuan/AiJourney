/**
 * src/api/payment.ts：支付（沙箱）相关 API 封装
 * 作用：封装创建订单、订单列表/详情、沙箱支付确认、取消订单、支付回调等接口调用
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, type StandardResponse } from '../request'

/**
 * PaymentCreateParams：创建支付订单请求参数
 */
export interface PaymentCreateParams {
  plan_id: string
  amount: number
  payment_method: 'alipay' | 'wechat' | 'bank_card'
}

/**
 * PaymentInfo：订单详情/支付响应（含订单摘要与支付参数）
 */
export interface PaymentInfo {
  order_id: string
  plan_id: string
  amount: number
  status: string
  payment_method: string | null
  created_at: string | null
  paid_at: string | null
  payment_params: {
    sandbox?: boolean
    order_id?: string
    amount?: number
    payment_method?: string
    pay_url?: string
    cancel_url?: string
  } | null
}

/**
 * OrderSummary：订单摘要记录
 */
export interface OrderSummary {
  order_id: string
  plan_id: string
  amount: number
  status: string
  payment_method: string | null
  created_at: string | null
  paid_at: string | null
}

/**
 * createPayment：为行程创建支付订单（沙箱）
 * @param params 订单参数（行程 ID、金额、支付方式）
 * @returns Promise<StandardResponse<PaymentInfo>> 订单与支付参数
 */
export function createPayment(params: PaymentCreateParams): Promise<StandardResponse<PaymentInfo>> {
  return httpPost<PaymentInfo>('/payment/create', params)
}

/**
 * getOrders：查询当前用户的订单列表
 * @param planId 可选，行程计划 ID（不传返回全部订单）
 * @returns Promise<StandardResponse<{ orders: OrderSummary[] }>> 订单摘要列表
 */
export function getOrders(planId?: string): Promise<StandardResponse<{ orders: OrderSummary[] }>> {
  return httpGet<{ orders: OrderSummary[] }>(
    '/payment/orders',
    planId ? { params: { plan_id: planId } } : undefined
  )
}

/**
 * getOrder：查询单个订单详情（含支付参数）
 * @param orderId 订单 ID
 * @returns Promise<StandardResponse<PaymentInfo>> 订单信息
 */
export function getOrder(orderId: string): Promise<StandardResponse<PaymentInfo>> {
  return httpGet<PaymentInfo>(`/payment/${orderId}`)
}

/**
 * payOrder：沙箱收银台确认支付，后端直接置为已支付
 * @param orderId 订单 ID
 * @returns Promise<StandardResponse<PaymentInfo>> 支付后的订单信息
 */
export function payOrder(orderId: string): Promise<StandardResponse<PaymentInfo>> {
  return httpPost<PaymentInfo>(`/payment/${orderId}/pay`)
}

/**
 * cancelOrder：取消待支付订单
 * @param orderId 订单 ID
 * @returns Promise<StandardResponse<OrderSummary>> 取消后的订单信息
 */
export function cancelOrder(orderId: string): Promise<StandardResponse<OrderSummary>> {
  return httpPost<OrderSummary>(`/payment/${orderId}/cancel`)
}

/**
 * payNotify：模拟第三方支付回调（服务器间通知语义，保留用于联调/演示）
 * @param orderId 订单 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function payNotify(orderId: string): Promise<StandardResponse<any>> {
  return httpPost<any>(`/payment/notify?order_id=${encodeURIComponent(orderId)}`, {
    sandbox: true,
    trade_status: 'TRADE_SUCCESS'
  })
}
