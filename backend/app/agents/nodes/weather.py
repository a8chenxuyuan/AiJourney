"""weather_agent_node：天气查询节点，调用高德天气接口获取逐日预报。"""

# ==================== 标准库导入 ====================
# asyncio 模块：提供异步编程支持，用于并行执行多个 IO 任务

# json 模块：用于 POI 摘要等场景的 JSON 序列化

# time 模块：提供时间相关函数，用于计算代码执行耗时
import time

# uuid 模块：生成唯一标识符，用于为缺少 ID 的数据生成临时 ID
# datetime 模块：处理日期和时间，用于解析用户输入的日期和计算旅行天数
from datetime import datetime, timedelta

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
    _calculate_days,
    _make_log,
)

# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.agents.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
from app.agents.tools import (
    get_weather,  # 调用高德天气 API，获取城市天气预报
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    WeatherInfo,  # 天气信息模型，包含日期、天气描述、温度、风力
)


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
