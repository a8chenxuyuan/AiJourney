/**
 * src/api/payment.ts：支付（沙箱）相关 API 封装
 * 作用：封装创建订单、查询订单列表、沙箱支付回调等接口调用
 */

// 导入统一响应类型与请求方法
import { httpGet, httpPost, type StandardResponse } from './request'

/**
 * PaymentCreateParams：创建支付订单请求参数
 */
export interface PaymentCreateParams {
  plan_id: string
  amount: number
  payment_method: 'alipay' | 'wechat' | 'bank_card'
}

/**
 * PaymentInfo：创建订单接口返回的支付信息
 */
export interface PaymentInfo {
  order_id: string
  amount: number
  status: string
  payment_params: {
    sandbox?: boolean
    order_id?: string
    amount?: number
    payment_method?: string
    mock_pay_url?: string
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
 * getOrders：查询当前用户在指定行程下的订单列表
 * @param planId 行程计划 ID
 * @returns Promise<StandardResponse<{ orders: OrderSummary[] }>> 订单摘要列表
 */
export function getOrders(planId: string): Promise<StandardResponse<{ orders: OrderSummary[] }>> {
  return httpGet<{ orders: OrderSummary[] }>('/payment/orders', { params: { plan_id: planId } })
}

/**
 * payNotify：沙箱支付完成后模拟第三方回调，通知后端更新订单状态
 * @param orderId 订单 ID
 * @returns Promise<StandardResponse<any>> 后端响应
 */
export function payNotify(orderId: string): Promise<StandardResponse<any>> {
  return httpPost<any>(`/payment/notify?order_id=${encodeURIComponent(orderId)}`, {
    sandbox: true,
    trade_status: 'TRADE_SUCCESS'
  })
}

/**
 * getOrder：查询单个订单状态
 * @param orderId 订单 ID
 * @returns Promise<StandardResponse<PaymentInfo>> 订单信息
 */
export function getOrder(orderId: string): Promise<StandardResponse<PaymentInfo>> {
  return httpGet<PaymentInfo>(`/payment/${orderId}`)
}
