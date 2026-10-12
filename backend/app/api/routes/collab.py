"""
backend/app/api/routes/collab.py

多人协作行程路由模块。

作用：
- 所有者生成邀请令牌，邀请其他注册用户成为行程协作者；
- 协作者可查看行程、提交反馈修订（由 trip.py 的读/编辑类端点配合完成）；
- 删除、分享管理、邀请管理仅限所有者。

注意：
- 本 router 整体挂载在 trip router 之前（见 app/api/main.py），
  固定路径 /collab/join/{token} 因此先于 trip 的 /{plan_id} 动态路由匹配，
  避免被误解析为 plan_id。

对应技术：
- FastAPI：APIRouter、Depends
- SQLAlchemy：协作成员/邀请令牌持久化
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user, get_owned_plan
from app.db.session import get_db
from app.models.db_models import PlanCollaborator, PlanInvite, TripPlanDB, User
from app.models.schemas import (
    CollaboratorJoinOut,
    CollaboratorOut,
    InviteOut,
    StandardResponse,
)

router = APIRouter()

# 邀请链接默认有效期（天），与 PlanInvite.expires_at 的列默认值保持一致
INVITE_EXPIRE_DAYS = 7


@router.post("/collab/join/{token}", response_model=StandardResponse)
async def join_plan_by_token(
    token: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    登录用户凭邀请令牌加入行程协作。

    流程：
    1. 按 token 查询邀请记录；不存在返回 404，已撤销/已过期返回 410；
    2. 校验邀请对应行程仍存在（行程可能已被所有者删除）；
    3. 已是所有者或已加入过 → 幂等成功（不重复计数、不重复建行）；
    4. 首次加入：创建协作者行（role=editor），邀请 use_count + 1。

    Args:
        token: 邀请令牌。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: data = CollaboratorJoinOut（plan_id 供前端跳转结果页）。
    """
    # 查询邀请记录
    result = await session.execute(select(PlanInvite).where(PlanInvite.token == token))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请链接无效")
    if invite.revoked:
        raise HTTPException(status_code=410, detail="邀请链接已被撤销")
    if invite.expires_at is not None and invite.expires_at < datetime.now():
        raise HTTPException(status_code=410, detail="邀请链接已过期")

    # 邀请对应的行程必须仍存在
    plan = await session.get(TripPlanDB, invite.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="行程不存在或已被删除")

    # 幂等：所有者本人或已加入过的用户直接成功返回
    join_result = await session.execute(
        select(PlanCollaborator).where(
            PlanCollaborator.plan_id == plan.id, PlanCollaborator.user_id == current_user.id
        )
    )
    existing = join_result.scalar_one_or_none()
    if plan.user_id == current_user.id:
        return StandardResponse(
            success=True,
            message="你是该行程的所有者，无需加入协作",
            data=CollaboratorJoinOut(plan_id=plan.id, city=plan.city, role="owner").model_dump(),
        )
    if existing is not None:
        return StandardResponse(
            success=True,
            message="你已加入该行程协作",
            data=CollaboratorJoinOut(
                plan_id=plan.id, city=plan.city, role=existing.role
            ).model_dump(),
        )

    # 首次加入：创建协作者行并累计邀请使用次数
    collaborator = PlanCollaborator(plan_id=plan.id, user_id=current_user.id, role="editor")
    session.add(collaborator)
    invite.use_count = (invite.use_count or 0) + 1
    await session.commit()
    logger.info(
        f"[协作] 用户 {current_user.id} 通过邀请加入行程 {plan.id}（邀请使用 {invite.use_count} 次）"
    )

    return StandardResponse(
        success=True,
        message="已加入行程协作",
        data=CollaboratorJoinOut(plan_id=plan.id, city=plan.city, role="editor").model_dump(),
    )


@router.post("/{plan_id}/collaborators/invite", response_model=StandardResponse)
async def invite_collaborator(
    plan_id: str,
    plan: TripPlanDB = Depends(get_owned_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    所有者为行程生成邀请令牌（仅所有者）。

    每次调用生成一个新令牌（有效期 7 天），持有者登录后凭令牌加入协作。

    Args:
        plan_id: 行程计划 ID。
        plan: 归属校验通过的行程计划（get_owned_plan 依赖注入）。
        session: 数据库会话。

    Returns:
        StandardResponse: data = InviteOut（token 与前端路由路径 /join/{token}）。
    """
    token = uuid.uuid4().hex
    expires_at = datetime.now() + timedelta(days=INVITE_EXPIRE_DAYS)
    invite = PlanInvite(
        plan_id=plan.id, token=token, created_by=plan.user_id, expires_at=expires_at
    )
    session.add(invite)
    await session.commit()
    logger.info(f"[协作] 行程 {plan.id} 所有者 {plan.user_id} 生成邀请令牌，有效期至 {expires_at}")

    return StandardResponse(
        success=True,
        message="邀请链接已生成",
        data=InviteOut(
            plan_id=plan.id,
            token=token,
            invite_path=f"/join/{token}",
            expires_at=expires_at.isoformat(),
        ).model_dump(),
    )


@router.get("/{plan_id}/collaborators", response_model=StandardResponse)
async def list_collaborators(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    查询行程成员列表（所有者或协作者均可）。

    返回所有者（role=owner）与全部协作者（role=editor），
    字段：user_id / username / role / joined_at。

    Args:
        plan_id: 行程计划 ID。
        plan: 访问校验通过的行程计划（get_accessible_plan 依赖注入）。
        session: 数据库会话。

    Returns:
        StandardResponse: data = {"plan_id", "collaborators": [CollaboratorOut]}。
    """
    members: list = []

    # 所有者行（单独查用户，避免 async 会话下懒加载关系）
    owner_result = await session.execute(select(User).where(User.id == plan.user_id))
    owner_user = owner_result.scalar_one_or_none()
    if owner_user is not None:
        members.append(
            CollaboratorOut(
                user_id=owner_user.id,
                username=owner_user.username,
                role="owner",
                joined_at=plan.created_at.isoformat() if plan.created_at else None,
            ).model_dump()
        )

    # 协作者行：联表取用户名，按加入时间正序
    collab_result = await session.execute(
        select(PlanCollaborator, User)
        .join(User, User.id == PlanCollaborator.user_id)
        .where(PlanCollaborator.plan_id == plan.id)
        .order_by(PlanCollaborator.created_at.asc())
    )
    for collaborator, user in collab_result.all():
        members.append(
            CollaboratorOut(
                user_id=user.id,
                username=user.username,
                role=collaborator.role or "editor",
                joined_at=collaborator.created_at.isoformat() if collaborator.created_at else None,
            ).model_dump()
        )

    return StandardResponse(
        success=True, message="获取成功", data={"plan_id": plan.id, "collaborators": members}
    )


@router.delete("/{plan_id}/collaborators/{collaborator_user_id}", response_model=StandardResponse)
async def remove_collaborator(
    plan_id: str,
    collaborator_user_id: int,
    plan: TripPlanDB = Depends(get_owned_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    所有者移除协作者（仅所有者）。

    被移除的用户立即失去该行程的访问权（读/编辑类端点的
    get_accessible_plan 校验将不再通过）。

    Args:
        plan_id: 行程计划 ID。
        collaborator_user_id: 待移除的协作者用户 ID。
        plan: 归属校验通过的行程计划（get_owned_plan 依赖注入）。
        session: 数据库会话。

    Returns:
        StandardResponse: 操作结果。

    Raises:
        HTTPException: 目标用户不是该行程协作者时 404（所有者本身不在协作者表，同样 404）。
    """
    result = await session.execute(
        select(PlanCollaborator).where(
            PlanCollaborator.plan_id == plan.id, PlanCollaborator.user_id == collaborator_user_id
        )
    )
    collaborator = result.scalar_one_or_none()
    if collaborator is None:
        raise HTTPException(status_code=404, detail="该用户不是此行程的协作者")

    await session.delete(collaborator)
    await session.commit()
    logger.info(f"[协作] 行程 {plan.id} 所有者移除协作者 {collaborator_user_id}")

    return StandardResponse(
        success=True,
        message="已移除协作者",
        data={"plan_id": plan.id, "removed_user_id": collaborator_user_id},
    )
