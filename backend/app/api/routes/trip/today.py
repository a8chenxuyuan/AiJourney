"""当日视图路由：行中"今天怎么走"聚合页 + 高德周边搜索代理。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan
from app.core.db.session import get_db
from app.models.db_models import TripCheckin, TripPlanDB
from app.models.schemas import StandardResponse
from app.planning.tools.amap_tools import get_weather
from app.services.amap_service import AmapService
from app.services.memory_service import MemoryService

router = APIRouter()

# 周边搜索类型 → 高德关键词映射（toilet 用关键词而非类型码，避免类型码版本差异）
_NEARBY_TYPE_KEYWORDS = {
    "restaurant": "美食",
    "cafe": "咖啡",
    "toilet": "公共厕所",
}


def _load_plan_data(plan: TripPlanDB, revision_json: dict | None) -> dict:
    """优先用当前生效 revision 的行程 JSON，无 revision 时回退 plan_data。"""
    return revision_json or plan.plan_data or {}


def _pick_today_weather(raw_weather: dict | None) -> dict | None:
    """从高德预报中挑出今天那条（date 匹配失败时退回首条）。"""
    forecasts = (raw_weather or {}).get("forecasts", []) or []
    if not forecasts:
        return None
    today_str = datetime.now().strftime("%Y-%m-%d")
    for item in forecasts:
        if item.get("date") == today_str:
            return item
    return forecasts[0]


@router.get("/{plan_id}/today", response_model=StandardResponse)
async def get_today_view(
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    当日视图聚合：今天是行程第几天的安排 + 各地点打卡状态 + 当日天气。

    行程未开始/已结束时返回 in_trip=False 及相应提示，不报错。

    Args:
        plan: 访问校验通过的行程计划。
        session: 数据库会话。

    Returns:
        StandardResponse: 当日视图数据。
    """
    revision = await MemoryService().get_current_revision(session, plan.id)
    plan_data = _load_plan_data(plan, revision.trip_plan_json if revision else None)
    if not plan_data:
        return StandardResponse(success=True, message="行程尚未生成", data={"in_trip": False})

    day_plans = plan_data.get("day_plans", []) or []
    today_str = datetime.now().strftime("%Y-%m-%d")
    start_str = plan_data.get("start_date") or plan.start_date
    end_str = plan_data.get("end_date") or plan.end_date

    today_plan = next((d for d in day_plans if d.get("date") == today_str), None)
    in_trip = today_plan is not None

    # 计算行前/行后语义信息
    days_until_start = None
    days_after_end = None
    if not in_trip:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            delta = (datetime.strptime(today_str, "%Y-%m-%d") - start_dt).days
            if delta < 0:
                days_until_start = -delta
            else:
                days_after_end = delta
        except ValueError:
            pass

    # 已打卡地点名称集合，用于标记当日各项打卡状态
    result = await session.execute(
        select(TripCheckin).where(TripCheckin.plan_id == plan.id)
    )
    checked_names = {c.spot_name for c in result.scalars().all()}

    def _with_checkin(spot: dict, spot_type: str) -> dict:
        return {
            **spot,
            "spot_type": spot_type,
            "checked_in": spot.get("name") in checked_names,
        }

    day_payload = None
    if today_plan is not None:
        day_payload = {
            "day_index": today_plan.get("day_index"),
            "date": today_plan.get("date"),
            "city": today_plan.get("city") or plan_data.get("city"),
            "description": today_plan.get("description"),
            "intercity_note": today_plan.get("intercity_note"),
            "attractions": [
                _with_checkin(a, "attraction") for a in today_plan.get("attractions", [])
            ],
            "meals": [_with_checkin(m, "meal") for m in today_plan.get("meals", [])],
            "hotel": (
                _with_checkin(today_plan["hotel"], "hotel") if today_plan.get("hotel") else None
            ),
        }

    # 当日天气（行中才查，失败不阻塞视图）
    weather = None
    if in_trip:
        try:
            raw_weather = await get_weather(day_payload.get("city") or plan.city)
            weather = _pick_today_weather(raw_weather)
        except Exception:
            weather = None

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "in_trip": in_trip,
            "today_plan": day_payload,
            "weather": weather,
            "days_until_start": days_until_start,
            "days_after_end": days_after_end,
            "plan_city": plan_data.get("city") or plan.city,
            "start_date": start_str,
            "end_date": end_str,
        },
    )


@router.get("/{plan_id}/nearby", response_model=StandardResponse)
async def search_nearby(
    longitude: float = Query(..., description="中心点经度"),
    latitude: float = Query(..., description="中心点纬度"),
    type: str = Query(
        default="restaurant", description="类型：restaurant/cafe/toilet 或自定义关键词"
    ),
    radius: int = Query(default=1000, ge=100, le=50000, description="搜索半径（米）"),
    plan: TripPlanDB = Depends(get_accessible_plan),
):
    """
    附近推荐：代理高德周边搜索（place/around），按距离升序。

    Args:
        longitude: 中心点经度（打卡点或当日景点坐标）。
        latitude: 中心点纬度。
        type: 搜索类型，restaurant/cafe/toilet 快捷映射，其他值透传为关键词。
        radius: 搜索半径（米）。
        plan: 访问校验通过的行程计划。

    Returns:
        StandardResponse: POI 列表。
    """
    keywords = _NEARBY_TYPE_KEYWORDS.get(type, type)
    service = AmapService()
    pois = await service.search_nearby(
        longitude=longitude, latitude=latitude, keywords=keywords, radius=radius, page_size=10
    )
    return StandardResponse(success=True, message="获取成功", data={"type": type, "pois": pois})
