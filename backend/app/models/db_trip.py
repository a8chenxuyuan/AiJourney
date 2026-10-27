"""
backend/app/models/db_trip.py

行程域数据库模型。

作用：
- 定义行程计划、版本/反馈、执行日志、通知、协作/邀请、打卡、游记相关的表结构；
- 原 db_models.py 按域拆分而来，所有模型继承自 app.db.base.Base。
"""

from datetime import datetime, timedelta

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class TripPlanDB(Base):
    """
    行程计划表。

    存储用户生成的旅行计划，plan_data 字段以 JSON 形式保存完整 TripPlan。
    """

    __tablename__ = "trip_plans"

    id = Column(String(64), primary_key=True, index=True, comment="计划 ID（UUID）")
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属用户 ID"
    )
    city = Column(String(100), nullable=False, comment="目标城市")
    start_date = Column(String(20), nullable=False, comment="开始日期")
    end_date = Column(String(20), nullable=False, comment="结束日期")
    travel_days = Column(Integer, nullable=False, comment="旅行天数")
    plan_data = Column(JSON, nullable=True, comment="完整行程计划 JSON")
    request_data = Column(JSON, nullable=True, comment="原始请求 JSON，用于后续修订")
    cities_json = Column(JSON, nullable=True, comment="多城市联游 [{city, days}]，null 为单城")
    status = Column(String(20), default="pending", comment="状态：pending/completed/failed")
    share_token = Column(
        String(64), unique=True, index=True, nullable=True, comment="分享令牌，非空表示开启分享"
    )
    share_expires_at = Column(DateTime, nullable=True, comment="分享过期时间，NULL 表示永久有效")
    share_view_count = Column(
        Integer, nullable=False, default=0, server_default="0", comment="分享页累计访问次数"
    )
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", back_populates="trip_plans")
    # 关系：一个计划有多个版本 revision
    revisions = relationship(
        "PlanRevision",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanRevision.version",
    )
    # 关系：一个计划有多条反馈
    plan_feedbacks = relationship(
        "PlanFeedback", foreign_keys="[PlanFeedback.plan_id]", cascade="all, delete-orphan"
    )


class PlanRevision(Base):
    """
    行程版本表。

    存储同一 plan_id 下的多个行程版本，形成版本链。
    初始行程为 v1，每次用户反馈修改后生成新的 revision。
    """

    __tablename__ = "plan_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="版本 ID")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="根计划 ID"
    )
    version = Column(Integer, nullable=False, default=1, comment="版本号，从 1 开始递增")
    parent_revision_id = Column(
        Integer, ForeignKey("plan_revisions.id"), nullable=True, index=True, comment="父版本 ID"
    )
    trip_plan_json = Column(JSON, nullable=False, comment="该版本完整行程 JSON")
    is_current = Column(Boolean, default=False, comment="是否为当前生效版本")
    source = Column(String(32), default="initial", comment="来源：initial/patch/full")
    diff_summary = Column(
        JSON, nullable=True, comment="本次修订的差异摘要（新增/删除/替换），由 finalize_node 计算"
    )
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    plan = relationship("TripPlanDB", back_populates="revisions")
    parent = relationship("PlanRevision", remote_side=[id], backref="children")
    feedbacks = relationship(
        "PlanFeedback",
        foreign_keys="[PlanFeedback.revision_id]",
        back_populates="revision",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PlanFeedback(Base):
    """
    行程反馈表。

    记录用户对某版本的反馈内容、结构化提取结果以及生成的修订版本。
    支持撤回（is_withdrawn）和编辑（通过新建记录并标记旧记录为 edited）。
    """

    __tablename__ = "plan_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="反馈 ID")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="根计划 ID"
    )
    revision_id = Column(
        Integer,
        ForeignKey("plan_revisions.id"),
        nullable=False,
        index=True,
        comment="基于哪个版本提的反馈",
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    day_index = Column(Integer, nullable=True, comment="针对第几天，null 表示全局")
    raw_text = Column(Text, nullable=False, comment="用户原始反馈文本")
    tags = Column(JSON, default=list, comment="快捷标签列表")
    structured_feedback = Column(JSON, default=dict, comment="FeedbackExtractor 提取的结构化约束")
    revision_type = Column(String(32), nullable=True, comment="实际采用的修订策略：patch/full")
    accepted_revision_id = Column(
        Integer,
        ForeignKey("plan_revisions.id"),
        nullable=True,
        index=True,
        comment="生成的修订版本 ID",
    )
    is_withdrawn = Column(Boolean, default=False, comment="是否已撤回")
    edited_by_feedback_id = Column(
        Integer,
        ForeignKey("plan_feedback.id"),
        nullable=True,
        index=True,
        comment="被哪个新反馈替代（编辑时）",
    )
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    revision = relationship("PlanRevision", foreign_keys=[revision_id], back_populates="feedbacks")
    accepted_revision = relationship("PlanRevision", foreign_keys=[accepted_revision_id])
    user = relationship("User", back_populates="feedbacks")


class PlanLogDB(Base):
    """
    Agent 执行日志表。

    存储规划/修订任务中每个 Agent 节点的执行日志（含任务结束标记），
    供 SSE 接口跨进程读取：API 进程与 ARQ Worker 进程通过共享数据库交换日志。
    """

    __tablename__ = "plan_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="日志 ID，按写入顺序递增")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID"
    )
    log_json = Column(JSON, nullable=False, comment="日志内容（AgentLog 结构或 done 结束标记）")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")


class PlanNotification(Base):
    """
    站内通知表。

    存储系统主动发给用户的通知（如出发前天气提醒）。
    dedup_key 唯一约束保证同一事件（同一行程同一出发日期的天气提醒）不重复通知。
    由 init_db 的 create_all 自动建表，无需登记 _IDEMPOTENT_COLUMNS。
    """

    __tablename__ = "plan_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="通知 ID")
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属用户 ID"
    )
    plan_id = Column(
        String(64),
        ForeignKey("trip_plans.id"),
        nullable=False,
        index=True,
        comment="关联行程计划 ID",
    )
    type = Column(String(32), nullable=False, comment="通知类型：weather/...")
    title = Column(String(128), nullable=False, comment="通知标题")
    content = Column(Text, nullable=False, comment="通知内容")
    dedup_key = Column(
        String(96), unique=True, index=True, nullable=False, comment="去重键，防重复通知"
    )
    is_read = Column(Boolean, default=False, comment="是否已读")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")


class PlanCollaborator(Base):
    """
    行程协作者表。

    存储被邀请参与某个行程协作的用户（可查看行程、提交反馈修订），
    行程的删除/分享管理/邀请管理仍仅限所有者。
    plan_id + user_id 唯一约束保证同一用户不会重复加入同一行程。
    与 PlanNotification 一样为新增表，由 init_db 的 create_all 自动建表（含索引与唯一约束），
    无需登记 _IDEMPOTENT_COLUMNS。
    """

    __tablename__ = "plan_collaborators"
    # 联合唯一：防止同一用户通过重复使用邀请链接被重复加入
    __table_args__ = (
        UniqueConstraint("plan_id", "user_id", name="uq_plan_collaborator_plan_user"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="协作记录 ID")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID"
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="协作者用户 ID"
    )
    role = Column(
        String(32), nullable=False, default="editor", comment="协作角色：editor（查看+提交反馈）"
    )
    created_at = Column(DateTime, default=func.now(), comment="加入时间")


class PlanInvite(Base):
    """
    行程邀请令牌表。

    所有者为行程生成的邀请令牌：登录用户凭 token 加入成为协作者。
    支持撤销（revoked）与过期（expires_at，默认生成后 7 天），use_count 记录实际加入人次。
    与 PlanNotification 一样为新增表，由 init_db 的 create_all 自动建表（含索引与唯一约束），
    无需登记 _IDEMPOTENT_COLUMNS。
    """

    __tablename__ = "plan_invites"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="邀请记录 ID")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID"
    )
    token = Column(
        String(64), unique=True, index=True, nullable=False, comment="邀请令牌（加入凭证）"
    )
    created_by = Column(
        Integer, ForeignKey("users.id"), nullable=False, comment="生成邀请的所有者用户 ID"
    )
    expires_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now() + timedelta(days=7),
        comment="过期时间，默认生成后 7 天",
    )
    use_count = Column(
        Integer, nullable=False, default=0, server_default="0", comment="通过该链接成功加入的人次"
    )
    revoked = Column(Boolean, nullable=False, default=False, comment="是否已被所有者撤销")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")


class TripCheckin(Base):
    """
    行程打卡表。

    记录用户在行程执行期间的地点打卡（含坐标、照片、感想），
    是足迹地图与游记生成的数据源。
    与 PlanNotification 等新增表一样由 init_db 的 create_all 自动建表。
    """

    __tablename__ = "trip_checkins"

    id = Column(String(64), primary_key=True, index=True, comment="打卡 ID（CK_{uuid}）")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID"
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="打卡人 ID"
    )
    day_index = Column(Integer, nullable=False, comment="行程第几天，从 1 开始")
    spot_type = Column(
        String(32), nullable=False, comment="地点类型：attraction/meal/hotel"
    )
    spot_name = Column(String(255), nullable=False, comment="地点名称")
    longitude = Column(Float, nullable=False, default=0.0, comment="经度（高德坐标）")
    latitude = Column(Float, nullable=False, default=0.0, comment="纬度（高德坐标）")
    checkin_at = Column(DateTime, default=func.now(), comment="打卡时间")
    photo_urls = Column(JSON, default=list, comment="照片 URL 列表")
    note = Column(String(500), nullable=True, comment="一句话感想")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")


class TripJournal(Base):
    """
    行程游记表。

    行程结束后由 LLM 基于"行程 JSON + 打卡记录"生成的分节图文游记。
    plan_id 唯一约束保证一个行程只生成一篇游记（防重复提交生成任务）。
    status 流转：generating → done / failed。
    is_public 默认 False，第二阶段内容中心回流时开启。
    """

    __tablename__ = "trip_journals"
    __table_args__ = (UniqueConstraint("plan_id", name="uq_trip_journal_plan"),)

    id = Column(String(64), primary_key=True, index=True, comment="游记 ID（JN_{uuid}）")
    plan_id = Column(
        String(64), ForeignKey("trip_plans.id"), nullable=False, comment="行程计划 ID（唯一）"
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="作者 ID")
    title = Column(String(255), nullable=False, default="", comment="游记标题")
    content = Column(JSON, nullable=True, comment="分节图文结构 [{day_index,title,text,photos}]")
    status = Column(
        String(20), nullable=False, default="generating", comment="状态：generating/done/failed"
    )
    is_public = Column(Boolean, nullable=False, default=False, comment="是否公开（第二阶段回流用）")
    public_token = Column(
        String(64), unique=True, index=True, nullable=True, comment="公开访问令牌"
    )
    generated_at = Column(DateTime, nullable=True, comment="生成完成时间")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")


__all__ = [
    "PlanCollaborator",
    "PlanFeedback",
    "PlanInvite",
    "PlanLogDB",
    "PlanNotification",
    "PlanRevision",
    "TripCheckin",
    "TripJournal",
    "TripPlanDB",
]
