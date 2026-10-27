"""游记路由：行程结束后生成/查询/编辑 LLM 图文游记。生成走 ARQ 后台任务。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user
from app.core.db.session import get_db
from app.core.utils.queue import enqueue_journal_task
from app.models.db_models import TripJournal, TripPlanDB, User
from app.models.schemas import JournalUpdateRequest, StandardResponse

router = APIRouter()


def _journal_out(journal: TripJournal) -> dict:
    """游记记录转响应 dict（content JSON → sections 列表）。"""
    sections = journal.content or []
    return {
        "id": journal.id,
        "plan_id": journal.plan_id,
        "title": journal.title,
        "status": journal.status,
        "sections": sections,
        "is_public": journal.is_public,
        "public_token": journal.public_token,
        "generated_at": journal.generated_at,
    }


@router.post("/{plan_id}/journal/generate", response_model=StandardResponse)
async def generate_journal(
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    触发游记生成（幂等）。

    - 无记录：创建 generating 记录并入队后台任务；
    - 已在生成/已完成：直接返回现有记录，不重复入队；
    - 之前失败：重置为 generating 重新入队。

    Args:
        plan: 访问校验通过的行程计划。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 游记记录（status=generating，前端轮询 GET /journal）。
    """
    result = await session.execute(select(TripJournal).where(TripJournal.plan_id == plan.id))
    journal = result.scalar_one_or_none()

    if journal is None:
        journal = TripJournal(
            id=f"JN_{uuid.uuid4().hex}",
            plan_id=plan.id,
            user_id=current_user.id,
            status="generating",
        )
        session.add(journal)
        await session.commit()
        await session.refresh(journal)
    elif journal.status == "failed":
        journal.status = "generating"
        journal.content = None
        await session.commit()
        await session.refresh(journal)
    else:
        # generating / done：直接返回，不重复生成（plan_id 唯一约束兜底）
        return StandardResponse(
            success=True, message="游记已存在", data=_journal_out(journal)
        )

    await enqueue_journal_task(plan_id=plan.id, journal_id=journal.id, user_id=current_user.id)
    logger.info(f"[Journal] 游记生成任务已入队 plan_id={plan.id} journal_id={journal.id}")

    return StandardResponse(success=True, message="游记生成已开始", data=_journal_out(journal))


@router.get("/{plan_id}/journal", response_model=StandardResponse)
async def get_journal(
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    查询行程的游记（前端轮询 status 判断生成进度）。

    Args:
        plan: 访问校验通过的行程计划。
        session: 数据库会话。

    Returns:
        StandardResponse: 游记记录，尚未生成时 data=null。
    """
    result = await session.execute(select(TripJournal).where(TripJournal.plan_id == plan.id))
    journal = result.scalar_one_or_none()
    return StandardResponse(
        success=True,
        message="获取成功",
        data=_journal_out(journal) if journal else None,
    )


@router.patch("/{plan_id}/journal", response_model=StandardResponse)
async def update_journal(
    payload: JournalUpdateRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    编辑游记标题与分节内容（仅游记作者可编辑，协作者只能查看）。

    Args:
        payload: 编辑内容（title / sections 均可选，只更新传入字段）。
        plan: 访问校验通过的行程计划。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 更新后的游记记录。
    """
    result = await session.execute(select(TripJournal).where(TripJournal.plan_id == plan.id))
    journal = result.scalar_one_or_none()
    if not journal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游记尚未生成")
    if journal.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅游记作者可以编辑"
        )
    if journal.status == "generating":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="游记生成中，暂不能编辑")

    if payload.title is not None:
        journal.title = payload.title
    if payload.sections is not None:
        journal.content = [s.model_dump(mode="json") for s in payload.sections]
    await session.commit()
    await session.refresh(journal)

    return StandardResponse(success=True, message="保存成功", data=_journal_out(journal))


@router.post("/{plan_id}/journal/publish", response_model=StandardResponse)
async def publish_journal(
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    将游记设为公开（第二阶段内容回流入口）。

    仅游记作者可操作，且游记须已生成完成（done）；首次公开时生成
    public_token，公开后游记进入 /api/journals/featured 与攻略流。

    Args:
        plan: 访问校验通过的行程计划。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: is_public 与 public_token（前端拼分享链接 /journal/{token}）。
    """
    result = await session.execute(select(TripJournal).where(TripJournal.plan_id == plan.id))
    journal = result.scalar_one_or_none()
    if not journal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游记尚未生成")
    if journal.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅游记作者可以设为公开")
    if journal.status != "done":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="游记尚未生成完成，无法公开"
        )

    journal.is_public = True
    if not journal.public_token:
        journal.public_token = uuid.uuid4().hex
    await session.commit()
    await session.refresh(journal)

    return StandardResponse(
        success=True,
        message="游记已公开",
        data={"is_public": True, "public_token": journal.public_token},
    )


@router.post("/{plan_id}/journal/unpublish", response_model=StandardResponse)
async def unpublish_journal(
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    取消游记公开（保留 public_token，重新公开后链接不变）。

    Args:
        plan: 访问校验通过的行程计划。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: is_public=False。
    """
    result = await session.execute(select(TripJournal).where(TripJournal.plan_id == plan.id))
    journal = result.scalar_one_or_none()
    if not journal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游记尚未生成")
    if journal.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅游记作者可以操作")

    journal.is_public = False
    await session.commit()
    await session.refresh(journal)

    return StandardResponse(
        success=True,
        message="游记已取消公开",
        data={"is_public": False, "public_token": journal.public_token},
    )
