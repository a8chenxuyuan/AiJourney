"""单条行程的查询与删除（/{plan_id} 动态路由，注册顺序需晚于单段固定路径）。"""

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user
from app.db.session import get_db
from app.models.db_models import (
    PlanCollaborator,
    PlanFeedback,
    PlanInvite,
    PlanLogDB,
    PlanNotification,
    PlanRevision,
    TripPlanDB,
    User,
)
from app.models.schemas import (
    StandardResponse,
)
from app.services.memory_service import MemoryService

router = APIRouter()


@router.get("/{plan_id}", response_model=StandardResponse)
async def get_plan(
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
    logger.debug(
        f"[GET /api/trip/{plan.id}] "
        f"returning version={current_revision.version if current_revision else None}, "
        f"diff_total={(diff_summary or {}).get('total_changes') if diff_summary else 0}"
    )

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
            "is_owner": plan.user_id == current_user.id,
        },
    )


@router.delete("/{plan_id}", response_model=StandardResponse)
async def delete_plan(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_403_FORBIDDEN, detail="仅行程所有者可以删除行程"
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

    return StandardResponse(success=True, message="行程已删除", data={"plan_id": plan_id})
