"""
backend/app/models/db_user.py

用户域数据库模型。

作用：
- 定义用户账号、偏好、记忆、收藏相关的表结构；
- 原 db_models.py 按域拆分而来，所有模型继承自 app.db.base.Base。
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.core.db.base import Base


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
    role = Column(String(20), nullable=False, default="user", comment="账号角色：user/admin")
    is_banned = Column(Boolean, nullable=False, default=False, index=True, comment="是否被封禁")
    created_at = Column(DateTime, default=func.now(), comment="注册时间")

    # 关系：一个用户有多个行程计划
    trip_plans = relationship("TripPlanDB", back_populates="user", cascade="all, delete-orphan")
    # 关系：一个用户有一份偏好设置
    preference = relationship(
        "UserPreferenceDB", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    # 关系：一个用户有多个订单
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    # 关系：一个用户有多条行程反馈
    feedbacks = relationship("PlanFeedback", back_populates="user", cascade="all, delete-orphan")
    # 关系：一个用户有多条 episodic 记忆
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")


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


class UserMemory(Base):
    """
    用户 episodic 记忆表。

    记录用户对具体实体（景点、餐厅、酒店等）的好恶或特定场景经验。
    文本会同步写入 Qdrant 向量库，用于后续相似场景回忆。
    """

    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="记忆 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    memory_type = Column(
        String(32), nullable=False, comment="记忆类型：attraction_like/restaurant_dislike/..."
    )
    entity_name = Column(String(128), nullable=True, comment="实体名称，如景点/餐厅名")
    city = Column(String(64), nullable=True, comment="所属城市")
    sentiment = Column(String(16), nullable=False, comment="情感：positive/negative/neutral")
    reason = Column(Text, nullable=True, comment="原因摘要")
    context = Column(Text, nullable=True, comment="原始上下文摘要")
    embedding_id = Column(String(64), nullable=True, index=True, comment="Qdrant point id")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", back_populates="memories")


class UserFactDB(Base):
    """
    用户规划事实表。

    跨会话记忆的"流水账"：finalize 成功后提取规划事实（去过城市、预算档位、
    行程节奏等）写入，由 agentkit/memory.py 的 MemoryLayer 读出注入后续规划。
    与 user_memories（LLM 提取的实体好恶记忆）语义不同，故独立建表。
    """

    __tablename__ = "user_facts"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="事实 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    kind = Column(
        String(32), nullable=False, comment="事实类型：visited_city/budget_level/travel_pattern"
    )
    content = Column(Text, nullable=False, comment="事实内容")
    source_plan_id = Column(String(64), nullable=True, comment="来源行程 ID")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")


class Favorite(Base):
    """
    用户收藏表。

    存储用户收藏的景点、酒店、餐厅等。
    """

    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="收藏 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="用户 ID")
    city = Column(
        String(100), index=True, nullable=True, comment="收藏对象所属城市，用于按城市聚合推荐"
    )
    item_type = Column(String(50), nullable=False, comment="收藏类型：attraction/hotel/restaurant")
    item_id = Column(String(100), nullable=False, comment="收藏对象 ID")
    item_name = Column(String(255), nullable=False, comment="收藏对象名称")
    item_data = Column(JSON, nullable=True, comment="收藏对象完整数据")
    created_at = Column(DateTime, default=func.now(), comment="收藏时间")


__all__ = [
    "Favorite",
    "User",
    "UserMemory",
    "UserPreferenceDB",
]
