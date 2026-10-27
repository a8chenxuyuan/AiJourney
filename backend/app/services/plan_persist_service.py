"""
backend/app/services/plan_persist_service.py

【模块作用】
行程计划（TripPlan）状态持久化服务：编排层落库动作下沉到服务层。

规划 / 修订 / 重算工作流成功后需要把数据库里的行程状态同步为 completed
（否则前端轮询一直看到 revising），执行失败时需要把状态改为 failed 并记录
错误信息——这类直接读写 TripPlan 表的逻辑统一收敛在本模块，agents 编排层
改为调用本服务（agents → services 方向合法），避免编排层直连数据库会话越界写库。

【对应技术】
- SQLAlchemy：异步 ORM（AsyncSessionLocal 会话工厂、session.get 主键查询、commit 提交）
"""


from sqlalchemy import update

from app.core.db.session import AsyncSessionLocal
from app.models.db_models import TripPlanDB


async def claim_plan_for_run(plan_id: str, include_running: bool = False) -> bool:
    """
    【函数作用】claim CAS 抢占行程执行权（M2 防多 worker 重复消费）。

    原子执行 UPDATE trip_plans SET status='running' WHERE id=:id AND
    status IN ('pending','pending_approval'[, 'running'])：
    - 更新 0 行 = 已被其他 worker 领取或状态不符，调用方应直接退出；
    - include_running=True 供断点续跑场景重新抢占（中断任务的行程仍是 running）。

    【参数】
    - plan_id：行程计划 ID
    - include_running：是否允许抢占 running 状态（续跑场景）

    【返回值】
    - bool：True=抢占成功（本次执行方负责跑）；False=抢占失败
    """
    statuses = ["pending", "pending_approval"] + (["running"] if include_running else [])
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(TripPlanDB)
            .where(TripPlanDB.id == plan_id, TripPlanDB.status.in_(statuses))
            .values(status="running")
        )
        await session.commit()
        return (result.rowcount or 0) > 0


async def mark_plan_completed(plan_id: str) -> None:
    """
    【函数作用】把行程记录状态置为 completed（记录不存在时静默跳过）。

    用于 run_revision_graph / run_recalculate_graph 成功收尾：
    finalize 节点已写入 plan_data，这里只把 status 改回 completed，
    否则前端通过 GET /api/trip/{id} 轮询会一直看到 revising。

    【参数】
    - plan_id：行程计划 ID
    """
    async with AsyncSessionLocal() as session:
        # 根据 plan_id 查询数据库记录
        db_plan = await session.get(TripPlanDB, plan_id)
        if db_plan:
            db_plan.status = "completed"
            await session.commit()


async def mark_plan_pending_approval(plan_id: str, detail: dict) -> None:
    """
    【函数作用】把行程标记为 pending_approval（M3 HITL 暂停态）。

    超支明细写入 plan_data.approval，前端通过 GET /api/trip/{id} 轮询
    读取并弹出审批确认卡；审批通过续跑完成后 finalize 会覆盖 plan_data
    为最终行程，明细无需单独清理。

    【参数】
    - plan_id：行程计划 ID
    - detail：审批明细（check_budget_overrun 的返回值）
    """
    async with AsyncSessionLocal() as session:
        db_plan = await session.get(TripPlanDB, plan_id)
        if db_plan:
            db_plan.status = "pending_approval"
            db_plan.plan_data = {"approval": detail}
            await session.commit()


async def mark_plan_failed(plan_id: str, error: object) -> None:
    """
    【函数作用】把行程记录标记为失败并写入错误信息（记录不存在时静默跳过）。

    用于规划 / 修订 / 重算执行异常时：只更新数据库 status 与错误信息，
    让前端通过轮询获取真实状态（修订/重算路径不推 SSE 失败标记，见 graph.py 说明）。

    【参数】
    - plan_id：行程计划 ID
    - error：失败原因（任意对象，内部 str() 后存入 plan_data.error）
    """
    async with AsyncSessionLocal() as session:
        # 根据 plan_id 查询数据库记录
        db_plan = await session.get(TripPlanDB, plan_id)
        if db_plan:
            db_plan.status = "failed"
            db_plan.plan_data = {"error": str(error)}
            await session.commit()
