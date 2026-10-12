"""budget_agent_node：预算统计节点，汇总门票/餐饮/住宿/交通费用。"""

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
# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    Budget,  # 预算数据模型，包含门票、餐饮、住宿、交通费用
)


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
