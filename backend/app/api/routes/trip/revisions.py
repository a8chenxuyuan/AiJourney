"""行程版本演化：单日重算、整单重新生成、版本列表。"""

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user
from app.core.db.session import get_db
from app.core.utils.queue import enqueue_recalculate_task, enqueue_revision_task
from app.models.db_models import (
    PlanFeedback,
    PlanRevision,
    TripPlanDB,
    User,
)
from app.models.schemas import (
    RecalculateRequest,
    RevisionSummary,
    StandardResponse,
    StructuredFeedback,
    TripPlan,
    TripRequest,
)
from app.services.memory_service import MemoryService

router = APIRouter()


@router.post("/{plan_id}/recalculate", response_model=StandardResponse)
async def recalculate_plan(
    recalc_request: RecalculateRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_400_BAD_REQUEST, detail="行程正在修订中，请等待当前任务完成"
        )
    if plan.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"行程当前状态为 {plan.status}，仅已完成的行程支持重算",
        )

    # 多城联游行程的重排需要按城市分段处理，暂不支持
    if plan.cities_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="多城联游行程暂不支持手动排序重算"
        )

    if not recalc_request.attraction_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="attraction_ids 不能为空"
        )

    # 加载当前生效版本作为重算基底
    memory_service = MemoryService()
    current_revision = await memory_service.get_current_revision(session, plan.id)
    if not current_revision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="未找到当前生效的行程版本"
        )
    previous_plan = TripPlan(**current_revision.trip_plan_json)

    # 定位目标天
    target_day = next(
        (d for d in previous_plan.day_plans if d.day_index == recalc_request.day_index), None
    )
    if target_day is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"第 {recalc_request.day_index} 天不存在"
                f"（行程共 {len(previous_plan.day_plans)} 天）"
            ),
        )
    if not target_day.attractions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"第 {recalc_request.day_index} 天没有景点，无法重排",
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
                detail=f"景点 {key} 不在第 {recalc_request.day_index} 天的行程中",
            )
        obj_key = id(attraction)
        if obj_key in matched_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"景点 {key} 重复出现"
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
        "end_date": plan.end_date,
    }
    await enqueue_recalculate_task(
        plan_id=plan.id,
        request=request_data,
        user_id=current_user.id,
        parent_revision_id=current_revision.id,
        previous_plan=previous_plan.model_dump(mode="json"),
        revision_notes=revision_notes,
        day_attractions=[a.model_dump(mode="json") for a in target_day.attractions],
    )
    logger.info(
        f"[重算] 行程 {plan.id} 第 {recalc_request.day_index} 天重排重算任务已入队，"
        f"新顺序：{ordered_names}"
    )

    return StandardResponse(
        success=True,
        message="重算请求已提交，正在重新规划路线和行程",
        data={
            "plan_id": plan.id,
            "status": "revising",
            "day_index": recalc_request.day_index,
            "attraction_count": len(target_day.attractions),
        },
    )


async def _load_regenerate_context(
    session: AsyncSession, plan_id: str
) -> tuple[PlanRevision, str, list[PlanFeedback]]:
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
            status_code=status.HTTP_404_NOT_FOUND, detail="未找到当前生效的行程版本"
        )

    # 聚合所有未撤回、未被替代的有效反馈
    aggregated_notes, feedbacks = await memory_service.aggregate_active_feedbacks(session, plan_id)
    if not aggregated_notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="暂无有效反馈，无法重新生成"
        )

    return current_revision, aggregated_notes, feedbacks


def _build_revision_request(
    plan: TripPlanDB, current_revision: PlanRevision, aggregated_notes: str
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
            accommodation="酒店",
        )

    revision_hint = f"【本次重新生成需要满足的修改意见】\n{aggregated_notes}"
    if trip_request.free_text_input:
        trip_request.free_text_input = f"{trip_request.free_text_input}\n\n{revision_hint}"
    else:
        trip_request.free_text_input = revision_hint
    return trip_request


def _build_full_feedback_constraint(
    feedbacks: list[PlanFeedback],
) -> tuple[StructuredFeedback, list[str]]:
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
        complexity="full",
    )
    return force_full_feedback, feedback_tags


@router.post("/{plan_id}/regenerate", response_model=StandardResponse)
async def regenerate_plan(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_400_BAD_REQUEST, detail="行程正在修订中，请等待当前任务完成"
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
        source="regenerate",
    )

    return StandardResponse(
        success=True,
        message=f"已聚合 {len(feedbacks)} 条反馈，正在重新生成完整行程",
        data={"plan_id": plan_id, "feedback_count": len(feedbacks), "status": "revising"},
    )


@router.get("/{plan_id}/revisions", response_model=StandardResponse)
async def list_revisions(
    plan_id: str,
    plan: TripPlanDB = Depends(get_accessible_plan),
    session: AsyncSession = Depends(get_db),
):
    """
    获取某行程计划的版本历史列表。
    """
    memory_service = MemoryService()
    revisions = await memory_service.get_revision_history(session, plan_id)

    # 防御性查询：单独拉取每个版本的反馈，避免依赖 ORM 关系懒加载
    revision_ids = [r.id for r in revisions]
    feedbacks_by_revision: dict[int, list[PlanFeedback]] = {}
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
        summaries.append(
            RevisionSummary(
                revision_id=r.id,
                version=r.version,
                source=r.source,
                created_at=r.created_at,
                feedback_preview=feedback_preview,
            )
        )

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"plan_id": plan_id, "revisions": [s.model_dump() for s in summaries]},
    )
