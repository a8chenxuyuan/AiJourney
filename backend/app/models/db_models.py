"""
backend/app/models/db_models.py

SQLAlchemy 数据库模型定义模块（兼容垫片）。

作用：
- 按业务域拆分后的 re-export 入口：真实定义见 db_user / db_trip / db_community / db_order / db_misc；
- 保持既有 import 路径不变，如 `from app.models.db_models import TripPlanDB`；
- 所有 ORM 类只在各自域文件中定义一次，本文件仅做转发。
"""

from app.models.db_agent import NodeAttemptDB, PlanCheckpointDB
from app.models.db_community import (
    ChatMessage,
    CommunityPost,
    Friendship,
    Notification,
    PostComment,
    PostLike,
)
from app.models.db_misc import CrawledDocument
from app.models.db_order import Order
from app.models.db_trip import (
    PlanCollaborator,
    PlanFeedback,
    PlanInvite,
    PlanLogDB,
    PlanNotification,
    PlanRevision,
    TripCheckin,
    TripJournal,
    TripPlanDB,
)
from app.models.db_user import Favorite, User, UserFactDB, UserMemory, UserPreferenceDB

__all__ = [
    "ChatMessage",
    "CommunityPost",
    "CrawledDocument",
    "Favorite",
    "Friendship",
    "Notification",
    "NodeAttemptDB",
    "PlanCheckpointDB",
    "Order",
    "PlanCollaborator",
    "PlanFeedback",
    "PlanInvite",
    "PlanLogDB",
    "PlanNotification",
    "PlanRevision",
    "PostComment",
    "PostLike",
    "TripCheckin",
    "TripJournal",
    "TripPlanDB",
    "User",
    "UserFactDB",
    "UserMemory",
    "UserPreferenceDB",
]
