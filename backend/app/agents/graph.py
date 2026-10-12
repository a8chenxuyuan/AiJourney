"""
backend/app/agents/graph.py

【模块作用】
LangGraph StateGraph 构建与执行模块。

这是 Agent 流程的"编排器"，负责：
1. 定义有哪些 Agent 节点（IntentAgent、AttractionAgent、WeatherAgent 等）
2. 决定节点之间的执行顺序（谁先谁后、谁可以并行）
3. 把节点串联成一个可执行的图（Graph）
4. 提供启动图的入口函数

【核心概念】
- StateGraph：LangGraph 的图结构，节点之间通过状态（TravelPlanningState）传递数据
- 节点（Node）：每个节点是一个函数，负责单一职责（如搜景点、查天气）
- 边（Edge）：定义节点之间的执行顺序，START 是起点，END 是终点
- 批次（Batch）编排：批内节点相互独立、并发执行，批间顺序执行。
  节点函数只通过返回值更新状态、互不写入共享字段，因此并发安全。

【执行流程】（fan-out / fan-in 并行）
START → intent_agent → [attraction_agent ∥ weather_agent ∥ hotel_agent
                        ∥ food_agent ∥ rag_agent]（并行批次）
       → route_agent → planner_agent → budget_agent
       → human_in_the_loop → finalize → END

【注意】
原始实现使用 LangGraph 的 ainvoke 自动编排节点，但在当前环境下，
LangGraph 的默认序列化机制在处理包含大量 Pydantic 对象的复杂状态时会出现卡住的情况。
因此实际执行改为手动调用节点函数：保持每个节点的实现不变，只替换编排层，
并用 asyncio.gather 实现"信息收集类节点"的并行执行。

【对应技术】
- LangGraph：StateGraph、节点、边、编译、ainvoke
- asyncio.gather：并行批次执行
- SQLAlchemy：行程计划持久化
"""

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from langgraph.graph import END, START, StateGraph
from loguru import logger

# 导入所有 Agent 节点函数
# 每个节点函数接收状态，返回状态更新字典
from app.agents.nodes import (
    attraction_agent_node,  # 景点检索 Agent
    budget_agent_node,  # 预算统计 Agent
    feedback_extractor_node,  # 反馈意图提取 Agent
    finalize_node,  # 收尾节点（保存到数据库）
    food_agent_node,  # 餐厅搜索 Agent
    hotel_agent_node,  # 酒店推荐 Agent
    human_in_the_loop_node,  # 人机协同节点
    intent_agent_node,  # 意图理解 Agent
    patch_plan_node,  # 行程局部修改 Agent
    planner_agent_node,  # 行程规划 Agent（核心）
    rag_agent_node,  # 知识检索 Agent
    route_agent_node,  # 路线规划 Agent
    weather_agent_node,  # 天气查询 Agent
)
from app.agents.state import TravelPlanningState
from app.agents.streaming import (
    mark_done,
    put_log,
)

# 多城联游的城际大交通计算复用路线 Agent 的高德方向 API 与 Haversine 估算
from app.agents.tools import haversine_distance, plan_route
from app.db.session import AsyncSessionLocal
from app.models.db_models import TripPlanDB
from app.models.schemas import AgentLog, Attraction, TripPlan, TripRequest

# 节点函数类型：接收状态，返回状态更新字典
NodeFunc = Callable[[TravelPlanningState], Awaitable[Dict[str, Any]]]


# ==================== 全局图实例缓存 ====================
# 编译 LangGraph 图有一定开销，这里用单例模式避免每次请求都重新编译

_planning_graph = None


def get_planning_graph():
    """
    【函数作用】获取编译后的旅行规划图实例（单例）。

    【为什么用单例】
    编译 LangGraph 图需要解析节点和边，有一定性能开销。
    把编译后的图缓存起来，后续请求直接复用，不用重复编译。

    【返回值】CompiledStateGraph：编译后的 LangGraph 工作流，可以直接调用 ainvoke 执行。

    【核心步骤】
    1. 如果已经编译过（_planning_graph 不为 None），直接返回
    2. 否则创建 StateGraph，指定状态类型为 TravelPlanningState
    3. 注册所有节点（add_node）
    4. 定义节点之间的边（add_edge）
    5. 编译图（compile）
    6. 缓存并返回
    """
    global _planning_graph

    # 步骤 1：如果已经编译过，直接返回缓存的图
    if _planning_graph is not None:
        return _planning_graph

    # 步骤 2：创建 StateGraph，指定状态类型
    # StateGraph 是 LangGraph 的核心数据结构，用来定义工作流
    builder = StateGraph(TravelPlanningState)

    # ==================== 步骤 3：注册节点 ====================
    # 每个节点对应一个 Agent 的专业职责
    # add_node(节点名称, 节点函数)
    # 节点函数的签名：async def node(state: TravelPlanningState) -> Dict[str, Any]

    builder.add_node("intent_agent", intent_agent_node)
    # 【IntentAgent】意图理解 Agent
    # 输入：request（用户表单）
    # 输出：intent_analysis（结构化意图）
    # 作用：把用户填写的信息解析成标准格式，推断隐含偏好

    builder.add_node("attraction_agent", attraction_agent_node)
    # 【AttractionAgent】景点检索 Agent
    # 输入：intent_analysis.city、intent_analysis.preferences
    # 输出：attractions（候选景点列表）
    # 作用：调用高德 POI 搜索，获取真实景点数据

    builder.add_node("weather_agent", weather_agent_node)
    # 【WeatherAgent】天气查询 Agent
    # 输入：intent_analysis.city、request.start_date/end_date
    # 输出：weather（每日天气信息）
    # 作用：调用高德天气接口，获取旅行期间天气预报

    builder.add_node("hotel_agent", hotel_agent_node)
    # 【HotelAgent】酒店推荐 Agent
    # 输入：intent_analysis.city、intent_analysis.accommodation
    # 输出：hotels（候选酒店列表）
    # 作用：调用高德 POI 搜索，获取酒店数据

    builder.add_node("food_agent", food_agent_node)
    # 【FoodAgent】餐厅搜索 Agent
    # 输入：intent_analysis.city、intent_analysis.preferences
    # 输出：restaurants（候选餐厅列表）
    # 作用：调用高德 POI 搜索，获取真实餐厅数据（含照片、评分、地址）

    builder.add_node("rag_agent", rag_agent_node)
    # 【RAGAgent】知识检索 Agent
    # 输入：intent_analysis.city、intent_analysis.preferences
    # 输出：rag_context（城市攻略上下文）
    # 作用：从 Qdrant 向量库检索相关攻略（当前可能为空）

    builder.add_node("route_agent", route_agent_node)
    # 【RouteAgent】路线规划 Agent
    # 输入：attractions（所有候选景点）
    # 输出：route_matrix（景点间距离/时间矩阵）
    # 作用：计算每两个景点之间的距离和通行时间

    builder.add_node("planner_agent", planner_agent_node)
    # 【PlannerAgent】行程规划 Agent（核心）
    # 输入：intent_analysis、attractions、weather、hotels、route_matrix、rag_context
    # 输出：final_plan（完整行程计划）
    # 作用：综合所有信息，调用 LLM 生成每日行程

    builder.add_node("budget_agent", budget_agent_node)
    # 【BudgetAgent】预算统计 Agent
    # 输入：final_plan（行程计划）
    # 输出：更新 final_plan.budget（各项费用）
    # 作用：统计门票、餐饮、住宿、交通费用

    builder.add_node("human_in_the_loop", human_in_the_loop_node)
    # 【HumanInTheLoop】人机协同节点
    # 输入：candidate_plans
    # 输出：human_decisions（用户决策）
    # 当前：自动放行，预留扩展

    builder.add_node("finalize", finalize_node)
    # 【Finalize】收尾节点
    # 输入：final_plan
    # 输出：写入数据库，状态改为 completed
    # 作用：持久化行程计划

    # ==================== 步骤 4：定义边 ====================
    # 边定义节点之间的执行顺序
    # add_edge(A, B) 表示 A 执行完后，自动执行 B

    # START 是 LangGraph 的特殊节点，表示图的入口
    builder.add_edge(START, "intent_agent")
    # 【执行顺序】START → intent_agent（第一个节点）

    # fan-out：intent_agent 之后，5 个信息收集节点彼此独立，并行执行
    # 它们都只依赖 intent_analysis 的产出，互不依赖对方的结果
    builder.add_edge("intent_agent", "attraction_agent")
    builder.add_edge("intent_agent", "weather_agent")
    builder.add_edge("intent_agent", "hotel_agent")
    builder.add_edge("intent_agent", "food_agent")
    builder.add_edge("intent_agent", "rag_agent")

    # fan-in：5 个并行节点全部完成后，汇聚到 route_agent 计算路线矩阵
    builder.add_edge("attraction_agent", "route_agent")
    builder.add_edge("weather_agent", "route_agent")
    builder.add_edge("hotel_agent", "route_agent")
    builder.add_edge("food_agent", "route_agent")
    builder.add_edge("rag_agent", "route_agent")

    builder.add_edge("route_agent", "planner_agent")
    # route_agent 计算完路线后，planner_agent 开始编排行程（核心）

    builder.add_edge("planner_agent", "budget_agent")
    # planner_agent 生成行程后，budget_agent 统计预算

    builder.add_edge("budget_agent", "human_in_the_loop")
    # budget_agent 统计完预算后，human_in_the_loop 等待用户确认（当前自动放行）

    builder.add_edge("human_in_the_loop", "finalize")
    # human_in_the_loop 放行后，finalize 保存到数据库

    # END 是 LangGraph 的特殊节点，表示图的出口
    builder.add_edge("finalize", END)
    # finalize 完成后，图执行结束

    # ==================== 步骤 5：编译图 ====================
    # compile() 把节点和边解析成可执行的图对象
    # 编译后的图可以调用 ainvoke() 或 astream_events() 执行
    _planning_graph = builder.compile()

    return _planning_graph


# ==================== 批次执行辅助（并行编排核心） ====================


async def _merge_update(state: TravelPlanningState, update: Dict[str, Any]) -> None:
    """
    把节点返回的状态更新合并到主状态。

    合并规则与 LangGraph 的 reducer 行为一致：logs / messages 追加，
    其余字段覆盖。注意该函数内部不含 await，合并在事件循环中是原子的。

    Args:
        state: 主状态字典（就地修改）。
        update: 节点返回的更新字典。
    """
    for key, value in update.items():
        if key in ("logs", "messages"):
            state[key] = state.get(key, []) + list(value)
        else:
            state[key] = value


async def _run_node(
    plan_id: str, state: TravelPlanningState, step_name: str, node_func: NodeFunc
) -> Dict[str, Any]:
    """
    执行单个节点并把它产生的日志实时推送到 SSE，返回更新字典。

    并行批次中多个 _run_node 协程会并发执行；put_log 是独立的数据库写入，
    互不共享可变状态，可安全并发。

    Args:
        plan_id: 行程计划 ID（日志推送用）。
        state: 主状态（节点只读）。
        step_name: 节点名称（日志用）。
        node_func: 节点函数。

    Returns:
        Dict[str, Any]: 节点返回的状态更新（由调用方统一合并）。
    """
    logger.info(f"[Manual Graph] 执行节点: {step_name}")
    update = await node_func(state)
    for log in update.get("logs") or []:
        await put_log(plan_id, log.model_dump(mode="json"))
    logger.info(f"[Manual Graph] 节点 {step_name} 执行完成")
    return update


async def _run_batches(
    plan_id: str, state: TravelPlanningState, batches: List[List[Tuple[str, NodeFunc]]]
) -> None:
    """
    按批次执行节点编排：批内节点并发执行（asyncio.gather），批间顺序执行。

    编排模型（fan-out / fan-in）：
    - 每个批次是一个 [(节点名, 节点函数)] 列表，批内节点彼此独立、只依赖
      之前批次的产出，且互不写入相同的状态字段，因此并发安全；
    - 单节点批次等价于顺序执行；
    - 所有节点完成后，按批次顺序统一合并更新到主状态（合并在单协程中
      顺序进行，避免并发写竞态）。

    Args:
        plan_id: 行程计划 ID。
        state: 主状态字典。
        batches: 批次列表，每个批次为 (节点名, 节点函数) 元组的列表。
    """
    for batch in batches:
        if len(batch) == 1:
            # 单节点批次：顺序执行
            step_name, node_func = batch[0]
            update = await _run_node(plan_id, state, step_name, node_func)
            await _merge_update(state, update)
        else:
            # 并行批次：gather 并发执行全部节点，完成后再统一合并
            logger.info(f"[Manual Graph] 并行批次开始: {[name for name, _ in batch]}")
            updates = await asyncio.gather(
                *(_run_node(plan_id, state, name, func) for name, func in batch)
            )
            for update in updates:
                await _merge_update(state, update)
            logger.info(f"[Manual Graph] 并行批次完成: {[name for name, _ in batch]}")


# ==================== 多城市联游编排节点 ====================
# 设计要点：
# - split_cities 负责把 request.cities 拆成 cities / city_days（无 cities 时 = [city] 全部天数）；
# - city_gather 对每个城市构造 scoped state（仅覆盖 intent_analysis.city），
#   内部并发跑 5 个原信息收集节点，归并到 *_by_city，主城市字段照常填充；
# - route_multi 逐城算路线矩阵，cities>=2 时再算相邻城市对的大交通 intercity_legs；
# - 单城场景下行为与原批次完全一致（提示词、日志、字段均保持原样）。


def _split_cities(state: TravelPlanningState) -> Tuple[List[str], Dict[str, int]]:
    """
    从请求中解析城市序列与停留天数。

    优先读取 request.cities（多城联游）；为空时退化为单城：
    [request.city] 独占全部旅行天数（含起止日）。

    Args:
        state: 主状态字典（只读 request）。

    Returns:
        Tuple[List[str], Dict[str, int]]: (有序城市列表, 城市→停留天数映射)。
    """
    request = state["request"]
    city_stays = getattr(request, "cities", None) or []
    if city_stays:
        cities = [stay.city for stay in city_stays]
        city_days = {stay.city: stay.days for stay in city_stays}
        return cities, city_days

    # 单城：总天数 = (end - start).days + 1
    start = datetime.strptime(request.start_date, "%Y-%m-%d")
    end = datetime.strptime(request.end_date, "%Y-%m-%d")
    total_days = (end - start).days + 1
    return [request.city], {request.city: total_days}


async def split_cities_node(state: TravelPlanningState) -> Dict[str, Any]:
    """
    【节点作用】多城联游城市拆分节点（_split_cities 的节点适配包装）。

    把 request.cities 解析为 cities / city_days 写入状态，供后续节点按城市 fan-out。
    单城请求同样写入（cities=[city]），保证下游节点读取逻辑统一。

    【输出】
    - cities / city_days：城市序列与停留天数
    - logs：执行日志
    """
    cities, city_days = _split_cities(state)
    logger.info(f"[Manual Graph] 城市拆分: cities={cities}, city_days={city_days}")
    log = AgentLog(
        step="split_cities",
        agent_name="MultiCityRouter",
        input_preview=f"city={state['request'].city}, cities={getattr(state['request'], 'cities', None)}",
        output_preview=f"cities={cities}, city_days={city_days}",
    )
    return {"cities": cities, "city_days": city_days, "logs": [log], "current_step": "split_cities"}


def _build_city_scoped_state(state: TravelPlanningState, city: str) -> TravelPlanningState:
    """
    构造"按城市隔离"的 scoped state：浅拷贝主状态并把意图分析的城市覆盖为指定城市。

    信息收集节点都从 intent_analysis.city 读目标城市，因此只需覆盖该字段即可让
    原节点函数无改动地服务于多城场景。intent_analysis 通常是 Pydantic 模型，
    用 model_copy 生成副本，避免并发协程间共享可变对象；兼容 dict 形式。

    Args:
        state: 主状态字典。
        city: 本协程负责的目标城市。

    Returns:
        TravelPlanningState: 城市隔离后的 scoped state。
    """
    scoped = dict(state)
    intent = state.get("intent_analysis")
    if intent is not None:
        if hasattr(intent, "model_copy"):
            scoped["intent_analysis"] = intent.model_copy(update={"city": city})
        elif isinstance(intent, dict):
            scoped_intent = dict(intent)
            scoped_intent["city"] = city
            scoped["intent_analysis"] = scoped_intent
    return scoped


def _merge_node_updates(updates: List[Any]) -> Dict[str, Any]:
    """
    把一组节点更新字典按 _merge_update 语义合并为单个更新字典。

    logs / messages 追加，其余字段覆盖；异常项（gather 的 return_exceptions
    产物）跳过并返回首个异常供调用方决定是否中断。

    Args:
        updates: 节点更新字典（或异常）列表。

    Returns:
        Tuple[Dict[str, Any], Optional[BaseException]]: (合并后的更新字典, 首个异常或 None)。
    """
    merged: Dict[str, Any] = {}
    first_error: Optional[BaseException] = None
    for update in updates:
        if isinstance(update, BaseException):
            if first_error is None:
                first_error = update
            continue
        for key, value in update.items():
            if key in ("logs", "messages"):
                merged[key] = merged.get(key, []) + list(value)
            else:
                merged[key] = value
    return merged, first_error


async def city_gather_node(state: TravelPlanningState) -> Dict[str, Any]:
    """
    【节点作用】多城信息收集节点（单节点批次，内部 fan-out / fan-in）。

    对 cities 中每个城市并发跑 5 个原信息收集节点
    （attraction / weather / hotel / food / rag），并把结果归并到
    attractions_by_city / hotels_by_city / restaurants_by_city /
    weather_by_city / rag_by_city；主城市（首城）数据照常写入原有单数字段，
    保证 route / planner 等后续节点与单城链路的读取方式一致。

    【输出】
    - *_by_city：按城市归并的信息收集结果
    - attractions / hotels / restaurants / weather / rag_context：首城数据
    - logs：所有子节点日志
    """
    plan_id = state["plan_id"]
    cities = state.get("cities") or [state["request"].city]

    async def _collect_for_city(city: str) -> List[Any]:
        """并发执行单个城市的 5 个信息收集节点，返回更新/异常列表。"""
        scoped = _build_city_scoped_state(state, city)
        # 单城时节点名保持原样，多城时附加城市后缀便于日志排查
        suffix = "" if len(cities) == 1 else f"[{city}]"
        return await asyncio.gather(
            _run_node(plan_id, scoped, f"attraction_agent{suffix}", attraction_agent_node),
            _run_node(plan_id, scoped, f"weather_agent{suffix}", weather_agent_node),
            _run_node(plan_id, scoped, f"hotel_agent{suffix}", hotel_agent_node),
            _run_node(plan_id, scoped, f"food_agent{suffix}", food_agent_node),
            _run_node(plan_id, scoped, f"rag_agent{suffix}", rag_agent_node),
            return_exceptions=True,
        )

    city_updates = await asyncio.gather(*(_collect_for_city(city) for city in cities))

    attractions_by_city: Dict[str, Any] = {}
    hotels_by_city: Dict[str, Any] = {}
    restaurants_by_city: Dict[str, Any] = {}
    weather_by_city: Dict[str, Any] = {}
    rag_by_city: Dict[str, str] = {}
    all_logs: List[Any] = []
    first_error: Optional[BaseException] = None

    for city, updates in zip(cities, city_updates):
        merged, city_error = _merge_node_updates(updates)
        # 与原并行批次语义一致：任一子节点失败则让整次规划失败（由外层捕获标记 failed）
        if city_error and first_error is None:
            first_error = city_error
        attractions_by_city[city] = merged.get("attractions", [])
        hotels_by_city[city] = merged.get("hotels", [])
        restaurants_by_city[city] = merged.get("restaurants", [])
        weather_by_city[city] = merged.get("weather", [])
        rag_by_city[city] = merged.get("rag_context", "")
        all_logs.extend(merged.get("logs", []))

    if first_error is not None:
        raise first_error

    primary = cities[0]
    log = AgentLog(
        step="city_gather",
        agent_name="MultiCityRouter",
        output_preview=f"多城信息收集完成: {cities}",
    )
    return {
        "attractions_by_city": attractions_by_city,
        "hotels_by_city": hotels_by_city,
        "restaurants_by_city": restaurants_by_city,
        "weather_by_city": weather_by_city,
        "rag_by_city": rag_by_city,
        # 主城市字段照常填充（单城=唯一城市；多城=首城），保持修订链路读取兼容
        "attractions": attractions_by_city.get(primary, []),
        "hotels": hotels_by_city.get(primary, []),
        "restaurants": restaurants_by_city.get(primary, []),
        "weather": weather_by_city.get(primary, []),
        "rag_context": rag_by_city.get(primary, ""),
        "logs": all_logs,
        "current_step": "city_gather",
    }


def _city_representative_point(
    state: TravelPlanningState, city: str
) -> Optional[Tuple[float, float]]:
    """
    取某城市的代表坐标（该城候选景点的几何中心），用于城际大交通估算。

    Args:
        state: 主状态字典（读 attractions_by_city）。
        city: 城市名。

    Returns:
        Optional[Tuple[float, float]]: (经度, 纬度)；该城无有效景点坐标时返回 None。
    """
    attractions = (state.get("attractions_by_city") or {}).get(city) or []
    points = [
        (a.location.longitude, a.location.latitude)
        for a in attractions
        if a.location and (a.location.longitude != 0 or a.location.latitude != 0)
    ]
    if not points:
        return None
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lon, lat


def _build_intercity_advice(from_city: str, to_city: str, distance_m: float) -> str:
    """
    生成相邻城市间的大交通建议文案（以高铁为默认出行方式）。

    按"高铁平均旅行速度约 220 km/h + 两端市内接驳 0.5 小时"估算行程时间。

    Args:
        from_city: 出发城市。
        to_city: 抵达城市。
        distance_m: 两城代表点间距离（米），<=0 表示未知。

    Returns:
        str: 建议文案，如"杭州→苏州：高铁约 1.5 小时（全程约 160 公里）"。
    """
    if distance_m and distance_m > 0:
        km = distance_m / 1000.0
        hours = max(0.5, round(km / 220.0 + 0.5, 1))
        return f"{from_city}→{to_city}：高铁约 {hours} 小时（全程约 {km:.0f} 公里），建议提前购票。"
    return f"{from_city}→{to_city}：暂无路线数据，建议提前查询高铁/长途交通班次。"


async def _compute_one_intercity_leg(
    state: TravelPlanningState, from_city: str, to_city: str
) -> Dict[str, Any]:
    """
    计算一对相邻城市间的大交通信息（绝不抛异常）。

    优先用高德方向 API（两城景点几何中心作为起终点，驾车模式）；
    API 失败或无景点坐标时退化为 Haversine 直线距离估算。
    duration_s 与 advice 保持一致，均为高铁口径的估算时长（秒）。

    Args:
        state: 主状态字典。
        from_city: 出发城市。
        to_city: 抵达城市。

    Returns:
        Dict[str, Any]: {from_city, to_city, distance_m, duration_s, advice}。
    """
    distance_m = 0.0
    origin_pt = _city_representative_point(state, from_city)
    dest_pt = _city_representative_point(state, to_city)

    if origin_pt and dest_pt:
        try:
            route_info = await plan_route(
                f"{origin_pt[0]},{origin_pt[1]}", f"{dest_pt[0]},{dest_pt[1]}", "driving"
            )
            distance_m = float(route_info.get("distance") or 0)
        except Exception as exc:
            # 高德 API 失败时静默退化为 Haversine 估算，不中断规划
            logger.warning(
                f"[RouteMulti] 城际方向 API 失败（{from_city}→{to_city}），退化 Haversine: {exc}"
            )

        if not distance_m:
            distance_m = haversine_distance(origin_pt[0], origin_pt[1], dest_pt[0], dest_pt[1])

    advice = _build_intercity_advice(from_city, to_city, distance_m)
    # 从 advice 中反解不出结构化时长，这里按同一公式独立估算（高铁口径）
    hours = max(0.5, round((distance_m / 1000.0) / 220.0 + 0.5, 1)) if distance_m > 0 else 0.0
    return {
        "from_city": from_city,
        "to_city": to_city,
        "distance_m": round(distance_m, 1),
        "duration_s": int(hours * 3600),
        "advice": advice,
    }


async def route_multi_node(state: TravelPlanningState) -> Dict[str, Any]:
    """
    【节点作用】多城路线规划节点。

    - 单城：直接执行原 route_agent_node，行为与原批次完全一致，
      只额外把结果同步到 route_matrix_by_city；
    - 多城：逐城用 scoped state（注入该城景点）并发执行 route_agent_node 得到
      route_matrix_by_city，并对相邻城市对计算大交通 intercity_legs
      （高德方向 API，失败退化为 Haversine 估算 + 固定建议文案，绝不抛异常）。

    【输出】
    - route_matrix：主城市路线矩阵（保持单数字段兼容）
    - route_matrix_by_city：城市 → 路线矩阵
    - intercity_legs：相邻城市大交通（多城时非空）
    """
    cities = state.get("cities") or [state["request"].city]

    # 单城：等价原 route_agent 行为
    if len(cities) <= 1:
        update = await route_agent_node(state)
        update["route_matrix_by_city"] = {cities[0]: update.get("route_matrix", {})}
        update["intercity_legs"] = []
        return update

    # 多城：逐城并发计算路线矩阵
    async def _route_for_city(city: str) -> Tuple[str, Dict[str, Any], List[Any]]:
        scoped = _build_city_scoped_state(state, city)
        scoped["attractions"] = (state.get("attractions_by_city") or {}).get(city, [])
        update = await route_agent_node(scoped)
        return city, update.get("route_matrix", {}), update.get("logs", [])

    results = await asyncio.gather(*(_route_for_city(city) for city in cities))
    route_matrix_by_city = {city: matrix for city, matrix, _ in results}
    all_logs = [log for _, _, logs in results for log in logs]

    # 相邻城市对的大交通（顺序计算，通常只有 1~3 段，无需并发）
    intercity_legs: List[Dict[str, Any]] = []
    for i in range(len(cities) - 1):
        leg = await _compute_one_intercity_leg(state, cities[i], cities[i + 1])
        intercity_legs.append(leg)

    log = AgentLog(
        step="route_multi",
        agent_name="MultiCityRouter",
        output_preview=(
            f"逐城路线矩阵 {len(route_matrix_by_city)} 份，城际大交通 {len(intercity_legs)} 段"
        ),
        tool_calls=[
            {"tool": "intercity_leg", **{k: leg[k] for k in ("from_city", "to_city", "distance_m")}}
            for leg in intercity_legs
        ],
    )
    return {
        "route_matrix": route_matrix_by_city.get(cities[0], {}),
        "route_matrix_by_city": route_matrix_by_city,
        "intercity_legs": intercity_legs,
        "logs": all_logs + [log],
        "current_step": "route_multi",
    }


async def run_planning_graph(
    plan_id: str, request: TripRequest, user_id: int
) -> Optional[TripPlan]:
    """
    【函数作用】启动旅行规划 LangGraph 工作流。

    这是后端路由调用 Agent 流程的入口函数。
    它会初始化状态，按顺序执行各个 Agent 节点，返回最终行程。

    【注意】
    原始实现使用 LangGraph 的 ainvoke 自动串联节点，但在当前环境下，
    LangGraph 的默认序列化机制在处理包含大量 Pydantic 对象的复杂状态时会出现卡住的情况。
    因此这里改为手动顺序调用节点函数，保持每个节点的实现不变，只替换编排层。

    【参数】
    - plan_id：行程计划 ID，由路由层生成
    - request：用户旅行请求（Pydantic 模型），包含城市、日期、偏好等
    - user_id：当前用户 ID，用于读取用户偏好

    【返回值】
    - Optional[TripPlan]：最终行程计划；失败返回 None

    【执行流程】
    1. 构造初始状态（state），所有列表字段初始化为空
    2. 按顺序调用每个 Agent 节点
    3. 将每个节点的返回更新合并到状态
    4. 从最终状态中提取 final_plan
    5. 如果执行失败，更新数据库状态为 failed
    """
    # ==================== 步骤 1：构造初始状态 ====================
    # state 是整条流水线的"公共记事本"的初始值
    # 每个节点会读取自己需要的字段，写入自己的产出
    state: TravelPlanningState = {
        # 任务标识
        "plan_id": plan_id,  # 行程 ID
        "user_id": user_id,  # 用户 ID
        # 用户输入（这是流程的起点）
        "request": request,  # 前端提交的表单数据
        # 中间产物（初始为空，由各节点逐步填充）
        "intent_analysis": None,  # IntentAgent 输出
        "attractions": [],  # 候选景点列表
        "hotels": [],  # 候选酒店列表
        "restaurants": [],  # 候选餐厅列表
        "weather": [],  # 每日天气信息
        "route_matrix": {},  # 景点间路线矩阵
        "rag_context": "",  # RAG 检索上下文
        # 多城联游中间产物（单城时 cities=[city]，*_by_city 只有一个键）
        "cities": [],  # 有序城市列表（split_cities_node 写入）
        "city_days": {},  # 城市 → 停留天数
        "attractions_by_city": {},  # 城市 → 候选景点
        "hotels_by_city": {},  # 城市 → 候选酒店
        "restaurants_by_city": {},  # 城市 → 候选餐厅
        "weather_by_city": {},  # 城市 → 每日天气
        "rag_by_city": {},  # 城市 → RAG 上下文
        "route_matrix_by_city": {},  # 城市 → 路线矩阵
        "intercity_legs": [],  # 相邻城市大交通（多城时非空）
        # 规划输出（初始为空）
        "candidate_plans": [],  # 候选方案列表
        "selected_plan_index": 0,  # 选中的方案索引
        "final_plan": None,  # 最终行程计划
        # 控制与日志
        "messages": [],  # LLM 消息上下文
        "current_step": "start",  # 当前步骤名称
        "logs": [],  # 执行日志（追加）
        "error": None,  # 错误信息
        "human_decisions": {},  # 人机协同决策
        # 修订专用字段（初始规划时不用）
        "previous_plan": None,  # 无上游版本
        "revision_notes": "",  # 无修订说明
        "structured_feedback": None,  # 无结构化反馈
        "revision_type": "initial",  # 初始规划
        "parent_revision_id": None,  # 无父版本
        "feedback_day_index": None,  # 无反馈天数
        "feedback_tags": [],  # 无反馈标签
    }

    # 节点编排（批次结构）：
    # - 批内节点相互独立、并发执行；批间顺序执行；
    # - 第一批：split_cities（解析城市序列，只读 request）与 intent_agent 互不依赖，并行执行；
    # - 第二批：city_gather 单节点批次，内部对每个城市 fan-out 5 个信息收集节点
    #   （attraction / weather / hotel / food / rag），单城时与原并行批次行为完全一致；
    # - 第三批：route_multi 逐城计算路线矩阵，多城时附带城际大交通计算。
    node_batches: List[List[Tuple[str, NodeFunc]]] = [
        [
            ("split_cities", split_cities_node),
            ("intent_agent", intent_agent_node),
        ],
        [("city_gather", city_gather_node)],
        [("route_multi", route_multi_node)],
        [("planner_agent", planner_agent_node)],
        [("budget_agent", budget_agent_node)],
        [("human_in_the_loop", human_in_the_loop_node)],
        [("finalize", finalize_node)],
    ]

    try:
        # ==================== 步骤 2：按批次执行节点 ====================
        await _run_batches(plan_id, state, node_batches)

        # ==================== 步骤 3：提取结果 ====================
        # 从最终状态中提取 final_plan（最终行程）
        logger.info(
            f"[Manual Graph] 全部节点执行完成，final_plan={state.get('final_plan') is not None}"
        )
        # 推送完成标记到日志表，SSE 据此结束推送
        await mark_done(plan_id, "completed")
        return state.get("final_plan")

    except Exception as exc:
        # ==================== 步骤 4：失败处理 ====================
        # 如果执行过程中抛出异常，更新数据库状态为 failed
        logger.exception(f"[Manual Graph] 执行失败: {exc}")

        # 推送失败标记到日志表，SSE 据此结束推送
        await mark_done(plan_id, "failed")

        async with AsyncSessionLocal() as session:
            # 根据 plan_id 查询数据库记录
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                # 更新状态和错误信息
                db_plan.status = "failed"
                db_plan.plan_data = {"error": str(exc)}
                await session.commit()

        # 返回 None 表示失败
        return None


async def run_revision_graph(
    plan_id: str,
    request: TripRequest,
    user_id: int,
    parent_revision_id: int,
    previous_plan: TripPlan,
    revision_notes: str,
    feedback_day_index: Optional[int] = None,
    feedback_tags: Optional[List[str]] = None,
    structured_feedback: Optional[Any] = None,
) -> Optional[Tuple[TripPlan, Dict[str, Any]]]:
    """
    【函数作用】启动行程修订工作流。

    用户基于已有行程提交反馈后，本函数决定走局部补丁（patch）还是完整重排（full），
    并执行相应节点生成新版本行程。

    【参数】
    - plan_id：根行程计划 ID
    - request：原始旅行请求
    - user_id：当前用户 ID
    - parent_revision_id：基于哪个版本进行修订
    - previous_plan：上一个版本的行程
    - revision_notes：用户的自然语言修改意见
    - feedback_day_index：反馈针对的天数（可选）
    - feedback_tags：反馈快捷标签（可选）
    - structured_feedback：已预提取的结构化反馈（可选，未提供则自动提取）

    【返回值】
    - Optional[Tuple[TripPlan, Dict[str, Any]]]：新版本的行程计划及结构化反馈；失败返回 None
    """
    state: TravelPlanningState = {
        "plan_id": plan_id,
        "user_id": user_id,
        "request": request,
        "intent_analysis": None,
        "attractions": [],
        "hotels": [],
        "restaurants": [],
        "weather": previous_plan.weather or [],
        "route_matrix": {},
        "rag_context": "",
        # 多城联游字段：patch 路径不读取（cities 留空即可）；
        # full 路径若 request.cities >= 2 会由 split_cities_node 写入（见下方批次编排）
        "cities": [],
        "city_days": {},
        "attractions_by_city": {},
        "hotels_by_city": {},
        "restaurants_by_city": {},
        "weather_by_city": {},
        "rag_by_city": {},
        "route_matrix_by_city": {},
        "intercity_legs": [],
        "candidate_plans": [],
        "selected_plan_index": 0,
        "final_plan": None,
        "messages": [],
        "current_step": "start",
        "logs": [],
        "error": None,
        "human_decisions": {},
        "previous_plan": previous_plan,
        "revision_notes": revision_notes,
        "structured_feedback": structured_feedback,
        "revision_type": "patch"
        if structured_feedback and structured_feedback.complexity == "patch"
        else "full",
        "parent_revision_id": parent_revision_id,
        "feedback_day_index": feedback_day_index,
        "feedback_tags": feedback_tags or [],
    }

    try:
        # 1. 如果没有预提取结构化反馈，先提取
        if structured_feedback is None:
            update = await feedback_extractor_node(state)
            for key, value in update.items():
                if key == "logs":
                    state["logs"] = state.get("logs", []) + list(value)
                    for log in value:
                        await put_log(plan_id, log.model_dump(mode="json"))
                elif key == "messages":
                    state["messages"] = state.get("messages", []) + list(value)
                else:
                    state[key] = value

        structured = state.get("structured_feedback")
        complexity = structured.complexity if structured else "full"
        state["revision_type"] = complexity

        # 2. 根据复杂度选择路径
        if complexity == "patch":
            # 局部修改路径（顺序执行，无并行空间）
            node_batches = [
                [("patch_plan", patch_plan_node)],
                [("budget_agent", budget_agent_node)],
                [("human_in_the_loop", human_in_the_loop_node)],
                [("finalize", finalize_node)],
            ]
        else:
            # 完整重排路径：复用初始规划的批次编排（5 个信息收集节点并行），
            # planner 会读到 previous_plan + revision_notes
            if len(getattr(request, "cities", None) or []) >= 2:
                # 多城联游行程的完整重排：沿用初始规划的多城批次
                # （split_cities 解析城市序列 → city_gather 按城 fan-out 收集 → route_multi 算城际交通），
                # 保证重排后 day.city / intercity_note 不丢失；
                # planner 的多城分支同样会追加修订上下文（previous_plan + revision_notes）
                node_batches = [
                    [("split_cities", split_cities_node), ("intent_agent", intent_agent_node)],
                    [("city_gather", city_gather_node)],
                    [("route_multi", route_multi_node)],
                    [("planner_agent", planner_agent_node)],
                    [("budget_agent", budget_agent_node)],
                    [("human_in_the_loop", human_in_the_loop_node)],
                    [("finalize", finalize_node)],
                ]
            else:
                # 单城行程的完整重排：原批次编排（单城行为零改动）
                node_batches = [
                    [("intent_agent", intent_agent_node)],
                    [
                        ("attraction_agent", attraction_agent_node),
                        ("weather_agent", weather_agent_node),
                        ("hotel_agent", hotel_agent_node),
                        ("food_agent", food_agent_node),
                        ("rag_agent", rag_agent_node),
                    ],
                    [("route_agent", route_agent_node)],
                    [("planner_agent", planner_agent_node)],
                    [("budget_agent", budget_agent_node)],
                    [("human_in_the_loop", human_in_the_loop_node)],
                    [("finalize", finalize_node)],
                ]

        # 3. 按批次执行节点（批内并发、批间顺序）
        await _run_batches(plan_id, state, node_batches)

        await mark_done(plan_id, "completed")
        # 把 DB 里的 plan.status 改回 completed，否则前端轮询永远看到 revising
        async with AsyncSessionLocal() as session:
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                db_plan.status = "completed"
                await session.commit()
        final_plan = state.get("final_plan")
        structured = state.get("structured_feedback")
        if final_plan:
            return final_plan, structured.model_dump(mode="json") if structured else {}
        return None

    except Exception as exc:
        logger.exception(f"[Manual Revision Graph] 执行失败: {exc}")

        # 注意：不要在这里调用 mark_done(plan_id, "failed")
        # 因为 mark_done 会通过 SSE 立即通知前端"失败"，导致用户看到错误提示
        # 但实际上 Agent 可能仍在重试（网络抖动、LLM 慢响应等）
        # 改为：只更新数据库 status，让前端通过 GET /api/trip/{id} 轮询获取真实状态

        async with AsyncSessionLocal() as session:
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                db_plan.status = "failed"
                db_plan.plan_data = {"error": str(exc)}
                await session.commit()

        return None


async def run_recalculate_graph(
    plan_id: str,
    request: TripRequest,
    user_id: int,
    parent_revision_id: int,
    previous_plan: TripPlan,
    revision_notes: str,
    day_attractions: List[Any],
) -> Optional[TripPlan]:
    """
    【函数作用】用户手动调整某天景点顺序后的"轻量重算"工作流。

    与完整修订（run_revision_graph）的区别：不重新收集信息（不做意图分析、
    不重新搜景点/天气/酒店/餐厅），所有输入都来自当前生效版本，只重跑
    RouteAgent（重算当天景点路线矩阵）+ PlannerAgent（按用户指定顺序重排当天、
    重排交通/餐饮衔接），是成本最低的 Agent 重执行路径。

    【参数】
    - plan_id：根行程计划 ID
    - request：原始旅行请求
    - user_id：当前用户 ID
    - parent_revision_id：基于哪个版本重算
    - previous_plan：当前生效版本的行程（其中目标天的景点顺序已由 API 层按用户要求重排）
    - revision_notes：重算说明文本（含用户指定的新顺序）
    - day_attractions：目标天重排后的景点列表（仅对这些景点算路线矩阵，避免全量 N² 调用）

    【返回值】
    - Optional[TripPlan]：重算后的新版本行程计划；失败返回 None
    """
    # ==================== 步骤 1：从上一版本构造状态 ====================
    # 信息收集类字段全部复用上一版本产物，RouteAgent / PlannerAgent 是仅有的重执行节点
    prev_attractions = [a for day in previous_plan.day_plans for a in day.attractions]
    # 跨进程入队后 day_attractions 是 dict 列表，需还原为 Attraction 对象供节点使用
    day_attractions = [
        Attraction(**a) if isinstance(a, dict) else a for a in (day_attractions or [])
    ]
    # 酒店按名称去重（多天可能住同一家）
    hotels_by_name: Dict[str, Any] = {}
    for day in previous_plan.day_plans:
        if day.hotel and day.hotel.name not in hotels_by_name:
            hotels_by_name[day.hotel.name] = day.hotel
    # 餐厅从每日三餐中去重
    restaurants_by_name: Dict[str, Any] = {}
    for day in previous_plan.day_plans:
        for meal in day.meals:
            if meal.name not in restaurants_by_name:
                restaurants_by_name[meal.name] = meal

    state: TravelPlanningState = {
        "plan_id": plan_id,
        "user_id": user_id,
        "request": request,
        "intent_analysis": None,  # 无意图分析，planner 回退 style="standard"
        "attractions": prev_attractions,  # 完整景点池，供 planner 复现其余天数
        "hotels": list(hotels_by_name.values()),
        "restaurants": list(restaurants_by_name.values()),
        "weather": previous_plan.weather or [],
        "route_matrix": {},
        "rag_context": "",
        # 多城联游不支持手动重算（API 层已拦截），这里保持单城路径
        "cities": [],
        "city_days": {},
        "attractions_by_city": {},
        "hotels_by_city": {},
        "restaurants_by_city": {},
        "weather_by_city": {},
        "rag_by_city": {},
        "route_matrix_by_city": {},
        "intercity_legs": [],
        "candidate_plans": [],
        "selected_plan_index": 0,
        "final_plan": None,
        "messages": [],
        "current_step": "start",
        "logs": [],
        "error": None,
        "human_decisions": {},
        "previous_plan": previous_plan,
        "revision_notes": revision_notes,
        "structured_feedback": None,  # 无结构化反馈，跳过记忆固化
        "revision_type": "recalculate",  # finalize 据此把版本来源记为 recalculate
        "parent_revision_id": parent_revision_id,
        "feedback_day_index": None,
        "feedback_tags": [],
    }

    try:
        # ==================== 步骤 2：批次编排 ====================
        # RouteAgent 只对目标天的景点算路线矩阵（scoped state，与多城 route_multi 同模式），
        # 避免 N² 全量路线调用；PlannerAgent 拿完整景点池 + 修订上下文重排行程。
        # BudgetAgent / human_in_the_loop / finalize 与初始规划一致（finalize 落新版本）。
        scoped_route_state = dict(state)
        if day_attractions:
            scoped_route_state["attractions"] = day_attractions
        route_update = await _run_node(plan_id, scoped_route_state, "route_agent", route_agent_node)
        await _merge_update(state, route_update)

        node_batches: List[List[Tuple[str, NodeFunc]]] = [
            [("planner_agent", planner_agent_node)],
            [("budget_agent", budget_agent_node)],
            [("human_in_the_loop", human_in_the_loop_node)],
            [("finalize", finalize_node)],
        ]
        await _run_batches(plan_id, state, node_batches)

        await mark_done(plan_id, "completed")
        # 与 run_revision_graph 一致：把 DB 状态改回 completed，前端轮询才能看到完成
        async with AsyncSessionLocal() as session:
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                db_plan.status = "completed"
                await session.commit()
        return state.get("final_plan")

    except Exception as exc:
        logger.exception(f"[Manual Recalculate Graph] 重算失败: {exc}")

        # 与 run_revision_graph 相同：不推 SSE 失败标记，只更新 DB 状态供前端轮询
        async with AsyncSessionLocal() as session:
            db_plan = await session.get(TripPlanDB, plan_id)
            if db_plan:
                db_plan.status = "failed"
                db_plan.plan_data = {"error": str(exc)}
                await session.commit()

        return None
