"""
backend/app/models/__init__.py

数据模型模块初始化文件。

作用：
- 标识 models 目录为一个 Python 包；
- 导出 Pydantic 模型和 SQLAlchemy 模型，方便其他模块引用。
"""

from app.models.schemas import (
    UserCreate,
    UserResponse,
    UserLogin,
    TripRequest,
    TripPlan,
    DayPlan,
    Attraction,
    Hotel,
    Meal,
    WeatherInfo,
    Budget,
    Location,
    IntentAnalysis,
    AgentLog,
    UserFeedback,
    TripPlanResponse,
    HumanDecisionRequest,
    RecalculateRequest,
    StandardResponse
)
from app.models.db_models import User, TripPlanDB, UserPreferenceDB, Order, CrawledDocument

__all__ = [
    "UserCreate",
    "UserResponse",
    "UserLogin",
    "TripRequest",
    "TripPlan",
    "DayPlan",
    "Attraction",
    "Hotel",
    "Meal",
    "WeatherInfo",
    "Budget",
    "Location",
    "IntentAnalysis",
    "AgentLog",
    "UserFeedback",
    "TripPlanResponse",
    "HumanDecisionRequest",
    "RecalculateRequest",
    "StandardResponse",
    "User",
    "TripPlanDB",
    "UserPreferenceDB",
    "Order",
    "CrawledDocument"
]
