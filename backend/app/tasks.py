"""
backend/app/tasks.py

后台任务定义模块（由 ARQ Worker 进程执行）。

作用：
- 定义 6 个后台任务入口：规划 run_planning_task、修订 run_revision_task、
  重算 run_recalculate_task、爬虫 run_crawler_task、天气检查 run_weather_check_task、
  游记生成 run_journal_task；任务函数名与参数签名即 arq 任务名的载体，
  worker.py 按函数名注册消费队列，严禁改名或改签名；
- 任务入口保持薄壳：入参反序列化 → 调用 agents/graph 或 services 执行 → 返回；
- 业务逻辑归位：锁管理 / 状态回写 / 天气检查 / 游记生成等下沉至
  app/services/trip_task_service.py；graph 编排调用保留在本模块
  （tasks 属编排层，可直接 import agents；services 层则禁止 import agents）。

对应技术：
- arq：任务函数第一个参数固定为 ctx（Worker 上下文），入参需可 JSON/Pickle 序列化
"""

from loguru import logger

from app.models.schemas import StructuredFeedback, TripPlan, TripRequest
from app.planning.graph import run_planning_graph, run_recalculate_graph, run_revision_graph
from app.services.crawler_service import CrawlerService
from app.services.trip_task_service import (
    clear_revision_running,
    generate_journal,
    get_revision_lock,
    mark_revision_running,
    revision_running_source,
    run_weather_check,
    set_plan_status,
    writeback_revision_feedback,
)


async def run_planning_task(
    ctx: dict,
    plan_id: str,
    request: dict,
    user_id: int,
    start_batch: int | None = None,
    approval_decision: str | None = None,
) -> None:
    """
    初始规划任务：执行 LangGraph 规划链路并持久化结果。

    任务异常会被捕获并记录，避免 arq 将任务标记为失败后重复重试。
    start_batch 为断点续跑起始批次（M2），None 表示全新执行；
    approval_decision 为审批决策（M3），审批通过续跑时为 approved，
    由 graph 注入 state["human_decisions"] 后从 finalize 批次继续。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典。
        user_id: 用户 ID。
        start_batch: 断点续跑起始批次；None 表示从头执行。
        approval_decision: 审批决策（approved）；None 表示非审批续跑。
    """
    try:
        await run_planning_graph(
            plan_id,
            TripRequest(**request),
            user_id,
            start_batch=start_batch,
            approval_decision=approval_decision,
        )
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
    feedback_id: int | None,
    feedback_day_index: int | None,
    feedback_tags: list[str],
    structured_feedback: dict | None = None,
    source: str = "feedback",
) -> None:
    """
    行程修订任务：执行 LangGraph 修订链路并回写反馈结果。

    完成后由 trip_task_service 回写 PlanFeedback 的 structured_feedback
    与 accepted_revision_id；若为聚合反馈（feedback_id 为 None），则不回写单条反馈记录。

    并发控制（锁与运行标记管理见 trip_task_service）：
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

    lock = get_revision_lock(plan_id)

    # 已有 revision 任务在跑则直接放弃
    if lock.locked():
        logger.warning(
            f"[Revision Lock] plan_id={plan_id} 已有修订任务在跑"
            f"（来源={revision_running_source(plan_id)}），新任务来源={source} 直接放弃"
        )
        # 不修改 plan.status / 不创建新 revision，避免把正在跑的任务结果覆盖
        return

    async with lock:
        mark_revision_running(plan_id, source)
        # 进入锁之后立刻把 plan 标记为 revising，让 SSE 进度页能正确进入等待状态。
        # 若被锁拒绝，状态不会被修改，避免卡在 revising。
        await set_plan_status(plan_id, "revising")
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
                structured_feedback=structured_input,
            )
            if result:
                _, structured_result = result
                await writeback_revision_feedback(plan_id, feedback_id, structured_result)
        except Exception as exc:
            logger.exception(f"[Background Revision Task] 修订任务 {plan_id} 执行失败: {exc}")
            await set_plan_status(plan_id, "failed")
        finally:
            # 无论成功失败都要清理 running 标记，锁会随 async with 自动释放
            clear_revision_running(plan_id)


async def run_recalculate_task(
    ctx: dict,
    plan_id: str,
    request: dict,
    user_id: int,
    parent_revision_id: int,
    previous_plan: dict,
    revision_notes: str,
    day_attractions: list,
) -> None:
    """
    行程重算任务：执行 RouteAgent + PlannerAgent 轻量重算链路并落新版本。

    与 run_revision_task 共用 per-plan_id 互斥锁（管理逻辑在 trip_task_service）：
    重算与修订不允许并行，避免两个任务同时写新版本互相覆盖。

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

    lock = get_revision_lock(plan_id)

    # 已有 revision/recalculate 任务在跑则直接放弃
    if lock.locked():
        logger.warning(
            f"[Revision Lock] plan_id={plan_id} 已有修订任务在跑"
            f"（来源={revision_running_source(plan_id)}），重算任务直接放弃"
        )
        return

    async with lock:
        mark_revision_running(plan_id, "recalculate")
        # 进入锁之后立刻把 plan 标记为 revising，前端轮询能看到等待状态
        await set_plan_status(plan_id, "revising")
        try:
            await run_recalculate_graph(
                plan_id=plan_id,
                request=trip_request,
                user_id=user_id,
                parent_revision_id=parent_revision_id,
                previous_plan=prev_plan,
                revision_notes=revision_notes,
                day_attractions=day_attractions,
            )
        except Exception as exc:
            logger.exception(f"[Background Recalculate Task] 重算任务 {plan_id} 执行失败: {exc}")
            await set_plan_status(plan_id, "failed")
        finally:
            clear_revision_running(plan_id)


async def run_crawler_task(
    ctx: dict, cities: list[str] | None, max_pages: int | None
) -> dict:
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


async def run_weather_check_task(ctx: dict) -> dict[str, int]:
    """
    出发前天气检查任务（每日 8 点定时执行，Worker 启动时也执行一次）。

    完整流程（查待出发行程 → 高德天气 → 雨天筛选 → 去重通知 → 投递自动改线）
    见 trip_task_service.run_weather_check。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。

    Returns:
        Dict[str, int]: {"checked": 检查的行程数, "notified": 发出的通知数}。
    """
    return await run_weather_check()


async def run_journal_task(ctx: dict, plan_id: str, journal_id: str, user_id: int) -> None:
    """
    游记生成任务：行程 JSON + 打卡记录 → LLM 分节图文游记。

    成功回写 title/content/status=done，失败降级或标记 failed，
    完整逻辑见 trip_task_service.generate_journal。

    Args:
        ctx: arq Worker 上下文（未使用，保持签名兼容）。
        plan_id: 行程计划 ID。
        journal_id: 游记记录 ID（回写目标）。
        user_id: 触发生成的用户 ID（不参与生成逻辑，保持签名兼容）。
    """
    await generate_journal(plan_id, journal_id)
