"""
backend/app/api/routes/map.py

地图相关路由模块。

作用：
- 提供 POI 搜索、天气查询、路线规划等地图服务接口；
- 调用 AmapService 获取高德地图数据。

对应技术：
- FastAPI：APIRouter、Depends、Query
- MCP：高德地图服务
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.models.db_models import User
from app.models.schemas import StandardResponse
from app.services.amap_service import AmapService

router = APIRouter()


def _get_amap_service() -> AmapService:
    """
    获取 AmapService 实例。

    Returns:
        AmapService: 高德地图服务实例。
    """
    return AmapService()


@router.get("/poi", response_model=StandardResponse)
async def search_poi(
    keyword: str = Query(..., description="搜索关键词"),
    city: str = Query(..., description="城市名称"),
    page_size: int = Query(10, ge=1, le=50, description="返回数量"),
    current_user: User = Depends(get_current_user),
):
    """
    POI 搜索接口。

    Args:
        keyword: 搜索关键词。
        city: 城市名称。
        page_size: 返回结果数量。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: POI 列表。
    """
    service = _get_amap_service()
    pois = await service.search_poi(keyword, city, page_size)

    return StandardResponse(success=True, message="搜索成功", data=pois)


@router.get("/weather", response_model=StandardResponse)
async def get_weather(
    city: str = Query(..., description="城市名称"), current_user: User = Depends(get_current_user)
):
    """
    天气查询接口。

    Args:
        city: 城市名称。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: 天气信息。
    """
    service = _get_amap_service()
    weather = await service.get_weather(city)

    return StandardResponse(success=True, message="查询成功", data=weather)


@router.post("/route", response_model=StandardResponse)
async def plan_route(
    origin: str = Query(..., description="起点"),
    destination: str = Query(..., description="终点"),
    mode: str = Query("driving", description="交通方式"),
    current_user: User = Depends(get_current_user),
):
    """
    路线规划接口。

    Args:
        origin: 起点地址或坐标。
        destination: 终点地址或坐标。
        mode: 交通方式。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: 路线信息。
    """
    service = _get_amap_service()
    route = await service.plan_route(origin, destination, mode)

    return StandardResponse(success=True, message="规划成功", data=route)
