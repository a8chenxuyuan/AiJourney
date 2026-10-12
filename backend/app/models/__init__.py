"""
backend/app/models/__init__.py

数据模型模块初始化文件。

作用：
- 标识 models 目录为一个 Python 包；
- 导出 Pydantic 模型和 SQLAlchemy 模型，方便其他模块引用。
"""

from app.models.db_models import CrawledDocument, Order, TripPlanDB, User, UserPreferenceDB
from app.models.schemas import (
    AgentLog,
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    HumanDecisionRequest,
    IntentAnalysis,
    Location,
    Meal,
    RecalculateRequest,
    StandardResponse,
    TripPlan,
    TripPlanResponse,
    TripRequest,
    UserCreate,
    UserFeedback,
    UserLogin,
    UserResponse,
    WeatherInfo,
)

__all__ = [
    "AgentLog",
    "Attraction",
    "Budget",
    "CrawledDocument",
    "DayPlan",
    "Hotel",
    "HumanDecisionRequest",
    "IntentAnalysis",
    "Location",
    "Meal",
    "Order",
    "RecalculateRequest",
    "StandardResponse",
    "TripPlan",
    "TripPlanDB",
    "TripPlanResponse",
    "TripRequest",
    "User",
    "UserCreate",
    "UserFeedback",
    "UserLogin",
    "UserPreferenceDB",
    "UserResponse",
    "WeatherInfo",
]
