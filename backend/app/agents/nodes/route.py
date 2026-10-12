"""route_agent_node：路线规划节点，调用高德路线接口计算每日景点间交通。"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务
import asyncio

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

# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
# 包内共享的通用工具函数（未用到的名字由 ruff F401 自动清理）
from app.agents.nodes._helpers import (
    _make_log,
)

# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.agents.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
from app.agents.tools import (
    haversine_distance,  # 计算两个经纬度坐标之间的直线距离（球面距离）
    plan_route,  # 调用高德路线规划 API，获取两点间的距离和通行时间
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Attraction,  # 景点数据模型，包含名称、位置、门票、评分等字段
)

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好

# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型


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
