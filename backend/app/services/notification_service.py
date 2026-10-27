"""
backend/app/services/notification_service.py

站内互动通知服务。

作用：
- 统一封装「写 Notification 表 + WS 实时推送」两步，供好友申请/同意、
  点赞/评论/回复钩子复用，保证通知落库与实时提醒行为一致；
- 提供侧边栏红点徽标聚合查询。

对应技术：SQLAlchemy 异步 ORM、ws_manager 推送。
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Notification, User
from app.services.ws_manager import manager

# 通知类型 -> 前端文案模板（{actor} 为触发者昵称占位）
_TYPE_TEXT = {
    "like": "{actor} 赞了你的帖子",
    "comment": "{actor} 评论了你的帖子",
    "reply": "{actor} 回复了你的评论",
    "friend_request": "{actor} 请求加你为好友",
    "friend_accepted": "{actor} 已同意你的好友申请",
}


async def push_notification(
    session: AsyncSession,
    user_id: int,
    actor_id: int | None,
    ntype: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """写入一条通知并尝试 WS 实时推送（不在线则靠前端对账兜底）。"""
    actor_name = None
    if actor_id:
        actor = await session.get(User, actor_id)
        actor_name = actor.username if actor else None

    notification = Notification(
        user_id=user_id,
        actor_id=actor_id,
        type=ntype,
        payload=payload or {},
    )
    session.add(notification)
    await session.flush()

    text = _TYPE_TEXT.get(ntype, "你有新的消息").format(actor=actor_name or "有人")
    await manager.send_to_user(
        user_id,
        {
            "type": "notification",
            "notification": {
                "id": notification.id,
                "ntype": ntype,
                "text": text,
                "payload": payload or {},
                "actor_id": actor_id,
                "actor_name": actor_name,
                "created_at": notification.created_at.isoformat()
                if notification.created_at
                else None,
            },
        },
    )


async def unread_count(session: AsyncSession, user_id: int) -> int:
    """未读互动通知数（侧边栏红点聚合的一部分）。"""
    result = await session.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
    )
    return int(result.scalar() or 0)


def to_dict(notification: Notification, actor_name: str | None) -> dict[str, Any]:
    """通知记录 -> 前端展示字典（system 公告直接用 payload 标题，不带 actor）。"""
    if notification.type == "system":
        title = (notification.payload or {}).get("title") or "系统公告"
        text = f"📢 {title}"
    else:
        text = _TYPE_TEXT.get(notification.type, "你有新的消息").format(
            actor=actor_name or "有人"
        )
    return {
        "id": notification.id,
        "ntype": notification.type,
        "text": text,
        "payload": notification.payload or {},
        "actor_id": notification.actor_id,
        "actor_name": actor_name,
        "is_read": notification.is_read,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }
