"""
backend/app/services/payment_service.py

支付服务模块（沙箱）。

作用：
- 创建支付订单并持久化到数据库；
- 模拟/封装第三方支付（支付宝/微信）沙箱接口；
- 处理支付回调并更新订单状态。

对应技术：
- SQLAlchemy 异步 ORM
- 支付宝/微信 SDK（可选，当前为模拟实现）
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db_models import Order, TripPlanDB
from app.models.schemas import PaymentResponse


class PaymentService:
    """
    支付服务类。

    当前使用沙箱模式，不触碰真实资金。
    """

    @staticmethod
    def generate_order_id() -> str:
        """
        生成唯一订单号。

        Returns:
            str: 以 ORDER_ 为前缀的 UUID 字符串。
        """
        return f"ORDER_{uuid.uuid4().hex[:16].upper()}"

    @staticmethod
    async def create_order(
        session: AsyncSession,
        user_id: int,
        plan_id: str,
        amount: float,
        payment_method: str = "alipay",
    ) -> Order | None:
        """
        创建支付订单。

        Args:
            session: 数据库会话。
            user_id: 用户 ID。
            plan_id: 关联的行程计划 ID。
            amount: 订单金额。
            payment_method: 支付方式。

        Returns:
            Optional[Order]: 创建成功的订单对象；如果行程计划不存在返回 None。
        """
        # 检查行程计划是否存在
        plan = await session.get(TripPlanDB, plan_id)
        if not plan:
            return None

        order = Order(
            id=PaymentService.generate_order_id(),
            user_id=user_id,
            plan_id=plan_id,
            amount=amount,
            status="pending",
            payment_method=payment_method,
            third_party_order_id=f"SANDBOX_{uuid.uuid4().hex[:12].upper()}",
        )
        session.add(order)
        await session.flush()
        await session.refresh(order)
        return order

    @staticmethod
    def build_payment_params(order: Order) -> dict[str, Any]:
        """
        构建第三方支付参数（沙箱）。

        Args:
            order: 订单对象。

        Returns:
            Dict[str, Any]: 用于前端调起支付的参数。
        """
        if settings.payment_sandbox:
            return {
                "sandbox": True,
                "order_id": order.id,
                "amount": order.amount,
                "payment_method": order.payment_method,
                "mock_pay_url": f"/api/payment/{order.id}/mock_pay",
            }
        # TODO: 接入真实支付宝/微信支付 SDK
        return {}

    @staticmethod
    async def process_payment_notification(
        session: AsyncSession, order_id: str, third_party_data: dict[str, Any]
    ) -> Order | None:
        """
        处理支付回调通知。

        Args:
            session: 数据库会话。
            order_id: 订单 ID。
            third_party_data: 第三方支付回调数据。

        Returns:
            Optional[Order]: 更新后的订单对象；未找到返回 None。
        """
        order = await session.get(Order, order_id)
        if not order:
            return None

        # 沙箱模式下直接认为支付成功
        # 真实环境需要校验签名和状态
        order.status = "paid"
        order.paid_at = datetime.now()

        await session.flush()
        await session.refresh(order)
        return order

    @staticmethod
    def to_payment_response(order: Order) -> PaymentResponse:
        """
        将 Order 对象转换为 PaymentResponse。

        Args:
            order: 订单数据库对象。

        Returns:
            PaymentResponse: 支付响应模型。
        """
        return PaymentResponse(
            order_id=order.id,
            amount=order.amount,
            status=order.status,
            payment_params=PaymentService.build_payment_params(order),
        )
