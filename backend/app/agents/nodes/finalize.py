"""human_in_the_loop_node 与 finalize_node：人机协同放行与收尾保存（含版本 diff）。"""

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
from app.db.session import AsyncSessionLocal

# TripPlanDB：行程计划的数据库模型类，对应数据库表结构
from app.models.db_models import TripPlanDB

# 数据模型：Pydantic 模型，定义了各个数据的结构和验证规则
# get_llm：获取 LLM 实例的工厂函数，根据配置创建不同类型的 LLM
# MemoryService：用户偏好记忆服务，用于读取和存储用户的历史偏好
from app.services.memory_service import MemoryService


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
        day1_count = len(final_plan.day_plans[0].attractions) if final_plan.day_plans else 0
        logger.debug(
            f"[Node] finalize_node final_plan 详情: city={final_plan.city}, "
            f"days={len(final_plan.day_plans)}, day1_attractions={day1_count}"
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
