"""个性化目的地推荐：多来源打分 + RAG 补充必去景点。"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.db_models import (
    Favorite,
    TripPlanDB,
    User,
    UserMemory,
)
from app.models.schemas import (
    StandardResponse,
)

router = APIRouter()


def _score_recommendation_cities(
    favorite_cities: list[str],
    memory_cities: list[str],
    history_cities: list[str],
    knowledge_cities: list[str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """
    纯函数：多来源加权打分，返回 [(city, 统计信息)]，按分数降序排列。

    权重：收藏 +2（列表按最近优先排序，仅影响同分顺序）、正向记忆 +2、
    已完成行程 +1、知识库收录 +1。
    统计信息含各来源计数与首次出现顺序，供路由层生成 reason / source。
    排序规则：分数降序 → 主来源优先级（favorites/memory/history/knowledge）→ 首现顺序。
    """
    stats: dict[str, dict[str, Any]] = {}

    def _add(city: str, source: str, weight: int) -> None:
        if not city:
            return
        if city not in stats:
            stats[city] = {
                "score": 0,
                "favorites": 0,
                "memory": 0,
                "history": 0,
                "knowledge": 0,
                "first_seen": len(stats),
            }
        stats[city]["score"] += weight
        stats[city][source] += 1

    for city in favorite_cities:
        _add(city, "favorites", 2)
    for city in memory_cities:
        _add(city, "memory", 2)
    for city in history_cities:
        _add(city, "history", 1)
    for city in knowledge_cities or []:
        _add(city, "knowledge", 1)

    source_priority = {"favorites": 0, "memory": 1, "history": 2, "knowledge": 3}

    def _dominant_source(info: dict[str, Any]) -> str:
        """取计数最多的来源（并列时取优先级更高的）。"""
        return min(
            (s for s in source_priority if info[s] > 0),
            key=lambda s: (-info[s], source_priority[s]),
        )

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, int, int]:
        _, info = item
        return (-info["score"], source_priority[_dominant_source(info)], info["first_seen"])

    return sorted(stats.items(), key=_sort_key)


def _build_recommendation_reason(info: dict[str, Any]) -> tuple[str, str]:
    """
    纯函数：根据来源计数生成推荐理由与来源标识。

    Returns:
        Tuple[str, str]: (reason, source)，source 取值 favorites/memory/history/knowledge。
    """
    if info["favorites"] > 0:
        return f"你收藏过该城市的{info['favorites']}个地点", "favorites"
    if info["memory"] > 0:
        return f"你有{info['memory']}条关于该城市的美好记忆", "memory"
    if info["history"] > 0:
        return f"你有过{info['history']}次该城市的行程", "history"
    return "知识库收录了该城市的旅行攻略", "knowledge"


async def _collect_knowledge_cities() -> list[str]:
    """
    从 Qdrant 知识库聚合已收录的城市列表。

    RAG 不可用（连接失败/嵌入模型缺失等）时返回空列表并跳过该来源，绝不抛异常。
    """
    try:
        from app.services.rag_service import get_rag_service

        service = get_rag_service()

        def _scroll_cities() -> list[str]:
            """同步执行 Qdrant scroll，提取 payload 中的去重城市列表。"""
            service._ensure_collection()
            points, _ = service.client.scroll(
                service.collection_name, limit=256, with_payload=True, with_vectors=False
            )
            cities: list[str] = []
            for point in points or []:
                city = (point.payload or {}).get("city")
                if city and city not in cities:
                    cities.append(city)
            return cities

        return await asyncio.to_thread(_scroll_cities)
    except Exception as exc:
        logger.warning(f"[Recommend] 知识库城市聚合失败，跳过该来源: {exc}")
        return []


@router.get("/recommendations", response_model=StandardResponse)
async def get_recommendations(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
):
    """
    个性化城市推荐（不使用 LLM）。

    候选城市来源与权重：收藏(+2)、正向记忆(+2)、已完成行程(+1)、知识库收录(+1)；
    打分取 Top 5，并对前 3 项用 RAG 检索补充该城必去景点标题（失败则省略 spots）。

    Returns:
        StandardResponse: data = {"items": [{city, reason, source, spots?}]}；
        空结果也是 success=True。
    """
    # ==================== 步骤 1：收集各来源城市 ====================
    fav_result = await session.execute(
        select(Favorite.city)
        .where(Favorite.user_id == current_user.id, Favorite.city.is_not(None))
        .order_by(Favorite.created_at.desc())
    )
    favorite_cities = [row[0] for row in fav_result if row[0]]

    mem_result = await session.execute(
        select(UserMemory.city)
        .where(
            UserMemory.user_id == current_user.id,
            UserMemory.sentiment == "positive",
            UserMemory.city.is_not(None),
        )
        .order_by(UserMemory.created_at.desc())
    )
    memory_cities = [row[0] for row in mem_result if row[0]]

    hist_result = await session.execute(
        select(TripPlanDB.city).where(
            TripPlanDB.user_id == current_user.id, TripPlanDB.status == "completed"
        )
    )
    history_cities = [row[0] for row in hist_result if row[0]]

    knowledge_cities = await _collect_knowledge_cities()

    # ==================== 步骤 2：加权打分取 Top 5 ====================
    scored = _score_recommendation_cities(
        favorite_cities, memory_cities, history_cities, knowledge_cities
    )
    items: list[dict[str, Any]] = []
    for city, info in scored[:5]:
        reason, source = _build_recommendation_reason(info)
        items.append({"city": city, "reason": reason, "source": source})

    # ==================== 步骤 3：Top 3 补充 RAG 必去景点（失败省略 spots） ====================
    if items:
        try:
            from app.services.rag_service import get_rag_service

            rag = get_rag_service()
            for item in items[:3]:
                try:
                    results = await asyncio.to_thread(
                        rag.search, query=f"{item['city']} 必去景点推荐", city=item["city"], top_k=3
                    )
                    titles = [r.get("title") for r in results if r.get("title")]
                    if titles:
                        item["spots"] = titles
                except Exception as exc:
                    logger.warning(f"[Recommend] {item['city']} 景点检索失败，省略 spots: {exc}")
        except Exception as exc:
            logger.warning(f"[Recommend] RAG 服务不可用，全部省略 spots: {exc}")

    return StandardResponse(success=True, message="获取成功", data={"items": items})
