"""
backend/app/agents/streaming.py

Agent 执行日志持久化模块。

作用：
- Agent 节点执行日志统一写入 plan_logs 表（含任务结束标记）；
- API 进程与 ARQ Worker 进程通过共享数据库交换日志，
  SSE 接口按日志 ID 增量读取并推送给前端；
- 替代旧的进程内 asyncio.Queue 方案（配合消息队列解耦改造：
  任务执行已迁移到独立 Worker 进程，进程内队列不再跨进程可见）。

对应技术：
- SQLAlchemy：异步会话写入与查询
"""

from typing import Any, Dict, List

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.db_models import PlanLogDB


async def put_log(plan_id: str, log: Dict[str, Any]) -> None:
    """
    将一条 Agent 执行日志写入 plan_logs 表。

    Args:
        plan_id: 行程计划 ID。
        log: 日志字典（AgentLog 结构或 done 结束标记）。
    """
    async with AsyncSessionLocal() as session:
        session.add(PlanLogDB(plan_id=plan_id, log_json=log))
        await session.commit()


async def get_history(plan_id: str) -> List[Dict[str, Any]]:
    """
    按写入顺序读取指定 plan_id 的全部日志（含结束标记）。

    Args:
        plan_id: 行程计划 ID。

    Returns:
        List[Dict[str, Any]]: 日志字典列表，顺序与写入顺序一致。
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PlanLogDB).where(PlanLogDB.plan_id == plan_id).order_by(PlanLogDB.id)
        )
        return [row.log_json for row in result.scalars().all()]


async def get_logs_after(plan_id: str, last_log_id: int) -> List[Any]:
    """
    增量读取指定 plan_id 中 ID 大于 last_log_id 的日志行（SSE 轮询用）。

    Args:
        plan_id: 行程计划 ID。
        last_log_id: 已读取的最大日志 ID，首次传 0。

    Returns:
        List[PlanLogDB]: 按写入顺序排列的日志 ORM 对象。
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PlanLogDB)
            .where(PlanLogDB.plan_id == plan_id, PlanLogDB.id > last_log_id)
            .order_by(PlanLogDB.id)
        )
        return list(result.scalars().all())


async def mark_done(plan_id: str, status: str = "completed") -> None:
    """
    写入任务结束标记日志，SSE 接口据此发送最终事件并断开。

    Args:
        plan_id: 行程计划 ID。
        status: 完成状态，completed 或 failed。
    """
    done_log = {"status": status, "done": True, "agent_name": "System", "step": "done"}
    await put_log(plan_id, done_log)
