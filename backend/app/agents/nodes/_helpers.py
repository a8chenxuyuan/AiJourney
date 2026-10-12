"""通用工具函数：被多个 LangGraph 节点共享的辅助逻辑（非节点本身）。"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务

# json 模块：用于 POI 摘要等场景的 JSON 序列化
import json

# time 模块：提供时间相关函数，用于计算代码执行耗时
# uuid 模块：生成唯一标识符，用于为缺少 ID 的数据生成临时 ID
# datetime 模块：处理日期和时间，用于解析用户输入的日期和计算旅行天数
from datetime import datetime, timedelta

# typing 模块：提供类型提示支持，使代码更清晰、更易维护
from typing import Any

# ==================== LangChain 核心导入 ====================
# HumanMessage：代表用户输入的消息，供 LLM 理解用户意图
# SystemMessage：代表系统指令消息，用于设置 LLM 的角色和行为规范
# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.agents.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    AgentLog,  # Agent 执行日志模型，记录每个节点的执行情况
    Attraction,  # 景点数据模型，包含名称、位置、门票、评分等字段
    Budget,  # 预算数据模型，包含门票、餐饮、住宿、交通费用
    DayPlan,  # 单日行程计划模型，包含当天的景点、餐饮、酒店
    Hotel,  # 酒店数据模型，包含名称、位置、价格、评分等字段
    Location,  # 位置数据模型，包含经度、纬度、地址
    Meal,  # 餐饮数据模型，包含餐次类型、菜系、预估费用
    TripPlan,  # 完整行程计划模型，包含多天行程、预算、建议
)

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好

# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型


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
    tool_calls: list[dict[str, Any]] | None = None,
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
                description=(
                    "未能从地图服务获取到该城市的景点数据，请检查城市名称或 API Key 配置。"
                ),  # 描述
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
