"""
backend/app/api/routes/memory.py

用户记忆/偏好路由模块。

作用：
- 提供读取用户偏好、更新用户偏好接口；
- 调用 MemoryService 完成偏好管理。

对应技术：
- FastAPI：APIRouter、Depends
- SQLAlchemy：用户偏好持久化
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.db_models import User
from app.models.schemas import StandardResponse
from app.services.memory_service import MemoryService

router = APIRouter()


@router.get("/{user_id}", response_model=StandardResponse)
async def get_user_preference(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    获取用户偏好设置。

    Args:
        user_id: 用户 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 用户偏好数据。
    """
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看其他用户偏好")

    memory_service = MemoryService()
    preference = await memory_service.get_or_create_preference(session, user_id)

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "budget_level": preference.budget_level,
            "favorite_tags": preference.favorite_tags,
            "disliked_tags": preference.disliked_tags,
            "transportation": preference.transportation,
            "accommodation": preference.accommodation,
            "dietary_restrictions": preference.dietary_restrictions,
            "visited_cities": preference.visited_cities,
        },
    )


@router.post("/{user_id}", response_model=StandardResponse)
async def update_user_preference(
    user_id: int,
    updates: dict[str, Any],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    更新用户偏好设置。

    Args:
        user_id: 用户 ID。
        updates: 需要更新的偏好字段。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 更新后的偏好数据。
    """
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权更新其他用户偏好")

    memory_service = MemoryService()
    preference = await memory_service.update_preference(session, user_id, updates)

    return StandardResponse(
        success=True,
        message="更新成功",
        data={
            "budget_level": preference.budget_level,
            "favorite_tags": preference.favorite_tags,
            "disliked_tags": preference.disliked_tags,
            "transportation": preference.transportation,
            "accommodation": preference.accommodation,
            "dietary_restrictions": preference.dietary_restrictions,
            "visited_cities": preference.visited_cities,
        },
    )
