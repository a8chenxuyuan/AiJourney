"""
backend/app/agentkit/checkpoint.py

agentkit（框架层）：断点快照服务（M2）。

作用：
- 每批次执行完成后把状态快照写入 plan_checkpoints 表
  （batch_index + state JSON，剔除 messages/logs 大字段）；
- worker 崩溃后重启，可按快照从 batch_index+1 续跑，已完成批次不重跑；
- state 中的 Pydantic 对象用通用 "__pydantic__" 包装编码/解码，
  框架层不感知业务模型类型。

对应技术：
- SQLAlchemy：异步 upsert / 查询 / 删除 plan_checkpoints 表
"""

import importlib
import json
from typing import Any

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from app.core.db.session import AsyncSessionLocal
from app.models.db_agent import PlanCheckpointDB

# 快照中剔除的大字段：消息上下文与执行日志体积大且续跑不需要
_EXCLUDED_KEYS = ("messages", "logs")


def _encode_default(obj: Any) -> Any:
    """JSON 编码兜底：Pydantic 模型包装为可还原的类型标记；其余转字符串。"""
    if isinstance(obj, BaseModel):
        cls = type(obj)
        return {
            "__pydantic__": f"{cls.__module__}.{cls.__name__}",
            "data": obj.model_dump(mode="json"),
        }
    return str(obj)


def encode_state(state: dict[str, Any]) -> dict[str, Any]:
    """状态 → 可 JSON 化的快照字典（剔除大字段，Pydantic 对象类型化包装）。"""
    slim = {k: v for k, v in state.items() if k not in _EXCLUDED_KEYS}
    return json.loads(json.dumps(slim, default=_encode_default, ensure_ascii=False))


def decode_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    """快照字典 → 运行时状态（递归还原 "__pydantic__" 包装的模型对象）。"""

    def _decode(obj: Any) -> Any:
        if isinstance(obj, dict):
            if set(obj.keys()) == {"__pydantic__", "data"}:
                module_path, _, cls_name = str(obj["__pydantic__"]).rpartition(".")
                cls = getattr(importlib.import_module(module_path), cls_name)
                return cls.model_validate(obj["data"])
            return {k: _decode(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_decode(v) for v in obj]
        return obj

    return _decode(snapshot)


async def save_checkpoint(plan_id: str, kind: str, batch_index: int, state: dict[str, Any]) -> None:
    """按 (plan_id, kind) upsert 快照；失败只告警，不阻断主流程。"""
    try:
        snapshot = encode_state(state)
        async with AsyncSessionLocal() as session:
            row = await session.get(PlanCheckpointDB, {"plan_id": plan_id, "kind": kind})
            if row is None:
                row = PlanCheckpointDB(plan_id=plan_id, kind=kind)
                session.add(row)
            row.batch_index = batch_index
            row.state_snapshot = snapshot
            await session.commit()
    except Exception as exc:
        logger.warning(f"[checkpoint] 保存快照失败 plan={plan_id} kind={kind}: {exc}")


async def load_checkpoint(plan_id: str, kind: str) -> dict[str, Any] | None:
    """读取快照；返回 {"batch_index": int, "state": dict}，无快照返回 None。"""
    async with AsyncSessionLocal() as session:
        row = await session.get(PlanCheckpointDB, {"plan_id": plan_id, "kind": kind})
        if row is None:
            return None
        return {"batch_index": row.batch_index, "state": row.state_snapshot}


async def clear_checkpoint(plan_id: str, kind: str) -> None:
    """清除快照（任务正常完成或终态失败后调用，防旧断点被误续跑）。"""
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(PlanCheckpointDB, {"plan_id": plan_id, "kind": kind})
            if row is not None:
                await session.delete(row)
                await session.commit()
    except Exception as exc:
        logger.warning(f"[checkpoint] 清除快照失败 plan={plan_id} kind={kind}: {exc}")


async def list_resumable_plans() -> list[dict[str, Any]]:
    """列出可续跑任务：planning 快照存在且行程状态仍为 running（worker 异常中断特征）。"""
    from app.models.db_models import TripPlanDB

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PlanCheckpointDB, TripPlanDB.user_id)
            .join(TripPlanDB, PlanCheckpointDB.plan_id == TripPlanDB.id)
            .where(PlanCheckpointDB.kind == "planning", TripPlanDB.status == "running")
        )
        return [
            {
                "plan_id": checkpoint.plan_id,
                "batch_index": checkpoint.batch_index,
                "state_snapshot": checkpoint.state_snapshot,
                "user_id": user_id,
            }
            for checkpoint, user_id in result.all()
        ]
