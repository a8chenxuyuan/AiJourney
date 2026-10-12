"""
backend/app/api/routes/user.py

用户相关路由模块。

作用：
- 提供用户资料查询、历史行程列表、收藏列表等接口；
- 所有接口都需要登录。

对应技术：
- FastAPI：APIRouter、Depends
- SQLAlchemy：异步查询
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.db_models import Favorite, TripPlanDB, User
from app.models.schemas import StandardResponse

router = APIRouter()


@router.get("/{user_id}/profile", response_model=StandardResponse)
async def get_user_profile(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    获取指定用户资料。

    当前用户只能查看自己的资料。

    Args:
        user_id: 用户 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 用户资料。
    """
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看其他用户资料")

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "created_at": current_user.created_at.isoformat(),
        },
    )


@router.get("/{user_id}/plans", response_model=StandardResponse)
async def get_user_plans(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的历史行程列表。

    Args:
        user_id: 用户 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 历史行程列表。
    """
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看其他用户行程")

    result = await session.execute(
        select(TripPlanDB)
        .where(TripPlanDB.user_id == user_id)
        .order_by(TripPlanDB.created_at.desc())
    )
    plans = result.scalars().all()

    return StandardResponse(
        success=True,
        message="获取成功",
        data=[
            {
                "plan_id": plan.id,
                "city": plan.city,
                "start_date": plan.start_date,
                "end_date": plan.end_date,
                "travel_days": plan.travel_days,
                "status": plan.status,
                "created_at": plan.created_at.isoformat(),
            }
            for plan in plans
        ],
    )


@router.get("/{user_id}/favorites", response_model=StandardResponse)
async def get_user_favorites(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的收藏列表。

    Args:
        user_id: 用户 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 收藏列表。
    """
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看其他用户收藏")

    result = await session.execute(
        select(Favorite).where(Favorite.user_id == user_id).order_by(Favorite.created_at.desc())
    )
    favorites = result.scalars().all()

    return StandardResponse(
        success=True,
        message="获取成功",
        data=[
            {
                "id": f.id,
                "item_type": f.item_type,
                "item_id": f.item_id,
                "item_name": f.item_name,
                "created_at": f.created_at.isoformat(),
            }
            for f in favorites
        ],
    )
