"""
backend/app/agents/nodes.py

【模块作用】
LangGraph 各 Agent 节点实现模块。

这是 Agent 流程的"工作台"，包含 10 个节点函数，每个负责单一职责：
1. intent_agent_node：意图理解（解析用户表单）
2. attraction_agent_node：景点检索（调高德 POI）
3. weather_agent_node：天气查询（调高德天气接口）
4. hotel_agent_node：酒店推荐（调高德 POI）
5. rag_agent_node：知识检索（调 Qdrant）
6. route_agent_node：路线规划（调高德路线接口）
7. planner_agent_node：行程编排（调 LLM，最核心）
8. budget_agent_node：预算统计
9. human_in_the_loop_node：人机协同（当前自动放行）
10. finalize_node：收尾保存

【核心概念】
- 节点函数：接收状态，返回状态更新字典
- 状态更新字典：只写需要更新的字段，LangGraph 会自动合并到全局状态
- AgentLog：每个节点都要写日志，供前端 SSE 实时展示

【对应技术】
- LangGraph StateGraph 节点
- LangChain LLM 调用
- 高德地图 MCP / RAG / SQLAlchemy
"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务
import asyncio

# json 模块：用于 POI 摘要等场景的 JSON 序列化
import json

# time 模块：提供时间相关函数，用于计算代码执行耗时
import time

# uuid 模块：生成唯一标识符，用于为缺少 ID 的数据生成临时 ID
import uuid

# datetime 模块：处理日期和时间，用于解析用户输入的日期和计算旅行天数
from datetime import datetime, timedelta

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

# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
from app.agents.config import AgentConfig

# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.agents.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
from app.agents.tools import (
    get_weather,  # 调用高德天气 API，获取城市天气预报
    haversine_distance,  # 计算两个经纬度坐标之间的直线距离（球面距离）
    plan_route,  # 调用高德路线规划 API，获取两点间的距离和通行时间
    search_attractions,  # 调用高德 POI 搜索 API，搜索景点
    search_hotels,  # 调用高德 POI 搜索 API，搜索酒店
    search_rag_context,  # 调用 Qdrant 向量数据库，检索相关知识库内容
    search_restaurants,  # 调用高德 POI 搜索 API，搜索真实餐厅
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
from app.db.session import AsyncSessionLocal

# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
from app.models.db_models import TripPlanDB

# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    AgentLog,  # Agent 执行日志模型，记录每个节点的执行情况
    Attraction,  # 景点数据模型，包含名称、位置、门票、评分等字段
    Budget,  # 预算数据模型，包含门票、餐饮、住宿、交通费用
    CityStay,  # 多城市联游的单城市停留安排（城市 + 天数）
    DayPlan,  # 单日行程计划模型，包含当天的景点、餐饮、酒店
    Hotel,  # 酒店数据模型，包含名称、位置、价格、评分等字段
    IntentAnalysis,  # 意图分析结果模型，从用户表单解析出的结构化数据
    Location,  # 位置数据模型，包含经度、纬度、地址
    Meal,  # 餐饮数据模型，包含餐次类型、菜系、预估费用
    StructuredFeedback,  # 结构化反馈模型
    TripPlan,  # 完整行程计划模型，包含多天行程、预算、建议
    WeatherInfo,  # 天气信息模型，包含日期、天气描述、温度、风力
)

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM
from app.services.llm_service import get_llm

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好
from app.services.memory_service import MemoryService

# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型
from app.utils.json_parser import parse_llm_json

# ==================== 通用工具函数 ====================
# 这些函数被多个节点复用，不是 LangGraph 节点


def _calculate_days(start_date: str, end_date: str) -> int:
    """
    【函数作用】计算旅行天数（包含起止日期）。

    【参数】
    - start_date：开始日期，格式 "YYYY-MM-DD"
    - end_date：结束日期，格式 "YYYY-MM-DD"

    【返回值】
    - int：旅行天数

    【示例】
    start_date="2026-07-01", end_date="2026-07-03" → 返回 3（7月1日、2日、3日）
    """
    # 将字符串格式的日期转换为 datetime 对象，方便后续计算
    # strptime 的第一个参数是日期字符串，第二个参数是日期格式模板
    start = datetime.strptime(start_date, "%Y-%m-%d")
    # 同样的方式解析结束日期
    end = datetime.strptime(end_date, "%Y-%m-%d")
    # 计算两个日期的差值（end - start 得到 timedelta 对象），取 .days 属性得到天数
    # 加 1 是因为包含起止两天（例如 7月1日到7月3日是 3 天，而不是 2 天）
    return (end - start).days + 1


def _make_log(
    agent_name: str,
    step: str,
    input_preview: str = "",
    output_preview: str = "",
    tool_calls: list[dict[str, Any]] = None,
) -> AgentLog:
    """
    【函数作用】构造 Agent 执行日志对象。

    每个节点执行完后，都要创建一个 AgentLog 对象，记录：
    - 执行了什么步骤
    - 输入输出摘要
    - 调用了哪些工具
    - 耗时多久

    这些日志会被追加到状态的 logs 列表，供前端 SSE 实时展示。

    【参数】
    - agent_name：Agent 名称，如 "IntentAgent"、"AttractionAgent"
    - step：步骤名称，如 "intent_analysis"、"search_attractions"
    - input_preview：输入摘要（截取前 500 字符）
    - output_preview：输出摘要（截取前 500 字符）
    - tool_calls：工具调用记录列表

    【返回值】
    - AgentLog：日志对象
    """
    # 构造并返回 AgentLog 对象
    # AgentLog 是 Pydantic 模型，构造时会自动验证字段类型
    return AgentLog(
        step=step,  # 步骤名称
        agent_name=agent_name,  # Agent 名称
        input_preview=input_preview[:500],  # 截取前 500 字符，避免日志过长
        output_preview=output_preview[:500],  # 截取前 500 字符
        tool_calls=tool_calls or [],  # 工具调用记录，默认为空列表
        timestamp=datetime.now(),  # 当前时间戳，记录日志生成时间
        duration_ms=0,  # 耗时会在函数返回后设置，这里先初始化为 0
    )


def _encode_polyline(points: list[dict[str, float]]) -> str:
    """
    【函数作用】将经纬度点列表编码为高德可识别的 polyline 字符串。

    输出格式："经度,纬度;经度,纬度;..."
    """
    if not points:
        return ""
    segments = []
    for p in points:
        lon = p.get("longitude")
        lat = p.get("latitude")
        if lon is None or lat is None:
            continue
        segments.append(f"{lon},{lat}")
    return ";".join(segments)


def _calculate_center(locations: list[Location]) -> Location | None:
    """
    【函数作用】计算一组坐标的几何中心点。

    返回中心点的 Location，地址字段为空。
    """
    if not locations:
        return None
    valid = [loc for loc in locations if loc.longitude != 0 or loc.latitude != 0]
    if not valid:
        return None
    avg_lon = sum(loc.longitude for loc in valid) / len(valid)
    avg_lat = sum(loc.latitude for loc in valid) / len(valid)
    return Location(longitude=avg_lon, latitude=avg_lat, address=None)


def _build_day_route_polyline(attractions: list[Attraction], route_matrix: dict[str, Any]) -> str:
    """
    【函数作用】根据当天景点顺序，从路线矩阵中拼接出完整 polyline。

    遍历相邻景点对，从 route_matrix 取出 polyline 点列表并拼接。
    如果某段缺失，则使用直线插值补充。
    """
    if len(attractions) < 2:
        return ""

    all_points: list[dict[str, float]] = []
    for i in range(len(attractions) - 1):
        a = attractions[i]
        b = attractions[i + 1]
        key = f"{a.name}|{b.name}"
        route_info = route_matrix.get(key, {})
        polyline = route_info.get("polyline", []) if isinstance(route_info, dict) else []

        if polyline:
            # 去重：与前一个点相同则跳过
            for point in polyline:
                if not all_points or point != all_points[-1]:
                    all_points.append(point)
        else:
            # 缺失路线时用直线补充
            if not all_points or all_points[-1] != {
                "longitude": a.location.longitude,
                "latitude": a.location.latitude,
            }:
                all_points.append(
                    {"longitude": a.location.longitude, "latitude": a.location.latitude}
                )
            all_points.append({"longitude": b.location.longitude, "latitude": b.location.latitude})

    return _encode_polyline(all_points)


def _enrich_day_plan_with_map_data(day: DayPlan, route_matrix: dict[str, Any]) -> None:
    """
    【函数作用】为单日行程补充地图相关字段。

    - map_center：当天所有景点位置的几何中心
    - route_polyline：当天景点顺序串联的路线 polyline
    """
    if day.attractions:
        locations = [a.location for a in day.attractions if a.location]
        day.map_center = _calculate_center(locations)
        day.route_polyline = _build_day_route_polyline(day.attractions, route_matrix)


def _enrich_plan_with_poi_details(plan: TripPlan, state: TravelPlanningState) -> None:
    """
    【函数作用】为 PlannerAgent 生成的行程补回候选 POI 的详细字段。

    PlannerAgent 的 prompt 中 POI 信息经过 _summarize_poi_for_prompt 压缩，
    去掉了 image_url、photos、phone 等长字段，导致 LLM 输出中这些字段缺失。
    本函数在 LLM 生成 TripPlan 后，按名称从原始候选池中匹配，补回图片、
    电话、营业时间、详情链接等字段。

    【匹配规则】
    - 精确匹配优先
    - 其次模糊匹配（名称互相包含）
    """
    # 构建候选池字典，key 为 POI 名称
    attractions_by_name: dict[str, Attraction] = {}
    for a in state.get("attractions", []) or []:
        name = a.name.strip() if a.name else ""
        if name:
            attractions_by_name[name] = a

    restaurants_by_name: dict[str, Meal] = {}
    for r in state.get("restaurants", []) or []:
        name = r.name.strip() if r.name else ""
        if name:
            restaurants_by_name[name] = r

    hotels_by_name: dict[str, Hotel] = {}
    for h in state.get("hotels", []) or []:
        name = h.name.strip() if h.name else ""
        if name:
            hotels_by_name[name] = h

    def _find_match(name: str, pool: dict[str, Any]) -> Any | None:
        """在候选池中按名称查找匹配项。"""
        if not name:
            return None
        name_clean = name.strip()
        # 精确匹配
        if name_clean in pool:
            return pool[name_clean]
        # 模糊匹配
        for cand_name, cand in pool.items():
            if name_clean in cand_name or cand_name in name_clean:
                return cand
        return None

    def _merge_poi_fields(target: Any, source: Any) -> None:
        """把 source 中的补充字段复制到 target（仅在 target 缺失时）。"""
        if not source:
            return
        fields = ["image_url", "photos", "phone", "business_hours", "detail_url"]
        for field in fields:
            if getattr(target, field, None) in (None, "", []):
                value = getattr(source, field, None)
                if value:
                    setattr(target, field, value)

    # 遍历每一天，补全景点、餐厅、酒店
    for day in plan.day_plans:
        for attraction in day.attractions:
            matched = _find_match(attraction.name, attractions_by_name)
            _merge_poi_fields(attraction, matched)

        for meal in day.meals:
            matched = _find_match(meal.name, restaurants_by_name)
            _merge_poi_fields(meal, matched)

        if day.hotel:
            matched = _find_match(day.hotel.name, hotels_by_name)
            _merge_poi_fields(day.hotel, matched)


def _summarize_poi_for_prompt(poi: dict[str, Any]) -> str:
    """
    【函数作用】将 POI 字典压缩为 PlannerAgent prompt 用的精简版本。

    原始 POI 包含 description、photos、image_url 等长字段，
    会让 prompt 长度膨胀到 23K+，导致 LLM 注意力分散、调用超时。
    这里只保留"name/location/price/rating/tags/business_hours"四要素，
    通常每个 POI 压缩到 200 字符以内，prompt 整体长度可减少 60-70%。

    【参数】
    - poi: POI 字典（Attraction / Hotel / Restaurant 都可）

    【返回值】
    - str: 一行 JSON 字符串
    """
    # 兼容 Pydantic v1/v2：可能是 BaseModel 或 dict
    if hasattr(poi, "model_dump"):
        poi = poi.model_dump()
    elif hasattr(poi, "dict"):
        poi = poi.dict()

    # 提取位置文本（兼容多种字段命名）
    location = poi.get("location") or {}
    location_text = (
        location.get("address")
        or location.get("name")
        or poi.get("address")
        or poi.get("location_name")
        or ""
    )

    # 提取价格字段
    price = (
        poi.get("ticket_price")
        or poi.get("price_per_night")
        or poi.get("estimated_cost")
        or poi.get("price")
    )

    # 提取评分
    rating = poi.get("rating")

    # 压缩后只保留关键字段
    compressed = {
        "name": poi.get("name"),
        "address": location_text if not location.get("address") else location.get("address"),
        "price": price,
        "rating": rating,
        "tags": poi.get("tags", []) or [],
        "business_hours": poi.get("business_hours", "") or "",
    }
    # 去掉 None 值
    compressed = {k: v for k, v in compressed.items() if v not in (None, "", [])}
    return json.dumps(compressed, ensure_ascii=False)


def _format_route_summary(route_matrix: dict[str, Any]) -> str:
    """
    【函数作用】将路线矩阵转为简短文本，供 PlannerAgent 使用。

    路线矩阵是字典，键为 "景点A|景点B"，值为距离和时间。
    这个函数把它转成人类可读的文本，如：
    "赤坎老街|金沙湾: 距离 5000 米，耗时 15 分钟"

    【参数】
    - route_matrix：路线矩阵字典

    【返回值】
    - str：路线摘要文本
    """
    # 如果路线矩阵为空或 None，返回提示信息
    if not route_matrix:
        return "暂无路线信息。"

    # 用于存储每条路线的文本描述
    lines = []
    # 遍历路线矩阵的每一项，只取前 10 条，避免文本过长影响 LLM 输入
    # route_matrix.items() 返回键值对，key 是 "景点A|景点B"，info 是距离/时间字典
    for key, info in list(route_matrix.items())[:10]:
        # 从 info 字典中获取距离（单位：米），默认为 0
        distance = info.get("distance", 0)
        # 从 info 字典中获取时长（单位：秒），默认为 0
        duration = info.get("duration", 0)
        # duration 是秒，转换为分钟（整数除法）
        # 格式化为一行文本："景点A|景点B: 距离 X 米，耗时 Y 分钟"
        lines.append(f"{key}: 距离 {distance} 米，耗时 {duration // 60} 分钟")

    # 将所有行用换行符连接成一个完整的字符串
    return "\n".join(lines)


# ==================== Agent 节点实现 ====================
# 以下是 LangGraph 的节点函数
# 每个函数的签名：async def node(state: TravelPlanningState) -> Dict[str, Any]


async def intent_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】意图理解 Agent。

    把用户填写的表单 + 自由文本解析成结构化的意图分析（IntentAnalysis）。

    【输入】
    - state["request"]：用户提交的表单数据
    - state["user_id"]：用户 ID（用于读取历史偏好）

    【输出】（返回的状态更新字典）
    - intent_analysis：结构化意图分析
    - messages：LLM 消息上下文
    - logs：执行日志
    - current_step：当前步骤名称

    【核心步骤】
    1. 读取用户历史偏好（如之前标记过"喜欢美食"）
    2. 拼接 system prompt + human prompt
    3. 调用 LLM，要求输出 JSON 格式的 IntentAnalysis
    4. 解析 LLM 输出，如果失败则从请求字段构造默认意图
    5. 记录日志，返回状态更新
    """
    # 节点入口日志
    logger.info(f"[Node] intent_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间，用于计算整个节点的执行耗时（毫秒）
    # time.perf_counter() 返回高精度的计时器值
    start_at = time.perf_counter()
    # 从状态字典中获取用户请求对象（包含表单数据）
    request = state["request"]

    # ==================== 步骤 1：读取用户历史偏好 ====================
    # 用户可能在之前的规划中标记过喜欢/不喜欢的标签
    # MemoryService 会从数据库读取，格式化为文本供 LLM 参考
    # 初始化偏好文本为默认值
    preference_text = "用户暂无历史偏好记录。"
    try:
        # 使用异步上下文管理器创建数据库会话
        # AsyncSessionLocal() 返回一个异步会话实例
        async with AsyncSessionLocal() as session:
            # 调用 MemoryService 的静态方法，获取或创建用户偏好记录
            # 如果用户是第一次使用，会创建默认偏好记录
            preference = await MemoryService.get_or_create_preference(session, state["user_id"])
            # 将偏好对象格式化为文本，供 LLM 理解
            # 例如："用户喜欢美食、文化，不喜欢购物"
            preference_text = MemoryService.format_preference_for_prompt(preference)
    except Exception as exc:
        # 如果读取偏好失败，记录错误信息，但不中断流程
        # 这样即使数据库异常，意图分析仍然可以继续
        preference_text = f"读取偏好失败：{exc}"

    # ==================== 步骤 2：拼接 prompt ====================
    # 使用 prompts.py 里定义的模板
    # INTENT_HUMAN_TEMPLATE 包含两个占位符：{request_json} 和 {preference_text}
    # request.model_dump_json() 将 Pydantic 模型序列化为 JSON 字符串
    # ensure_ascii=False 保证中文字符不被转义为 \uXXXX 格式
    # indent=2 使 JSON 格式化缩进，方便 LLM 阅读理解
    prompt = prompts.INTENT_HUMAN_TEMPLATE.format(
        request_json=request.model_dump_json(ensure_ascii=False, indent=2),
        preference_text=preference_text,
    )

    # 构造消息列表，供 LLM 使用
    # LangChain 使用消息列表模式与 LLM 交互
    messages = [
        # SystemMessage 是系统指令，告诉 LLM 它的角色和任务
        # INTENT_SYSTEM_PROMPT 定义了："你是旅行规划意图分析专家..."
        SystemMessage(content=prompts.INTENT_SYSTEM_PROMPT),
        # HumanMessage 是用户输入，包含表单数据和偏好信息
        HumanMessage(content=prompt),
    ]
    logger.debug(f"[Node] intent_agent_node prompt 构造完成，长度={len(prompt)}")

    # ==================== 步骤 3：调用 LLM ====================
    # 初始化意图分析结果为 None，如果 LLM 调用失败，后续会使用兜底逻辑
    intent = None
    # 初始化工具调用记录列表，用于日志
    tool_calls = []  # 记录工具调用，用于日志

    try:
        # 获取 LLM 实例（温度设为 0.3，更稳定）
        # temperature 参数控制 LLM 输出的随机性：0 表示最确定性，1 表示最随机
        # 对于意图分析这类需要稳定输出的任务，使用较低温度
        logger.info("[Node] intent_agent_node 准备调用 LLM...")
        llm = get_llm(temperature=0.3)
        logger.debug(f"[Node] intent_agent_node LLM 实例已创建，messages 长度={len(messages)}")
        # ainvoke 是异步调用方法，await 等待 LLM 响应
        # messages 是之前构造的系统指令 + 用户输入
        response = await llm.ainvoke(messages)
        logger.info("[Node] intent_agent_node LLM 调用完成")
        # 记录 LLM 调用到工具调用列表，截取前 200 字符预览
        # response.content 是 LLM 返回的文本内容
        tool_calls.append({"tool": "llm", "preview": str(response.content)[:200]})

        # 尝试解析 LLM 输出为 IntentAnalysis 对象
        # parse_llm_json 会处理 JSON 提取和验证
        # 它会从 LLM 响应中提取 JSON 块，并尝试解析为 IntentAnalysis Pydantic 模型
        # 如果 JSON 格式不正确或字段缺失，会抛出异常
        logger.info("[Node] intent_agent_node 开始解析 LLM 输出...")
        intent = parse_llm_json(str(response.content), IntentAnalysis)
        logger.info("[Node] intent_agent_node LLM 输出解析完成")
    except Exception as exc:
        # 如果 LLM 调用或解析失败，记录错误信息到工具调用列表
        # 这样前端可以通过日志看到具体错误原因
        logger.exception(f"[Node] intent_agent_node LLM 调用或解析失败: {exc}")
        tool_calls.append({"tool": "llm", "error": str(exc)})
        # 不再兜底，直接抛出异常，让上层捕获并返回真实错误
        raise RuntimeError(f"IntentAgent 解析失败: {exc}") from exc

    # ==================== 步骤 4：记录日志并返回 ====================
    # 计算节点执行耗时：当前时间 - 开始时间，转换为毫秒
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象，记录本次意图分析的输入输出
    log = _make_log(
        "IntentAgent",  # Agent 名称
        "intent_analysis",  # 步骤名称
        input_preview=prompt[:300],  # 输入预览（截取前 300 字符）
        output_preview=intent.model_dump_json(ensure_ascii=False)[
            :300
        ],  # 输出预览（截取前 300 字符）
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时字段
    log.duration_ms = duration_ms

    # 返回状态更新字典
    # LangGraph 会把这些字段合并到全局状态
    # 注意：这里只返回需要更新的字段，而不是完整的状态
    return {
        "intent_analysis": intent,  # 结构化意图分析结果
        # messages 列表包含原始消息 + LLM 输出的意图 JSON
        # 这样后续节点可以看到完整的对话上下文
        "messages": messages + [HumanMessage(content=intent.model_dump_json(ensure_ascii=False))],
        "logs": [log],  # 执行日志列表
        "current_step": "intent_agent",  # 当前步骤名称，用于前端展示进度
    }


async def attraction_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】景点检索 Agent。

    根据意图分析中的城市、偏好标签、必去景点，调用高德 POI 搜索，获取真实景点数据。

    【输入】
    - state["intent_analysis"].city：目标城市
    - state["intent_analysis"].preferences：偏好标签（如["美食", "文化"]）
    - state["intent_analysis"].must_visit：必去景点

    【输出】
    - attractions：候选景点列表（List[Attraction]）
    - logs：执行日志
    - current_step：当前步骤名称

    【核心步骤】
    1. 构造搜索关键词（偏好标签 + 必去景点 + 默认关键词）
    2. 对每个关键词调用 search_attractions 工具
    3. 去重并转换为 Attraction 模型
    """
    logger.info(f"[Node] attraction_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间，用于计算节点执行耗时
    start_at = time.perf_counter()
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]
    # 获取目标城市：优先从意图分析中获取，如果没有则从请求中获取
    city = intent.city if intent else state["request"].city

    # ==================== 步骤 1：构造搜索关键词 ====================
    # 搜索关键词 = 偏好标签 + 必去景点 + 默认关键词
    # 初始化为包含默认关键词"景点"的列表
    search_keywords = ["景点"]  # 默认关键词
    # 如果意图分析存在且包含偏好标签，扩展到搜索关键词列表
    # extend 方法会将列表中的元素逐一添加到原列表
    search_keywords.extend(intent.preferences if intent else [])
    # 如果意图分析存在且包含必去景点，扩展到搜索关键词列表
    search_keywords.extend(intent.must_visit if intent else [])
    # 去重：先对每个关键词去除首尾空格，过滤空字符串，然后转为集合去重，最后转回列表
    # set() 会自动去重，list() 将集合转回列表
    search_keywords = list(set([k.strip() for k in search_keywords if k.strip()]))

    # 限制最终返回的景点数量，避免后续路线规划节点因景点过多而产生大量 API 调用
    max_attractions = 10

    # 初始化景点列表，用于存储搜索结果
    attractions: list[Attraction] = []
    # 用于去重的集合，记录已处理的景点名称
    # 同一景点可能在不同关键词的搜索结果中重复出现，需要去重
    seen_names = set()  # 用于去重（同一景点可能被多次搜索到）
    # 初始化工具调用记录列表，用于日志
    tool_calls = []

    # ==================== 步骤 2：优先搜索必去景点 ====================
    # 必去景点（must_visit）是用户明确指定的，必须优先保证它们进入候选列表
    # 对每个必去景点单独搜索，确保不会因为关键词截断或 LLM 选择而丢失
    must_visit = intent.must_visit if intent else []
    for must_visit_name in must_visit:
        must_visit_name = must_visit_name.strip()
        if not must_visit_name:
            continue
        try:
            raw_list = await search_attractions(city=city, keyword=must_visit_name, page_size=5)
            tool_calls.append(
                {
                    "tool": "search_attractions_must_visit",
                    "keyword": must_visit_name,
                    "count": len(raw_list),
                }
            )

            for raw in raw_list:
                name = raw.get("name", "")
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                loc = raw.get("location", {})
                attractions.append(
                    Attraction(
                        id=raw.get("id") or f"attr_{uuid.uuid4().hex[:8]}",
                        name=name,
                        location=Location(
                            longitude=float(loc.get("longitude", 0)),
                            latitude=float(loc.get("latitude", 0)),
                            address=raw.get("address"),
                        ),
                        description=raw.get("description") or f"{name} 是 {city} 的热门景点。",
                        duration=raw.get("duration") or "2 小时",
                        ticket_price=float(raw.get("ticket_price", 0))
                        if raw.get("ticket_price")
                        else None,
                        rating=float(raw.get("rating", 4.5)) if raw.get("rating") else None,
                        tags=raw.get("tags", ["观光"]),
                        image_url=raw.get("image_url"),
                        photos=raw.get("photos", []),
                        business_hours=raw.get("business_hours"),
                        phone=raw.get("phone"),
                        detail_url=raw.get("detail_url"),
                    )
                )

                # 找到匹配的必去景点后，不再继续搜同一关键词的其它结果
                if must_visit_name in name or name in must_visit_name:
                    break

        except Exception as exc:
            tool_calls.append(
                {
                    "tool": "search_attractions_must_visit",
                    "keyword": must_visit_name,
                    "error": str(exc),
                }
            )

    # ==================== 步骤 3：按偏好关键词搜索更多景点 ====================
    # 限制最多搜索 4 个关键词，避免请求过多
    # 多个关键词可能会返回重叠的结果，所以需要去重
    for keyword in search_keywords[:4]:
        try:
            # 调用 search_attractions 工具（内部会调高德 API）
            # city: 目标城市
            # keyword: 搜索关键词
            # page_size: 每页返回结果数量，限制为 6 条
            # await 等待异步调用完成
            raw_list = await search_attractions(city=city, keyword=keyword, page_size=6)
            # 记录搜索结果到工具调用列表，包含关键词和结果数量
            tool_calls.append(
                {"tool": "search_attractions", "keyword": keyword, "count": len(raw_list)}
            )

            # 遍历搜索结果，转换为 Attraction 模型
            # raw 是高德 API 返回的原始字典数据
            for raw in raw_list:
                # 获取景点名称
                name = raw.get("name", "")
                # 如果名称为空或已经处理过，跳过该景点
                if not name or name in seen_names:
                    continue  # 跳过空名称或重复景点

                # 将景点名称添加到去重集合
                seen_names.add(name)
                # 获取位置信息字典，包含经度、纬度、地址
                loc = raw.get("location", {})

                # 构造 Attraction 对象
                # 将高德 API 返回的原始数据转换为我们的数据模型
                attractions.append(
                    Attraction(
                        # 景点 ID：如果 API 没有返回，生成一个临时 ID
                        # uuid.uuid4().hex[:8] 取 UUID 的前 8 位作为临时 ID
                        id=raw.get("id") or f"attr_{uuid.uuid4().hex[:8]}",
                        name=name,  # 景点名称
                        # 位置信息：构造 Location 对象
                        location=Location(
                            # 经度：转换为浮点数，默认为 0
                            longitude=float(loc.get("longitude", 0)),
                            # 纬度：转换为浮点数，默认为 0
                            latitude=float(loc.get("latitude", 0)),
                            # 地址：可能为空
                            address=raw.get("address"),
                        ),
                        # 景点描述：如果 API 没有返回，使用默认描述
                        description=raw.get("description") or f"{name} 是 {city} 的热门景点。",
                        # 建议游玩时长：如果 API 没有返回，默认为 2 小时
                        duration=raw.get("duration") or "2 小时",
                        # 门票价格：转换为浮点数，可能为空
                        ticket_price=float(raw.get("ticket_price", 0))
                        if raw.get("ticket_price")
                        else None,
                        # 评分：转换为浮点数，可能为空
                        rating=float(raw.get("rating", 4.5)) if raw.get("rating") else None,
                        # 标签：景点类型标签列表
                        tags=raw.get("tags", ["观光"]),
                        # 图片 URL：可能为空
                        image_url=raw.get("image_url"),
                        # 图片列表：高德可能返回多张图片
                        photos=raw.get("photos", []),
                        # 营业时间
                        business_hours=raw.get("business_hours"),
                        # 联系电话
                        phone=raw.get("phone"),
                        # 高德详情页链接
                        detail_url=raw.get("detail_url"),
                    )
                )
            # 当已收集到足够数量的景点时，提前结束搜索
            # 避免后续路线规划节点因景点过多而产生大量 API 调用
            if len(attractions) >= max_attractions:
                break

        except Exception as exc:
            # 如果某个关键词的搜索失败，记录错误信息，但不中断整个流程
            # 继续处理其他关键词的搜索结果
            tool_calls.append({"tool": "search_attractions", "keyword": keyword, "error": str(exc)})

    # 再次截断，确保最终返回的景点数量不超过限制
    # 注意：必去景点已经排在列表前面，截断不会丢失它们
    attractions = attractions[:max_attractions]

    # ==================== 步骤 4：为景点补充背景知识（RAG 缓存 + 百度百科） ====================
    # 如果有景点，尝试从缓存或外部搜索获取背景知识
    if attractions:
        try:
            from app.services.rag_service import get_rag_service

            rag = get_rag_service()

            # 批量搜索景点的背景知识
            attraction_names = [a.name for a in attractions]
            logger.info(
                f"[Node] attraction_agent_node 开始搜索背景知识，景点数量={len(attraction_names)}"
            )

            # 使用 RAG 的 batch_search_or_fetch 方法
            # 先查缓存，未命中则调百度百科，结果自动存入缓存
            background_results = await rag.batch_search_or_fetch(
                queries=attraction_names, city=city, source_type="attraction", min_score=0.75
            )

            # 将背景知识合并到景点对象
            for i, attraction in enumerate(attractions):
                if i < len(background_results):
                    bg = background_results[i]
                    # 如果背景知识比默认描述更丰富，则替换
                    if bg.get("content") and len(bg["content"]) > len(attraction.description or ""):
                        attraction.description = bg["content"]
                        logger.debug(
                            f"[Node] attraction_agent_node 为 {attraction.name} 补充背景知识，来源缓存={bg.get('from_cache')}"
                        )
                    # 如果有百科链接，也补充上
                    if bg.get("url") and not attraction.detail_url:
                        attraction.detail_url = bg["url"]

            tool_calls.append(
                {
                    "tool": "rag_background_search",
                    "count": len(background_results),
                    "from_cache": sum(1 for b in background_results if b.get("from_cache")),
                }
            )

        except Exception as exc:
            # 背景知识搜索失败不影响主流程，记录日志即可
            logger.exception(f"[Node] attraction_agent_node 背景知识搜索失败: {exc}")
            tool_calls.append({"tool": "rag_background_search", "error": str(exc)})

    # ==================== 步骤 5：记录日志并返回 ====================
    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "AttractionAgent",  # Agent 名称
        "search_attractions",  # 步骤名称
        input_preview=f"城市：{city}，关键词：{search_keywords}",  # 输入预览
        output_preview=f"检索到 {len(attractions)} 个景点",  # 输出预览
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "attractions": attractions,  # 检索到的景点列表
        "logs": [log],  # 执行日志
        "current_step": "attraction_agent",  # 当前步骤名称
    }


async def weather_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】天气查询 Agent。

    调用高德天气接口，获取旅行期间每日天气预报。

    【输入】
    - state["intent_analysis"].city：目标城市
    - state["request"].start_date / end_date：旅行日期

    【输出】
    - weather：每日天气列表（List[WeatherInfo]）

    【核心步骤】
    1. 调用 get_weather 工具获取高德天气预报
    2. 根据旅行日期匹配每天的天气
    3. 如果日期超出预报范围，使用最后一条预报兜底
    """
    logger.info(f"[Node] weather_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]
    # 从状态中获取用户请求
    request = state["request"]
    # 获取目标城市：优先从意图分析中获取，如果没有则从请求中获取
    city = intent.city if intent else request.city
    # 获取旅行天数：优先从意图分析中获取，如果没有则从请求计算
    travel_days = (
        intent.travel_days if intent else _calculate_days(request.start_date, request.end_date)
    )

    # 初始化工具调用记录列表
    tool_calls = []
    # 初始化天气列表，用于存储每日天气信息
    weather_list: list[WeatherInfo] = []

    try:
        # ==================== 步骤 1：调用天气接口 ====================
        # 调用 get_weather 工具获取高德天气 API 的原始数据
        raw_weather = await get_weather(city)
        # 记录天气调用到工具列表，截取前 200 字符预览
        tool_calls.append({"tool": "get_weather", "city": city, "result": str(raw_weather)[:200]})

        # ==================== 步骤 2：解析高德天气预报格式 ====================
        # 高德天气接口返回 forecasts 数组，每个元素是一天的预报
        # 初始化预报列表
        forecasts = []
        # 检查返回数据是否为字典且包含 "forecasts" 键
        if isinstance(raw_weather, dict) and "forecasts" in raw_weather:
            # 获取预报数组
            forecasts = raw_weather.get("forecasts", [])

        # 按日期建立映射，方便后续查找
        # 字典推导式：键为日期字符串，值为预报字典
        forecast_by_date = {f.get("date"): f for f in forecasts if f.get("date")}

        # ==================== 步骤 3：生成每日天气 ====================
        # 解析开始日期字符串为 datetime 对象
        start = datetime.strptime(request.start_date, "%Y-%m-%d")
        # 遍历每一天，生成天气信息
        for i in range(travel_days):
            # 计算当前日期：开始日期 + i 天
            # timedelta(days=i) 表示 i 天的时间差
            date_str = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            # 从预报映射中查找当前日期的预报
            # get() 方法在键不存在时返回 None
            cast = forecast_by_date.get(date_str)

            # 如果找到了当天的预报
            if cast:
                # 组合白天与夜间天气
                # 获取白天天气，默认"晴"
                day_weather = cast.get("day_weather", "晴")
                # 获取夜间天气，默认"晴"
                night_weather = cast.get("night_weather", "晴")
                # 如果白天和夜间天气不同，用"转"连接；否则只显示白天天气
                weather_desc = (
                    f"{day_weather}转{night_weather}"
                    if day_weather != night_weather
                    else day_weather
                )

                # 获取白天温度
                day_temp = cast.get("day_temp", "")
                # 获取夜间温度
                night_temp = cast.get("night_temp", "")
                # 组合温度范围："最低温~最高温℃"
                temp_desc = f"{night_temp}~{day_temp}℃" if day_temp and night_temp else ""

                # 获取白天风向
                day_wind = cast.get("day_wind", "")
                # 获取白天风力等级
                day_power = cast.get("day_power", "")
                # 组合风力描述："风向 风力级"
                wind_desc = f"{day_wind} {day_power}级" if day_wind else ""
            else:
                # 超出预报范围时使用最后一条可用预报兜底
                # 高德天气预报通常只能提供未来 3-4 天
                # 如果列表为空，使用空字典；否则取最后一个元素
                last_cast = forecasts[-1] if forecasts else {}
                # 使用最后一条预报的天气，默认"晴"
                weather_desc = last_cast.get("day_weather", "晴")
                # 使用最后一条预报的温度范围
                temp_desc = f"{last_cast.get('night_temp', '')}~{last_cast.get('day_temp', '')}℃"
                # 使用最后一条预报的风力
                wind_desc = f"{last_cast.get('day_wind', '')} {last_cast.get('day_power', '')}级"

            # 构造 WeatherInfo 对象并添加到列表
            weather_list.append(
                WeatherInfo(
                    date=date_str,  # 日期
                    weather=weather_desc,  # 天气描述
                    temperature=temp_desc,  # 温度范围
                    wind=wind_desc,  # 风力描述
                )
            )
    except Exception as exc:
        # 如果天气接口调用失败，记录错误信息
        tool_calls.append({"tool": "get_weather", "city": city, "error": str(exc)})

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "WeatherAgent",  # Agent 名称
        "get_weather",  # 步骤名称
        input_preview=f"城市：{city}，天数：{travel_days}",  # 输入预览
        output_preview=f"生成 {len(weather_list)} 条天气记录",  # 输出预览
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "weather": weather_list,  # 每日天气列表
        "logs": [log],  # 执行日志
        "current_step": "weather_agent",  # 当前步骤名称
    }


async def hotel_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】酒店推荐 Agent。

    调用高德 POI 搜索酒店，获取真实酒店数据。

    【输入】
    - state["intent_analysis"].city：目标城市
    - state["intent_analysis"].accommodation：住宿偏好（如"酒店"、"民宿"）

    【输出】
    - hotels：候选酒店列表（List[Hotel]）
    """
    logger.info(f"[Node] hotel_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]
    # 从状态中获取用户请求
    request = state["request"]
    # 获取目标城市：优先从意图分析中获取，如果没有则从请求中获取
    city = intent.city if intent else request.city
    # 获取住宿偏好：优先从意图分析中获取，如果没有则从请求中获取
    accommodation = intent.accommodation if intent else request.accommodation

    # 搜索关键词：用户指定的住宿偏好，或默认"酒店"
    # 如果用户没有指定住宿偏好，使用默认关键词"酒店"
    keyword = accommodation if accommodation else "酒店"
    # 初始化工具调用记录列表
    tool_calls = []
    # 初始化酒店列表
    hotels: list[Hotel] = []

    try:
        # 调用 search_hotels 工具
        # city: 目标城市
        # keyword: 搜索关键词
        # page_size: 每页返回结果数量
        raw_list = await search_hotels(city=city, keyword=keyword, page_size=6)
        # 记录酒店搜索到工具列表
        tool_calls.append(
            {"tool": "search_hotels", "city": city, "keyword": keyword, "count": len(raw_list)}
        )

        # 转换为 Hotel 模型
        # 遍历搜索结果，将原始字典转换为 Hotel 对象
        for raw in raw_list:
            # 获取位置信息字典
            loc = raw.get("location", {})
            # 构造 Hotel 对象并添加到列表
            hotels.append(
                Hotel(
                    # 酒店 ID：如果 API 没有返回，生成临时 ID
                    id=raw.get("id") or f"hotel_{uuid.uuid4().hex[:8]}",
                    # 酒店名称，默认"未知酒店"
                    name=raw.get("name", "未知酒店"),
                    # 位置信息：构造 Location 对象
                    location=Location(
                        # 经度：转换为浮点数
                        longitude=float(loc.get("longitude", 0)),
                        # 纬度：转换为浮点数
                        latitude=float(loc.get("latitude", 0)),
                        # 地址
                        address=raw.get("address"),
                    ),
                    # 每晚价格：转换为浮点数，可能为空
                    # 如果 API 没有返回，默认 400 元
                    price_per_night=float(raw.get("price_per_night", 400))
                    if raw.get("price_per_night")
                    else None,
                    # 评分：转换为浮点数，可能为空
                    # 如果 API 没有返回，默认 4.2 分
                    rating=float(raw.get("rating", 4.2)) if raw.get("rating") else None,
                    # 图片 URL：可能为空
                    image_url=raw.get("image_url"),
                    # 酒店简介
                    description=raw.get("description"),
                    # 营业时间/入住时间
                    business_hours=raw.get("business_hours"),
                    # 联系电话
                    phone=raw.get("phone"),
                    # 高德详情页链接
                    detail_url=raw.get("detail_url"),
                )
            )
    except Exception as exc:
        # 如果酒店搜索失败，记录错误信息
        tool_calls.append(
            {"tool": "search_hotels", "city": city, "keyword": keyword, "error": str(exc)}
        )

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "HotelAgent",  # Agent 名称
        "search_hotels",  # 步骤名称
        input_preview=f"城市：{city}，关键词：{keyword}",  # 输入预览
        output_preview=f"检索到 {len(hotels)} 个酒店",  # 输出预览
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "hotels": hotels,  # 酒店列表
        "logs": [log],  # 执行日志
        "current_step": "hotel_agent",  # 当前步骤名称
    }


async def food_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】餐厅搜索 Agent。

    调用高德 POI 搜索真实餐厅，获取带照片、评分、地址的店铺数据，
    供 PlannerAgent 在安排三餐时直接选择，避免编造餐厅名称。

    【输入】
    - state["intent_analysis"].city：目标城市
    - state["intent_analysis"].preferences：偏好标签（如"美食"、"海鲜"）
    - state["request"].dietary_restrictions：饮食禁忌

    【输出】
    - restaurants：候选餐厅列表（List[Meal]）
    """
    logger.info(f"[Node] food_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]
    # 从状态中获取用户请求
    request = state["request"]
    # 获取目标城市
    city = intent.city if intent else request.city
    # 获取偏好标签，用于构造餐厅搜索关键词
    preferences = intent.preferences if intent else request.preferences

    # 初始化工具调用记录列表
    tool_calls = []
    # 初始化候选餐厅列表
    restaurants: list[Meal] = []

    # 构造搜索关键词：优先根据用户偏好，如"海鲜"、"美食"，默认"餐厅"
    search_keywords = ["餐厅"]
    for pref in preferences:
        if pref and pref not in search_keywords:
            search_keywords.append(pref)

    # 限制最多搜索 2 个关键词，避免请求过多
    search_keywords = search_keywords[:2]

    # 用于去重的集合
    seen_names = set()

    try:
        for keyword in search_keywords:
            raw_list = await search_restaurants(city=city, keyword=keyword, page_size=15)
            tool_calls.append(
                {"tool": "search_restaurants", "keyword": keyword, "count": len(raw_list)}
            )

            for raw in raw_list:
                name = raw.get("name", "")
                if not name or name in seen_names:
                    continue
                seen_names.add(name)

                loc = raw.get("location", {})
                restaurants.append(
                    Meal(
                        type="restaurant",
                        name=name,
                        cuisine=raw.get("type", "").split(";")[-1] if raw.get("type") else None,
                        estimated_cost=raw.get("estimated_cost"),
                        location=Location(
                            longitude=float(loc.get("longitude", 0)),
                            latitude=float(loc.get("latitude", 0)),
                            address=raw.get("address"),
                        ),
                        location_name=raw.get("address"),
                        detail_url=raw.get("detail_url"),
                        image_url=raw.get("image_url"),
                        photos=raw.get("photos", []),
                        rating=float(raw.get("rating")) if raw.get("rating") else None,
                        phone=raw.get("phone"),
                        business_hours=raw.get("business_hours"),
                        address=raw.get("address"),
                    )
                )

                # 每个关键词最多取 10 条，避免列表过长
                if sum(1 for r in restaurants if keyword in (r.cuisine or "")) >= 10:
                    break

            # 如果已经收集到足够多的餐厅，提前结束
            if len(restaurants) >= 15:
                break

    except Exception as exc:
        tool_calls.append({"tool": "search_restaurants", "error": str(exc)})

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "FoodAgent",
        "search_restaurants",
        input_preview=f"城市：{city}，关键词：{search_keywords}",
        output_preview=f"检索到 {len(restaurants)} 个餐厅",
        tool_calls=tool_calls,
    )
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {"restaurants": restaurants, "logs": [log], "current_step": "food_agent"}


async def rag_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】知识检索 Agent。

    从 Qdrant 向量库检索城市攻略或景点背景知识。
    当前知识库可能为空（需要导入数据），所以返回空字符串。

    【输入】
    - state["intent_analysis"].city：目标城市
    - state["intent_analysis"].preferences：偏好标签

    【输出】
    - rag_context：检索到的上下文文本（供 PlannerAgent 参考）
    """
    logger.info(f"[Node] rag_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]
    # 从状态中获取用户请求
    request = state["request"]
    # 获取目标城市：优先从意图分析中获取，如果没有则从请求中获取
    city = intent.city if intent else request.city
    # 获取偏好标签：优先从意图分析中获取，如果没有则从请求中获取
    preferences = intent.preferences if intent else request.preferences

    # 构造查询文本：城市 + "旅游攻略" + 偏好标签（用空格连接）
    # 例如："北京旅游攻略 美食 文化"
    query = f"{city}旅游攻略 {' '.join(preferences)}"
    # 初始化工具调用记录，包含查询信息
    tool_calls = [{"tool": "search_rag_context", "query": query}]

    try:
        # 调用 search_rag_context 工具
        # query: 查询文本
        # city: 目标城市
        # top_k: 返回最相关的 K 条结果
        # search_rag_context 是同步函数（内部做向量编码 + Qdrant 检索），
        # 必须放入线程池执行，避免阻塞事件循环导致 SSE 流假死
        context = await asyncio.to_thread(search_rag_context, query=query, city=city, top_k=5)
    except Exception as exc:
        # 如果检索失败，返回空字符串，不影响后续流程
        context = ""
        # 记录错误信息到工具调用列表
        tool_calls[0]["error"] = str(exc)

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "RAGAgent",  # Agent 名称
        "search_rag_context",  # 步骤名称
        input_preview=query,  # 输入预览
        output_preview=context[:300],  # 输出预览（截取前 300 字符）
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "rag_context": context,  # RAG 检索到的上下文文本
        "logs": [log],  # 执行日志
        "current_step": "rag_agent",  # 当前步骤名称
    }


async def route_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】路线规划 Agent。

    计算候选景点之间的距离和通行时间矩阵。
    这个矩阵会被 PlannerAgent 参考，用于决定每天安排哪些景点（相近的放同一天）。

    【输入】
    - state["attractions"]：所有候选景点（包含经纬度）
    - state["intent_analysis"].transportation：交通方式

    【输出】
    - route_matrix：路线矩阵字典，键为 "景点A|景点B"，值为距离/时间

    【核心逻辑】
    - 对每两个景点，调用高德路线规划接口
    - 如果接口失败，使用 Haversine 直线距离估算
    """
    logger.info(f"[Node] route_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取景点列表
    attractions = state["attractions"]
    # 从状态中获取意图分析结果
    intent = state["intent_analysis"]

    # 根据交通方式选择路线规划模式
    # 高德 API 支持多种交通方式，对应不同的参数值
    mode = "driving"  # 默认驾车
    # 如果交通方式是公共交通类，使用 "transit" 模式
    if intent and intent.transportation in ["公共交通", "公交", "地铁"]:
        mode = "transit"
    # 如果交通方式是步行类，使用 "walking" 模式
    elif intent and intent.transportation in ["步行", "走路"]:
        mode = "walking"

    # 初始化路线矩阵字典
    # 键为 "景点A|景点B"，值为包含距离和时间的字典
    route_matrix: dict[str, Any] = {}
    # 初始化工具调用记录列表
    tool_calls = []

    # ==================== 辅助函数：计算单个景点对的路线 ====================
    # 将每个景点对的路线计算封装成独立的异步任务，后续用 asyncio.gather 并行执行
    async def _compute_one_route(a: Attraction, b: Attraction) -> tuple:
        """
        计算单个景点对 (a -> b) 的路线。

        返回：
        - key: "景点A名称|景点B名称"
        - route_info: 路线信息字典
        - tool_call: 工具调用记录
        """
        key = f"{a.name}|{b.name}"

        try:
            # 高德要求坐标格式为 "经度,纬度"（注意顺序）
            origin = f"{a.location.longitude},{a.location.latitude}"
            destination = f"{b.location.longitude},{b.location.latitude}"
            # 调用高德路线规划 API，返回包含距离（米）和时长（秒）的字典
            route_info = await plan_route(origin, destination, mode)
            return key, route_info, {"tool": "plan_route", "key": key, "status": "ok"}

        except Exception:
            # 如果高德 API 调用失败，使用 Haversine 公式计算直线距离并估算时间
            distance = haversine_distance(
                a.location.longitude, a.location.latitude, b.location.longitude, b.location.latitude
            )

            # 根据交通方式估算通行时间（秒/米）
            speed_map = {"driving": 0.5, "transit": 1.0, "walking": 3.0}
            duration = distance * speed_map.get(mode, 0.5)

            route_info = {
                "origin": a.name,
                "destination": b.name,
                "mode": mode,
                "distance": round(distance, 1),
                "duration": round(duration, 1),
                "polyline": [],
            }
            return key, route_info, {"tool": "haversine_estimate", "key": key}

    # ==================== 步骤 1：构造所有路线计算任务 ====================
    # 遍历所有景点对（排除自己到自己），每个景点对创建一个异步任务
    route_tasks = []
    for i, a in enumerate(attractions):
        for j, b in enumerate(attractions):
            if i == j:
                continue
            route_tasks.append(_compute_one_route(a, b))

    # ==================== 步骤 2：并行执行所有路线计算 ====================
    # asyncio.gather 会同时发起多个高德 API 请求，显著缩短总体耗时
    results = await asyncio.gather(*route_tasks, return_exceptions=True)

    # ==================== 步骤 3：合并结果 ====================
    # 将每个任务的结果合并到路线矩阵和工具调用记录中
    for result in results:
        # 如果某个任务抛出异常，使用 Haversine 估算兜底
        if isinstance(result, Exception):
            continue
        key, route_info, tool_call = result
        route_matrix[key] = route_info
        tool_calls.append(tool_call)

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "RouteAgent",  # Agent 名称
        "plan_route",  # 步骤名称
        input_preview=f"景点数：{len(attractions)}，交通方式：{mode}",  # 输入预览
        output_preview=f"生成 {len(route_matrix)} 条路线",  # 输出预览
        tool_calls=tool_calls[:10],  # 日志中只保留前 10 条，避免日志过长
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "route_matrix": route_matrix,  # 路线矩阵
        "logs": [log],  # 执行日志
        "current_step": "route_agent",  # 当前步骤名称
    }


# ==================== 多城市联游规划辅助 ====================
# 以下函数仅被 planner_agent_node 的多城分支调用；单城链路不经过这些代码。


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


async def _call_llm_for_plan(
    messages: list[Any], tool_calls: list[dict[str, Any]]
) -> TripPlan | None:
    """
    调用 LLM 生成 TripPlan（带一次重试），解析失败返回 None。

    与单城 planner 的调用口径一致：temperature 0.4，首次 300 秒超时，重试 180 秒。
    """
    try:
        llm = get_llm(temperature=0.4, timeout=300)
        try:
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=300)
        except TimeoutError:
            raise RuntimeError("PlannerAgent LLM 调用超时（>300秒）")
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
            f"[Node] 多城 planner 将必去景点 {mv_name} 插入第 {target_day.day_index} 天（{target_day.city}）"
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
            f"第{d.day_index}天({d.date} {city_label}景点[{attr_names}] | 餐饮[{meal_names}] | 酒店[{hotel_name}]"
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
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    logger.debug(f"[Node] 多城 planner prompt 构造完成，长度={len(human_prompt)}")

    # ==================== 步骤 2：调用 LLM（失败重试 + 兜底） ====================
    tool_calls: list[dict[str, Any]] = []
    plan = await _call_llm_for_plan(messages, tool_calls)
    if plan is None:
        # 兜底计划基于主城市数据机械拼装，随后由规范化步骤补 city / intercity_note
        plan = _build_fallback_plan(state)
        tool_calls.append({"tool": "fallback_plan", "status": "used"})
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
        llm = get_llm(temperature=0.4, timeout=300)
        logger.debug(f"[Node] planner_agent_node LLM 实例已创建，messages 长度={len(messages)}")
        # 调用 LLM，生成行程计划
        # 用 asyncio.wait_for 强制 5 分钟超时，防止百炼 API 在巨大 prompt 下无限挂起
        try:
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=300)
        except TimeoutError:
            raise RuntimeError(
                f"PlannerAgent LLM 调用超时（>300秒），prompt 长度={len(human_prompt)}"
            )
        logger.info("[Node] planner_agent_node LLM 调用完成")
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
                    f"[Node] planner_agent_node 将必去景点 {mv_name} 插入到第 {target_day.day_index} 天"
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


async def budget_agent_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】预算统计 Agent。

    根据 final_plan 中的景点门票、餐饮、酒店计算预算。

    【输入】
    - state["final_plan"]：完整行程计划

    【输出】
    - final_plan.budget：预算统计（门票、餐饮、住宿、交通）

    【计算逻辑】
    - 门票：累加所有景点的 ticket_price
    - 餐饮：累加所有餐食的 estimated_cost
    - 住宿：酒店价格 ×（旅行天数 - 1）晚
    - 交通：固定 50 元/人/天
    """
    logger.info(f"[Node] budget_agent_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取最终行程计划
    final_plan = state["final_plan"]

    # 如果 final_plan 为空，直接返回，跳过预算计算
    if not final_plan:
        return {
            "logs": [
                _make_log("BudgetAgent", "calculate", output_preview="无 final_plan，跳过")
            ],  # 日志
            "current_step": "budget_agent",  # 当前步骤名称
        }

    # 初始化各项费用，全部为浮点数
    attractions_cost = 0.0  # 门票费用
    meals_cost = 0.0  # 餐饮费用
    hotels_cost = 0.0  # 住宿费用
    transportation_cost = 0.0  # 交通费用

    # 遍历每天行程
    for day in final_plan.day_plans:
        # 累加门票费用
        # 遍历当天的所有景点
        for attr in day.attractions:
            # 如果景点有门票价格，累加到总费用
            # 使用 or 0 避免空值
            attractions_cost += attr.ticket_price or 0
        # 累加餐饮费用
        # 遍历当天的所有餐食
        for meal in day.meals:
            # 如果餐食有预估费用，累加到总费用
            meals_cost += meal.estimated_cost or 0

    # 住宿费用：按（旅行天数 - 1）晚计算
    # 例如 3 天 2 晚，住宿费用 = 单晚价格 × 2
    # max(1, ...) 确保至少 1 晚，避免负数或零
    nights = max(1, final_plan.travel_days - 1)
    # 初始化酒店单价为 0
    hotel_price = 0.0
    # 遍历每天的行程，找到第一个有酒店的日期
    for day in final_plan.day_plans:
        # 如果当天有酒店信息且酒店有每晚价格
        if day.hotel and day.hotel.price_per_night:
            # 获取酒店每晚价格
            hotel_price = day.hotel.price_per_night
            # 找到第一个酒店后退出循环
            break
    # 计算总住宿费用
    hotels_cost = hotel_price * nights

    # 交通费用：固定 50 元/人/天
    # 这是简化的估算，实际交通费用可能因城市和行程而异
    transportation_cost = final_plan.travel_days * 50.0

    # 计算总费用：所有费用之和
    total = attractions_cost + meals_cost + hotels_cost + transportation_cost

    # 构造 Budget 对象
    budget = Budget(
        attractions=round(attractions_cost, 2),  # 门票费用，保留 2 位小数
        meals=round(meals_cost, 2),  # 餐饮费用，保留 2 位小数
        hotels=round(hotels_cost, 2),  # 住宿费用，保留 2 位小数
        transportation=round(transportation_cost, 2),  # 交通费用，保留 2 位小数
        total=round(total, 2),  # 总费用，保留 2 位小数
        currency="CNY",  # 货币单位：人民币
        notes="预算仅供参考，实际价格以现场为准。",  # 备注
    )

    # 更新 final_plan 的 budget 字段
    final_plan.budget = budget

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "BudgetAgent",  # Agent 名称
        "calculate_budget",  # 步骤名称
        input_preview=f"行程天数：{final_plan.travel_days}",  # 输入预览
        output_preview=budget.model_dump_json(ensure_ascii=False),  # 输出预览
        tool_calls=[{"tool": "sum", "total": total}],  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "final_plan": final_plan,  # 更新后的行程计划（包含预算）
        "logs": [log],  # 执行日志
        "current_step": "budget_agent",  # 当前步骤名称
    }


async def human_in_the_loop_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】人机协同节点（当前为自动通过）。

    预留的扩展点，用于在关键决策点暂停并等待用户确认。
    当前实现：自动放行，记录 {"auto_approved": True}。

    【输入】
    - state["candidate_plans"]：候选方案列表

    【输出】
    - human_decisions：用户决策（当前为自动通过）
    """
    logger.info(f"[Node] human_in_the_loop_node 开始执行，plan_id={state.get('plan_id')}")
    # 构造日志对象
    # 这个节点当前是自动通过模式，不需要用户确认
    log = _make_log(
        "HumanInTheLoop",  # Agent 名称
        "await_decision",  # 步骤名称
        output_preview="当前为自动通过模式，未触发人工确认。",  # 输出预览
    )

    # 返回状态更新字典
    return {
        "human_decisions": {"auto_approved": True},  # 用户决策：自动通过
        "logs": [log],  # 执行日志
        "current_step": "human_in_the_loop",  # 当前步骤名称
    }


async def finalize_node(state: TravelPlanningState) -> dict[str, Any]:
    """
    【节点作用】收尾节点。

    将 final_plan 写入数据库，更新状态为 completed。

    【输入】
    - state["final_plan"]：最终行程计划
    - state["plan_id"]：行程 ID

    【输出】
    - logs：执行日志
    """
    logger.info(f"[Node] finalize_node 开始执行，plan_id={state.get('plan_id')}")
    # 记录开始时间
    start_at = time.perf_counter()
    # 从状态中获取最终行程计划
    final_plan = state["final_plan"]
    # 从状态中获取行程 ID
    plan_id = state["plan_id"]

    logger.info(f"[Node] finalize_node final_plan 检查: final_plan={final_plan is not None}")
    if final_plan:
        logger.debug(
            f"[Node] finalize_node final_plan 详情: city={final_plan.city}, days={len(final_plan.day_plans)}, day1_attractions={len(final_plan.day_plans[0].attractions) if final_plan.day_plans else 0}"
        )

    # 初始化工具调用记录列表
    tool_calls = []

    revision_type = state.get("revision_type", "initial")
    memory_service = MemoryService()

    try:
        # 使用异步上下文管理器创建数据库会话
        async with AsyncSessionLocal() as session:
            # 根据 plan_id 查询数据库记录
            # session.get() 是 SQLAlchemy 2.0 的异步查询方法
            db_plan = await session.get(TripPlanDB, plan_id)

            # 如果数据库记录存在且最终行程计划存在
            if db_plan and final_plan:
                # 更新状态为 "completed"（已完成）
                db_plan.status = "completed"
                # 将行程计划序列化为 JSON 并存入数据库
                # model_dump(mode="json") 将 Pydantic 模型转为可 JSON 序列化的字典
                db_plan.plan_data = final_plan.model_dump(mode="json")
                # 多城市联游：把请求中的城市停留分配单独落列，便于按城市查询（单城为 None）
                request = state.get("request")
                request_cities = getattr(request, "cities", None) if request is not None else None
                db_plan.cities_json = (
                    [c.model_dump(mode="json") for c in request_cities] if request_cities else None
                )

                # 创建或更新 PlanRevision 版本记录
                if revision_type == "initial":
                    await memory_service.create_initial_revision(session, plan_id, final_plan)
                else:
                    parent_revision_id = state.get("parent_revision_id")
                    if parent_revision_id:
                        # 计算新旧行程的 diff，写到新版本的 metadata 里
                        # 前端可以展示"本次重新生成修改了 N 处"，避免"看不出变化"
                        previous_plan = state.get("previous_plan")
                        diff_summary = _compute_plan_diff(previous_plan, final_plan)
                        new_revision = await memory_service.create_revision(
                            session,
                            plan_id,
                            parent_revision_id,
                            final_plan,
                            source=revision_type,
                            diff_summary=diff_summary,
                        )
                        logger.debug(
                            f"[Finalize] v{new_revision.version} diff_summary: {diff_summary}"
                        )
                    else:
                        await memory_service.create_initial_revision(session, plan_id, final_plan)

                # 如果是反馈触发的修订，固化长期记忆
                structured_feedback = state.get("structured_feedback")
                if structured_feedback and revision_type in ("patch", "full"):
                    try:
                        # structured_feedback 在重新生成时可能是 dict，统一转为 Pydantic 对象
                        from app.models.schemas import StructuredFeedback

                        if isinstance(structured_feedback, dict):
                            try:
                                sf_obj = StructuredFeedback(**structured_feedback)
                            except Exception:
                                sf_obj = None
                        else:
                            sf_obj = structured_feedback

                        if sf_obj:
                            await memory_service.consolidate_memory(
                                session=session,
                                user_id=state.get("user_id"),
                                city=final_plan.city,
                                structured_feedback=sf_obj,
                                raw_text=state.get("revision_notes", ""),
                            )
                    except Exception as mem_exc:
                        logger.warning(f"[Finalize] 记忆固化失败: {mem_exc}")

                # 提交数据库事务
                await session.commit()
                # 记录成功的数据库更新
                tool_calls.append({"tool": "db_update", "plan_id": plan_id, "status": "completed"})
                tool_calls.append({"tool": "revision_persist", "revision_type": revision_type})

            # 如果数据库记录存在但没有最终行程计划
            elif db_plan:
                # 标记状态为 "failed"（失败）
                db_plan.status = "failed"
                # 存入错误信息
                db_plan.plan_data = {"error": "未生成有效行程"}
                # 提交数据库事务
                await session.commit()
                # 记录失败的数据库更新
                tool_calls.append({"tool": "db_update", "plan_id": plan_id, "status": "failed"})

    except Exception as exc:
        # 如果数据库操作失败，记录错误信息
        tool_calls.append({"tool": "db_update", "plan_id": plan_id, "error": str(exc)})

    # 计算节点执行耗时
    duration_ms = int((time.perf_counter() - start_at) * 1000)
    # 构造日志对象
    log = _make_log(
        "Finalize",  # Agent 名称
        "persist_plan",  # 步骤名称
        output_preview=f"计划 {plan_id} 已持久化",  # 输出预览
        tool_calls=tool_calls,  # 工具调用记录
    )
    # 设置日志的执行耗时
    log.duration_ms = duration_ms

    # 返回状态更新字典
    return {
        "logs": [log],  # 执行日志
        "current_step": "finalize",  # 当前步骤名称
    }


# ==================== 兜底/辅助函数 ====================


def _compute_plan_diff(previous_plan: Any, new_plan: Any) -> dict[str, Any]:
    """
    【函数作用】对比新旧行程，返回"修改了什么"的结构化摘要。

    用户提意见后 regenerate 总是看到"行程没变化"，其实有变化但前端不知道。
    这里把"哪天的哪个景点/餐厅/酒店被改了"算出来，存入 revision 记录的 metadata，
    前端可以基于这个字段展示"本次重新生成修改了 N 处"。

    【参数】
    - previous_plan: 上一次的 TripPlan (Pydantic 或 dict)
    - new_plan: 新生成的 TripPlan (Pydantic 或 dict)

    【返回值】
    - Dict[str, Any]: {
        "total_changes": 5,
        "days": [
          {
            "day_index": 2,
            "attractions": {"added": ["水族馆"], "removed": ["赤坎老街"]},
            "meals": {"changed": [{"meal_type": "lunch", "from": "喜苑餐厅", "to": "唐苑"}]},
            "hotel": {"from": "二祥宾馆", "to": "二祥宾馆"}
          }
        ]
      }
    """

    def to_dict(plan):
        if plan is None:
            return {}
        if hasattr(plan, "model_dump"):
            return plan.model_dump(mode="json")
        if hasattr(plan, "dict"):
            return plan.dict()
        return plan or {}

    prev = to_dict(previous_plan)
    new = to_dict(new_plan)

    diff = {"total_changes": 0, "days": []}

    prev_days = {d["day_index"]: d for d in prev.get("day_plans", [])}
    new_days = {d["day_index"]: d for d in new.get("day_plans", [])}

    for day_idx in sorted(set(prev_days.keys()) | set(new_days.keys())):
        p = prev_days.get(day_idx, {})
        n = new_days.get(day_idx, {})

        # 景点名称集合
        prev_attrs = {a.get("name", "") for a in p.get("attractions", [])}
        new_attrs = {a.get("name", "") for a in n.get("attractions", [])}
        added = new_attrs - prev_attrs
        removed = prev_attrs - new_attrs

        # 餐厅对比（按 type 对比 name）
        prev_meals = {m.get("type"): m.get("name") for m in p.get("meals", [])}
        new_meals = {m.get("type"): m.get("name") for m in n.get("meals", [])}
        changed_meals = []
        for t in set(prev_meals.keys()) | set(new_meals.keys()):
            if prev_meals.get(t) != new_meals.get(t):
                changed_meals.append(
                    {
                        "meal_type": t,
                        "from": prev_meals.get(t),
                        "to": new_meals.get(t),
                    }
                )

        # 酒店对比
        prev_hotel = (p.get("hotel") or {}).get("name")
        new_hotel = (n.get("hotel") or {}).get("name")

        day_changes = {
            "day_index": day_idx,
            "attractions": {"added": sorted(added), "removed": sorted(removed)},
            "meals": {"changed": changed_meals},
            "hotel": {"from": prev_hotel, "to": new_hotel} if prev_hotel != new_hotel else None,
        }
        # 统计这一天有多少处变化
        day_change_count = len(added) + len(removed) + len(changed_meals)
        if day_changes["hotel"]:
            day_change_count += 1
        if day_change_count > 0:
            day_changes["change_count"] = day_change_count
            diff["days"].append(day_changes)
            diff["total_changes"] += day_change_count

    return diff


def _build_fallback_plan(state: TravelPlanningState) -> TripPlan:
    """
    【函数作用】构造兜底行程计划。

    当 LLM 解析失败时使用。优先使用已获取的真实景点和酒店数据；
    若完全没有景点数据，则返回明确提示，而不是编造虚假景点。

    【参数】
    - state：当前工作流状态

    【返回值】
    - TripPlan：基于真实数据的兜底行程计划

    【核心逻辑】
    1. 如果有景点数据，按天均匀分配（每天 2 个）
    2. 如果没有景点数据，返回"数据不足"提示
    """
    # 从状态中获取用户请求
    request = state["request"]
    # 从状态中获取景点列表
    attractions = state["attractions"]
    # 从状态中获取酒店列表
    hotels = state["hotels"]
    # 计算旅行天数
    travel_days = _calculate_days(request.start_date, request.end_date)
    # 解析开始日期为 datetime 对象
    start = datetime.strptime(request.start_date, "%Y-%m-%d")

    # 初始化每日行程列表
    day_plans: list[DayPlan] = []

    # 判断是否有景点数据
    if not attractions:
        # ==================== 情况 1：完全没有景点数据 ====================
        # 这种情况下，无法安排景点，生成提示性的行程
        # 遍历每一天
        for day_index in range(1, travel_days + 1):
            # 计算当前日期：开始日期 + (day_index - 1) 天
            date_str = (start + timedelta(days=day_index - 1)).strftime("%Y-%m-%d")
            # 构造当天的行程计划
            # 由于没有景点，只安排餐饮和住宿
            day_plan = DayPlan(
                day_index=day_index,  # 天数索引
                date=date_str,  # 日期
                description="未能从地图服务获取到该城市的景点数据，请检查城市名称或 API Key 配置。",  # 描述
                attractions=[],  # 景点列表（空）
                meals=[  # 餐饮安排
                    Meal(
                        type="breakfast",
                        name="酒店早餐/自理",
                        cuisine="本地菜",
                        estimated_cost=30.0,
                    ),
                    Meal(type="lunch", name="附近餐厅", cuisine="本地菜", estimated_cost=80.0),
                    Meal(type="dinner", name="附近餐厅", cuisine="本地菜", estimated_cost=100.0),
                ],
                hotel=hotels[0] if hotels else None,  # 酒店：使用第一个酒店，如果没有则为 None
                transportation=request.transportation,  # 交通方式
            )
            _enrich_day_plan_with_map_data(day_plan, state.get("route_matrix", {}))
            day_plans.append(day_plan)
        # 设置整体建议信息
        overall_suggestions = "本次规划未能获取景点数据，请确认高德 API Key 有效且城市名称正确。"

    else:
        # ==================== 情况 2：有真实景点数据 ====================
        # 遍历每一天
        for day_index in range(1, travel_days + 1):
            # 计算当前日期
            date_str = (start + timedelta(days=day_index - 1)).strftime("%Y-%m-%d")

            # 每天取 2 个景点，按顺序切片
            # 计算景点在列表中的起始索引
            start_i = (day_index - 1) * 2
            # 切片获取当天的景点（最多 2 个）
            day_attractions = attractions[start_i : start_i + 2]

            # 构造当天的餐饮安排
            meals = [
                Meal(type="breakfast", name="酒店早餐", cuisine="中式", estimated_cost=30.0),
                Meal(type="lunch", name="上午景点附近餐厅", cuisine="本地菜", estimated_cost=80.0),
                Meal(
                    type="dinner", name="下午景点附近餐厅", cuisine="本地菜", estimated_cost=100.0
                ),
            ]

            # 酒店安排：使用第一个酒店
            hotel = hotels[0] if hotels else None

            # 构造当天的行程计划
            day_plan = DayPlan(
                day_index=day_index,  # 天数索引
                date=date_str,  # 日期
                description=f"第 {day_index} 天行程，基于高德地图真实 POI 数据。",  # 描述
                attractions=day_attractions,  # 景点列表
                meals=meals,  # 餐饮安排
                hotel=hotel,  # 酒店
                transportation=request.transportation,  # 交通方式
            )
            _enrich_day_plan_with_map_data(day_plan, state.get("route_matrix", {}))
            day_plans.append(day_plan)
        # 设置整体建议信息
        overall_suggestions = (
            "本次行程基于高德地图真实 POI 数据生成。门票和餐饮为估算值，实际请以现场为准。"
        )

    # 构造并返回完整的行程计划对象
    return TripPlan(
        plan_id=state["plan_id"],  # 行程 ID
        user_id=state["user_id"],  # 用户 ID
        city=request.city,  # 目标城市
        start_date=request.start_date,  # 开始日期
        end_date=request.end_date,  # 结束日期
        travel_days=travel_days,  # 旅行天数
        overall_suggestions=overall_suggestions,  # 整体建议
        day_plans=day_plans,  # 每日行程列表
        budget=Budget(),  # 预算（空对象，后续由 budget_agent_node 填充）
        weather=state["weather"],  # 天气信息
        style="standard",  # 行程节奏
    )


# ==================== 行程迭代修订节点 ====================


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
