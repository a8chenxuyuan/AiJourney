"""
backend/app/api/routes/poi.py

POI 详情与图片路由模块。

作用：
- 提供 POI 详情查询接口；
- 提供景点图片搜索接口；
- 当前为占位实现，后续可接入高德 POI 详情和 Unsplash/Bing 图片搜索。

对应技术：
- FastAPI：APIRouter、Depends、Query
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.models.db_models import User
from app.models.schemas import StandardResponse


router = APIRouter()


@router.get("/{poi_id}", response_model=StandardResponse)
async def get_poi_detail(
    poi_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    查询 POI 详情。

    Args:
        poi_id: POI 唯一标识。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: POI 详情。
    """
    # TODO: 接入真实 POI 详情查询
    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "id": poi_id,
            "name": "示例景点",
            "address": "示例地址",
            "description": "这是一个示例景点描述。",
            "rating": 4.5,
            "ticket_price": 50.0
        }
    )


@router.get("/photo", response_model=StandardResponse)
async def get_poi_photos(
    keyword: str = Query(..., description="搜索关键词"),
    page_size: int = Query(5, ge=1, le=20, description="返回数量"),
    current_user: User = Depends(get_current_user)
):
    """
    景点图片搜索接口。

    Args:
        keyword: 搜索关键词。
        page_size: 返回图片数量。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: 图片 URL 列表。
    """
    # TODO: 接入真实图片搜索服务
    return StandardResponse(
        success=True,
        message="获取成功",
        data=[
            {"url": f"https://example.com/photo_{i}.jpg", "source": "mock"}
            for i in range(page_size)
        ]
    )
