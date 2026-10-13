"""旅行档案路由：当前用户的历史行程汇总与打卡统计（固定路径 /archive，需先于动态路由注册）。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.db_models import TripCheckin, TripPlanDB, User
from app.models.schemas import StandardResponse

router = APIRouter()


@router.get("/archive", response_model=StandardResponse)
async def get_archive(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    旅行档案：当前用户的全部行程 + 打卡统计。

    统计口径：
    - 去过城市：行程数（多城行程按 cities_json 展开，单城按 city）；
    - 打卡次数 / 照片数：trip_checkins 全量聚合；
    - 足迹 span：最早打卡日 ~ 最晚打卡日。

    Args:
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: {stats, plans}。
    """
    # 行程列表（创建时间倒序）
    plans_result = await session.execute(
        select(TripPlanDB)
        .where(TripPlanDB.user_id == current_user.id)
        .order_by(TripPlanDB.created_at.desc())
    )
    plans = list(plans_result.scalars().all())

    # 打卡全量拉到 Python 统计（个人量级小，SQLite 无便捷 JSON 长度聚合）
    checkin_result = await session.execute(
        select(TripCheckin).where(TripCheckin.user_id == current_user.id)
    )
    all_checkins = list(checkin_result.scalars().all())
    checkin_total = len(all_checkins)
    photo_total = sum(len(c.photo_urls or []) for c in all_checkins)
    checkin_times = [c.checkin_at for c in all_checkins if c.checkin_at]
    first_at = min(checkin_times) if checkin_times else None
    last_at = max(checkin_times) if checkin_times else None

    # 每行程打卡数
    checkin_by_plan: dict[str, int] = {}
    for c in all_checkins:
        checkin_by_plan[c.plan_id] = checkin_by_plan.get(c.plan_id, 0) + 1

    # 城市去重集合：单城用 city，多城展开 cities_json
    cities: set[str] = set()
    plan_items = []
    for p in plans:
        if p.cities_json:
            cities.update(c.get("city", "") for c in p.cities_json if c.get("city"))
        elif p.city:
            cities.add(p.city)
        plan_items.append(
            {
                "plan_id": p.id,
                "city": p.city,
                "cities": p.cities_json,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "travel_days": p.travel_days,
                "status": p.status,
                "budget_total": (p.plan_data or {}).get("budget", {}).get("total"),
                "checkin_count": checkin_by_plan.get(p.id, 0),
            }
        )

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "stats": {
                "plan_count": len(plans),
                "city_count": len(cities),
                "cities": sorted(cities),
                "checkin_total": checkin_total or 0,
                "photo_total": photo_total or 0,
                "first_checkin_at": first_at,
                "last_checkin_at": last_at,
            },
            "plans": plan_items,
        },
    )
