"""行程计划的创建、分享链接与我的行程列表。"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_plan
from app.db.session import get_db
from app.models.db_models import (
    TripPlanDB,
    User,
)
from app.models.schemas import (
    ShareCreateRequest,
    ShareInfo,
    StandardResponse,
    TripPlanResponse,
    TripRequest,
)
from app.services.memory_service import MemoryService
from app.utils.queue import enqueue_planning_task

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
    session: AsyncSession = Depends(get_db),
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
        status="pending",
    )
    session.add(db_plan)
    await session.flush()
    # 立即提交，确保后台任务能读取到 pending 记录
    await session.commit()

    # 投递到 Redis 队列，由 ARQ Worker 进程异步执行，实现 API 与任务执行解耦
    await enqueue_planning_task(
        plan_id=plan_id, request=request.model_dump(mode="json"), user_id=current_user.id
    )

    return StandardResponse(
        success=True,
        message="规划任务已创建",
        data=TripPlanResponse(plan_id=plan_id, status="pending").model_dump(),
    )


# ==================== 行程分享 ====================
# 注意：以下静态路径路由（/share/xxx、/favorites）必须注册在 "/{plan_id}" 动态路由之前，
# 否则 FastAPI 会把 share/favorites 误匹配为 plan_id。


@router.get("/share/{token}", response_model=StandardResponse)
async def get_shared_plan(token: str, session: AsyncSession = Depends(get_db)):
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
    result = await session.execute(select(TripPlanDB).where(TripPlanDB.share_token == token))
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
            "plan": plan_data,
        },
    )


@router.post("/{plan_id}/share", response_model=StandardResponse)
async def create_share(
    plan_id: str,
    share_request: ShareCreateRequest,
    plan: TripPlanDB = Depends(get_owned_plan),
    session: AsyncSession = Depends(get_db),
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
            share_view_count=plan.share_view_count or 0,
        ).model_dump(),
    )


@router.delete("/{plan_id}/share", response_model=StandardResponse)
async def close_share(
    plan: TripPlanDB = Depends(get_owned_plan), session: AsyncSession = Depends(get_db)
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


@router.get("/my/list", response_model=StandardResponse)
async def list_my_plans(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
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
        data.append(
            {
                "plan_id": p.id,
                "city": p.city,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "travel_days": p.travel_days,
                "status": p.status,
                "budget_total": budget.get("total", 0) if isinstance(budget, dict) else 0,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )

    return StandardResponse(success=True, message="获取成功", data={"plans": data})
