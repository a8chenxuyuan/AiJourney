"""feedback_extractor_node 与 patch_plan_node：反馈意图提取与行程局部修改（改动后重算当日路线）。"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务

# json 模块：用于 POI 摘要等场景的 JSON 序列化

# time 模块：提供时间相关函数，用于计算代码执行耗时
import time

# uuid 模块：生成唯一标识符，用于为缺少 ID 的数据生成临时 ID
# datetime 模块：处理日期和时间，用于解析用户输入的日期和计算旅行天数
# typing 模块：提供类型提示支持，使代码更清晰、更易维护
from typing import Any

# ==================== LangChain 核心导入 ====================
# HumanMessage：代表用户输入的消息，供 LLM 理解用户意图
# SystemMessage：代表系统指令消息，用于设置 LLM 的角色和行为规范
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
from app.agents import prompts

# 包内共享的通用工具函数（未用到的名字由 ruff F401 自动清理）
from app.agents.nodes._helpers import (
    _enrich_day_plan_with_map_data,
    _make_log,
)

# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.agents.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
from app.agents.tools import (
    haversine_distance,  # 计算两个经纬度坐标之间的直线距离（球面距离）
    plan_route,  # 调用高德路线规划 API，获取两点间的距离和通行时间
    search_attractions,  # 调用高德 POI 搜索 API，搜索景点
    search_hotels,  # 调用高德 POI 搜索 API，搜索酒店
    search_restaurants,  # 调用高德 POI 搜索 API，搜索真实餐厅
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Attraction,  # 景点数据模型，包含名称、位置、门票、评分等字段
    Hotel,  # 酒店数据模型，包含名称、位置、价格、评分等字段
    Meal,  # 餐饮数据模型，包含餐次类型、菜系、预估费用
    StructuredFeedback,  # 结构化反馈模型
    TripPlan,  # 完整行程计划模型，包含多天行程、预算、建议
)

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM
from app.services.llm_service import get_llm

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好
# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型
from app.utils.json_parser import parse_llm_json


async def feedback_extractor_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】反馈意图提取 Agent。

    把用户的自然语言反馈解析成结构化修改指令，并判断走 patch 还是 full 重排。
    """
    logger.info(f"[Node] feedback_extractor_node 开始执行，plan_id={state.get('plan_id')}")
    start_at = time.perf_counter()

    previous_plan = state.get("previous_plan")
    revision_notes = state.get("revision_notes", "")
    request = state.get("request")

    # 如果已经传入了结构化反馈，直接复用
    existing = state.get("structured_feedback")
    if existing:
        return {
            "structured_feedback": existing,
            "revision_type": existing.complexity,
            "logs": [],
            "current_step": "feedback_extractor",
        }

    system_prompt = prompts.FEEDBACK_EXTRACTOR_SYSTEM_PROMPT
    human_prompt = prompts.FEEDBACK_EXTRACTOR_HUMAN_TEMPLATE.format(
        current_plan_json=previous_plan.model_dump_json(ensure_ascii=False, indent=2)
        if previous_plan
        else "{}",
        day_index=state.get("feedback_day_index", "未指定"),
        tags=", ".join(state.get("feedback_tags", [])),
        raw_text=revision_notes,
    )

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]

    tool_calls = []
    structured = None

    try:
        llm = get_llm(temperature=0.1, timeout=120)
        response = await llm.ainvoke(messages)
        tool_calls.append({"tool": "llm", "preview": str(response.content)[:200]})
        structured = parse_llm_json(str(response.content), StructuredFeedback)
        if structured is None:
            raise ValueError("反馈结构化解析失败")
    except Exception as exc:
        logger.exception(f"[Node] feedback_extractor_node 失败: {exc}")
        tool_calls.append({"tool": "llm", "error": str(exc)})
        # 解析失败时回退到 full 重排，避免错误 patch
        structured = StructuredFeedback(
            scope="whole" if request else "day",
            affected_days=[state.get("feedback_day_index")]
            if state.get("feedback_day_index")
            else [],
            actions=[],
            preference_signals=[],
            complexity="full",
        )

    duration_ms = int((time.perf_counter() - start_at) * 1000)
    log = _make_log(
        "FeedbackExtractorAgent",
        "extract_feedback",
        input_preview=revision_notes[:300],
        output_preview=structured.model_dump_json(ensure_ascii=False)[:300] if structured else "",
        tool_calls=tool_calls,
    )
    log.duration_ms = duration_ms

    return {
        "structured_feedback": structured,
        "revision_type": structured.complexity if structured else "full",
        "logs": [log],
        "messages": messages,
        "current_step": "feedback_extractor",
    }


async def _gather_patch_candidates(
    cities: list[str], previous_plan: TripPlan, structured: StructuredFeedback
) -> tuple[list[Attraction], list[Meal], list[Hotel]]:
    """
    根据结构化反馈动作，从高德 POI 搜索候选替换项。

    多城行程时对每个涉及城市分别搜索并合并候选池，保证替换候选与目标城市匹配；
    单城时列表只有一个元素，行为与原实现一致。

    Args:
        cities: 参与搜索的城市列表（多城去重、有序）。
        previous_plan: 上一版本的行程（保留参数供后续按天细分候选）。
        structured: 结构化反馈（动作列表决定搜索关键词与类型）。

    返回 (候选景点, 候选餐厅, 候选酒店)。
    """
    attractions: list[Attraction] = []
    restaurants: list[Meal] = []
    hotels: list[Hotel] = []

    for action in structured.actions:
        action_type = action.type
        name_hint = action.name or ""
        constraints = action.constraints or ""

        if action_type in ("replace_meal", "add_meal"):
            keyword = name_hint or constraints or "餐厅"
            for city in cities:
                try:
                    results = await search_restaurants(city=city, keyword=keyword, page_size=10)
                    for raw in results:
                        # 显式覆盖高德 POI 的 type 字段，避免 Meal.type 被设为高德分类字符串
                        raw["type"] = "restaurant"
                        restaurants.append(Meal(**raw))
                except Exception as e:
                    logger.warning(f"[Patch] 搜索餐厅失败 {city} {keyword}: {e}")

        elif action_type in ("add_attraction", "replace_attraction", "remove_attraction"):
            if action_type != "remove_attraction":
                keyword = name_hint or constraints or "景点"
                for city in cities:
                    try:
                        results = await search_attractions(city=city, keyword=keyword, page_size=10)
                        for raw in results:
                            attractions.append(Attraction(**raw))
                    except Exception as e:
                        logger.warning(f"[Patch] 搜索景点失败 {city} {keyword}: {e}")

        elif action_type in ("replace_hotel", "add_hotel"):
            keyword = name_hint or constraints or "酒店"
            for city in cities:
                try:
                    results = await search_hotels(city=city, keyword=keyword, page_size=6)
                    for raw in results:
                        hotels.append(Hotel(**raw))
                except Exception as e:
                    logger.warning(f"[Patch] 搜索酒店失败 {city} {keyword}: {e}")

    # 去重
    seen = set()
    unique_attractions = []
    for a in attractions:
        key = a.name
        if key not in seen:
            seen.add(key)
            unique_attractions.append(a)

    seen = set()
    unique_restaurants = []
    for r in restaurants:
        key = r.name
        if key not in seen:
            seen.add(key)
            unique_restaurants.append(r)

    seen = set()
    unique_hotels = []
    for h in hotels:
        key = h.name
        if key not in seen:
            seen.add(key)
            unique_hotels.append(h)

    return unique_attractions, unique_restaurants, unique_hotels


async def _recompute_routes_for_days(
    plan: TripPlan, affected_days: list[int], transportation: str
) -> dict[str, Any]:
    """
    为受影响的日期重新计算景点间路线矩阵。
    """
    mode = "driving"
    if transportation in ["公共交通", "公交", "地铁"]:
        mode = "transit"
    elif transportation in ["步行", "走路"]:
        mode = "walking"

    route_matrix: dict[str, Any] = {}

    for day in plan.day_plans:
        if day.day_index not in affected_days:
            continue
        attractions = day.attractions
        if len(attractions) < 2:
            continue

        for i in range(len(attractions) - 1):
            a = attractions[i]
            b = attractions[i + 1]
            key = f"{a.name}|{b.name}"
            try:
                origin = f"{a.location.longitude},{a.location.latitude}"
                destination = f"{b.location.longitude},{b.location.latitude}"
                route_info = await plan_route(origin, destination, mode)
                route_matrix[key] = route_info
            except Exception:
                distance = haversine_distance(
                    a.location.longitude,
                    a.location.latitude,
                    b.location.longitude,
                    b.location.latitude,
                )
                speed_map = {"driving": 0.5, "transit": 1.0, "walking": 3.0}
                duration = distance * speed_map.get(mode, 0.5)
                route_matrix[key] = {
                    "origin": a.name,
                    "destination": b.name,
                    "mode": mode,
                    "distance": round(distance, 1),
                    "duration": round(duration, 1),
                    "polyline": [],
                }

    return route_matrix


async def patch_plan_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】行程局部修改 Agent（PatchPlanAgent）。

    仅修改用户明确指出的项目，其余天和项目原样保留。
    """
    logger.info(f"[Node] patch_plan_node 开始执行，plan_id={state.get('plan_id')}")
    start_at = time.perf_counter()

    previous_plan = state["previous_plan"]
    structured = state["structured_feedback"]
    request = state.get("request")
    city = previous_plan.city

    # 0. 解析候选搜索城市：优先取受影响天所在城市（多城时保证候选与目标城市匹配），
    #    受影响天缺失或无法定位时退化为行程全部城市（单城即 [city]，行为不变）
    plan_cities = [s.city for s in (previous_plan.cities or [])] or [city]
    affected_cities: list[str] = []
    prev_days_map = {d.day_index: d for d in previous_plan.day_plans}
    for day_index in structured.affected_days or []:
        prev_day = prev_days_map.get(day_index)
        if prev_day and getattr(prev_day, "city", None) and prev_day.city not in affected_cities:
            affected_cities.append(prev_day.city)
    cities_for_search = affected_cities or plan_cities

    # 1. 为修改动作搜索候选池
    candidate_attractions, candidate_restaurants, candidate_hotels = await _gather_patch_candidates(
        cities=cities_for_search, previous_plan=previous_plan, structured=structured
    )

    # 2. 把候选池和当前计划一起传给 LLM
    system_prompt = prompts.PATCH_PLANNER_SYSTEM_PROMPT
    human_prompt = prompts.PATCH_PLANNER_HUMAN_TEMPLATE.format(
        current_plan_json=previous_plan.model_dump_json(ensure_ascii=False, indent=2),
        attractions_json="\n".join(
            a.model_dump_json(ensure_ascii=False) for a in candidate_attractions[:20]
        ),
        restaurants_json="\n".join(
            r.model_dump_json(ensure_ascii=False) for r in candidate_restaurants[:20]
        ),
        hotels_json="\n".join(h.model_dump_json(ensure_ascii=False) for h in candidate_hotels[:6]),
        actions_json=structured.model_dump_json(ensure_ascii=False, indent=2),
    )

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]

    tool_calls = [
        {
            "tool": "search_candidates",
            "attractions": len(candidate_attractions),
            "restaurants": len(candidate_restaurants),
            "hotels": len(candidate_hotels),
        }
    ]
    plan = None

    try:
        llm = get_llm(temperature=0.3, timeout=300)
        response = await llm.ainvoke(messages)
        tool_calls.append({"tool": "llm", "preview": str(response.content)[:200]})
        plan = parse_llm_json(str(response.content), TripPlan)
        if plan is None:
            raise ValueError("PatchPlanner 输出解析失败")
    except Exception as exc:
        logger.exception(f"[Node] patch_plan_node LLM 失败: {exc}")
        tool_calls.append({"tool": "llm", "error": str(exc)})
        raise RuntimeError(f"PatchPlanner 局部修改失败: {exc}") from exc

    # 3. 补齐元数据
    plan.plan_id = state["plan_id"]
    plan.user_id = state["user_id"]
    plan.city = previous_plan.city
    plan.start_date = previous_plan.start_date
    plan.end_date = previous_plan.end_date
    plan.travel_days = previous_plan.travel_days
    plan.weather = previous_plan.weather
    plan.style = previous_plan.style
    # 多城：城市停留分配是行程结构属性，LLM 可能漏回显，以上一版为准强制保留
    plan.cities = previous_plan.cities

    # 3.5 多城：天 → 城市归属由停留分配决定，局部修改不应改变换城节奏，
    # 以上一版为准强制写回 day.city，并补回 LLM 可能丢失的城际交通说明
    for day in plan.day_plans:
        prev_day = prev_days_map.get(day.day_index)
        if prev_day is None:
            continue
        if getattr(prev_day, "city", None):
            day.city = prev_day.city
        if getattr(prev_day, "intercity_note", None) and not day.intercity_note:
            day.intercity_note = prev_day.intercity_note

    # 4. 重新计算受影响天的路线
    affected_days = structured.affected_days or []
    transportation = request.transportation if request else "公共交通"
    route_matrix = await _recompute_routes_for_days(plan, affected_days, transportation)

    for day in plan.day_plans:
        if day.day_index in affected_days:
            _enrich_day_plan_with_map_data(day, route_matrix)

    duration_ms = int((time.perf_counter() - start_at) * 1000)
    log = _make_log(
        "PatchPlanAgent",
        "patch_plan",
        input_preview=human_prompt[:300],
        output_preview=plan.model_dump_json(ensure_ascii=False)[:300],
        tool_calls=tool_calls,
    )
    log.duration_ms = duration_ms

    return {
        "final_plan": plan,
        "candidate_plans": [plan],
        "messages": messages,
        "logs": [log],
        "current_step": "patch_plan",
    }
