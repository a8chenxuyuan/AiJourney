"""rag_agent_node：知识检索节点，从 Qdrant 检索目的地知识库内容。"""

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
from app.planning.agents._helpers import (
    _make_log,
    _save_full_artifact,
)

# TravelPlanningState：整个工作流的状态类型定义，包含所有节点的输入输出字段
from app.planning.state import TravelPlanningState

# 工具函数：用于调用外部服务（高德地图 API、RAG 检索等）
from app.planning.tools import (
    search_rag_context,  # 调用 Qdrant 向量数据库，检索相关知识库内容
)

# AsyncSessionLocal：异步数据库会话工厂，用于创建数据库连接

# TripPlanDB：行程计划的数据库模型类，对应数据库表结构

# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则

# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM

# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好

# parse_llm_json：解析 LLM 输出的 JSON 字符串并验证为 Pydantic 模型


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

    # M1 上下文瘦身：攻略上下文落 artifact_store（state 保留原样，按 kind 可回溯）
    artifact_refs = await _save_full_artifact(state["plan_id"], f"rag:{city}", context)

    # 返回状态更新字典
    return {
        "rag_context": context,  # RAG 检索到的上下文文本
        "artifact_refs": artifact_refs,  # 全量结果引用
        "logs": [log],  # 执行日志
        "current_step": "rag_agent",  # 当前步骤名称
    }
