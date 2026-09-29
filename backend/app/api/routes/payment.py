"""
backend/app/api/routes/payment.py

支付路由模块（沙箱）。

作用：
- 提供创建支付订单、查询订单状态、处理支付回调等接口；
- 调用 PaymentService 完成订单相关业务逻辑。

对应技术：
- FastAPI：APIRouter、Depends
- SQLAlchemy：订单持久化
"""

from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.db_models import User, Order
from app.models.schemas import StandardResponse, PaymentCreateRequest
from app.services.payment_service import PaymentService


router = APIRouter()


def _order_to_dict(order: Order) -> Dict[str, Any]:
    """
    将订单对象转换为响应字典。

    Args:
        order: 订单数据库对象。

    Returns:
        Dict[str, Any]: 订单摘要字段。
    """
    return {
        "order_id": order.id,
        "plan_id": order.plan_id,
        "amount": order.amount,
        "status": order.status,
        "payment_method": order.payment_method,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None
    }


@router.post("/create", response_model=StandardResponse)
async def create_payment(
    request: PaymentCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    创建支付订单。

    Args:
        request: 支付创建请求。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 订单信息及支付参数。
    """
    order = await PaymentService.create_order(
        session,
        current_user.id,
        request.plan_id,
        request.amount,
        request.payment_method
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="关联的行程计划不存在"
        )

    return StandardResponse(
        success=True,
        message="订单创建成功",
        data=PaymentService.to_payment_response(order).model_dump()
    )


@router.get("/orders", response_model=StandardResponse)
async def list_orders(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    查询当前用户在指定行程下的订单列表。

    用于结果页展示"已预订"徽标与订单记录。

    Args:
        plan_id: 行程计划 ID（查询参数）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 订单摘要列表，按创建时间倒序。
    """
    result = await session.execute(
        select(Order)
        .where(Order.user_id == current_user.id, Order.plan_id == plan_id)
        .order_by(Order.created_at.desc())
    )
    orders: List[Order] = list(result.scalars().all())

    return StandardResponse(
        success=True,
        message="查询成功",
        data={"orders": [_order_to_dict(o) for o in orders]}
    )


@router.get("/{order_id}", response_model=StandardResponse)
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    查询订单状态。

    Args:
        order_id: 订单 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 订单信息。
    """
    order = await session.get(Order, order_id)
    if not order or order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="订单不存在"
        )

    return StandardResponse(
        success=True,
        message="查询成功",
        data=PaymentService.to_payment_response(order).model_dump()
    )


@router.post("/notify", response_model=StandardResponse)
async def payment_notify(
    order_id: str,
    notify_data: Dict[str, Any],
    session: AsyncSession = Depends(get_db)
):
    """
    支付回调通知接口（沙箱）。

    真实环境中该接口由第三方支付平台服务器调用（服务器间通信，无法携带
    用户登录态），因此不依赖 get_current_user；安全性靠验签保证，
    接入真实支付时需在校验签名后才能更新订单状态。

    前端完成沙箱支付后，模拟第三方调用此接口，后端更新订单状态。

    Args:
        order_id: 订单 ID（查询参数）。
        notify_data: 第三方支付回调数据。
        session: 数据库会话。

    Returns:
        StandardResponse: 回调处理结果。
    """
    order = await PaymentService.process_payment_notification(session, order_id, notify_data)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="订单不存在"
        )

    return StandardResponse(
        success=True,
        message="支付状态更新成功",
        data={"order_id": order.id, "status": order.status}
    )
