"""
backend/app/models/schemas.py

Pydantic 数据模型定义模块（兼容垫片）。

作用：
- 按业务域拆分后的 re-export 入口：真实定义见 schema_common / schema_user / schema_trip /
  schema_collab / schema_social / schema_misc；
- 保持既有 import 路径不变，如 `from app.models.schemas import TripPlan`；
- 所有 Pydantic 模型只在各自域文件中定义一次，本文件仅做转发。
"""

from app.models.schema_collab import (
    CollaboratorJoinOut,
    CollaboratorOut,
    InviteOut,
    ShareCreateRequest,
    ShareInfo,
)
from app.models.schema_common import AgentLog, Location, StandardResponse
from app.models.schema_misc import (
    CrawlerTriggerRequest,
    DestinationAskRequest,
    PaymentCreateRequest,
    PaymentResponse,
    RAGSearchRequest,
    RAGSearchResponse,
    RAGUploadRequest,
)
from app.models.schema_social import (
    CheckinCreateRequest,
    CheckinOut,
    CommentCreateRequest,
    CommentOut,
    FeedOut,
    JournalOut,
    JournalSection,
    JournalUpdateRequest,
    PostCreateRequest,
    PostDetailOut,
    PostOut,
)
from app.models.schema_trip import (
    Attraction,
    Budget,
    CityStay,
    DayPlan,
    FeedbackRecord,
    Hotel,
    HumanDecisionRequest,
    IntentAnalysis,
    Meal,
    PlanChatMessage,
    PlanChatRequest,
    PlanFeedbackRequest,
    PlanFeedbackResponse,
    RecalculateRequest,
    ReplicateRequest,
    RevisionSummary,
    StructuredFeedback,
    StructuredFeedbackAction,
    TripPlan,
    TripPlanResponse,
    TripRequest,
    WeatherInfo,
)
from app.models.schema_user import (
    FavoriteCreateRequest,
    FavoriteOut,
    UserCreate,
    UserFeedback,
    UserLogin,
    UserResponse,
)

__all__ = [
    "AgentLog",
    "Attraction",
    "Budget",
    "CheckinCreateRequest",
    "CheckinOut",
    "CityStay",
    "CollaboratorJoinOut",
    "CollaboratorOut",
    "CommentCreateRequest",
    "CommentOut",
    "CrawlerTriggerRequest",
    "DayPlan",
    "DestinationAskRequest",
    "FavoriteCreateRequest",
    "FavoriteOut",
    "FeedOut",
    "FeedbackRecord",
    "Hotel",
    "HumanDecisionRequest",
    "IntentAnalysis",
    "InviteOut",
    "JournalOut",
    "JournalSection",
    "JournalUpdateRequest",
    "Location",
    "Meal",
    "PaymentCreateRequest",
    "PaymentResponse",
    "PlanChatMessage",
    "PlanChatRequest",
    "PlanFeedbackRequest",
    "PlanFeedbackResponse",
    "PostCreateRequest",
    "PostDetailOut",
    "PostOut",
    "RAGSearchRequest",
    "RAGSearchResponse",
    "RAGUploadRequest",
    "RecalculateRequest",
    "ReplicateRequest",
    "RevisionSummary",
    "ShareCreateRequest",
    "ShareInfo",
    "StandardResponse",
    "StructuredFeedback",
    "StructuredFeedbackAction",
    "TripPlan",
    "TripPlanResponse",
    "TripRequest",
    "UserCreate",
    "UserFeedback",
    "UserLogin",
    "UserResponse",
    "WeatherInfo",
]
