"""
backend/app/api/routes/trip 包

旅行规划路由，按功能域拆分：

- plans.py：创建行程、分享链接、我的行程列表
- favorites.py：收藏管理
- notifications.py：站内通知
- recommendations.py：个性化目的地推荐
- plan_detail.py：单条行程查询/删除（/{plan_id} 动态路由）
- revisions.py：单日重算、整单重新生成、版本列表
- feedback.py：行程反馈
- chat.py：对话式修改助手

include 顺序即路由注册顺序：单段固定路径（/favorites、/my/list 等）
必须先于 /{plan_id} 动态路由注册，否则会被误解析为 plan_id。

【对应技术】
- FastAPI：APIRouter、Depends
- LangGraph：Agent 执行
- SQLAlchemy：行程数据持久化
"""

from fastapi import APIRouter

from app.api.routes.trip import (
    chat,
    favorites,
    feedback,
    notifications,
    plan_detail,
    plans,
    recommendations,
    revisions,
)
from app.api.routes.trip.plans import _calculate_days
from app.api.routes.trip.recommendations import _score_recommendation_cities

router = APIRouter()
router.include_router(plans.router)
router.include_router(favorites.router)
router.include_router(notifications.router)
router.include_router(recommendations.router)
router.include_router(plan_detail.router)
router.include_router(revisions.router)
router.include_router(feedback.router)
router.include_router(chat.router)

# 兼容既有引用（tests/test_units.py 直接从包根导入这两个私有符号）
__all__ = ["_calculate_days", "_score_recommendation_cities", "router"]
