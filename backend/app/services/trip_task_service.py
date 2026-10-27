"""
backend/app/services/trip_task_service.py

后台任务领域服务模块。

作用：
- 承接 app/tasks.py 各后台任务体内的业务逻辑，让 tasks.py 只保留任务入口薄壳；
- revision/recalculate 共用的 per-plan_id 进程内互斥锁与运行标记管理；
- 行程状态落库（revising/failed）与修订反馈结果回写；
- 出发前天气检查全流程（查待出发行程 → 高德天气 → 雨天判定 → 站内通知去重落库
  → 投递自动改线修订任务）；
- 游记生成全流程（行程/打卡加载 → LLM 分节游记 → 失败降级拼接 → 状态回写）。

分层说明：
- 本模块属 services 层，禁止 import app.planning / app.tasks / app.api（check_layers 强制）；
- 天气数据统一走 AmapService（app/planning/tools 的 get_weather 亦为其薄封装，行为一致）。

对应技术：SQLAlchemy 异步 ORM、ARQ 队列（enqueue_revision_task）、LangChain LLM。
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.agentkit.checkpoint import decode_state, list_resumable_plans
from app.core.db.session import AsyncSessionLocal
from app.core.utils.queue import enqueue_revision_task
from app.llm.client import get_llm
from app.models.db_models import PlanNotification, TripCheckin, TripJournal, TripPlanDB
from app.services.amap_service import AmapService
from app.services.memory_service import MemoryService

# ==================== Revision/Recalculate 任务并发控制（Worker 进程内） ====================
# 同一 plan_id 同时只允许一个 revision/recalculate 任务在跑。
# 设计要点：
# 1. 用 per-plan_id 的 asyncio.Lock 做互斥，任务开始前非阻塞检查，已占用则放弃；
# 2. 用 _revision_running 记录"正在跑的 revision 任务来源"，便于日志排查；
# 3. 任务结束（无论成功 / 失败 / 异常）都必须清理 running 标记，锁随调用方 async with 释放。
_revision_locks: dict[str, asyncio.Lock] = {}
_revision_running: dict[str, str] = {}  # plan_id -> 来源标识（feedback/regenerate/weather/recalculate）


def get_revision_lock(plan_id: str) -> asyncio.Lock:
    """
    获取（或惰性创建）指定 plan_id 的 revision 任务锁。
    """
    lock = _revision_locks.get(plan_id)
    if lock is None:
        lock = asyncio.Lock()
        _revision_locks[plan_id] = lock
    return lock


def revision_running_source(plan_id: str) -> str | None:
    """返回当前占用 plan_id 的 revision 任务来源，空闲时为 None。"""
    return _revision_running.get(plan_id)


def mark_revision_running(plan_id: str, source: str) -> None:
    """进入锁之后标记正在运行的任务来源（供新任务被拒绝时的告警展示）。"""
    _revision_running[plan_id] = source


def clear_revision_running(plan_id: str) -> None:
    """任务结束（成功/失败/异常）时清理运行标记；锁由调用方的 async with 释放。"""
    _revision_running.pop(plan_id, None)


# ==================== 行程状态与修订结果回写 ====================


async def set_plan_status(plan_id: str, status: str) -> None:
    """更新行程状态（行程不存在时静默跳过）。"""
    async with AsyncSessionLocal() as session:
        db_plan = await session.get(TripPlanDB, plan_id)
        if db_plan:
            db_plan.status = status
            await session.commit()


async def writeback_revision_feedback(
    plan_id: str,
    feedback_id: int | None,
    structured_result: dict[str, Any] | None,
) -> None:
    """
    修订完成后回写反馈结果：结构化反馈与实际采用的版本号。

    仅针对单条反馈（feedback_id 为 None 的聚合反馈不回写，直接返回）。
    """
    if feedback_id is None:
        return
    async with AsyncSessionLocal() as session:
        memory_service = MemoryService()
        # 回写结构化反馈（仅针对单条反馈）
        if structured_result:
            await memory_service.update_feedback_structured(
                session, feedback_id=feedback_id, structured_feedback=structured_result
            )
        # 找到刚创建的最新版本并回写采纳结果
        current_revision = await memory_service.get_current_revision(session, plan_id)
        if current_revision:
            await memory_service.update_feedback_revision_result(
                session,
                feedback_id=feedback_id,
                revision_type=current_revision.source,
                accepted_revision_id=current_revision.id,
            )
            await session.commit()


# ==================== 天气联动检查（出发前提醒 + 自动改线） ====================


def _is_rainy(forecast_day: dict[str, Any]) -> bool:
    """
    纯函数：判断单日预报是否为雨天（白天或夜间天气含"雨"字）。

    Args:
        forecast_day: 高德预报的单日条目，含 day_weather / night_weather。

    Returns:
        bool: 是否下雨。
    """
    return "雨" in (forecast_day.get("day_weather") or "") or "雨" in (
        forecast_day.get("night_weather") or ""
    )


def _find_rainy_dates(forecasts: list[dict[str, Any]], start_date: str, end_date: str) -> list[str]:
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


def _format_rainy_revision_note(rainy_dates: list[str], start_date: str) -> str:
    """
    纯函数：生成"雨天自动改线"的修订说明文本（带第 X 天标注）。

    Args:
        rainy_dates: 雨天日期列表（YYYY-MM-DD）。
        start_date: 行程开始日期，用于换算第几天。

    Returns:
        str: 如"第2天(2026-10-02)预报有雨，请将当天户外景点替换为博物馆/美术馆等室内景点，
            并适当调整顺序"。
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


async def run_weather_check() -> dict[str, int]:
    """
    出发前天气检查（每日 8 点定时执行，Worker 启动时也执行一次）。

    流程：
    1. 查询 status="completed" 且出发日期在明天~未来 3 天内（含明天，不含今天）的行程；
    2. 对每个行程调高德天气接口，筛出行程日期内的雨天；
    3. 有雨才行动：按 dedup_key 去重后写入站内通知，并投递自动改线修订任务
       （复用 enqueue_revision_task，revision_notes 写明雨天日期与替换要求）。

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

        amap_service = AmapService()
        for plan in plans:
            checked += 1
            try:
                # 与 app/agents/tools.get_weather 行为一致（该函数即此调用的薄封装）
                raw_weather = await amap_service.get_weather(plan.city, forecast=True)
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

                session.add(
                    PlanNotification(
                        user_id=plan.user_id,
                        plan_id=plan.id,
                        type="weather",
                        title="出发前天气提醒",
                        content=(
                            f"您的行程（{plan.city}，{plan.start_date} 出发）中，{note}。"
                            f"雨天出行请携带雨具，建议提前确认室内景点开放时间。"
                        ),
                        dedup_key=dedup_key,
                    )
                )
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
                        logger.warning(
                            f"[Weather Check] {plan.id} 无当前版本或 request_data，跳过自动改线"
                        )
                except Exception as exc:
                    # 通知已发出，改线投递失败不回滚，仅记录告警
                    logger.warning(f"[Weather Check] {plan.id} 自动改线任务投递失败: {exc}")

    except Exception as exc:
        logger.exception(f"[Weather Check] 天气检查任务失败: {exc}")

    logger.info(f"[Weather Check] 检查完成 checked={checked} notified={notified}")
    return {"checked": checked, "notified": notified}


# ==================== 游记生成 ====================


def _extract_json(text: str) -> dict | None:
    """
    从 LLM 输出中提取 JSON 对象（容忍 ```json 围栏与前后杂文本）。

    Args:
        text: LLM 原始输出。

    Returns:
        Optional[dict]: 解析成功返回 dict，失败返回 None。
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_journal_fallback(plan_data: dict, checkins: list[TripCheckin]) -> dict:
    """
    降级生成：LLM 失败时用行程每日描述 + 打卡感想拼接分节游记。

    Args:
        plan_data: 行程 JSON。
        checkins: 打卡记录列表。

    Returns:
        dict: {title, sections}。
    """
    city = plan_data.get("city", "旅行")
    day_plans = plan_data.get("day_plans", []) or []
    photos_by_day: dict[int, list[str]] = {}
    for c in checkins:
        if c.day_index and c.photo_urls:
            photos_by_day.setdefault(c.day_index, []).extend(c.photo_urls[:3])

    sections = [
        {
            "day_index": None,
            "title": "序",
            "text": f"这次 {city} 之旅共 {plan_data.get('travel_days', len(day_plans))} 天，"
            "把路上的打卡与感想整理成册，留作纪念。",
            "photos": [],
        }
    ]
    for day in day_plans:
        day_index = day.get("day_index")
        names = [a.get("name", "") for a in day.get("attractions", []) if a.get("name")]
        notes = [c.note for c in checkins if c.day_index == day_index and c.note]
        text_parts = [f"第 {day_index} 天，{'、'.join(names) if names else '自由活动'}。"]
        if notes:
            text_parts.append("当天感想：" + "；".join(notes))
        sections.append(
            {
                "day_index": day_index,
                "title": f"第 {day_index} 天 · {day.get('city') or city}",
                "text": "".join(text_parts),
                "photos": photos_by_day.get(day_index, []),
            }
        )

    return {"title": f"{city} 之旅", "sections": sections}


def _summarize_plan_for_prompt(plan_data: dict) -> str:
    """把行程 JSON 压缩为 LLM 可读的逐天文本摘要（只保留名称/日期/描述，控制 token）。"""
    lines = [
        f"目的地：{plan_data.get('city')}",
        f"日期：{plan_data.get('start_date')} 至 {plan_data.get('end_date')}"
        f"（{plan_data.get('travel_days')} 天）",
    ]
    for day in plan_data.get("day_plans", []) or []:
        spots = "、".join(a.get("name", "") for a in day.get("attractions", []) if a.get("name"))
        meals = "、".join(m.get("name") or m.get("type", "") for m in day.get("meals", []))
        lines.append(
            f"第{day.get('day_index')}天({day.get('date')})：景点[{spots}] 餐饮[{meals}]"
            f" 住宿[{(day.get('hotel') or {}).get('name', '')}]"
        )
    return "\n".join(lines)


def _summarize_checkins_for_prompt(checkins: list[TripCheckin]) -> str:
    """把打卡记录压缩为逐条文本（含感想），无打卡时返回提示。"""
    if not checkins:
        return "（用户没有留下打卡记录，请仅根据行程安排创作）"
    lines = []
    for c in checkins:
        note = f"，感想：{c.note}" if c.note else ""
        lines.append(f"第{c.day_index}天打卡「{c.spot_name}」{note}")
    return "\n".join(lines)


async def generate_journal(plan_id: str, journal_id: str) -> None:
    """
    游记生成：行程 JSON + 打卡记录 → LLM 分节图文游记。

    成功回写 title/content/status=done；LLM 解析失败降级为"逐天摘要拼接"
    （仍标记 done，保证用户能拿到结果）；任务整体异常时标记 failed 允许重试。

    Args:
        plan_id: 行程计划 ID。
        journal_id: 游记记录 ID（回写目标）。
    """
    try:
        async with AsyncSessionLocal() as session:
            journal = await session.get(TripJournal, journal_id)
            if not journal:
                logger.warning(f"[Journal Task] 游记 {journal_id} 不存在，跳过")
                return

            plan = await session.get(TripPlanDB, plan_id)
            if not plan:
                await _mark_journal(session, journal, "failed", None)
                return

            # 取当前生效版本的行程 JSON
            memory_service = MemoryService()
            current_revision = await memory_service.get_current_revision(session, plan_id)
            plan_data = (
                current_revision.trip_plan_json if current_revision else plan.plan_data
            ) or {}
            if not plan_data:
                await _mark_journal(session, journal, "failed", None)
                return

            checkin_result = await session.execute(
                select(TripCheckin)
                .where(TripCheckin.plan_id == plan_id)
                .order_by(TripCheckin.day_index, TripCheckin.checkin_at)
            )
            checkins = list(checkin_result.scalars().all())

            # LLM 生成（失败降级拼接）
            try:
                llm = get_llm(temperature=0.7)
                prompt = (
                    "你是一位游记作者。请根据下面的行程安排与打卡记录，写一篇第一人称旅行游记。\n"
                    "要求：\n"
                    "1. 每个行程天写一节，融入打卡感想，每节 150-250 字，语言生动自然；\n"
                    "2. 开头加一节序（day_index 用 null），结尾加一节尾声（day_index 用 null）；\n"
                    "3. 严格输出 JSON，格式：\n"
                    '{"title": "游记标题", "sections": '
                    '[{"day_index": 1, "title": "节标题", "text": "节正文"}]}\n'
                    "4. 只输出 JSON，不要任何其他文字。\n\n"
                    f"【行程安排】\n{_summarize_plan_for_prompt(plan_data)}\n\n"
                    f"【打卡记录】\n{_summarize_checkins_for_prompt(checkins)}"
                )
                response = await llm.ainvoke(prompt)
                raw_text = response.content if hasattr(response, "content") else str(response)
                parsed = _extract_json(raw_text)
                sections = []
                if parsed and isinstance(parsed.get("sections"), list):
                    photos_by_day: dict[int, list[str]] = {}
                    for c in checkins:
                        if c.day_index and c.photo_urls:
                            photos_by_day.setdefault(c.day_index, []).extend(c.photo_urls[:3])
                    for s in parsed["sections"]:
                        if not isinstance(s, dict) or not s.get("title") or not s.get("text"):
                            continue
                        day_index = s.get("day_index")
                        is_day = isinstance(day_index, int)
                        sections.append(
                            {
                                "day_index": day_index if is_day else None,
                                "title": str(s["title"])[:120],
                                "text": str(s["text"]),
                                "photos": photos_by_day.get(day_index, []) if is_day else [],
                            }
                        )
                if sections:
                    result = {
                        "title": str(parsed.get("title", ""))[:200] if parsed else "",
                        "sections": sections,
                    }
                else:
                    result = _build_journal_fallback(plan_data, checkins)
            except Exception as exc:
                logger.warning(f"[Journal Task] LLM 生成失败，降级拼接: {exc}")
                result = _build_journal_fallback(plan_data, checkins)

            await _mark_journal(session, journal, "done", result)
            logger.info(f"[Journal Task] 游记 {journal_id} 生成完成（plan={plan_id}）")

    except Exception as exc:
        logger.exception(f"[Journal Task] 游记生成任务 {journal_id} 执行失败: {exc}")
        async with AsyncSessionLocal() as session:
            journal = await session.get(TripJournal, journal_id)
            if journal:
                await _mark_journal(session, journal, "failed", None)


async def _mark_journal(session, journal: TripJournal, status: str, result: dict | None) -> None:
    """回写游记状态：done 时写入标题/分节/生成时间，failed 时仅置状态。"""
    journal.status = status
    if status == "done" and result:
        journal.title = result.get("title", "")
        journal.content = result.get("sections", [])
        journal.generated_at = datetime.now()
    await session.commit()



async def find_resumable_plans() -> list[dict]:
    """
    【函数作用】M2 断点续跑：扫描 worker 异常中断的规划任务。

    判定条件：plan_checkpoints 存在 planning 快照 且 行程状态仍为 running
    （正常完成/失败都会清快照或改状态）。返回重新入队所需的最小参数集。

    【返回值】
    - list[dict]：[{plan_id, start_batch, request, user_id}]；request 为
      TripRequest 的 JSON 字典，快照损坏时跳过该条。
    """
    result: list[dict] = []
    for item in await list_resumable_plans():
        try:
            state = decode_state(item["state_snapshot"])
            request = state.get("request")
            request_dict = (
                request.model_dump(mode="json") if hasattr(request, "model_dump") else None
            )
        except Exception as exc:
            logger.warning(f"[Resume] 快照解码失败 plan={item['plan_id']}，跳过: {exc}")
            continue
        if request_dict is None:
            continue
        result.append(
            {
                "plan_id": item["plan_id"],
                "start_batch": item["batch_index"] + 1,
                "request": request_dict,
                "user_id": item["user_id"],
            }
        )
    return result
