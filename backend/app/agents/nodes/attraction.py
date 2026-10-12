"""attraction_agent_node：景点检索节点，调用高德 POI 搜索真实景点。"""

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
    search_attractions,  # 调用高德 POI 搜索 API，搜索景点
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Attraction,  # 景点数据模型，包含名称、位置、门票、评分等字段
    Location,  # 位置数据模型，包含经度、纬度、地址
)


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
    search_keywords = list({k.strip() for k in search_keywords if k.strip()})

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
                            f"[Node] attraction_agent_node 为 {attraction.name} 补充背景知识，"
                            f"来源缓存={bg.get('from_cache')}"
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
