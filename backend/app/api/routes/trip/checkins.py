"""行程打卡路由：行中在地点打卡，记录坐标/照片/感想，供足迹地图与游记生成使用。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user
from app.db.session import get_db
from app.models.db_models import TripCheckin, TripPlanDB, User
from app.models.schemas import CheckinCreateRequest, StandardResponse

router = APIRouter()


def _checkin_out(checkin: TripCheckin) -> dict:
    """打卡记录转响应 dict。"""
    return {
        "id": checkin.id,
        "plan_id": checkin.plan_id,
        "day_index": checkin.day_index,
        "spot_type": checkin.spot_type,
        "spot_name": checkin.spot_name,
        "longitude": checkin.longitude,
        "latitude": checkin.latitude,
        "checkin_at": checkin.checkin_at,
        "photo_urls": checkin.photo_urls or [],
        "note": checkin.note,
    }


@router.post("/{plan_id}/checkins", response_model=StandardResponse)
async def create_checkin(
    payload: CheckinCreateRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    创建打卡（所有者或协作者均可）。

    Args:
        payload: 打卡内容（天序号、地点类型/名称、坐标、照片、感想）。
        plan: 访问校验通过的行程计划。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 新建的打卡记录。
    """
    checkin = TripCheckin(
        id=f"CK_{uuid.uuid4().hex}",
        plan_id=plan.id,
        user_id=current_user.id,
        day_index=payload.day_index,
        spot_type=payload.spot_type,
        spot_name=payload.spot_name,
        longitude=payload.longitude,
        latitude=payload.latitude,
        checkin_at=payload.checkin_at or datetime.now(),
        photo_urls=payload.photo_urls,
        note=payload.note,
    )
    session.add(checkin)
    await session.commit()
    await session.refresh(checkin)
    logger.info(
        f"[Checkin] 用户 {current_user.id} 行程 {plan.id} 第{payload.day_index}天"
        f"打卡：{payload.spot_name}"
    )

    return StandardResponse(success=True, message="打卡成功", data=_checkin_out(checkin))


@router.get("/{plan_id}/checkins", response_model=StandardResponse)
async def list_checkins(
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    查询行程的全部打卡记录，按天分组返回（足迹地图与当日视图用）。

    Args:
        plan: 访问校验通过的行程计划。
        session: 数据库会话。

    Returns:
        StandardResponse: {checkins: 平铺列表, by_day: {day_index: [打卡记录]}}。
    """
    result = await session.execute(
        select(TripCheckin)
        .where(TripCheckin.plan_id == plan.id)
        .order_by(TripCheckin.day_index, TripCheckin.checkin_at)
    )
    checkins = list(result.scalars().all())

    by_day: dict[int, list[dict]] = {}
    items = []
    for c in checkins:
        item = _checkin_out(c)
        items.append(item)
        by_day.setdefault(c.day_index, []).append(item)

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"checkins": items, "by_day": by_day, "total": len(items)},
    )


@router.delete("/checkins/{checkin_id}", response_model=StandardResponse)
async def delete_checkin(
    checkin_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    删除打卡（仅打卡人本人可删）。

    Args:
        checkin_id: 打卡 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 操作结果。
    """
    checkin = await session.get(TripCheckin, checkin_id)
    if not checkin or checkin.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="打卡记录不存在")

    plan_id = checkin.plan_id
    await session.execute(delete(TripCheckin).where(TripCheckin.id == checkin_id))
    await session.commit()
    logger.info(f"[Checkin] 用户 {current_user.id} 删除打卡 {checkin_id}（行程 {plan_id}）")
    return StandardResponse(success=True, message="已删除", data={"checkin_id": checkin_id})
