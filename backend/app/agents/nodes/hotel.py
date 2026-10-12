"""hotel_agent_node：酒店推荐节点，调用高德 POI 搜索真实酒店。"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务

# json 模块：用于 POI 摘要等场景的 JSON 序列化

# time 模块：提供时间相关函数，用于计算代码执行耗时
import time

# uuid 模块：生成唯一标识符，用于为缺少 ID 的数据生成临时 ID
import uuid

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
    search_hotels,  # 调用高德 POI 搜索 API，搜索酒店
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Hotel,  # 酒店数据模型，包含名称、位置、价格、评分等字段
    Location,  # 位置数据模型，包含经度、纬度、地址
)


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
