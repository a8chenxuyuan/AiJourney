"""food_agent_node：餐厅推荐节点，调用高德 POI 搜索真实餐厅。"""

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
from loguru import logger

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM
# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好
# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型
# 包内共享的通用工具函数（未用到的名字由 ruff F401 自动清理）
from app.agents.nodes._helpers import (
    _make_log,
)

# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.agents.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
from app.agents.tools import (
    search_restaurants,  # 调用高德 POI 搜索 API，搜索真实餐厅
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Location,  # 位置数据模型，包含经度、纬度、地址
    Meal,  # 餐饮数据模型，包含餐次类型、菜系、预估费用
)


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
