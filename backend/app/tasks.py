"""
backend/app/tasks.py

后台任务定义模块（由 ARQ Worker 进程执行）。

作用：
- 定义初始规划任务 run_planning_task 与行程修订任务 run_revision_task；
- 任务逻辑自 trip.py 迁移而来，与 API 进程解耦：API 只负责入队，
  本模块由 worker.py 在独立进程中消费执行；
- revision 任务保留 per-plan_id 的进程内互斥锁：同一行程同时只允许一个修订任务
  （单 Worker 进程部署下有效；多 Worker 实例需换用 Redis 分布式锁）。

对应技术：
- arq：任务函数第一个参数固定为 ctx（Worker 上下文），入参需可 JSON/Pickle 序列化
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select

from app.agents.graph import run_planning_graph, run_recalculate_graph, run_revision_graph
from app.agents.tools import get_weather
from app.db.session import AsyncSessionLocal
from app.models.db_models import PlanNotification, TripPlanDB
from app.models.schemas import StructuredFeedback, TripPlan, TripRequest
from app.services.crawler_service import CrawlerService
from app.services.memory_service import MemoryService
from app.utils.queue import enqueue_revision_task


# ==================== Revision 任务并发控制（Worker 进程内） ====================
# 同一 plan_id 同时只允许一个 revision 任务在跑。
# 设计要点：
# 1. 用 per-plan_id 的 asyncio.Lock 做互斥，任务开始前非阻塞检查，已占用则放弃；
# 2. 用 _revision_running 记录"正在跑的 revision 任务来源"，便于日志排查；
# 3. 任务结束（无论成功 / 失败 / 异常）都必须清理 running 标记，锁随 async with 释放。
_revision_locks: Dict[str, asyncio.Lock] = {}
_revision_running: Dict[str, str] = {}  # plan_id -> 来源标识（feedback/regenerate）


def _get_revision_lock(plan_id: str) -> asyncio.Lock:
    """
    获取（或惰性创建）指定 plan_id 的 revision 任务锁。
    """
    lock = _revision_locks.get(plan_id)
    if lock is None:
        lock = asyncio.Lock()
        _revision_locks[plan_id] = lock
    return lock


async def run_planning_task(ctx: dict, plan_id: str, request: dict, user_id: int) -> None:
    """
    初始规划任务：执行 LangGraph 规划链路并持久化结果。

    任务异常会被捕获并记录，避免 arq 将任务标记为失败后重复重试。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典。
        user_id: 用户 ID。
    """
    try:
        await run_planning_graph(plan_id, TripRequest(**request), user_id)
    except Exception as exc:
        logger.exception(f"[Background Task] 规划任务 {plan_id} 执行失败: {exc}")


async def run_revision_task(
    ctx: dict,
    plan_id: str,
    request: dict,
    user_id: int,
    parent_revision_id: int,
    previous_plan: dict,
    revision_notes: str,
    feedback_id: Optional[int],
    feedback_day_index: Optional[int],
    feedback_tags: List[str],
    structured_feedback: Optional[dict] = None,
    source: str = "feedback"
) -> None:
    """
    行程修订任务：执行 LangGraph 修订链路并回写反馈结果。

    完成后更新 PlanFeedback 的 structured_feedback 与 accepted_revision_id。
    若为聚合反馈（feedback_id 为 None），则不回写单条反馈记录。

    并发控制：
    - 同一 plan_id 同时只允许一个 revision 任务在跑；
    - 已有任务在跑时，新任务直接放弃（不修改数据库状态，避免覆盖前一个任务的结果）；
    - 任务结束（成功 / 失败 / 异常）都会释放锁，允许下一次提交。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典。
        user_id: 用户 ID。
        parent_revision_id: 父版本 ID。
        previous_plan: TripPlan.model_dump(mode="json") 的字典（当前生效行程）。
        revision_notes: 聚合后的修改意见文本。
        feedback_id: 单条反馈 ID，聚合反馈时为 None。
        feedback_day_index: 反馈涉及的天序号，可为 None。
        feedback_tags: 反馈标签列表。
        structured_feedback: 预提取的结构化反馈字典，可为 None（传入则跳过提取）。
        source: 任务来源标识（feedback/regenerate）。
    """
    trip_request = TripRequest(**request)
    prev_plan = TripPlan(**previous_plan)
    structured_input = StructuredFeedback(**structured_feedback) if structured_feedback else None

    lock = _get_revision_lock(plan_id)

    # 已有 revision 任务在跑则直接放弃
    if lock.locked():
        logger.warning(f"[Revision Lock] plan_id={plan_id} 已有修订任务在跑（来源={_revision_running.get(plan_id)}），"
                       f"新任务来源={source} 直接放弃")
        # 不修改 plan.status / 不创建新 revision，避免把正在跑的任务结果覆盖
        return

    async with lock:
        _revision_running[plan_id] = source
        # 进入锁之后立刻把 plan 标记为 revising，让 SSE 进度页能正确进入等待状态。
        # 若被锁拒绝，状态不会被修改，避免卡在 revising。
        async with AsyncSessionLocal() as session:
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                db_plan.status = "revising"
                await session.commit()
        try:
            result = await run_revision_graph(
                plan_id=plan_id,
                request=trip_request,
                user_id=user_id,
                parent_revision_id=parent_revision_id,
                previous_plan=prev_plan,
                revision_notes=revision_notes,
                feedback_day_index=feedback_day_index,
                feedback_tags=feedback_tags,
                structured_feedback=structured_input
            )

            if result:
                _, structured_result = result
                async with AsyncSessionLocal() as session:
                    memory_service = MemoryService()
                    # 回写结构化反馈（仅针对单条反馈）
                    if feedback_id is not None and structured_result:
                        await memory_service.update_feedback_structured(
                            session,
                            feedback_id=feedback_id,
                            structured_feedback=structured_result
                        )
                    # 找到刚创建的最新版本
                    current_revision = await memory_service.get_current_revision(session, plan_id)
                    if current_revision and feedback_id is not None:
                        await memory_service.update_feedback_revision_result(
                            session,
                            feedback_id=feedback_id,
                            revision_type=current_revision.source,
                            accepted_revision_id=current_revision.id
                        )
                        await session.commit()
        except Exception as exc:
            logger.exception(f"[Background Revision Task] 修订任务 {plan_id} 执行失败: {exc}")
            async with AsyncSessionLocal() as session:
                db_plan = await session.get(TripPlanDB, plan_id)
                if db_plan:
                    db_plan.status = "failed"
                    await session.commit()
        finally:
            # 无论成功失败都要清理 running 标记，锁会随 async with 自动释放
            _revision_running.pop(plan_id, None)


async def run_recalculate_task(
    ctx: dict,
    plan_id: str,
    request: dict,
    user_id: int,
    parent_revision_id: int,
    previous_plan: dict,
    revision_notes: str,
    day_attractions: list
) -> None:
    """
    行程重算任务：执行 RouteAgent + PlannerAgent 轻量重算链路并落新版本。

    与 run_revision_task 共用 per-plan_id 互斥锁：重算与修订不允许并行，
    避免两个任务同时写新版本互相覆盖。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典。
        user_id: 用户 ID。
        parent_revision_id: 父版本 ID。
        previous_plan: TripPlan.model_dump(mode="json") 的字典（目标天顺序已重排）。
        revision_notes: 重算说明文本（含用户指定的新顺序）。
        day_attractions: 目标天重排后的景点列表（dict）。
    """
    trip_request = TripRequest(**request)
    prev_plan = TripPlan(**previous_plan)

    lock = _get_revision_lock(plan_id)

    # 已有 revision/recalculate 任务在跑则直接放弃
    if lock.locked():
        logger.warning(f"[Revision Lock] plan_id={plan_id} 已有修订任务在跑（来源={_revision_running.get(plan_id)}），"
                       f"重算任务直接放弃")
        return

    async with lock:
        _revision_running[plan_id] = "recalculate"
        # 进入锁之后立刻把 plan 标记为 revising，前端轮询能看到等待状态
        async with AsyncSessionLocal() as session:
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                db_plan.status = "revising"
                await session.commit()
        try:
            await run_recalculate_graph(
                plan_id=plan_id,
                request=trip_request,
                user_id=user_id,
                parent_revision_id=parent_revision_id,
                previous_plan=prev_plan,
                revision_notes=revision_notes,
                day_attractions=day_attractions
            )
        except Exception as exc:
            logger.exception(f"[Background Recalculate Task] 重算任务 {plan_id} 执行失败: {exc}")
            async with AsyncSessionLocal() as session:
                db_plan = await session.get(TripPlanDB, plan_id)
                if db_plan:
                    db_plan.status = "failed"
                    await session.commit()
        finally:
            _revision_running.pop(plan_id, None)


async def run_crawler_task(ctx: dict, cities: Optional[List[str]], max_pages: Optional[int]) -> Dict:
    """
    爬虫任务：抓取城市攻略并入向量库（由 Worker 进程执行）。

    返回值会被 arq 存为 job result，供 get_job_status 读取。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。
        cities: 目标城市列表，None 表示默认热门城市。
        max_pages: 最大抓取页面数。

    Returns:
        Dict: 抓取结果统计（城市列表、文档数等）。
    """
    logger.info(f"[Crawler Task] 开始抓取 cities={cities} max_pages={max_pages}")
    service = CrawlerService()
    result = await service.crawl_city_guides(cities=cities, max_pages=max_pages)
    logger.info(f"[Crawler Task] 抓取完成 documents_added={result.get('documents_added')}")
    return result


# ==================== 天气联动检查任务（出发前提醒 + 自动改线） ====================


def _is_rainy(forecast_day: Dict[str, Any]) -> bool:
    """
    纯函数：判断单日预报是否为雨天（白天或夜间天气含"雨"字）。

    Args:
        forecast_day: 高德预报的单日条目，含 day_weather / night_weather。

    Returns:
        bool: 是否下雨。
    """
    return (
        "雨" in (forecast_day.get("day_weather") or "")
        or "雨" in (forecast_day.get("night_weather") or "")
    )


def _find_rainy_dates(
    forecasts: List[Dict[str, Any]],
    start_date: str,
    end_date: str
) -> List[str]:
    """
    纯函数：从高德预报中筛出行程期间（含起止日）内的雨天日期。

    Args:
        forecasts: 高德天气返回的 forecasts 数组（date/day_weather/night_weather）。
        start_date: 行程开始日期（YYYY-MM-DD）。
        end_date: 行程结束日期（YYYY-MM-DD）。

    Returns:
        List[str]: 雨天日期列表，按日期升序。
    """
    rainy = []
    for day in forecasts:
        date = day.get("date")
        if not date:
            continue
        # 日期为 ISO 字符串，字符串比较即时间先后比较
        if start_date <= date <= end_date and _is_rainy(day):
            rainy.append(date)
    return sorted(rainy)


def _format_rainy_revision_note(rainy_dates: List[str], start_date: str) -> str:
    """
    纯函数：生成"雨天自动改线"的修订说明文本（带第 X 天标注）。

    Args:
        rainy_dates: 雨天日期列表（YYYY-MM-DD）。
        start_date: 行程开始日期，用于换算第几天。

    Returns:
        str: 如"第2天(2026-10-02)预报有雨，请将当天户外景点替换为博物馆/美术馆等室内景点，并适当调整顺序"。
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    parts = []
    for date in rainy_dates:
        try:
            day_index = (datetime.strptime(date, "%Y-%m-%d") - start).days + 1
            parts.append(f"第{day_index}天({date})")
        except ValueError:
            parts.append(date)
    joined = "、".join(parts)
    return f"{joined}预报有雨，请将当天户外景点替换为博物馆/美术馆等室内景点，并适当调整顺序"


async def run_weather_check_task(ctx: dict) -> Dict[str, int]:
    """
    出发前天气检查任务（每日 8 点定时执行，Worker 启动时也执行一次）。

    流程：
    1. 查询 status="completed" 且出发日期在明天~未来 3 天内（含明天，不含今天）的行程；
    2. 对每个行程调高德天气接口，筛出行程日期内的雨天；
    3. 有雨才行动：按 dedup_key 去重后写入站内通知，并投递自动改线修订任务
       （复用 enqueue_revision_task，revision_notes 写明雨天日期与替换要求）。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。

    Returns:
        Dict[str, int]: {"checked": 检查的行程数, "notified": 发出的通知数}。
    """
    logger.info("[Weather Check] 开始出发前天气检查")
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    horizon = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    checked = 0
    notified = 0

    try:
        # 查询即将出发的已完成行程（start_date 为 ISO 字符串，字符串比较即日期比较）
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TripPlanDB).where(
                    TripPlanDB.status == "completed",
                    TripPlanDB.start_date >= tomorrow,
                    TripPlanDB.start_date <= horizon,
                )
            )
            plans = list(result.scalars().all())

        for plan in plans:
            checked += 1
            try:
                raw_weather = await get_weather(plan.city)
            except Exception as exc:
                logger.warning(f"[Weather Check] {plan.id} 天气查询失败，跳过: {exc}")
                continue

            forecasts = raw_weather.get("forecasts", []) if isinstance(raw_weather, dict) else []
            rainy_dates = _find_rainy_dates(forecasts, plan.start_date, plan.end_date)
            if not rainy_dates:
                continue

            note = _format_rainy_revision_note(rainy_dates, plan.start_date)
            dedup_key = f"{plan.id}:weather:{plan.start_date}"
            async with AsyncSessionLocal() as session:
                # 同一行程同一出发日期只提醒一次
                exists = await session.execute(
                    select(PlanNotification.id).where(PlanNotification.dedup_key == dedup_key)
                )
                if exists.scalar_one_or_none():
                    continue

                session.add(PlanNotification(
                    user_id=plan.user_id,
                    plan_id=plan.id,
                    type="weather",
                    title="出发前天气提醒",
                    content=(
                        f"您的行程（{plan.city}，{plan.start_date} 出发）中，{note}。"
                        f"雨天出行请携带雨具，建议提前确认室内景点开放时间。"
                    ),
                    dedup_key=dedup_key
                ))
                await session.commit()
                notified += 1

                # 复用修订链路触发自动改线：previous_plan / parent_revision_id 取当前生效版本
                try:
                    current_revision = await MemoryService().get_current_revision(session, plan.id)
                    if current_revision and plan.request_data:
                        await enqueue_revision_task(
                            plan_id=plan.id,
                            request=plan.request_data,
                            user_id=plan.user_id,
                            parent_revision_id=current_revision.id,
                            previous_plan=current_revision.trip_plan_json,
                            revision_notes=note,
                            feedback_id=None,
                            feedback_day_index=None,
                            feedback_tags=[],
                            structured_feedback=None,
                            source="weather",
                        )
                    else:
                        logger.warning(f"[Weather Check] {plan.id} 无当前版本或 request_data，跳过自动改线")
                except Exception as exc:
                    # 通知已发出，改线投递失败不回滚，仅记录告警
                    logger.warning(f"[Weather Check] {plan.id} 自动改线任务投递失败: {exc}")

    except Exception as exc:
        logger.exception(f"[Weather Check] 天气检查任务失败: {exc}")

    logger.info(f"[Weather Check] 检查完成 checked={checked} notified={notified}")
    return {"checked": checked, "notified": notified}
