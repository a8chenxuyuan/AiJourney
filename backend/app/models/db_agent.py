"""
backend/app/models/db_agent.py

Agent 执行记录域模型。

- node_attempts：节点执行记录（事件总线订阅方落库），用于执行回溯与断点续跑排查。
"""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)

from app.core.db.base import Base


class NodeAttemptDB(Base):
    """
    节点执行记录表。

    每个节点开始执行时插入一行 running 记录，结束时回填终态（success / failed），
    由 agentkit/events.py 的订阅方写入。
    """

    __tablename__ = "node_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记录 ID")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID"
    )
    node_name = Column(String(64), nullable=False, comment="节点名称")
    batch_index = Column(Integer, nullable=True, comment="所属批次序号（从 0 开始）")
    status = Column(String(16), nullable=False, comment="执行状态：running / success / failed")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    error = Column(Text, nullable=True, comment="失败原因")


class PlanCheckpointDB(Base):
    """
    断点快照表。

    每批次执行完成后由 agentkit/executor.py 写入（batch_index + 状态快照 JSON），
    worker 异常中断后可从 batch_index+1 续跑；kind 区分运行种类，
    避免修订/重算快照覆盖初始规划断点。
    """

    __tablename__ = "plan_checkpoints"

    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), primary_key=True, comment="行程计划 ID"
    )
    kind = Column(String(32), primary_key=True, comment="运行种类：planning / revision / recalculate")
    batch_index = Column(Integer, nullable=False, comment="已完成的最大批次序号")
    state_snapshot = Column(JSON, nullable=False, comment="状态快照（剔除 messages/logs 大字段）")
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), comment="更新时间"
    )
