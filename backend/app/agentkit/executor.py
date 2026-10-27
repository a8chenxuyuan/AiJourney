"""
backend/app/agentkit/executor.py

agentkit（框架层）：手动批次执行器 + 断点快照钩子。

【模块作用】
LangGraph ainvoke 的替代编排层（批次执行核心），零业务感知：
1. _merge_update：把节点返回的状态更新按 reducer 语义合并到主状态
2. _run_node：执行单个节点，事件（node_start/node_end/log）统一进总线
3. _run_batches：按批次执行节点编排——批内 asyncio.gather 并发、批间顺序执行；
   可选 checkpoint_kind 开启断点快照（M2）：每批次合并完成后保存快照，
   支持 start_batch 续跑（跳过已完成批次）。

【对应技术】
- asyncio.gather：并行批次执行
- agentkit.events：唯一事件总线
- agentkit.checkpoint：plan_checkpoints 表快照读写
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from app.agentkit.checkpoint import clear_checkpoint, save_checkpoint
from app.agentkit.events import NODE_END, NODE_START, publish

# 节点函数类型：接收任意状态字典，返回状态更新字典（框架层不感知业务状态结构）
NodeFunc = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# 批次间暂停钩子类型：每批次合并后调用，返回 True 时提前停止批次执行（M3 HITL）
StopPredicate = Callable[[dict[str, Any]], Awaitable[bool]]


# ==================== 批次执行辅助（并行编排核心） ====================


async def _merge_update(state: dict[str, Any], update: dict[str, Any]) -> None:
    """
    把节点返回的状态更新合并到主状态。

    合并规则与 LangGraph 的 reducer 行为一致：logs / messages 追加，
    artifact_refs 按字典合并，其余字段覆盖。注意该函数内部不含 await，
    合并在事件循环中是原子的。

    Args:
        state: 主状态字典（就地修改）。
        update: 节点返回的更新字典。
    """
    for key, value in update.items():
        if key in ("logs", "messages"):
            state[key] = state.get(key, []) + list(value)
        elif key == "artifact_refs" and isinstance(value, dict):
            state[key] = {**state.get(key, {}), **value}
        else:
            state[key] = value


async def _run_node(
    plan_id: str,
    state: dict[str, Any],
    step_name: str,
    node_func: NodeFunc,
    batch_index: int | None = None,
) -> dict[str, Any]:
    """
    执行单个节点：node_start/node_end 事件进总线（attempt 落库），
    节点产出的日志以 log 事件进总线（SSE 传输订阅方落 plan_logs）。

    并行批次中多个 _run_node 协程会并发执行；事件订阅方各自独立写库，
    互不共享可变状态，可安全并发。

    Args:
        plan_id: 任务 ID。
        state: 主状态（节点只读）。
        step_name: 节点名称。
        node_func: 节点函数。
        batch_index: 所属批次序号（attempt 记录用）。

    Returns:
        Dict[str, Any]: 节点返回的状态更新（由调用方统一合并）。
    """
    logger.info(f"[Manual Graph] 执行节点: {step_name}")
    await publish(plan_id, NODE_START, node=step_name, batch_index=batch_index)
    try:
        update = await node_func(state)
    except Exception as exc:
        await publish(
            plan_id, NODE_END, node=step_name, batch_index=batch_index,
            status="failed", error=str(exc),
        )
        raise
    await publish(plan_id, NODE_END, node=step_name, batch_index=batch_index, status="success")
    for log in update.get("logs") or []:
        await publish(plan_id, "log", **log.model_dump(mode="json"))
    logger.info(f"[Manual Graph] 节点 {step_name} 执行完成")
    return update


async def _run_batches(
    plan_id: str,
    state: dict[str, Any],
    batches: list[list[tuple[str, NodeFunc]]],
    checkpoint_kind: str | None = None,
    start_batch: int = -1,
    stop_predicate: StopPredicate | None = None,
) -> None:
    """
    按批次执行节点编排：批内节点并发执行（asyncio.gather），批间顺序执行。

    编排模型（fan-out / fan-in）：
    - 每个批次是一个 [(节点名, 节点函数)] 列表，批内节点彼此独立、只依赖
      之前批次的产出，且互不写入相同的状态字段，因此并发安全；
    - 单节点批次等价于顺序执行；
    - 所有节点完成后，按批次顺序统一合并更新到主状态（合并在单协程中
      顺序进行，避免并发写竞态）。

    断点快照（M2）：
    - checkpoint_kind 非 None 时，每批次合并完成写入快照（batch_index + state）；
    - start_batch 指定从该批次继续（跳过 ≤ start_batch 的已完成批次），
      state 必须是断点处的快照恢复值；
    - 全部批次执行完毕后清除快照，避免残留旧断点。

    批次间暂停钩子（M3 HITL）：
    - stop_predicate 在每批次合并（及快照保存）后调用，返回 True 时提前
      停止批次执行——当前批次快照已保存、断点保留，等待调用方审批后续跑。

    Args:
        plan_id: 任务 ID。
        state: 主状态字典。
        batches: 批次列表，每个批次为 (节点名, 节点函数) 元组的列表。
        checkpoint_kind: 快照种类标识（如 "planning"）；None 表示不写快照。
        start_batch: 续跑起始批次（跳过之前的批次）；默认 -1 表示从头执行。
        stop_predicate: 批次间暂停钩子；None 表示不暂停。
    """
    for batch_index, batch in enumerate(batches):
        if batch_index <= start_batch:
            # 断点续跑：该批次在快照中已完成，跳过
            logger.info(f"[Manual Graph] 断点续跑跳过已完成批次 {batch_index}")
            continue
        if len(batch) == 1:
            # 单节点批次：顺序执行
            step_name, node_func = batch[0]
            update = await _run_node(
                plan_id, state, step_name, node_func, batch_index=batch_index
            )
            await _merge_update(state, update)
        else:
            # 并行批次：gather 并发执行全部节点，完成后再统一合并
            logger.info(f"[Manual Graph] 并行批次开始: {[name for name, _ in batch]}")
            updates = await asyncio.gather(
                *(
                    _run_node(plan_id, state, name, func, batch_index=batch_index)
                    for name, func in batch
                )
            )
            for update in updates:
                await _merge_update(state, update)
            logger.info(f"[Manual Graph] 并行批次完成: {[name for name, _ in batch]}")

        # 批次完成后保存快照（大字段 messages/logs 不入快照，避免膨胀）
        if checkpoint_kind is not None:
            await save_checkpoint(plan_id, checkpoint_kind, batch_index, state)

        # 批次间暂停钩子：命中时提前返回（快照已保存、断点保留，不执行 clear）
        if stop_predicate is not None and await stop_predicate(state):
            logger.info(f"[Manual Graph] stop_predicate 命中，批次 {batch_index} 后暂停执行")
            return

    if checkpoint_kind is not None and start_batch < len(batches) - 1:
        # 全部批次执行完（非纯跳过场景）清除快照，防旧断点被误续跑
        await clear_checkpoint(plan_id, checkpoint_kind)
