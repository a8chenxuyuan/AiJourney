"""planner_agent_node：行程编排节点（核心），调 LLM 生成 TripPlan，含多城联游与修订重排分支。"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务
import asyncio

# json 模块：用于 POI 摘要等场景的 JSON 序列化
# time 模块：提供时间相关函数，用于计算代码执行耗时
import time

# uuid 模块：生成唯一标识符，用于为缺少 ID 的数据生成临时 ID
import uuid

# datetime 模块：处理日期和时间，用于解析用户输入的日期和计算旅行天数
from datetime import datetime, timedelta
from types import SimpleNamespace

# typing 模块：提供类型提示支持，使代码更清晰、更易维护
from typing import Any

# ==================== LangChain 核心导入 ====================
# HumanMessage：代表用户输入的消息，供 LLM 理解用户意图
# SystemMessage：代表系统指令消息，用于设置 LLM 的角色和行为规范
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.agentkit.context.manager import context_manager
from app.agentkit.events import TOKEN_DELTA, publish

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好
# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型
from app.core.utils.json_parser import parse_llm_json

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM
from app.llm.client import get_llm
from app.llm.usage import record_llm_usage, usage_recorder

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Attraction,  # 景点数据模型，包含名称、位置、门票、评分等字段
    CityStay,  # 多城市联游的单城市停留安排（城市 + 天数）
    DayPlan,  # 单日行程计划模型，包含当天的景点、餐饮、酒店
    IntentAnalysis,  # 意图分析结果模型，从用户表单解析出的结构化数据
    Location,  # 位置数据模型，包含经度、纬度、地址
    TripPlan,  # 完整行程计划模型，包含多天行程、预算、建议
    WeatherInfo,  # 天气信息模型，包含日期、天气描述、温度、风力
)

# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
from app.planning import prompts

# 包内共享的通用工具函数（未用到的名字由 ruff F401 自动清理）
from app.planning.agents._helpers import (
    _build_fallback_plan,
    _calculate_days,
    _enrich_day_plan_with_map_data,
    _enrich_plan_with_poi_details,
    _format_route_summary,
    _make_log,
    _summarize_poi_for_prompt,
)

# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
from app.planning.config import AgentConfig

# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.planning.state import TravelPlanningState


def _assign_day_city_ranges(
    cities: list[str], city_days: dict[str, int], travel_days: int
) -> dict[int, str]:
    """
    按城市停留天数顺序，把第 1..travel_days 天映射到所在城市。

    天数分配从第 1 天开始连续切片；若天数之和小于总天数（异常兜底），
    剩余天数归属最后一个城市。

    Args:
        cities: 有序城市列表。
        city_days: 城市 → 停留天数。
        travel_days: 总旅行天数。

    Returns:
        Dict[int, str]: day_index → 城市名。
    """
    mapping: dict[int, str] = {}
    day = 1
    for city in cities:
        for _ in range(city_days.get(city, 0)):
            if day > travel_days:
                return mapping
            mapping[day] = city
            day += 1
    # 兜底：城市天数之和不足时，剩余天归属最后一个城市
    while day <= travel_days and cities:
        mapping[day] = cities[-1]
        day += 1
    return mapping


def _format_cities_plan(
    cities: list[str], city_days: dict[str, int], day_city_map: dict[int, str]
) -> str:
    """
    把城市停留分配格式化为提示词文本，如"杭州：2 天（第1-2天）"。
    """
    lines = []
    days_sorted = sorted(day_city_map.keys())
    for city in cities:
        city_day_list = [d for d in days_sorted if day_city_map[d] == city]
        if city_day_list:
            days_text = (
                f"第{city_day_list[0]}-{city_day_list[-1]}天"
                if len(city_day_list) > 1
                else f"第{city_day_list[0]}天"
            )
        else:
            days_text = "无"
        lines.append(f"- {city}：{city_days.get(city, 0)} 天（{days_text}）")
    return "\n".join(lines)


def _format_intercity_legs(legs: list[dict[str, Any]]) -> str:
    """
    把城际大交通列表格式化为提示词文本；为空时给出占位说明。
    """
    if not legs:
        return "暂无城际交通信息。"
    lines = []
    for leg in legs:
        fallback = f"{leg.get('from_city')}→{leg.get('to_city')}"
        lines.append(f"- {leg.get('advice') or fallback}")
    return "\n".join(lines)


def _format_day_city_weather(
    day_city_map: dict[int, str],
    weather_by_city: dict[str, list[WeatherInfo]],
    start_date: str,
    travel_days: int,
) -> str:
    """
    按"天 → 所在城市"映射生成每日天气提示词文本。

    每天取该城市天气列表中日期匹配的记录；找不到时显示"暂无"。
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    lines = []
    for day in range(1, travel_days + 1):
        date_str = (start + timedelta(days=day - 1)).strftime("%Y-%m-%d")
        city = day_city_map.get(day, "")
        matched = next((w for w in (weather_by_city.get(city) or []) if w.date == date_str), None)
        if matched:
            lines.append(
                f'{{"day_index": {day}, "date": "{date_str}", "city": "{city}", '
                f'"weather": "{matched.weather}", "temperature": "{matched.temperature or ""}"}}'
            )
        else:
            lines.append(
                f'{{"day_index": {day}, "date": "{date_str}", "city": "{city}", "weather": "暂无"}}'
            )
    return "\n".join(lines)


def _format_city_sections(
    cities: list[str],
    city_days: dict[str, int],
    day_city_map: dict[int, str],
    attractions_by_city: dict[str, list[Any]],
    hotels_by_city: dict[str, list[Any]],
    restaurants_by_city: dict[str, list[Any]],
    rag_by_city: dict[str, str],
    route_matrix_by_city: dict[str, dict[str, Any]],
) -> str:
    """
    把各城市的候选景点/酒店/餐厅/攻略/路线矩阵汇总为提示词分节文本。

    POI 沿用 _summarize_poi_for_prompt 压缩，避免多城 prompt 膨胀。
    """
    days_sorted = sorted(day_city_map.keys())
    sections = []
    for city in cities:
        city_day_list = [d for d in days_sorted if day_city_map[d] == city]
        days_text = (
            f"第{city_day_list[0]}-{city_day_list[-1]}天"
            if len(city_day_list) > 1
            else f"第{city_day_list[0]}天"
        )
        attraction_lines = (
            "\n".join(
                _summarize_poi_for_prompt(a.model_dump())
                for a in (attractions_by_city.get(city) or [])[:12]
            )
            or "无"
        )
        hotel_lines = (
            "\n".join(
                _summarize_poi_for_prompt(h.model_dump())
                for h in (hotels_by_city.get(city) or [])[:4]
            )
            or "无"
        )
        restaurant_lines = (
            "\n".join(
                _summarize_poi_for_prompt(r.model_dump())
                for r in (restaurants_by_city.get(city) or [])[:12]
            )
            or "无"
        )
        route_summary = _format_route_summary(route_matrix_by_city.get(city) or {})
        sections.append(
            f"━━ 城市：{city}（停留 {city_days.get(city, 0)} 天，{days_text}）━━\n"
            f"【候选景点】\n{attraction_lines}\n"
            f"【候选酒店】\n{hotel_lines}\n"
            f"【候选餐厅】\n{restaurant_lines}\n"
            f"【路线矩阵摘要】\n{route_summary}\n"
            f"【城市攻略】\n{rag_by_city.get(city) or '无额外攻略信息。'}"
        )
    return "\n\n".join(sections)


async def _call_llm_streaming(
    plan_id: str | None, llm: Any, messages: list[Any], timeout: int
) -> Any:
    """
    流式调用 LLM 生成行程（M3 token 流）。

    逐 chunk 向唯一事件总线发布 token_delta 事件（协议贯通；SSE 传输订阅方
    不持久化该类型，后续前端流式渲染可直接订阅）；开始/结束各发一条粗粒度
    进度 log 事件进 SSE 进度流。

    返回聚合响应对象（content + 可选 usage_metadata），与 ainvoke 返回的
    AIMessage 读取口径兼容（record_llm_usage / parse_llm_json 均按属性读取）。
    百炼流式模式下用量信息在末尾 chunk 聚合，缺失时打点静默跳过。
    """
    start_log = _make_log(
        "PlannerAgent", "llm_stream_start", output_preview="开始流式生成行程方案…"
    )
    await publish(plan_id or "-", "log", **start_log.model_dump(mode="json"))
    chunks: list[str] = []
    last_chunk: Any = None

    async def _consume() -> None:
        nonlocal last_chunk
        async for chunk in llm.astream(messages):
            last_chunk = chunk
            text = chunk.content if isinstance(chunk.content, str) else str(chunk.content or "")
            if text:
                chunks.append(text)
                await publish(
                    plan_id or "-", TOKEN_DELTA, agent="PlannerAgent", chars=len(text)
                )

    await asyncio.wait_for(_consume(), timeout=timeout)
    total_chars = sum(len(c) for c in chunks)
    done_log = _make_log(
        "PlannerAgent", "llm_stream_done", output_preview=f"行程方案流式生成完成，共 {total_chars} 字符"
    )
    await publish(plan_id or "-", "log", **done_log.model_dump(mode="json"))
    return SimpleNamespace(
        content="".join(chunks), usage_metadata=getattr(last_chunk, "usage_metadata", None)
    )


async def _call_llm_for_plan(
    plan_id: str | None, messages: list[Any], tool_calls: list[dict[str, Any]]
) -> TripPlan | None:
    """
    调用 LLM 生成 TripPlan（带一次重试），解析失败返回 None。

    与单城 planner 的调用口径一致：temperature 0.4，首次 300 秒超时，重试 180 秒。
    """
    try:
        llm = get_llm(temperature=0.4, timeout=300, streaming=True)
        response = await _call_llm_streaming(plan_id, llm, messages, 300)
        record_llm_usage(plan_id or "-", "PlannerAgent", response)
        tool_calls.append({"tool": "llm", "preview": str(response.content)[:200]})
        plan = parse_llm_json(str(response.content), TripPlan)
        if plan is None:
            raise ValueError("LLM 输出解析为 TripPlan 失败，请检查 JSON 格式和字段类型")
        return plan
    except Exception as exc:
        logger.warning(f"[Node] 多城 planner LLM 调用或解析失败，尝试重试: {exc}")
        tool_calls.append({"tool": "llm", "error": str(exc)})
        try:
            retry_llm = get_llm(temperature=0.4, timeout=180)
            retry_response = await asyncio.wait_for(retry_llm.ainvoke(messages), timeout=180)
            plan = parse_llm_json(str(retry_response.content), TripPlan)
            if plan is None:
                raise ValueError("重试后 LLM 输出仍无法解析为 TripPlan")
            record_llm_usage(plan_id or "-", "PlannerAgent", retry_response)
            tool_calls.append({"tool": "llm_retry", "status": "success"})
            return plan
        except Exception as retry_exc:
            logger.exception(f"[Node] 多城 planner 重试仍失败: {retry_exc}")
            tool_calls.append({"tool": "llm_retry", "error": str(retry_exc)})
            return None


def _enforce_multi_city_must_visit(
    plan: TripPlan,
    intent: IntentAnalysis | None,
    attractions_by_city: dict[str, list[Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    """
    强制校验多城行程中的 must_visit 必去景点，缺失时补入对应城市天数中。

    优先把缺失景点插入"其所属城市、景点最少的那一天"；无法判断所属城市时
    插入全局景点最少的一天。
    """
    must_visit_names = [m.strip() for m in (intent.must_visit if intent else []) if m.strip()]
    if not must_visit_names or not plan.day_plans:
        return

    planned_names = {a.name.strip() for day in plan.day_plans for a in day.attractions}
    missing = [
        mv for mv in must_visit_names if not any(mv in pn or pn in mv for pn in planned_names)
    ]
    if not missing:
        return

    logger.info(f"[Node] 多城 planner 发现缺失的必去景点: {missing}")
    # 全城市候选池：景点名 → (景点对象, 所属城市)
    candidate_map: dict[str, tuple[Any, str]] = {}
    for city, pool in (attractions_by_city or {}).items():
        for cand in pool:
            if cand.name and cand.name.strip():
                candidate_map[cand.name.strip()] = (cand, city)

    for mv_name in missing:
        matched = None
        matched_city = ""
        for cand_name, (cand, city) in candidate_map.items():
            if mv_name in cand_name or cand_name in mv_name:
                matched, matched_city = cand, city
                break

        if matched is None:
            # 候选池也没有：构造占位景点，位置用首日酒店或原点
            default_location = Location(longitude=0, latitude=0, address=None)
            if plan.day_plans and plan.day_plans[0].hotel and plan.day_plans[0].hotel.location:
                default_location = plan.day_plans[0].hotel.location
            matched = Attraction(
                id=f"attr_must_{uuid.uuid4().hex[:8]}",
                name=mv_name,
                location=default_location,
                description=f"{mv_name} 是您指定的必去景点。",
                duration="2 小时",
                tags=["必去景点"],
            )

        # 目标天：所属城市内景点最少的一天；未知城市则全局最少
        target_candidates = [d for d in plan.day_plans if d.city and d.city == matched_city]
        target_day = min(target_candidates or plan.day_plans, key=lambda d: len(d.attractions))
        target_day.attractions.append(matched)
        logger.info(
            f"[Node] 多城 planner 将必去景点 {mv_name} "
            f"插入第 {target_day.day_index} 天（{target_day.city}）"
        )

    tool_calls.append({"tool": "must_visit_enforce", "inserted": missing})


def _normalize_multi_city_plan(
    plan: TripPlan, state: TravelPlanningState, day_city_map: dict[int, str], travel_days: int
) -> None:
    """
    把 LLM（或 fallback）生成的多城行程规范化：
    1. 每天的 city 以天数分配为准强制写回；
    2. 换城日补 intercity_note（LLM 未填时取 intercity_legs 的建议文案）；
    3. 用当天所在城市的路线矩阵补地图数据（中心点 / polyline）；
    4. 补齐缺失的 day_index 天（LLM 少写天数时按城市候选资源兜底为空行程）。
    """
    intercity_legs = state.get("intercity_legs") or []
    legs_by_pair = {(leg.get("from_city"), leg.get("to_city")): leg for leg in intercity_legs}
    route_matrix_by_city = state.get("route_matrix_by_city") or {}

    existing_days = {day.day_index: day for day in plan.day_plans}
    normalized: list[DayPlan] = []
    for day_index in range(1, travel_days + 1):
        day = existing_days.get(day_index)
        if day is None:
            # LLM 漏掉该天：生成占位空行程，保证 day_plans 连续
            day = DayPlan(
                day_index=day_index, date="", description="（该天行程生成缺失，请手动补充）"
            )
        day.city = day_city_map.get(day_index, day.city)
        normalized.append(day)
    plan.day_plans = normalized

    # 换城日补城际交通说明
    for i in range(1, len(plan.day_plans)):
        day = plan.day_plans[i]
        prev_day = plan.day_plans[i - 1]
        from_city = day_city_map.get(prev_day.day_index) or prev_day.city
        to_city = day_city_map.get(day.day_index) or day.city
        if from_city and to_city and from_city != to_city and not day.intercity_note:
            leg = legs_by_pair.get((from_city, to_city))
            day.intercity_note = (
                leg["advice"] if leg else f"{from_city}→{to_city}：请提前查询城际交通班次。"
            )

    # 按天所在城市的路线矩阵补地图数据，并补回 POI 详细字段（跨城合并候选池）
    for day in plan.day_plans:
        _enrich_day_plan_with_map_data(day, route_matrix_by_city.get(day.city or "", {}) or {})

    merged_state = dict(state)
    merged_state["attractions"] = [
        a for pool in (state.get("attractions_by_city") or {}).values() for a in pool
    ]
    merged_state["hotels"] = [
        h for pool in (state.get("hotels_by_city") or {}).values() for h in pool
    ]
    merged_state["restaurants"] = [
        r for pool in (state.get("restaurants_by_city") or {}).values() for r in pool
    ]
    _enrich_plan_with_poi_details(plan, merged_state)


def _build_revision_context_block(previous_plan: Any, revision_notes: str) -> str:
    """
    构建追加到 planner 提示词末尾的修订上下文文本（单城/多城 planner 共用）。

    只提取上一版行程的精简摘要（每天城市 + 景点 + 餐厅 + 酒店名称），
    避免把整份 JSON 塞进 prompt 导致 LLM 调用超时。

    Args:
        previous_plan: 上一版本的 TripPlan，可为 None（非修订模式）。
        revision_notes: 用户修改意见文本，可为空串。

    Returns:
        str: 修订上下文文本；非修订模式（previous_plan 或 revision_notes 为空）返回空串。
    """
    if not previous_plan or not revision_notes:
        return ""

    # 只提取行程的精简摘要（每天城市+景点+餐厅名称），避免把整份 JSON 塞进 prompt 导致 LLM 调用超时
    prev_lines = []
    for d in previous_plan.day_plans:
        attr_names = "、".join(a.name for a in d.attractions[:5])
        meal_names = "、".join(f"{m.type}:{m.name}" for m in d.meals)
        hotel_name = d.hotel.name if d.hotel else "无"
        city_label = f"{d.city}, " if getattr(d, "city", None) else ""
        prev_lines.append(
            f"第{d.day_index}天({d.date} {city_label}景点[{attr_names}]"
            f" | 餐饮[{meal_names}] | 酒店[{hotel_name}]"
        )
    prev_summary = "\n".join(prev_lines)
    return f"""

【修订说明 - 重要！】
这是用户对上一份行程的修改要求，你必须基于以下已有行程进行修改：

用户修改意见：
{revision_notes}

已有行程摘要（请保持整体框架不变）：
{prev_summary}

要求：
1. 行程的城市、日期、天数、整体框架保持不变。
2. 对于用户没有提出意见的天数和项目，尽量沿用原安排，不要随意替换。
3. 只针对用户明确提到的问题进行调整（如换餐厅、换酒店、减少景点、增加某景点等）。
4. must_visit 必去景点仍然必须全部包含。
5. 如果修改涉及餐厅/酒店/景点，必须从候选列表中选取真实名称，不能编造。
6. 修改后给出调整后的完整行程，不要只返回差异部分。
"""


async def _build_skill_block(state: TravelPlanningState) -> str:
    """M4：技能仓库按 intent 偏好标签注入（SkillLayer 经唯一装配入口）。

    命中 workspace/skills 的技能时返回待追加文本块，未命中返回空串。
    """
    intent = state.get("intent_analysis")
    skill_text = await context_manager.assemble(
        state.get("plan_id", "-"),
        "PlannerAgent",
        user_id=state.get("user_id"),
        tags=list(intent.preferences) if intent else [],
    )
    return f"\n\n{skill_text}" if skill_text else ""


async def _run_multi_city_planner(state: TravelPlanningState) -> dict[str, Any]:
    """
    多城联游的行程规划分支（planner_agent_node 在 cities>=2 时转入）。

    与单城分支的差异：
    - 提示词按城市分段输入各城候选资源、停留天数分配与城际大交通；
    - LLM 输出解析后按天数分配强制规范化 city / intercity_note / 地图数据；
    - plan.weather 按"天 → 所在城市"映射重组，plan.cities 写入 CityStay 列表。

    返回值结构与单城分支一致（candidate_plans / final_plan / messages / logs）。
    """
    logger.info(f"[Node] planner_agent_node 进入多城分支，plan_id={state.get('plan_id')}")
    start_at = time.perf_counter()
    intent = state.get("intent_analysis")
    request = state["request"]
    cities = state.get("cities") or []
    city_days = state.get("city_days") or {}
    travel_days = _calculate_days(request.start_date, request.end_date)
    day_city_map = _assign_day_city_ranges(cities, city_days, travel_days)

    # ==================== 步骤 1：拼接多城提示词 ====================
    system_prompt = prompts.MULTI_CITY_PLANNER_SYSTEM_PROMPT.format(
        min_attractions=AgentConfig.min_attractions_per_day,
        max_attractions=AgentConfig.max_attractions_per_day,
        style=intent.pace if intent else "standard",
    )
    human_prompt = prompts.MULTI_CITY_HUMAN_TEMPLATE.format(
        intent_json=intent.model_dump_json(ensure_ascii=False, indent=2) if intent else "{}",
        cities_plan=_format_cities_plan(cities, city_days, day_city_map),
        intercity_legs=_format_intercity_legs(state.get("intercity_legs") or []),
        weather_json=_format_day_city_weather(
            day_city_map, state.get("weather_by_city") or {}, request.start_date, travel_days
        ),
        city_sections=_format_city_sections(
            cities,
            city_days,
            day_city_map,
            state.get("attractions_by_city") or {},
            state.get("hotels_by_city") or {},
            state.get("restaurants_by_city") or {},
            state.get("rag_by_city") or {},
            state.get("route_matrix_by_city") or {},
        ),
    )
    # 修订模式（完整重排）：追加修订上下文，与单城 planner 共用同一构建函数，
    # 保证多城重排同样尊重用户修改意见并沿用未提及的安排
    revision_context = _build_revision_context_block(
        state.get("previous_plan"), state.get("revision_notes", "")
    )
    if revision_context:
        human_prompt = human_prompt + revision_context
    # M4：技能仓库注入（按 intent 偏好标签匹配 workspace/skills，未命中为空）
    human_prompt += await _build_skill_block(state)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    logger.debug(f"[Node] 多城 planner prompt 构造完成，长度={len(human_prompt)}")

    # ==================== 步骤 2：调用 LLM（失败重试 + 兜底） ====================
    tool_calls: list[dict[str, Any]] = []
    plan = await _call_llm_for_plan(state.get("plan_id"), messages, tool_calls)
    if plan is None:
        # 兜底计划基于主城市数据机械拼装，随后由规范化步骤补 city / intercity_note
        plan = _build_fallback_plan(state)
        tool_calls.append({"tool": "fallback_plan", "status": "used"})
        # M1：planner 阶段 token 用量汇总（prompt 瘦身度量）
        logger.info(f"[Planner] token 用量: {usage_recorder.summary(state.get('plan_id', '-'))}")
        if plan is None:
            raise RuntimeError("PlannerAgent 生成多城行程失败（重试与兜底均失败）")
        plan.plan_id = state["plan_id"]
        plan.user_id = state["user_id"]

    # ==================== 步骤 3：补齐基础字段与多城规范化 ====================
    plan.plan_id = state["plan_id"]
    plan.user_id = state["user_id"]
    plan.city = request.city  # 首城市
    plan.start_date = request.start_date
    plan.end_date = request.end_date
    plan.travel_days = travel_days
    plan.style = intent.pace if intent else "standard"
    plan.cities = [CityStay(city=stay.city, days=stay.days) for stay in (request.cities or [])] or [
        CityStay(city=c, days=city_days.get(c, 1)) for c in cities
    ]

    # 天气按"天 → 所在城市"重组，保证与 day_plans 的日期一一对应
    weather_by_city = state.get("weather_by_city") or {}
    start_dt = datetime.strptime(request.start_date, "%Y-%m-%d")
    day_weather: list[WeatherInfo] = []
    for day_index in range(1, travel_days + 1):
        date_str = (start_dt + timedelta(days=day_index - 1)).strftime("%Y-%m-%d")
        city_of_day = day_city_map.get(day_index, cities[0] if cities else request.city)
        matched = next(
            (w for w in (weather_by_city.get(city_of_day) or []) if w.date == date_str), None
        )
        if matched:
            day_weather.append(matched)
    plan.weather = day_weather

    _normalize_multi_city_plan(plan, state, day_city_map, travel_days)
    _enforce_multi_city_must_visit(plan, intent, state.get("attractions_by_city") or {}, tool_calls)

    # ==================== 步骤 4：记录日志并返回 ====================
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    log = _make_log(
        "PlannerAgent",
        "generate_plan",
        input_preview=human_prompt[:300],
        output_preview=plan.model_dump_json(ensure_ascii=False)[:300],
        tool_calls=tool_calls,
    )
    log.duration_ms = duration_ms
    return {
        "candidate_plans": [plan],
        "final_plan": plan,
        "messages": messages,
        "logs": [log],
        "current_step": "planner_agent",
    }


async def planner_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】行程规划 Agent（核心）。

    这是整个流程最重要的节点，负责：
    - 综合所有前置信息（意图、景点、天气、酒店、路线、攻略）
    - 调用 LLM 生成完整的每日行程计划

    【输入】
    - state["intent_analysis"]：结构化意图
    - state["attractions"]：候选景点
    - state["weather"]：天气信息
    - state["hotels"]：候选酒店
    - state["route_matrix"]：路线矩阵
    - state["rag_context"]：RAG 上下文

    【输出】
    - candidate_plans：候选方案列表（当前只有一个）
    - final_plan：最终行程计划
    - messages：LLM 消息上下文
    - logs：执行日志

    【核心逻辑】
    1. 拼接系统提示词（PLANNER_SYSTEM_PROMPT）+ 用户提示词（PLANNER_HUMAN_TEMPLATE）
    2. 调用 LLM，要求输出 JSON 格式的 TripPlan
    3. 如果 LLM 失败，调用 _build_fallback_plan 兜底
    4. 补齐 plan 基础字段（plan_id、user_id、city 等）
    """
    logger.info(f"[Node] planner_agent_node 开始执行，plan_id={state.get('plan_id')}")

    # ==================== 多城联游分支 ====================
    # cities>=2 时转入多城提示词分支（按城市分段输入、按天分配城市）；
    # 单城（含修订链路）保持原代码路径完全不变。
    if len(state.get("cities") or []) >= 2:
        return await _run_multi_city_planner(state)

    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]
    # 从状态中获取用户请求
    request = state["request"]

    # ==================== 步骤 1：拼接系统提示词 ====================
    # PLANNER_SYSTEM_PROMPT 定义了 LLM 的角色和输出要求
    # 使用 format() 方法填充占位符
    # {min_attractions} 和 {max_attractions} 来自配置，定义每天最少/最多景点数
    # {style} 是行程节奏，如 "relaxed"（宽松）、"standard"（标准）、"tight"（紧凑）
    system_prompt = prompts.PLANNER_SYSTEM_PROMPT.format(
        min_attractions=AgentConfig.min_attractions_per_day,  # 每天最少景点数
        max_attractions=AgentConfig.max_attractions_per_day,  # 每天最多景点数
        style=intent.pace if intent else "standard",  # 行程节奏
    )

    # ==================== 步骤 2：拼接用户提示词 ====================
    # PLANNER_HUMAN_TEMPLATE 包含所有前置信息，是 LLM 生成行程的主要输入
    # 将所有信息格式化为 JSON 字符串，方便 LLM 理解和解析
    # 注意：候选 POI 的 description/photos 字段会显著拉长 prompt，
    # 这里用 _summarize_poi 压缩成"姓名/位置/价格/评分"四要素，prompt 长度可减少 ~70%
    human_prompt = prompts.PLANNER_HUMAN_TEMPLATE.format(
        # 意图分析：JSON 格式，包含城市、日期、偏好等
        intent_json=intent.model_dump_json(ensure_ascii=False, indent=2) if intent else "{}",
        # 景点列表：每个景点一行 JSON，限制前 20 个
        attractions_json="\n".join(
            _summarize_poi_for_prompt(a.model_dump()) for a in state["attractions"][:20]
        ),
        # 天气列表：每天天气一行 JSON
        weather_json="\n".join(w.model_dump_json(ensure_ascii=False) for w in state["weather"]),
        # 酒店列表：每个酒店一行 JSON，限制前 6 个
        hotels_json="\n".join(
            _summarize_poi_for_prompt(h.model_dump()) for h in state["hotels"][:6]
        ),
        # 餐厅列表：每个餐厅一行 JSON，限制前 20 个，供 PlannerAgent 选择三餐
        restaurants_json="\n".join(
            _summarize_poi_for_prompt(r.model_dump()) for r in state.get("restaurants", [])[:20]
        ),
        # 路线摘要：将路线矩阵转为简短文本
        route_summary=_format_route_summary(state["route_matrix"]),
        # RAG 上下文：如果为空，显示默认提示
        rag_context=state["rag_context"] or "无额外攻略信息。",
    )

    # ==================== 步骤 2.5：如果是修订模式，追加修订上下文 ====================
    # 修订上下文由单城/多城 planner 共用的 _build_revision_context_block 构建
    revision_context = _build_revision_context_block(
        state.get("previous_plan"), state.get("revision_notes", "")
    )
    if revision_context:
        human_prompt = human_prompt + revision_context

    # M4：技能仓库注入（按 intent 偏好标签匹配 workspace/skills，未命中为空）
    human_prompt += await _build_skill_block(state)

    # 构造消息列表
    # SystemMessage: 定义 LLM 的角色和行为规范
    # HumanMessage: 提供具体的任务输入
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    logger.debug(f"[Node] planner_agent_node prompt 构造完成，长度={len(human_prompt)}")

    # ==================== 步骤 3：调用 LLM ====================
    # 初始化行程计划为 None
    plan = None
    # 初始化工具调用记录列表
    tool_calls = []

    try:
        # 获取 LLM 实例
        # temperature 设为 0.4，比意图分析稍高，允许一定创造性
        # 但仍然保持相对稳定的输出
        # timeout 设为 300 秒（5 分钟），因为 planner 需要处理大量上下文并生成完整行程
        logger.info("[Node] planner_agent_node 准备调用 LLM...")
        llm = get_llm(temperature=0.4, timeout=300, streaming=True)
        logger.debug(f"[Node] planner_agent_node LLM 实例已创建，messages 长度={len(messages)}")
        # 流式调用 LLM（M3 token 流：token_delta 进总线 + 粗粒度进度 log）
        # 用 asyncio.wait_for 强制 5 分钟超时，防止百炼 API 在巨大 prompt 下无限挂起
        try:
            response = await _call_llm_streaming(state["plan_id"], llm, messages, 300)
        except TimeoutError as err:
            raise RuntimeError(
                f"PlannerAgent LLM 调用超时（>300秒），prompt 长度={len(human_prompt)}"
            ) from err
        logger.info("[Node] planner_agent_node LLM 调用完成")
        # token 用量打点（M1 prompt 瘦身的度量地基）
        record_llm_usage(state["plan_id"], "PlannerAgent", response)
        # M1：planner 阶段 token 用量汇总（prompt 瘦身度量）
        logger.info(f"[Planner] token 用量: {usage_recorder.summary(state['plan_id'])}")
        # 记录 LLM 调用到工具列表
        tool_calls.append({"tool": "llm", "preview": str(response.content)[:200]})

        # 尝试解析 LLM 输出为 TripPlan 对象
        # parse_llm_json 会从响应中提取 JSON 并验证为 TripPlan 模型
        logger.info("[Node] planner_agent_node 开始解析 LLM 输出...")
        plan = parse_llm_json(str(response.content), TripPlan)
        if plan is None:
            raise ValueError("LLM 输出解析为 TripPlan 失败，请检查 JSON 格式和字段类型")
        logger.info("[Node] planner_agent_node LLM 输出解析完成")
    except Exception as exc:
        # 如果 LLM 调用或解析失败，先重试一次（百炼 API 偶发超时）
        # 重试后仍然失败则回退到 _build_fallback_plan
        logger.warning(f"[Node] planner_agent_node LLM 调用或解析失败，尝试重试: {exc}")
        tool_calls.append({"tool": "llm", "error": str(exc)})
        try:
            retry_llm = get_llm(temperature=0.4, timeout=180)
            retry_response = await asyncio.wait_for(retry_llm.ainvoke(messages), timeout=180)
            plan = parse_llm_json(str(retry_response.content), TripPlan)
            if plan is None:
                raise ValueError("重试后 LLM 输出仍无法解析为 TripPlan")
            record_llm_usage(state["plan_id"], "PlannerAgent", retry_response)
            logger.info("[Node] planner_agent_node 重试成功")
            tool_calls.append({"tool": "llm_retry", "status": "success"})
        except Exception as retry_exc:
            logger.exception(f"[Node] planner_agent_node 重试仍失败，回退到 fallback: {retry_exc}")
            tool_calls.append({"tool": "llm_retry", "error": str(retry_exc)})
            # 回退到兜底计划：基于候选景点/餐厅机械拼装日程
            plan = _build_fallback_plan(state)
            tool_calls.append({"tool": "fallback_plan", "status": "used"})
            if plan is None:
                raise RuntimeError(
                    f"PlannerAgent 生成行程失败: {exc}（重试和兜底都失败: {retry_exc}）"
                ) from exc
            # 修正 plan_id 和 user_id（fallback 内部可能没设置）
            plan.plan_id = state["plan_id"]
            plan.user_id = state["user_id"]

    # ==================== 步骤 4：补齐 plan 基础字段 ====================
    # LLM 输出可能不包含这些字段，这里强制补齐
    # 确保行程计划的元数据完整
    plan.plan_id = state["plan_id"]  # 行程 ID
    plan.user_id = state["user_id"]  # 用户 ID
    plan.city = request.city  # 目标城市
    plan.start_date = request.start_date  # 开始日期
    plan.end_date = request.end_date  # 结束日期
    # 计算旅行天数
    plan.travel_days = _calculate_days(request.start_date, request.end_date)
    # 设置行程节奏，默认 "standard"
    plan.style = intent.pace if intent else "standard"
    # 设置天气信息
    plan.weather = state["weather"]

    # ==================== 步骤 4.5：补回 POI 图片等详细字段 ====================
    # PlannerAgent prompt 中 POI 字段被压缩，LLM 输出缺少 image_url/photos 等。
    # 这里从原始候选池中按名称匹配，补回图片、电话、营业时间、详情链接。
    _enrich_plan_with_poi_details(plan, state)

    # ==================== 步骤 5：强制校验 must_visit 必去景点 ====================
    # LLM 可能因上下文过长或理解偏差遗漏必去景点，这里强制补入
    must_visit_names = [m.strip() for m in (intent.must_visit if intent else []) if m.strip()]
    if must_visit_names:
        # 收集当前行程中已包含的景点名称
        planned_names = set()
        for day in plan.day_plans:
            for a in day.attractions:
                planned_names.add(a.name.strip())

        # 找出缺失的必去景点
        missing_must_visit = []
        for mv in must_visit_names:
            # 模糊匹配：必去景点名包含在已安排景点名中，或反之
            found = any(mv in pn or pn in mv for pn in planned_names)
            if not found:
                missing_must_visit.append(mv)

        if missing_must_visit:
            logger.info(f"[Node] planner_agent_node 发现缺失的必去景点: {missing_must_visit}")
            # 从候选景点中查找缺失的必去景点
            candidate_map = {a.name.strip(): a for a in state["attractions"]}

            # 依次将缺失的必去景点插入到行程中
            for mv_name in missing_must_visit:
                matched_attraction = None
                # 精确或模糊匹配候选景点
                for cand_name, cand in candidate_map.items():
                    if mv_name in cand_name or cand_name in mv_name:
                        matched_attraction = cand
                        break

                if matched_attraction is None:
                    # 候选列表中也没有，构造一个占位景点（使用城市中心或第一天的酒店位置）
                    default_location = Location(longitude=0, latitude=0, address=None)
                    if (
                        plan.day_plans
                        and plan.day_plans[0].hotel
                        and plan.day_plans[0].hotel.location
                    ):
                        default_location = plan.day_plans[0].hotel.location
                    matched_attraction = Attraction(
                        id=f"attr_must_{uuid.uuid4().hex[:8]}",
                        name=mv_name,
                        location=default_location,
                        description=f"{mv_name} 是您指定的必去景点。",
                        duration="2 小时",
                        tags=["必去景点"],
                    )

                # 插入到景点最少的那一天，避免某天景点过多
                target_day = min(plan.day_plans, key=lambda d: len(d.attractions))
                target_day.attractions.append(matched_attraction)
                logger.info(
                    f"[Node] planner_agent_node 将必去景点 {mv_name} "
                    f"插入到第 {target_day.day_index} 天"
                )

            tool_calls.append({"tool": "must_visit_enforce", "inserted": missing_must_visit})

    # ==================== 步骤 6：补充每日地图数据 ====================
    # 为每个 DayPlan 计算地图中心点和路线 polyline
    # 这些数据来自 route_agent_node 生成的路线矩阵
    route_matrix = state.get("route_matrix", {}) or {}
    for day in plan.day_plans:
        _enrich_day_plan_with_map_data(day, route_matrix)

    # ==================== 步骤 7：记录日志并返回 ====================
    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "PlannerAgent",  # Agent 名称
        "generate_plan",  # 步骤名称
        input_preview=human_prompt[:300],  # 输入预览
        output_preview=plan.model_dump_json(ensure_ascii=False)[:300],  # 输出预览
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "candidate_plans": [plan],  # 候选方案列表（当前只生成一个）
        "final_plan": plan,  # 最终行程计划
        "messages": messages,  # LLM 消息上下文
        "logs": [log],  # 执行日志
        "current_step": "planner_agent",  # 当前步骤名称
    }
