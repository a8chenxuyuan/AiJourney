"""
backend/app/api/routes/trip.py

旅行规划路由模块。

作用：
- 提供创建规划、查询规划结果、调整景点后重算、提交反馈等接口；
- 调用 Agent 层完成核心规划逻辑；
- 将规划结果持久化到数据库。

对应技术：
- FastAPI：APIRouter、Depends
- LangGraph：Agent 执行
- SQLAlchemy：行程数据持久化
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import get_current_user, get_owned_plan, get_accessible_plan
from app.models.db_models import (
    PlanNotification,
    PlanCollaborator,
    PlanInvite,
    PlanLogDB,
    TripPlanDB,
    User,
    UserMemory,
    PlanFeedback,
    PlanRevision,
    Favorite
)
from app.models.schemas import (
    TripRequest,
    TripPlan,
    TripPlanResponse,
    StandardResponse,
    RecalculateRequest,
    UserFeedback,
    PlanFeedbackRequest,
    PlanFeedbackResponse,
    PlanChatRequest,
    PlanChatMessage,
    RevisionSummary,
    FeedbackRecord,
    StructuredFeedback,
    ShareCreateRequest,
    ShareInfo,
    FavoriteCreateRequest,
    FavoriteOut,
)
from app.utils.queue import enqueue_planning_task, enqueue_revision_task, enqueue_recalculate_task
from app.services.memory_service import MemoryService
from app.services.llm_service import get_llm


router = APIRouter()


def _calculate_days(start_date: str, end_date: str) -> int:
    """
    计算旅行天数（包含起止日期）。

    Args:
        start_date: 开始日期字符串。
        end_date: 结束日期字符串。

    Returns:
        int: 旅行天数。
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return (end - start).days + 1


@router.post("/plan", response_model=StandardResponse)
async def create_plan(
    request: TripRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    创建旅行规划任务。

    流程：
    1. 生成唯一 plan_id；
    2. 在数据库中创建 pending 状态的行程记录；
    3. 把规划任务投递到 Redis 队列（ARQ），由 Worker 进程异步执行；
    4. 立即返回 plan_id，前端通过 SSE 监听进度。

    Args:
        request: 旅行规划请求。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 包含 plan_id 和初始状态。
    """
    plan_id = f"PLAN_{uuid.uuid4().hex[:16].upper()}"
    travel_days = _calculate_days(request.start_date, request.end_date)

    # 创建数据库记录
    db_plan = TripPlanDB(
        id=plan_id,
        user_id=current_user.id,
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        travel_days=travel_days,
        request_data=request.model_dump(mode="json"),
        status="pending"
    )
    session.add(db_plan)
    await session.flush()
    # 立即提交，确保后台任务能读取到 pending 记录
    await session.commit()

    # 投递到 Redis 队列，由 ARQ Worker 进程异步执行，实现 API 与任务执行解耦
    await enqueue_planning_task(
        plan_id=plan_id,
        request=request.model_dump(mode="json"),
        user_id=current_user.id
    )

    return StandardResponse(
        success=True,
        message="规划任务已创建",
        data=TripPlanResponse(plan_id=plan_id, status="pending").model_dump()
    )


# ==================== 行程分享 ====================
# 注意：以下静态路径路由（/share/xxx、/favorites）必须注册在 "/{plan_id}" 动态路由之前，
# 否则 FastAPI 会把 share/favorites 误匹配为 plan_id。


@router.get("/share/{token}", response_model=StandardResponse)
async def get_shared_plan(
    token: str,
    session: AsyncSession = Depends(get_db)
):
    """
    通过分享令牌公开查看行程（无需登录）。

    流程：
    1. 按 token 查询行程；令牌不存在或已关闭分享返回 404；
    2. 校验过期时间，过期返回 410；
    3. 返回行程只读数据（与 GET /{plan_id} 的 plan 结构一致，但不含反馈等私有信息）。

    Args:
        token: 分享令牌。
        session: 数据库会话。

    Returns:
        StandardResponse: 行程只读数据。
    """
    result = await session.execute(
        select(TripPlanDB).where(TripPlanDB.share_token == token)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="分享链接不存在或已被关闭")
    if plan.share_expires_at is not None and plan.share_expires_at < datetime.now():
        raise HTTPException(status_code=410, detail="分享链接已过期")

    # 累计分享页访问次数（供行程所有者查看传播效果）
    plan.share_view_count = (plan.share_view_count or 0) + 1
    await session.commit()

    # 只读数据同样优先返回当前生效的 revision 版本
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan.id)
    plan_data = current_revision.trip_plan_json if current_revision else plan.plan_data

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "plan_id": plan.id,
            "status": plan.status,
            "city": plan.city,
            "version": current_revision.version if current_revision else None,
            "plan": plan_data
        }
    )


@router.post("/{plan_id}/share", response_model=StandardResponse)
async def create_share(
    plan_id: str,
    share_request: ShareCreateRequest,
    plan: TripPlanDB = Depends(get_owned_plan),
    session: AsyncSession = Depends(get_db)
):
    """
    开启行程分享：为行程生成（或复用）分享令牌。

    若行程已存在未过期的分享令牌则直接复用，避免每次点击都换链接。

    Args:
        plan_id: 行程计划 ID。
        share_request: 分享有效期配置。
        plan: 归属校验通过的行程计划。
        session: 数据库会话。

    Returns:
        StandardResponse: 分享信息（token 与前端路由路径）。
    """
    now = datetime.now()
    # 已有令牌且未过期 → 直接复用
    if plan.share_token and (plan.share_expires_at is None or plan.share_expires_at > now):
        token = plan.share_token
        expires_at = plan.share_expires_at
    else:
        token = uuid.uuid4().hex
        expires_at = now + timedelta(days=share_request.expires_days)
        plan.share_token = token
        plan.share_expires_at = expires_at
        await session.commit()
        logger.info(f"[分享] 行程 {plan.id} 开启分享，有效期至 {expires_at}")

    return StandardResponse(
        success=True,
        message="分享已开启",
        data=ShareInfo(
            plan_id=plan.id,
            share_token=token,
            share_path=f"/share/{token}",
            expires_at=expires_at.isoformat() if expires_at else None,
            share_view_count=plan.share_view_count or 0
        ).model_dump()
    )


@router.delete("/{plan_id}/share", response_model=StandardResponse)
async def close_share(
    plan: TripPlanDB = Depends(get_owned_plan),
    session: AsyncSession = Depends(get_db)
):
    """
    关闭行程分享：清空分享令牌，原链接立即失效。

    Args:
        plan: 归属校验通过的行程计划。
        session: 数据库会话。

    Returns:
        StandardResponse: 操作结果。
    """
    plan.share_token = None
    plan.share_expires_at = None
    await session.commit()
    logger.info(f"[分享] 行程 {plan.id} 已关闭分享")
    return StandardResponse(success=True, message="分享已关闭", data=None)


# ==================== 收藏与复购 ====================


@router.post("/favorites", response_model=StandardResponse)
async def add_favorite(
    fav_request: FavoriteCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
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
            Favorite.user_id == current_user.id,
            Favorite.item_id == fav_request.item_id
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
                created_at=existing.created_at.isoformat() if existing.created_at else None
            ).model_dump()
        )

    favorite = Favorite(
        user_id=current_user.id,
        city=fav_request.city,
        item_type=fav_request.item_type,
        item_id=fav_request.item_id,
        item_name=fav_request.item_name,
        item_data=fav_request.item_data
    )
    session.add(favorite)
    await session.commit()
    await session.refresh(favorite)
    logger.info(f"[收藏] 用户 {current_user.id} 收藏 {fav_request.item_type} {fav_request.item_name}")

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
            created_at=favorite.created_at.isoformat() if favorite.created_at else None
        ).model_dump()
    )


@router.get("/favorites", response_model=StandardResponse)
async def list_favorites(
    city: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
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
                    created_at=f.created_at.isoformat() if f.created_at else None
                ).model_dump()
                for f in favorites
            ]
        }
    )


@router.get("/favorites/cities", response_model=StandardResponse)
async def list_favorite_cities(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
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
        select(Favorite.city).where(
            Favorite.user_id == current_user.id,
            Favorite.city.is_not(None)
        ).order_by(Favorite.created_at.desc())
    )
    # 按收藏时间倒序去重，保留最近收藏的城市优先
    cities: List[str] = []
    for (city,) in result.all():
        if city and city not in cities:
            cities.append(city)

    return StandardResponse(success=True, message="获取成功", data={"cities": cities})


@router.delete("/favorites/{favorite_id}", response_model=StandardResponse)
async def remove_favorite(
    favorite_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
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
        select(Favorite).where(
            Favorite.id == favorite_id,
            Favorite.user_id == current_user.id
        )
    )
    favorite = result.scalar_one_or_none()
    if favorite is None:
        raise HTTPException(status_code=404, detail="收藏记录不存在")

    await session.delete(favorite)
    await session.commit()
    return StandardResponse(success=True, message="已取消收藏", data=None)


# ==================== 站内通知（出发前天气提醒等） ====================
# 注意：以下静态路径必须注册在 GET /{plan_id} 动态路由之前，避免被误匹配为 plan_id。


@router.get("/notifications", response_model=StandardResponse)
async def list_notifications(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    获取当前用户的站内通知列表（created_at 倒序，限 50 条）与未读数。

    Returns:
        StandardResponse: data = {"notifications": [...], "unread_count": n}。
    """
    result = await session.execute(
        select(PlanNotification)
        .where(PlanNotification.user_id == current_user.id)
        .order_by(PlanNotification.created_at.desc())
        .limit(50)
    )
    unread_result = await session.execute(
        select(func.count())
        .select_from(PlanNotification)
        .where(PlanNotification.user_id == current_user.id, PlanNotification.is_read == False)  # noqa: E712
    )
    notifications = [
        {
            "id": item.id,
            "type": item.type,
            "title": item.title,
            "content": item.content,
            "is_read": bool(item.is_read),
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in result.scalars().all()
    ]
    return StandardResponse(
        success=True,
        message="获取成功",
        data={"notifications": notifications, "unread_count": int(unread_result.scalar() or 0)}
    )


@router.post("/notifications/read-all", response_model=StandardResponse)
async def read_all_notifications(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    把当前用户的全部未读通知标记为已读。

    Returns:
        StandardResponse: data = {"marked": n}（本次标记的条数）。
    """
    result = await session.execute(
        update(PlanNotification)
        .where(PlanNotification.user_id == current_user.id, PlanNotification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await session.commit()
    return StandardResponse(success=True, message="已全部标记为已读", data={"marked": result.rowcount or 0})


# ==================== 个性化推荐 ====================


def _score_recommendation_cities(
    favorite_cities: List[str],
    memory_cities: List[str],
    history_cities: List[str],
    knowledge_cities: Optional[List[str]] = None
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    纯函数：多来源加权打分，返回 [(city, 统计信息)]，按分数降序排列。

    权重：收藏 +2（列表按最近优先排序，仅影响同分顺序）、正向记忆 +2、
    已完成行程 +1、知识库收录 +1。
    统计信息含各来源计数与首次出现顺序，供路由层生成 reason / source。
    排序规则：分数降序 → 主来源优先级（favorites/memory/history/knowledge）→ 首现顺序。
    """
    stats: Dict[str, Dict[str, Any]] = {}

    def _add(city: str, source: str, weight: int) -> None:
        if not city:
            return
        if city not in stats:
            stats[city] = {
                "score": 0, "favorites": 0, "memory": 0,
                "history": 0, "knowledge": 0, "first_seen": len(stats)
            }
        stats[city]["score"] += weight
        stats[city][source] += 1

    for city in favorite_cities:
        _add(city, "favorites", 2)
    for city in memory_cities:
        _add(city, "memory", 2)
    for city in history_cities:
        _add(city, "history", 1)
    for city in (knowledge_cities or []):
        _add(city, "knowledge", 1)

    source_priority = {"favorites": 0, "memory": 1, "history": 2, "knowledge": 3}

    def _dominant_source(info: Dict[str, Any]) -> str:
        """取计数最多的来源（并列时取优先级更高的）。"""
        return min(
            (s for s in source_priority if info[s] > 0),
            key=lambda s: (-info[s], source_priority[s])
        )

    def _sort_key(item: Tuple[str, Dict[str, Any]]) -> Tuple[int, int, int]:
        city, info = item
        return (-info["score"], source_priority[_dominant_source(info)], info["first_seen"])

    return sorted(stats.items(), key=_sort_key)


def _build_recommendation_reason(info: Dict[str, Any]) -> Tuple[str, str]:
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


async def _collect_knowledge_cities() -> List[str]:
    """
    从 Qdrant 知识库聚合已收录的城市列表。

    RAG 不可用（连接失败/嵌入模型缺失等）时返回空列表并跳过该来源，绝不抛异常。
    """
    try:
        from app.services.rag_service import get_rag_service
        service = get_rag_service()

        def _scroll_cities() -> List[str]:
            """同步执行 Qdrant scroll，提取 payload 中的去重城市列表。"""
            service._ensure_collection()
            points, _ = service.client.scroll(
                service.collection_name,
                limit=256,
                with_payload=True,
                with_vectors=False
            )
            cities: List[str] = []
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
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    个性化城市推荐（不使用 LLM）。

    候选城市来源与权重：收藏(+2)、正向记忆(+2)、已完成行程(+1)、知识库收录(+1)；
    打分取 Top 5，并对前 3 项用 RAG 检索补充该城必去景点标题（失败则省略 spots）。

    Returns:
        StandardResponse: data = {"items": [{city, reason, source, spots?}]}；空结果也是 success=True。
    """
    # ==================== 步骤 1：收集各来源城市 ====================
    fav_result = await session.execute(
        select(Favorite.city)
        .where(Favorite.user_id == current_user.id, Favorite.city.is_not(None))
        .order_by(Favorite.created_at.desc())
    )
    favorite_cities = [row[0] for row in fav_result if row[0]]

    mem_result = await session.execute(
        select(UserMemory.city).where(
            UserMemory.user_id == current_user.id,
            UserMemory.sentiment == "positive",
            UserMemory.city.is_not(None)
        ).order_by(UserMemory.created_at.desc())
    )
    memory_cities = [row[0] for row in mem_result if row[0]]

    hist_result = await session.execute(
        select(TripPlanDB.city).where(
            TripPlanDB.user_id == current_user.id,
            TripPlanDB.status == "completed"
        )
    )
    history_cities = [row[0] for row in hist_result if row[0]]

    knowledge_cities = await _collect_knowledge_cities()

    # ==================== 步骤 2：加权打分取 Top 5 ====================
    scored = _score_recommendation_cities(favorite_cities, memory_cities, history_cities, knowledge_cities)
    items: List[Dict[str, Any]] = []
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
                        rag.search,
                        query=f"{item['city']} 必去景点推荐",
                        city=item["city"],
                        top_k=3
                    )
                    titles = [r.get("title") for r in results if r.get("title")]
                    if titles:
                        item["spots"] = titles
                except Exception as exc:
                    logger.warning(f"[Recommend] {item['city']} 景点检索失败，省略 spots: {exc}")
        except Exception as exc:
            logger.warning(f"[Recommend] RAG 服务不可用，全部省略 spots: {exc}")

    return StandardResponse(success=True, message="获取成功", data={"items": items})


@router.get("/{plan_id}", response_model=StandardResponse)
async def get_plan(
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    查询指定行程计划的当前结果（所有者或协作者均可）。

    Args:
        plan: 访问校验通过的行程计划（get_accessible_plan 依赖注入）。
        current_user: 当前登录用户（用于计算 is_owner，前端据此区分协作权限）。
        session: 数据库会话。

    Returns:
        StandardResponse: 行程计划数据（含 is_owner 标识）。
    """
    # 优先返回当前生效的 revision 版本
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan.id)
    plan_data = current_revision.trip_plan_json if current_revision else plan.plan_data
    # 同时把当前版本的 diff_summary 透出，前端 Result.vue 可展示"本次重新生成修改了 N 处"
    diff_summary = current_revision.diff_summary if current_revision else None

    # 调试日志：记录每次 fetchPlan 的响应版本
    logger.debug(f"[GET /api/trip/{plan.id}] returning version={current_revision.version if current_revision else None}, diff_total={(diff_summary or {}).get('total_changes') if diff_summary else 0}")

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "plan_id": plan.id,
            "status": plan.status,
            "revision_id": current_revision.id if current_revision else None,
            "version": current_revision.version if current_revision else None,
            "diff_summary": diff_summary,
            "plan": plan_data,
            # 是否为行程所有者：决定前端能否展示分享/删除/邀请管理等 owner 专属操作
            "is_owner": plan.user_id == current_user.id
        }
    )


@router.delete("/{plan_id}", response_model=StandardResponse)
async def delete_plan(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    删除行程计划（仅所有者）。

    权限语义：
    - 所有者：删除行程及其版本/反馈/协作成员/邀请令牌/日志/通知等关联数据；
    - 协作者：知道行程存在，返回 403 明确"无权删除"；
    - 无关用户：沿用现有归属校验语义返回 404，不泄露行程存在性。

    Args:
        plan_id: 行程计划 ID。
        plan: 访问校验通过的行程计划（get_accessible_plan 依赖注入）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 操作结果。
    """
    # 删除是 owner 专属操作：协作者通过可访问校验后，在此处被 403 拦截
    if plan.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅行程所有者可以删除行程"
        )

    # 先显式清理以 plan_id 关联的子表数据（不走 ORM 级联，行为更可控），
    # 再删除行程本身
    await session.execute(delete(PlanRevision).where(PlanRevision.plan_id == plan_id))
    await session.execute(delete(PlanFeedback).where(PlanFeedback.plan_id == plan_id))
    await session.execute(delete(PlanCollaborator).where(PlanCollaborator.plan_id == plan_id))
    await session.execute(delete(PlanInvite).where(PlanInvite.plan_id == plan_id))
    await session.execute(delete(PlanLogDB).where(PlanLogDB.plan_id == plan_id))
    await session.execute(delete(PlanNotification).where(PlanNotification.plan_id == plan_id))
    await session.delete(plan)
    await session.commit()
    logger.info(f"[行程] 行程 {plan_id} 已被所有者 {current_user.id} 删除")

    return StandardResponse(
        success=True,
        message="行程已删除",
        data={"plan_id": plan_id}
    )


@router.post("/{plan_id}/recalculate", response_model=StandardResponse)
async def recalculate_plan(
    recalc_request: RecalculateRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    用户调整某天景点顺序后重新规划路线和行程。

    流程：
    1. 校验行程已完成、非修订中、非多城联游（多城重算暂不支持）；
    2. 加载当前生效版本，把目标天的景点按 attraction_ids 重排
       （未提及的景点按原相对顺序追加在末尾）；
    3. 把重算任务投递到 Redis 队列（ARQ），Worker 只重跑
       RouteAgent（重算当天路线矩阵）+ PlannerAgent（按新顺序重排行程），
       不重新收集信息，是成本最低的 Agent 重执行路径；
    4. 立即返回，后台异步生成新版本，前端轮询 GET /{plan_id} 获取结果。

    Args:
        recalc_request: 重算请求（day_index + 调整后的景点 ID 顺序）。
        plan: 访问校验通过的行程计划（get_accessible_plan 依赖注入）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 重算任务受理结果。
    """
    # 行程必须是已完成状态才能重算（修订中防并发，其余状态没有可重算的版本）
    if plan.status == "revising":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程正在修订中，请等待当前任务完成"
        )
    if plan.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"行程当前状态为 {plan.status}，仅已完成的行程支持重算"
        )

    # 多城联游行程的重排需要按城市分段处理，暂不支持
    if plan.cities_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="多城联游行程暂不支持手动排序重算"
        )

    if not recalc_request.attraction_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="attraction_ids 不能为空"
        )

    # 加载当前生效版本作为重算基底
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan.id)
    if not current_revision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到当前生效的行程版本"
        )
    previous_plan = TripPlan(**current_revision.trip_plan_json)

    # 定位目标天
    target_day = next(
        (d for d in previous_plan.day_plans if d.day_index == recalc_request.day_index),
        None
    )
    if target_day is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"第 {recalc_request.day_index} 天不存在（行程共 {len(previous_plan.day_plans)} 天）"
        )
    if not target_day.attractions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"第 {recalc_request.day_index} 天没有景点，无法重排"
        )

    # 按用户提交的 ID 顺序重排（id 缺失时按名称兜底匹配）
    attr_by_id = {a.id: a for a in target_day.attractions if a.id}
    attr_by_name = {a.name: a for a in target_day.attractions if not a.id}
    matched = []
    matched_keys = set()
    for key in recalc_request.attraction_ids:
        attraction = attr_by_id.get(key) or attr_by_name.get(key)
        if attraction is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"景点 {key} 不在第 {recalc_request.day_index} 天的行程中"
            )
        obj_key = id(attraction)
        if obj_key in matched_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"景点 {key} 重复出现"
            )
        matched_keys.add(obj_key)
        matched.append(attraction)
    # 未提及的景点按原相对顺序追加在末尾，保证不丢景点
    remaining = [a for a in target_day.attractions if id(a) not in matched_keys]
    target_day.attractions = matched + remaining

    # 重算说明：明确要求 planner 严格保持新顺序，只调整衔接
    ordered_names = " → ".join(a.name for a in target_day.attractions)
    revision_notes = (
        f"用户手动调整了第{recalc_request.day_index}天的景点游览顺序，"
        f"新顺序为：{ordered_names}。请严格保持该顺序不变，"
        f"重新安排当天各景点间的交通衔接与餐饮安排，其余天数保持原行程不变。"
    )

    # 投递重算任务（previous_plan 已含重排后的目标天），由 Worker 执行 RouteAgent + PlannerAgent
    # 老数据可能没有 request_data，此时用行程列兜底构造最小请求
    request_data = plan.request_data or {
        "city": plan.city,
        "start_date": plan.start_date,
        "end_date": plan.end_date
    }
    await enqueue_recalculate_task(
        plan_id=plan.id,
        request=request_data,
        user_id=current_user.id,
        parent_revision_id=current_revision.id,
        previous_plan=previous_plan.model_dump(mode="json"),
        revision_notes=revision_notes,
        day_attractions=[a.model_dump(mode="json") for a in target_day.attractions]
    )
    logger.info(f"[重算] 行程 {plan.id} 第 {recalc_request.day_index} 天重排重算任务已入队，"
                f"新顺序：{ordered_names}")

    return StandardResponse(
        success=True,
        message="重算请求已提交，正在重新规划路线和行程",
        data={
            "plan_id": plan.id,
            "status": "revising",
            "day_index": recalc_request.day_index,
            "attraction_count": len(target_day.attractions)
        }
    )


@router.post("/{plan_id}/feedback", response_model=StandardResponse)
async def submit_plan_feedback(
    plan_id: str,
    feedback: PlanFeedbackRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    提交用户对行程计划的修改反馈。

    流程：
    1. 校验行程计划存在且属于当前用户；
    2. 获取当前生效版本作为父版本；
    3. 创建 PlanFeedback 记录；
    4. 立即返回 feedback_id（不立即触发后台任务）。

    任务触发时机：
    - 提交本接口只把意见写入数据库，不立即跑 Agent；
    - 等用户在前端点"基于所有反馈重新生成行程"按钮，由 /regenerate 统一触发；
    - 这样可以一次提交多条意见，避免反复被打断。

    Args:
        plan_id: 行程计划 ID。
        feedback: 行程修改反馈请求。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 包含 feedback_id。
    """
    # 行程必须在"已完成"状态才能接受反馈
    if plan.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程生成失败，请重新发起规划"
        )
    if plan.status == "revising":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程正在修订中，请等待当前任务完成后再提交反馈"
        )
    if plan.status not in ("completed", "revising"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"行程当前状态为 {plan.status}，无法提交反馈"
        )

    # 获取当前生效版本
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan_id)
    if not current_revision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到当前生效的行程版本"
        )

    # 创建反馈记录
    feedback_record = await memory_service.create_feedback(
        session=session,
        plan_id=plan_id,
        revision_id=current_revision.id,
        user_id=current_user.id,
        day_index=feedback.day_index,
        tags=feedback.tags,
        raw_text=feedback.raw_text
    )
    await session.commit()

    return StandardResponse(
        success=True,
        message="意见已保存，点'根据所有反馈重新生成行程'可统一处理",
        data=PlanFeedbackResponse(
            feedback_id=feedback_record.id,
            revision_id=current_revision.id,
            revision_type="pending",
            status="saved"
        ).model_dump()
    )


async def _load_regenerate_context(
    session: AsyncSession,
    plan_id: str
) -> Tuple[PlanRevision, str, List[PlanFeedback]]:
    """
    加载重新生成所需的上下文：当前生效版本 + 聚合后的有效反馈。

    Args:
        session: 数据库会话。
        plan_id: 行程计划 ID。

    Returns:
        Tuple[PlanRevision, str, List[PlanFeedback]]: (当前生效版本, 聚合修改意见, 有效反馈列表)。

    Raises:
        HTTPException: 无当前生效版本时 404；无有效反馈时 400。
    """
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan_id)
    if not current_revision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到当前生效的行程版本"
        )

    # 聚合所有未撤回、未被替代的有效反馈
    aggregated_notes, feedbacks = await memory_service.aggregate_active_feedbacks(session, plan_id)
    if not aggregated_notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="暂无有效反馈，无法重新生成"
        )

    return current_revision, aggregated_notes, feedbacks


def _build_revision_request(
    plan: TripPlanDB,
    current_revision: PlanRevision,
    aggregated_notes: str
) -> TripRequest:
    """
    反序列化原始规划请求，并注入本次重新生成的修改意见。

    原始请求缺失或损坏时，基于行程数据兜底构造。
    把聚合后的修改意见注入 free_text_input，
    让全流程（意图分析、候选搜索、Planner）都能感知。

    Args:
        plan: 行程计划记录。
        current_revision: 当前生效版本。
        aggregated_notes: 聚合后的修改意见文本。

    Returns:
        TripRequest: 注入修改意见后的规划请求。
    """
    request_data = plan.request_data or {}
    try:
        trip_request = TripRequest(**request_data)
    except Exception:
        plan_data = current_revision.trip_plan_json or {}
        trip_request = TripRequest(
            city=plan_data.get("city", plan.city),
            start_date=plan_data.get("start_date", plan.start_date),
            end_date=plan_data.get("end_date", plan.end_date),
            transportation="公共交通",
            accommodation="酒店"
        )

    revision_hint = f"【本次重新生成需要满足的修改意见】\n{aggregated_notes}"
    if trip_request.free_text_input:
        trip_request.free_text_input = f"{trip_request.free_text_input}\n\n{revision_hint}"
    else:
        trip_request.free_text_input = revision_hint
    return trip_request


def _build_full_feedback_constraint(
    feedbacks: List[PlanFeedback]
) -> Tuple[StructuredFeedback, List[str]]:
    """
    根据反馈列表构造"强制完整重排"的结构化约束。

    聚合反馈必须走完整重排（full），不允许 FeedbackExtractor 误判为 patch。

    Args:
        feedbacks: 有效反馈列表。

    Returns:
        Tuple[StructuredFeedback, List[str]]: (强制 full 的结构化约束, 反馈标签列表)。
    """
    # 收集反馈标签和受影响天数，用于强制走完整重排
    feedback_tag_set = set()
    affected_days = set()
    for fb in feedbacks:
        feedback_tag_set.update(fb.tags or [])
        if fb.day_index is not None:
            affected_days.add(fb.day_index)
    feedback_tags = list(feedback_tag_set) or ["aggregate"]

    force_full_feedback = StructuredFeedback(
        scope="whole",
        affected_days=sorted(affected_days),
        actions=[],
        preference_signals=[],
        complexity="full"
    )
    return force_full_feedback, feedback_tags


@router.post("/{plan_id}/regenerate", response_model=StandardResponse)
async def regenerate_plan(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    基于所有有效反馈重新生成完整行程。

    流程：
    1. 校验行程计划存在且属于当前用户；
    2. 聚合所有未撤回、未被替代的有效反馈；
    3. 把修订任务投递到 Redis 队列（ARQ），由 Worker 进程走完整重排（full）生成新版本；
    4. 立即返回，后台异步执行修订。

    职责拆分：
    - _load_regenerate_context：加载当前生效版本与聚合反馈；
    - _build_revision_request：构造注入修改意见的规划请求；
    - _build_full_feedback_constraint：构造强制完整重排约束。
    """
    # 同一 plan_id 只允许一个 revision 任务在跑：Worker 侧由进程内互斥锁兜底，
    # 接口侧通过 plan.status（任务开始后即变为 revising）拦截重复提交。
    if plan.status == "revising":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程正在修订中，请等待当前任务完成"
        )

    current_revision, aggregated_notes, feedbacks = await _load_regenerate_context(session, plan_id)

    trip_request = _build_revision_request(plan, current_revision, aggregated_notes)
    previous_plan = TripPlan(**current_revision.trip_plan_json)
    force_full_feedback, feedback_tags = _build_full_feedback_constraint(feedbacks)

    # 注意：不在这里把 status 改为 revising，改由 Worker 任务在进入锁之后立即设置，
    # 避免任务被锁拒绝时状态卡在 revising。

    # 投递修订任务到 Redis 队列，feedback_id 为 None 表示聚合反馈
    await enqueue_revision_task(
        plan_id=plan_id,
        request=trip_request.model_dump(mode="json"),
        user_id=current_user.id,
        parent_revision_id=current_revision.id,
        previous_plan=previous_plan.model_dump(mode="json"),
        revision_notes=aggregated_notes,
        feedback_id=None,
        feedback_day_index=None,
        feedback_tags=feedback_tags,
        structured_feedback=force_full_feedback.model_dump(mode="json"),
        source="regenerate"
    )

    return StandardResponse(
        success=True,
        message=f"已聚合 {len(feedbacks)} 条反馈，正在重新生成完整行程",
        data={
            "plan_id": plan_id,
            "feedback_count": len(feedbacks),
            "status": "revising"
        }
    )


@router.get("/{plan_id}/revisions", response_model=StandardResponse)
async def list_revisions(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db)
):
    """
    获取某行程计划的版本历史列表。
    """
    memory_service = MemoryService()
    revisions = await memory_service.get_revision_history(session, plan_id)

    # 防御性查询：单独拉取每个版本的反馈，避免依赖 ORM 关系懒加载
    revision_ids = [r.id for r in revisions]
    feedbacks_by_revision: Dict[int, List[PlanFeedback]] = {}
    if revision_ids:
        feedback_result = await session.execute(
            select(PlanFeedback)
            .where(PlanFeedback.revision_id.in_(revision_ids))
            .order_by(PlanFeedback.created_at.asc())
        )
        for fb in feedback_result.scalars().all():
            feedbacks_by_revision.setdefault(fb.revision_id, []).append(fb)

    summaries = []
    for r in revisions:
        feedback_preview = ""
        fbs = feedbacks_by_revision.get(r.id, [])
        if fbs:
            fb = fbs[0]
            raw_text = fb.raw_text or ""
            feedback_preview = (raw_text[:50] + "...") if len(raw_text) > 50 else raw_text
        summaries.append(RevisionSummary(
            revision_id=r.id,
            version=r.version,
            source=r.source,
            created_at=r.created_at,
            feedback_preview=feedback_preview
        ))

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"plan_id": plan_id, "revisions": [s.model_dump() for s in summaries]}
    )


@router.get("/{plan_id}/feedback", response_model=StandardResponse)
async def list_feedback(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db)
):
    """
    获取某行程计划下的有效反馈列表。
    """
    memory_service = MemoryService()
    feedbacks = await memory_service.get_active_feedbacks(session, plan_id)

    records = []
    for fb in feedbacks:
        structured = None
        if fb.structured_feedback:
            try:
                structured = StructuredFeedback(**fb.structured_feedback)
            except Exception:
                structured = None
        records.append(FeedbackRecord(
            feedback_id=fb.id,
            day_index=fb.day_index,
            tags=fb.tags,
            raw_text=fb.raw_text,
            structured_feedback=structured,
            revision_type=fb.revision_type,
            is_withdrawn=fb.is_withdrawn,
            created_at=fb.created_at
        ))

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"plan_id": plan_id, "feedbacks": [r.model_dump() for r in records]}
    )


@router.post("/{plan_id}/feedback/{feedback_id}/withdraw", response_model=StandardResponse)
async def withdraw_plan_feedback(
    plan_id: str,
    feedback_id: int,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db)
):
    """
    撤回一条反馈。

    注意：撤回不会自动回滚已生成的行程版本。
    """
    memory_service = MemoryService()
    await memory_service.withdraw_feedback(session, feedback_id)
    await session.commit()

    return StandardResponse(
        success=True,
        message="反馈已撤回",
        data={"feedback_id": feedback_id}
    )


@router.put("/{plan_id}/feedback/{feedback_id}", response_model=StandardResponse)
async def edit_plan_feedback(
    plan_id: str,
    feedback_id: int,
    feedback: PlanFeedbackRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db)
):
    """
    编辑一条反馈：旧记录标记为被替代，生成新反馈记录。

    与 submit_feedback 行为对齐：本接口只更新数据库，不立即触发后台任务。
    后台任务由用户在 Result.vue 点"基于所有反馈重新生成行程"统一触发。
    """
    if plan.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程生成失败，请重新发起规划"
        )

    memory_service = MemoryService()
    new_feedback = await memory_service.edit_feedback(
        session=session,
        feedback_id=feedback_id,
        day_index=feedback.day_index,
        tags=feedback.tags,
        raw_text=feedback.raw_text
    )
    await session.commit()

    return StandardResponse(
        success=True,
        message="意见已更新，点'根据所有反馈重新生成行程'可统一处理",
        data={"feedback_id": new_feedback.id, "old_feedback_id": feedback_id}
    )


@router.post("/{plan_id}/feedback_legacy", response_model=StandardResponse)
async def submit_legacy_feedback(
    plan_id: str,
    feedback: UserFeedback,
    plan: TripPlanDB = Depends(get_accessible_plan),
):
    """
    保留旧版总体评分反馈入口（用于前端兼容）。

    当前仅记录反馈内容，不触发修订。
    """
    return StandardResponse(
        success=True,
        message="反馈提交成功",
        data={"plan_id": plan_id, "feedback": feedback.model_dump()}
    )


# ==================== 我的历史行程 ====================

@router.get("/my/list", response_model=StandardResponse)
async def list_my_plans(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    获取当前用户的历史行程列表（摘要信息，供个人中心展示）。

    摘要字段来自 trip_plans 表列（城市/日期/天数/状态），预算总额从 plan_data JSON 提取；
    最多返回最近 50 条，按创建时间倒序。

    Args:
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: plans 摘要列表。
    """
    result = await session.execute(
        select(TripPlanDB)
        .where(TripPlanDB.user_id == current_user.id)
        .order_by(TripPlanDB.created_at.desc())
        .limit(50)
    )
    plans = result.scalars().all()

    data = []
    for p in plans:
        plan_data = p.plan_data or {}
        budget = plan_data.get("budget") or {}
        data.append({
            "plan_id": p.id,
            "city": p.city,
            "start_date": p.start_date,
            "end_date": p.end_date,
            "travel_days": p.travel_days,
            "status": p.status,
            "budget_total": budget.get("total", 0) if isinstance(budget, dict) else 0,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"plans": data}
    )


# ==================== 对话式修改助手 ====================

# 对话意图提取的系统提示词：让 LLM 输出严格 JSON，
# intent=feedback（修改意见）时附带 day_index/tags；intent=question（咨询）时 reply 直接回答。
CHAT_SYSTEM_PROMPT = """你是一个旅行行程助手的意图分析模块。用户会针对已有的旅行行程输入一句话，你需要：
1. 判断意图：
   - "feedback"：用户提出了对行程的修改意见（如换景点/换餐厅/换酒店/行程太满/太赶/想加某地/想删某地/嫌贵等）；
   - "question"：用户在咨询行程相关信息（如天气、路线、建议、某个景点介绍等），不构成修改意见。
2. 若是 feedback，提取：
   - day_index：针对第几天（整数）；无法确定则为 null（表示整体意见）；
   - tags：从这些标签中选择最匹配的若干个：["餐饮不满意","景点不喜欢","行程太满","想加某地","想删某地","换酒店","其他"]；
3. reply：用中文给用户一句自然、友好的回复（feedback 时要复述你理解到的意见以便用户确认；question 时直接基于行程上下文回答，回答要具体、简洁，不超过 120 字）。
4. 参考最近的对话历史理解指代（如"第二天也这样"）。

只输出如下 JSON，不要输出其他任何内容：
{"intent": "feedback|question", "day_index": null, "tags": [], "reply": "..."}"""


def _build_plan_digest(plan_data: dict) -> str:
    """
    _build_plan_digest：把行程 JSON 压缩成 LLM 可读的紧凑文本摘要。

    只保留 天数/景点名/餐饮名/酒店名/整体建议，避免超长 prompt。

    Args:
        plan_data: 行程结果 JSON（TripPlan 结构）。

    Returns:
        str: 多行文本摘要。
    """
    if not plan_data:
        return "（暂无行程数据）"

    lines: List[str] = []
    city = plan_data.get("city", "")
    days = plan_data.get("day_plans") or []
    lines.append(f"目的地：{city}，共 {plan_data.get('travel_days', len(days))} 天")

    for day in days:
        spots = "、".join([a.get("name", "?") for a in (day.get("attractions") or [])]) or "无"
        meals = "、".join(
            [f"{m.get('type','')}{m.get('name','')}" for m in (day.get("meals") or []) if m.get("name")]
        ) or "无"
        hotel = (day.get("hotel") or {}).get("name", "无")
        lines.append(f"第{day.get('day_index', '?')}天：景点[{spots}]；餐饮[{meals}]；酒店[{hotel}]")

    if plan_data.get("overall_suggestions"):
        lines.append(f"整体建议：{plan_data['overall_suggestions']}")
    return "\n".join(lines)


def _parse_chat_llm_output(text: str) -> Optional[dict]:
    """
    _parse_chat_llm_output：解析 LLM 输出的意图 JSON（带容错）。

    处理两种常见情况：纯 JSON 字符串、被 ```json ... ``` 包裹的字符串。

    Args:
        text: LLM 原始输出。

    Returns:
        Optional[dict]: 解析成功返回字典，失败返回 None。
    """
    if not text:
        return None
    cleaned = text.strip()
    # 去掉 markdown 代码围栏
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def _load_chat_context(
    session: AsyncSession,
    plan_id: str,
    plan: TripPlanDB,
    chat: PlanChatRequest
) -> Dict:
    """
    加载对话修改助手所需的上下文。

    汇总：当前生效版本行程数据、已有有效反馈、最近对话历史。

    Args:
        session: 数据库会话。
        plan_id: 行程计划 ID。
        plan: 行程计划记录。
        chat: 对话请求。

    Returns:
        dict: {"plan_data": 行程 JSON, "feedback_context": 已提交意见文本, "history_context": 对话历史文本}。
    """
    memory_service = MemoryService()
    # 行程摘要 + 当前生效版本
    current_revision = await memory_service.get_current_revision(session, plan_id)
    plan_data = current_revision.trip_plan_json if current_revision else plan.plan_data

    # 已有有效反馈（写入 prompt 让 LLM 知道用户已经提过什么，避免重复确认）
    active_feedbacks = await memory_service.get_active_feedbacks(session, plan_id)
    feedback_lines = [
        f"- 第{fb.day_index if fb.day_index else '整体'}天：{fb.raw_text}"
        for fb in active_feedbacks[-10:]  # 最多带最近 10 条，防止 prompt 过长
    ]
    feedback_context = "\n".join(feedback_lines) if feedback_lines else "（暂无）"

    # 对话历史（只取最近 6 轮，且保证是 user/assistant 两种角色）
    history_lines = [
        f"{('用户' if m.role == 'user' else '助手')}：{m.content}"
        for m in chat.history[-6:]
    ]
    history_context = "\n".join(history_lines) if history_lines else "（无）"

    return {
        "plan_data": plan_data,
        "feedback_context": feedback_context,
        "history_context": history_context,
    }


async def _extract_chat_intent(
    message: str,
    plan_data: dict,
    feedback_context: str,
    history_context: str
) -> Dict:
    """
    调用 LLM 识别对话意图并提取结构化信息，失败时走关键词降级。

    Args:
        message: 用户本轮输入。
        plan_data: 行程 JSON。
        feedback_context: 已提交意见文本。
        history_context: 对话历史文本。

    Returns:
        dict: {"intent": "feedback|question", "day_index": Optional[int],
               "tags": List[str], "reply": str}。
    """
    # 组装 prompt 并调用 LLM
    user_prompt = (
        f"【当前行程】\n{_build_plan_digest(plan_data)}\n\n"
        f"【用户已提交的修改意见】\n{feedback_context}\n\n"
        f"【最近对话历史】\n{history_context}\n\n"
        f"【用户本轮输入】\n{message}"
    )

    parsed: Optional[dict] = None
    try:
        llm = get_llm(temperature=0.3)
        result = await llm.ainvoke([
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ])
        parsed = _parse_chat_llm_output(getattr(result, "content", "") or "")
    except Exception as e:
        logger.exception(f"[chat_with_plan] LLM 调用失败: {e}")

    if parsed and parsed.get("intent") in ("feedback", "question"):
        raw_day = parsed.get("day_index")
        raw_tags = parsed.get("tags")
        return {
            "intent": parsed["intent"],
            "day_index": raw_day if isinstance(raw_day, int) and raw_day >= 1 else None,
            "tags": [str(t) for t in raw_tags if t][:4] if isinstance(raw_tags, list) else [],
            "reply": str(parsed.get("reply") or "").strip()
        }

    # 降级策略：JSON 解析失败时用关键词判断是否保存为整体意见
    modify_keywords = ("换", "删", "去掉", "添加", "加个", "加一", "太贵", "太满", "太赶", "不喜欢", "不想", "改成")
    if any(k in message for k in modify_keywords):
        return {
            "intent": "feedback",
            "day_index": None,
            "tags": ["其他"],
            "reply": "已记录你的意见（本次未识别到具体天数，将作为整体调整参与下次重新生成）。你可以继续补充，或点下方按钮重新生成行程。"
        }
    return {
        "intent": "question",
        "day_index": None,
        "tags": [],
        "reply": "抱歉，我暂时没能理解这条消息。你可以试着描述想怎么修改行程，例如：'第二天太赶了，去掉一个景点'。"
    }


async def _persist_chat_feedback(
    session: AsyncSession,
    plan_id: str,
    user_id: int,
    message: str,
    intent_result: Dict
) -> Tuple[Optional[int], bool]:
    """
    feedback 意图时把对话内容写入反馈表（与手动反馈同表，不触发重排）。

    Args:
        session: 数据库会话。
        plan_id: 行程计划 ID。
        user_id: 当前用户 ID。
        message: 用户原始输入（作为反馈正文）。
        intent_result: _extract_chat_intent 的返回结果。

    Returns:
        Tuple[Optional[int], bool]: (feedback_id, 是否写入失败)。
        非 feedback 意图或无当前版本时返回 (None, False)；写库异常时返回 (None, True)。
    """
    if intent_result.get("intent") != "feedback":
        return None, False

    memory_service = MemoryService()
    try:
        current_revision = await memory_service.get_current_revision(session, plan_id)
        if not current_revision:
            return None, False
        feedback_record = await memory_service.create_feedback(
            session=session,
            plan_id=plan_id,
            revision_id=current_revision.id,
            user_id=user_id,
            day_index=intent_result.get("day_index"),
            tags=intent_result.get("tags") or [],
            raw_text=message
        )
        await session.commit()
        return feedback_record.id, False
    except Exception as e:
        await session.rollback()
        logger.exception(f"[chat_with_plan] 反馈写入失败: {e}")
        return None, True


@router.post("/{plan_id}/chat", response_model=StandardResponse)
async def chat_with_plan(
    plan_id: str,
    chat: PlanChatRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
):
    """
    对话式修改行程助手。

    流程：
    1. 校验行程计划存在、属于当前用户且已完成；
    2. 组装行程摘要 + 已有反馈 + 对话历史，调用 LLM 做意图识别与信息提取；
    3. intent=feedback → 提取结构化反馈写入数据库（与手动反馈同表，不立即触发重排）；
       intent=question → 直接返回 LLM 回答；
    4. 返回 reply 与反馈元信息（pending_count 供前端提示"已积累 N 条意见"）。

    LLM 调用失败时的降级策略：
    - 若用户消息包含明显修改关键词，按"整体意见"保存，回复确认语；
    - 否则返回兜底话术，不写库。

    Args:
        plan_id: 行程计划 ID。
        chat: 对话请求（message + history）。
        plan: 归属校验通过的行程计划（get_owned_plan 依赖注入）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: reply、intent、day_index、tags、feedback_id、pending_count。

    职责拆分：
    - _load_chat_context：加载行程/反馈/对话历史上下文；
    - _extract_chat_intent：LLM 意图识别 + 关键词降级；
    - _persist_chat_feedback：feedback 意图落库。
    """
    if plan.status == "revising":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程正在修订中，请等待当前任务完成后再使用修改助手"
        )
    if plan.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"行程当前状态为 {plan.status}，暂无法使用修改助手"
        )

    context = await _load_chat_context(session, plan_id, plan, chat)
    intent = await _extract_chat_intent(
        message=chat.message,
        plan_data=context["plan_data"],
        feedback_context=context["feedback_context"],
        history_context=context["history_context"]
    )

    feedback_id, persist_failed = await _persist_chat_feedback(
        session=session,
        plan_id=plan_id,
        user_id=current_user.id,
        message=chat.message,
        intent_result=intent
    )
    if persist_failed:
        intent["reply"] = "（意见记录失败，请稍后重试或使用手动反馈表单）" + intent["reply"]

    # 待处理反馈数（含本次）
    memory_service = MemoryService()
    active_feedbacks = await memory_service.get_active_feedbacks(session, plan_id)

    return StandardResponse(
        success=True,
        message="ok",
        data={
            "reply": intent["reply"],
            "intent": intent["intent"],
            "day_index": intent["day_index"],
            "tags": intent["tags"],
            "feedback_id": feedback_id,
            "pending_count": len(active_feedbacks)
        }
    )
