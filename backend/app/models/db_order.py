"""
backend/app/models/db_order.py

订单/支付域数据库模型。

作用：
- 定义支付/预订订单表结构；
- 原 db_models.py 按域拆分而来，所有模型继承自 app.db.base.Base。
"""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Order(Base):
    """
    订单表。

    存储用户发起的支付/预订订单，当前仅用于沙箱演示。
    """

    __tablename__ = "orders"

    id = Column(String(64), primary_key=True, index=True, comment="订单 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID"
    )
    amount = Column(Float, nullable=False, comment="订单金额")
    status = Column(String(20), default="pending", comment="状态：pending/paid/cancelled/refunded")
    payment_method = Column(String(20), nullable=True, comment="支付方式")
    third_party_order_id = Column(String(255), nullable=True, comment="第三方支付订单号")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    paid_at = Column(DateTime, nullable=True, comment="支付时间")

    user = relationship("User", back_populates="orders")


__all__ = ["Order"]
