"""intent_agent_node：意图理解节点，把用户表单解析为结构化 IntentAnalysis。"""

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

# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型
from app.agentkit.context.manager import context_manager

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接
from app.core.db.session import AsyncSessionLocal
from app.core.utils.json_parser import parse_llm_json

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM
from app.llm.client import get_llm
from app.llm.usage import record_llm_usage

# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
from app.models.schemas import (
    IntentAnalysis,  # 意图分析结果模型，从用户表单解析出的结构化数据
)

# ==================== 本地模块导入 ====================
# prompts 模块：包含所有 Agent 的提示词模板（system prompt 和 human prompt）
from app.planning import prompts

# 包内共享的通用工具函数（未用到的名字由 ruff F401 自动清理）
from app.planning.agents._helpers import (
    _make_log,
)

# AgentConfig：Agent 配置类，包含最小/最大景点数等配置项
# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.planning.state import TravelPlanningState

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好
from app.services.memory_service import MemoryService


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

    # M1：跨会话规划事实经 context_manager 的 MemoryLayer 注入（唯一装配入口）
    memory_text = await context_manager.assemble(
        state["plan_id"], "IntentAgent", user_id=state["user_id"]
    )
    if memory_text:
        preference_text = f"{preference_text}\n\n{memory_text}"

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
        # token 用量打点（M1 prompt 瘦身的度量地基）
        record_llm_usage(state["plan_id"], "IntentAgent", response)
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
        "messages": [*messages, HumanMessage(content=intent.model_dump_json(ensure_ascii=False))],
        "logs": [log],  # 执行日志列表
        "current_step": "intent_agent",  # 当前步骤名称，用于前端展示进度
    }
