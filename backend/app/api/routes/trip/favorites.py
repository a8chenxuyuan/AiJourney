"""收藏：添加、列表、按城市聚合、取消收藏。"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.db_models import (
    Favorite,
    User,
)
from app.models.schemas import (
    FavoriteCreateRequest,
    FavoriteOut,
    StandardResponse,
)

router = APIRouter()


@router.post("/favorites", response_model=StandardResponse)
async def add_favorite(
    fav_request: FavoriteCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    添加收藏（景点/酒店/餐厅）。

    同一用户对同一 item_id 重复收藏时直接返回已有记录，保证幂等。

    Args:
        fav_request: 收藏内容。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 收藏记录。
    """
    # 幂等：已收藏过同一对象则不再重复插入
    result = await session.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id, Favorite.item_id == fav_request.item_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return StandardResponse(
            success=True,
            message="已收藏过该内容",
            data=FavoriteOut(
                id=existing.id,
                item_type=existing.item_type,
                item_id=existing.item_id,
                item_name=existing.item_name,
                city=existing.city,
                item_data=existing.item_data,
                created_at=existing.created_at.isoformat() if existing.created_at else None,
            ).model_dump(),
        )

    favorite = Favorite(
        user_id=current_user.id,
        city=fav_request.city,
        item_type=fav_request.item_type,
        item_id=fav_request.item_id,
        item_name=fav_request.item_name,
        item_data=fav_request.item_data,
    )
    session.add(favorite)
    await session.commit()
    await session.refresh(favorite)
    logger.info(
        f"[收藏] 用户 {current_user.id} 收藏 {fav_request.item_type} {fav_request.item_name}"
    )

    return StandardResponse(
        success=True,
        message="收藏成功",
        data=FavoriteOut(
            id=favorite.id,
            item_type=favorite.item_type,
            item_id=favorite.item_id,
            item_name=favorite.item_name,
            city=favorite.city,
            item_data=favorite.item_data,
            created_at=favorite.created_at.isoformat() if favorite.created_at else None,
        ).model_dump(),
    )


@router.get("/favorites", response_model=StandardResponse)
async def list_favorites(
    city: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    查询当前用户的收藏列表，支持按城市过滤。

    Args:
        city: 可选的城市过滤条件。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 收藏记录数组。
    """
    query = select(Favorite).where(Favorite.user_id == current_user.id)
    if city:
        query = query.where(Favorite.city == city)
    query = query.order_by(Favorite.created_at.desc())
    result = await session.execute(query)
    favorites = result.scalars().all()

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "favorites": [
                FavoriteOut(
                    id=f.id,
                    item_type=f.item_type,
                    item_id=f.item_id,
                    item_name=f.item_name,
                    city=f.city,
                    item_data=f.item_data,
                    created_at=f.created_at.isoformat() if f.created_at else None,
                ).model_dump()
                for f in favorites
            ]
        },
    )


@router.get("/favorites/cities", response_model=StandardResponse)
async def list_favorite_cities(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
):
    """
    查询当前用户收藏内容涉及的城市列表（去重）。

    用于首页"你可能想去"个性化入口。

    Args:
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 城市名数组（按收藏时间倒序）。
    """
    result = await session.execute(
        select(Favorite.city)
        .where(Favorite.user_id == current_user.id, Favorite.city.is_not(None))
        .order_by(Favorite.created_at.desc())
    )
    # 按收藏时间倒序去重，保留最近收藏的城市优先
    cities: list[str] = []
    for (city,) in result.all():
        if city and city not in cities:
            cities.append(city)

    return StandardResponse(success=True, message="获取成功", data={"cities": cities})


@router.delete("/favorites/{favorite_id}", response_model=StandardResponse)
async def remove_favorite(
    favorite_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    取消收藏（仅能删除自己的收藏）。

    Args:
        favorite_id: 收藏记录 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 操作结果。
    """
    result = await session.execute(
        select(Favorite).where(Favorite.id == favorite_id, Favorite.user_id == current_user.id)
    )
    favorite = result.scalar_one_or_none()
    if favorite is None:
        raise HTTPException(status_code=404, detail="收藏记录不存在")

    await session.delete(favorite)
    await session.commit()
    return StandardResponse(success=True, message="已取消收藏", data=None)


# ==================== 站内通知（出发前天气提醒等） ====================
# 注意：以下静态路径必须注册在 GET /{plan_id} 动态路由之前，避免被误匹配为 plan_id。
