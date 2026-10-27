"""站内通知：列表与全部标记已读。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.models.db_models import (
    PlanNotification,
    User,
)
from app.models.schemas import (
    StandardResponse,
)

router = APIRouter()


@router.get("/notifications", response_model=StandardResponse)
async def list_notifications(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
):
    """
    获取当前用户的站内通知列表（created_at 倒序，限 50 条）与未读数。

    Returns:
        StandardResponse: data = {"notifications": [...], "unread_count": n}。
    """
    result = await session.execute(
        select(PlanNotification)
        .where(PlanNotification.user_id == current_user.id)
        .order_by(PlanNotification.created_at.desc())
        .limit(50)
    )
    unread_result = await session.execute(
        select(func.count())
        .select_from(PlanNotification)
        .where(PlanNotification.user_id == current_user.id, PlanNotification.is_read.is_(False))
    )
    notifications = [
        {
            "id": item.id,
            "type": item.type,
            "title": item.title,
            "content": item.content,
            "is_read": bool(item.is_read),
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in result.scalars().all()
    ]
    return StandardResponse(
        success=True,
        message="获取成功",
        data={"notifications": notifications, "unread_count": int(unread_result.scalar() or 0)},
    )


@router.post("/notifications/read-all", response_model=StandardResponse)
async def read_all_notifications(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
):
    """
    把当前用户的全部未读通知标记为已读。

    Returns:
        StandardResponse: data = {"marked": n}（本次标记的条数）。
    """
    result = await session.execute(
        update(PlanNotification)
        .where(PlanNotification.user_id == current_user.id, PlanNotification.is_read.is_(False))
        .values(is_read=True)
    )
    await session.commit()
    return StandardResponse(
        success=True, message="已全部标记为已读", data={"marked": result.rowcount or 0}
    )


# ==================== 个性化推荐 ====================
