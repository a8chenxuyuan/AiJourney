"""
backend/app/agentkit/events.py

agentkit（框架层）：唯一事件总线。

作用：
- 所有执行期事件（node_start / node_end / log / token_delta / state /
  approval_required / done / failed）统一经 publish() 发布，禁止任何模块
  绕过总线自行推送；
- SSE 推送（plan_logs 表传输）、node_attempt 执行记录落库均为同一事件流的
  订阅方，后续新订阅方（trace 日志等）只增不改。

跨进程现实：
- API 进程与 ARQ Worker 进程不共享内存，持久传输订阅方把事件写入 plan_logs
  表，SSE 接口按日志 ID 增量读取——对外行为与拆分前完全一致。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy import func, select

from app.core.db.session import AsyncSessionLocal
from app.core.sse import put_log
from app.models.db_agent import NodeAttemptDB

# ==================== 事件类型常量 ====================
NODE_START = "node_start"
NODE_END = "node_end"
LOG = "log"
TOKEN_DELTA = "token_delta"
STATE = "state"
APPROVAL_REQUIRED = "approval_required"
DONE = "done"
FAILED = "failed"


@dataclass
class Event:
    """事件对象：plan_id 定位任务，type 区分种类，payload 携带内容。"""

    plan_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[Event], Awaitable[None]]
_subscribers: list[Subscriber] = []


def subscribe(fn: Subscriber) -> Subscriber:
    """注册事件订阅方；传输、落库、trace 等订阅方一律从这里接入。"""
    _subscribers.append(fn)
    return fn


async def publish(plan_id: str, event_type: str, **payload: Any) -> None:
    """向总线发布事件，依次通知所有订阅方。

    单个订阅方失败只告警，不影响其他订阅方与规划主流程。
    """
    event = Event(plan_id=plan_id, type=event_type, payload=payload)
    for fn in list(_subscribers):
        try:
            await fn(event)
        except Exception as exc:
            logger.warning(
                f"[events] 订阅方 {getattr(fn, '__name__', fn)} 处理 {event_type} 失败: {exc}"
            )


# ==================== 内置订阅方 1：SSE 持久传输 ====================
# 只持久化 log / done / failed 三类事件——plan_logs 行流与拆分前完全一致，
# node_start / node_end 等执行细节不进 SSE 流，避免破坏前端解析。

_PERSIST_TYPES = (LOG, DONE, FAILED)


async def _persist_to_plan_logs(event: Event) -> None:
    """传输订阅方：把事件写入 plan_logs 表，SSE 接口按 ID 增量读取。"""
    if event.type not in _PERSIST_TYPES:
        return
    if event.type == LOG:
        await put_log(event.plan_id, event.payload)
        return
    # done / failed 结束标记行结构与拆分前 mark_done 完全一致
    status = event.payload.get("status", "completed")
    done_log = {"status": status, "done": True, "agent_name": "System", "step": "done"}
    await put_log(event.plan_id, done_log)


# ==================== 内置订阅方 2：节点执行记录落库 ====================


async def _record_node_attempt(event: Event) -> None:
    """attempt 落库订阅方：node_start 建行（running），node_end 置终态。"""
    if event.type not in (NODE_START, NODE_END):
        return
    node = str(event.payload.get("node", ""))
    batch_index = event.payload.get("batch_index")
    async with AsyncSessionLocal() as session:
        if event.type == NODE_START:
            session.add(
                NodeAttemptDB(
                    plan_id=event.plan_id,
                    node_name=node,
                    batch_index=batch_index,
                    status="running",
                    started_at=func.now(),
                )
            )
        else:
            # 终态回填：定位该任务同节点最近一条 running 记录
            status = str(event.payload.get("status", "success"))
            result = await session.execute(
                select(NodeAttemptDB)
                .where(
                    NodeAttemptDB.plan_id == event.plan_id,
                    NodeAttemptDB.node_name == node,
                    NodeAttemptDB.status == "running",
                )
                .order_by(NodeAttemptDB.id.desc())
                .limit(1)
            )
            attempt = result.scalar_one_or_none()
            if attempt is not None:
                attempt.status = status
                attempt.finished_at = func.now()
                if event.payload.get("error"):
                    attempt.error = str(event.payload["error"])
        await session.commit()


subscribe(_persist_to_plan_logs)
subscribe(_record_node_attempt)
