"""
backend/app/models/db_models.py

SQLAlchemy 数据库模型定义模块。

作用：
- 定义所有数据库表结构；
- 与 Pydantic schemas 配合：schemas 负责 API 校验，db_models 负责持久化；
- 所有模型继承自 app.db.base.Base。

对应技术：
- SQLAlchemy ORM：Column、relationship、ForeignKey、JSON 等
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    func
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class PlanRevision(Base):
    """
    行程版本表。

    存储同一 plan_id 下的多个行程版本，形成版本链。
    初始行程为 v1，每次用户反馈修改后生成新的 revision。
    """
    __tablename__ = "plan_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="版本 ID")
    plan_id = Column(String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="根计划 ID")
    version = Column(Integer, nullable=False, default=1, comment="版本号，从 1 开始递增")
    parent_revision_id = Column(Integer, ForeignKey("plan_revisions.id"), nullable=True, index=True, comment="父版本 ID")
    trip_plan_json = Column(JSON, nullable=False, comment="该版本完整行程 JSON")
    is_current = Column(Boolean, default=False, comment="是否为当前生效版本")
    source = Column(String(32), default="initial", comment="来源：initial/patch/full")
    diff_summary = Column(JSON, nullable=True, comment="本次修订的差异摘要（新增/删除/替换），由 finalize_node 计算")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    plan = relationship("TripPlanDB", back_populates="revisions")
    parent = relationship("PlanRevision", remote_side=[id], backref="children")
    feedbacks = relationship(
        "PlanFeedback",
        foreign_keys="[PlanFeedback.revision_id]",
        back_populates="revision",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class PlanFeedback(Base):
    """
    行程反馈表。

    记录用户对某版本的反馈内容、结构化提取结果以及生成的修订版本。
    支持撤回（is_withdrawn）和编辑（通过新建记录并标记旧记录为 edited）。
    """
    __tablename__ = "plan_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="反馈 ID")
    plan_id = Column(String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="根计划 ID")
    revision_id = Column(Integer, ForeignKey("plan_revisions.id"), nullable=False, index=True, comment="基于哪个版本提的反馈")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    day_index = Column(Integer, nullable=True, comment="针对第几天，null 表示全局")
    raw_text = Column(Text, nullable=False, comment="用户原始反馈文本")
    tags = Column(JSON, default=list, comment="快捷标签列表")
    structured_feedback = Column(JSON, default=dict, comment="FeedbackExtractor 提取的结构化约束")
    revision_type = Column(String(32), nullable=True, comment="实际采用的修订策略：patch/full")
    accepted_revision_id = Column(Integer, ForeignKey("plan_revisions.id"), nullable=True, index=True, comment="生成的修订版本 ID")
    is_withdrawn = Column(Boolean, default=False, comment="是否已撤回")
    edited_by_feedback_id = Column(Integer, ForeignKey("plan_feedback.id"), nullable=True, index=True, comment="被哪个新反馈替代（编辑时）")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    revision = relationship("PlanRevision", foreign_keys=[revision_id], back_populates="feedbacks")
    accepted_revision = relationship("PlanRevision", foreign_keys=[accepted_revision_id])
    user = relationship("User", back_populates="feedbacks")


class UserMemory(Base):
    """
    用户 episodic 记忆表。

    记录用户对具体实体（景点、餐厅、酒店等）的好恶或特定场景经验。
    文本会同步写入 Qdrant 向量库，用于后续相似场景回忆。
    """
    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记忆 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    memory_type = Column(String(32), nullable=False, comment="记忆类型：attraction_like/restaurant_dislike/...")
    entity_name = Column(String(128), nullable=True, comment="实体名称，如景点/餐厅名")
    city = Column(String(64), nullable=True, comment="所属城市")
    sentiment = Column(String(16), nullable=False, comment="情感：positive/negative/neutral")
    reason = Column(Text, nullable=True, comment="原因摘要")
    context = Column(Text, nullable=True, comment="原始上下文摘要")
    embedding_id = Column(String(64), nullable=True, index=True, comment="Qdrant point id")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", back_populates="memories")


class User(Base):
    """
    用户表。

    存储注册用户的基本信息和登录凭证。
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="用户 ID")
    username = Column(String(50), unique=True, index=True, nullable=False, comment="用户名")
    email = Column(String(100), unique=True, index=True, nullable=False, comment="邮箱")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    created_at = Column(DateTime, default=func.now(), comment="注册时间")

    # 关系：一个用户有多个行程计划
    trip_plans = relationship("TripPlanDB", back_populates="user", cascade="all, delete-orphan")
    # 关系：一个用户有一份偏好设置
    preference = relationship("UserPreferenceDB", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # 关系：一个用户有多个订单
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    # 关系：一个用户有多条行程反馈
    feedbacks = relationship("PlanFeedback", back_populates="user", cascade="all, delete-orphan")
    # 关系：一个用户有多条 episodic 记忆
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")


class TripPlanDB(Base):
    """
    行程计划表。

    存储用户生成的旅行计划，plan_data 字段以 JSON 形式保存完整 TripPlan。
    """
    __tablename__ = "trip_plans"

    id = Column(String(64), primary_key=True, index=True, comment="计划 ID（UUID）")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属用户 ID")
    city = Column(String(100), nullable=False, comment="目标城市")
    start_date = Column(String(20), nullable=False, comment="开始日期")
    end_date = Column(String(20), nullable=False, comment="结束日期")
    travel_days = Column(Integer, nullable=False, comment="旅行天数")
    plan_data = Column(JSON, nullable=True, comment="完整行程计划 JSON")
    request_data = Column(JSON, nullable=True, comment="原始请求 JSON，用于后续修订")
    cities_json = Column(JSON, nullable=True, comment="多城市联游 [{city, days}]，null 为单城")
    status = Column(String(20), default="pending", comment="状态：pending/completed/failed")
    share_token = Column(String(64), unique=True, index=True, nullable=True, comment="分享令牌，非空表示开启分享")
    share_expires_at = Column(DateTime, nullable=True, comment="分享过期时间，NULL 表示永久有效")
    share_view_count = Column(Integer, nullable=False, default=0, server_default="0", comment="分享页累计访问次数")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", back_populates="trip_plans")
    # 关系：一个计划有多个版本 revision
    revisions = relationship("PlanRevision", back_populates="plan", cascade="all, delete-orphan", order_by="PlanRevision.version")
    # 关系：一个计划有多条反馈
    plan_feedbacks = relationship("PlanFeedback", foreign_keys="[PlanFeedback.plan_id]", cascade="all, delete-orphan")


class UserPreferenceDB(Base):
    """
    用户偏好表。

    存储用户长期偏好，用于个性化推荐。
    """
    __tablename__ = "user_preferences"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True, comment="用户 ID")
    budget_level = Column(String(20), default="standard", comment="预算等级")
    favorite_tags = Column(JSON, default=list, comment="喜欢的标签")
    disliked_tags = Column(JSON, default=list, comment="不喜欢的标签")
    transportation = Column(JSON, default=list, comment="偏好的交通方式")
    accommodation = Column(JSON, default=list, comment="偏好的住宿类型")
    dietary_restrictions = Column(JSON, default=list, comment="饮食禁忌")
    visited_cities = Column(JSON, default=list, comment="去过的城市")
    preference_data = Column(JSON, default=dict, comment="动态学习到的抽象偏好，JSON 格式")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", back_populates="preference")


class Order(Base):
    """
    订单表。

    存储用户发起的支付/预订订单，当前仅用于沙箱演示。
    """
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True, index=True, comment="订单 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    plan_id = Column(String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID")
    amount = Column(Float, nullable=False, comment="订单金额")
    status = Column(String(20), default="pending", comment="状态：pending/paid/cancelled/refunded")
    payment_method = Column(String(20), nullable=True, comment="支付方式")
    third_party_order_id = Column(String(255), nullable=True, comment="第三方支付订单号")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    paid_at = Column(DateTime, nullable=True, comment="支付时间")

    user = relationship("User", back_populates="orders")


class CrawledDocument(Base):
    """
    爬虫文档表。

    存储爬虫抓取的原始文档内容，用于后续切分和向量化。
    """
    __tablename__ = "crawled_documents"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="文档 ID")
    url = Column(String(512), unique=True, index=True, nullable=True, comment="来源 URL")
    title = Column(String(255), nullable=False, comment="文档标题")
    content = Column(Text, nullable=False, comment="文档正文")
    city = Column(String(100), index=True, nullable=True, comment="所属城市")
    source_type = Column(String(50), default="crawler", comment="来源类型：crawler/manual")
    crawled_at = Column(DateTime, default=func.now(), comment="抓取时间")


class Favorite(Base):
    """
    用户收藏表。

    存储用户收藏的景点、酒店、餐厅等。
    """
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="收藏 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    city = Column(String(100), index=True, nullable=True, comment="收藏对象所属城市，用于按城市聚合推荐")
    item_type = Column(String(50), nullable=False, comment="收藏类型：attraction/hotel/restaurant")
    item_id = Column(String(100), nullable=False, comment="收藏对象 ID")
    item_name = Column(String(255), nullable=False, comment="收藏对象名称")
    item_data = Column(JSON, nullable=True, comment="收藏对象完整数据")
    created_at = Column(DateTime, default=func.now(), comment="收藏时间")


class PlanLogDB(Base):
    """
    Agent 执行日志表。

    存储规划/修订任务中每个 Agent 节点的执行日志（含任务结束标记），
    供 SSE 接口跨进程读取：API 进程与 ARQ Worker 进程通过共享数据库交换日志。
    """
    __tablename__ = "plan_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="日志 ID，按写入顺序递增")
    plan_id = Column(String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="行程计划 ID")
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属用户 ID")
    plan_id = Column(String(64), ForeignKey("trip_plans.id"), nullable=False, index=True, comment="关联行程计划 ID")
    type = Column(String(32), nullable=False, comment="通知类型：weather/...")
    title = Column(String(128), nullable=False, comment="通知标题")
    content = Column(Text, nullable=False, comment="通知内容")
    dedup_key = Column(String(96), unique=True, index=True, nullable=False, comment="去重键，防重复通知")
    is_read = Column(Boolean, default=False, comment="是否已读")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
