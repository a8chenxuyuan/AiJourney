"""行程反馈：提交、查看、撤回、编辑（新旧两套接口）。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user
from app.db.session import get_db
from app.models.db_models import (
    TripPlanDB,
    User,
)
from app.models.schemas import (
    FeedbackRecord,
    PlanFeedbackRequest,
    PlanFeedbackResponse,
    StandardResponse,
    StructuredFeedback,
    UserFeedback,
)
from app.services.memory_service import MemoryService

router = APIRouter()


@router.post("/{plan_id}/feedback", response_model=StandardResponse)
async def submit_plan_feedback(
    plan_id: str,
    feedback: PlanFeedbackRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_400_BAD_REQUEST, detail="行程生成失败，请重新发起规划"
        )
    if plan.status == "revising":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程正在修订中，请等待当前任务完成后再提交反馈",
        )
    if plan.status not in ("completed", "revising"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"行程当前状态为 {plan.status}，无法提交反馈",
        )

    # 获取当前生效版本
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan_id)
    if not current_revision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="未找到当前生效的行程版本"
        )

    # 创建反馈记录
    feedback_record = await memory_service.create_feedback(
        session=session,
        plan_id=plan_id,
        revision_id=current_revision.id,
        user_id=current_user.id,
        day_index=feedback.day_index,
        tags=feedback.tags,
        raw_text=feedback.raw_text,
    )
    await session.commit()

    return StandardResponse(
        success=True,
        message="意见已保存，点'根据所有反馈重新生成行程'可统一处理",
        data=PlanFeedbackResponse(
            feedback_id=feedback_record.id,
            revision_id=current_revision.id,
            revision_type="pending",
            status="saved",
        ).model_dump(),
    )


@router.get("/{plan_id}/feedback", response_model=StandardResponse)
async def list_feedback(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
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
        records.append(
            FeedbackRecord(
                feedback_id=fb.id,
                day_index=fb.day_index,
                tags=fb.tags,
                raw_text=fb.raw_text,
                structured_feedback=structured,
                revision_type=fb.revision_type,
                is_withdrawn=fb.is_withdrawn,
                created_at=fb.created_at,
            )
        )

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"plan_id": plan_id, "feedbacks": [r.model_dump() for r in records]},
    )


@router.post("/{plan_id}/feedback/{feedback_id}/withdraw", response_model=StandardResponse)
async def withdraw_plan_feedback(
    plan_id: str,
    feedback_id: int,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    撤回一条反馈。

    注意：撤回不会自动回滚已生成的行程版本。
    """
    memory_service = MemoryService()
    await memory_service.withdraw_feedback(session, feedback_id)
    await session.commit()

    return StandardResponse(success=True, message="反馈已撤回", data={"feedback_id": feedback_id})


@router.put("/{plan_id}/feedback/{feedback_id}", response_model=StandardResponse)
async def edit_plan_feedback(
    plan_id: str,
    feedback_id: int,
    feedback: PlanFeedbackRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    编辑一条反馈：旧记录标记为被替代，生成新反馈记录。

    与 submit_feedback 行为对齐：本接口只更新数据库，不立即触发后台任务。
    后台任务由用户在 Result.vue 点"基于所有反馈重新生成行程"统一触发。
    """
    if plan.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="行程生成失败，请重新发起规划"
        )

    memory_service = MemoryService()
    new_feedback = await memory_service.edit_feedback(
        session=session,
        feedback_id=feedback_id,
        day_index=feedback.day_index,
        tags=feedback.tags,
        raw_text=feedback.raw_text,
    )
    await session.commit()

    return StandardResponse(
        success=True,
        message="意见已更新，点'根据所有反馈重新生成行程'可统一处理",
        data={"feedback_id": new_feedback.id, "old_feedback_id": feedback_id},
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
        data={"plan_id": plan_id, "feedback": feedback.model_dump()},
    )


# ==================== 我的历史行程 ====================
