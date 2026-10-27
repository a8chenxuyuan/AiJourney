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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.models.db_models import Order, User
from app.models.schemas import PaymentCreateRequest, StandardResponse
from app.services.payment_service import PaymentService

router = APIRouter()


def _order_to_dict(order: Order) -> dict[str, Any]:
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
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }


@router.post("/create", response_model=StandardResponse)
async def create_payment(
    request: PaymentCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
        session, current_user.id, request.plan_id, request.amount, request.payment_method
    )

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联的行程计划不存在")

    return StandardResponse(
        success=True,
        message="订单创建成功",
        data=PaymentService.to_payment_response(order).model_dump(),
    )


@router.get("/orders", response_model=StandardResponse)
async def list_orders(
    plan_id: str | None = Query(default=None, description="可选，按行程过滤；不传返回全部订单"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    查询当前用户的订单列表。

    传 plan_id 时用于结果页展示"已预订"徽标；不传用于「我的订单」页全量展示。

    Args:
        plan_id: 行程计划 ID（可选查询参数）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 订单摘要列表，按创建时间倒序。
    """
    stmt = select(Order).where(Order.user_id == current_user.id)
    if plan_id:
        stmt = stmt.where(Order.plan_id == plan_id)
    result = await session.execute(stmt.order_by(Order.created_at.desc()))
    orders: list[Order] = list(result.scalars().all())

    return StandardResponse(
        success=True, message="查询成功", data={"orders": [_order_to_dict(o) for o in orders]}
    )


async def _get_owned_order(
    order_id: str, current_user: User, session: AsyncSession
) -> Order:
    """按 ID 取属于当前用户的订单，不存在或非本人统一 404。"""
    order = await session.get(Order, order_id)
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return order


@router.post("/{order_id}/pay", response_model=StandardResponse)
async def pay_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    沙箱收银台确认支付。

    真实环境中此处应跳第三方收银台并在回调（/notify）中更新状态；
    沙箱下由登录用户在本端点直接确认，置为已支付。

    Args:
        order_id: 订单 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 支付后的订单信息。
    """
    order = await _get_owned_order(order_id, current_user, session)
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="订单已支付或已取消，无需重复支付"
        )
    order = await PaymentService.process_payment_notification(session, order_id, {"sandbox": True})
    data = {**_order_to_dict(order), "payment_params": PaymentService.build_payment_params(order)}

    return StandardResponse(success=True, message="支付成功", data=data)


@router.post("/{order_id}/cancel", response_model=StandardResponse)
async def cancel_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    取消待支付订单。

    Args:
        order_id: 订单 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 取消后的订单信息。
    """
    order = await _get_owned_order(order_id, current_user, session)
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅待支付订单可取消"
        )
    order.status = "cancelled"
    await session.flush()
    await session.refresh(order)

    return StandardResponse(
        success=True, message="订单已取消", data=_order_to_dict(order)
    )


@router.get("/{order_id}", response_model=StandardResponse)
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")

    # 返回订单摘要 + 支付参数（收银台页需要 plan_id/amount/status 全量信息）
    return StandardResponse(
        success=True,
        message="查询成功",
        data={
            **_order_to_dict(order),
            "payment_params": PaymentService.build_payment_params(order),
        },
    )


@router.post("/notify", response_model=StandardResponse)
async def payment_notify(
    order_id: str, notify_data: dict[str, Any], session: AsyncSession = Depends(get_db)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")

    return StandardResponse(
        success=True,
        message="支付状态更新成功",
        data={"order_id": order.id, "status": order.status},
    )
