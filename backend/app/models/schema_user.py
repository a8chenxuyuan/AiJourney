"""
backend/app/models/schema_user.py

用户域 Pydantic 模型。

作用：
- 定义注册/登录/用户信息、用户反馈、收藏相关的请求与响应结构；
- 原 schemas.py 按域拆分而来。
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """
    用户注册请求模型。
    """

    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱地址")
    password: str = Field(..., min_length=6, description="密码，至少 6 位")


class UserLogin(BaseModel):
    """
    用户登录请求模型。
    """

    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class UserResponse(BaseModel):
    """
    用户信息响应模型。

    注意：响应中不包含 password_hash，避免泄露敏感信息。
    """

    id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱地址")
    role: str = Field(default="user", description="账号角色：user/admin")
    is_banned: bool = Field(default=False, description="是否被封禁")
    created_at: datetime = Field(description="注册时间")

    class Config:
        from_attributes = True


class UserFeedback(BaseModel):
    """
    用户反馈模型。
    """

    plan_id: str = Field(..., description="行程计划 ID")
    overall_score: int = Field(..., ge=1, le=5, description="总体评分 1-5")
    tag_feedback: dict[str, int] = Field(default_factory=dict, description="各维度评分")
    text_feedback: str | None = Field(default=None, description="文字反馈")
    would_use_again: bool = Field(default=False, description="是否愿意再次使用")


class FavoriteCreateRequest(BaseModel):
    """
    添加收藏请求。

    收藏行程结果中的景点、酒店、餐厅等对象，item_data 保存完整快照供回显。
    """

    item_type: str = Field(..., description="收藏类型：attraction/hotel/restaurant")
    item_id: str = Field(
        ..., min_length=1, description="收藏对象唯一标识（如景点名/酒店名的 hash）"
    )
    item_name: str = Field(..., min_length=1, description="收藏对象名称")
    city: str | None = Field(None, description="所属城市，用于按城市聚合推荐")
    item_data: dict | None = Field(None, description="收藏对象完整数据快照（JSON）")


class FavoriteOut(BaseModel):
    """
    收藏记录响应。

    与 favorites 表字段对应，item_data 原样返回。
    """

    id: int = Field(..., description="收藏 ID")
    item_type: str = Field(..., description="收藏类型")
    item_id: str = Field(..., description="收藏对象标识")
    item_name: str = Field(..., description="收藏对象名称")
    city: str | None = Field(None, description="所属城市")
    item_data: dict | None = Field(None, description="收藏对象完整数据快照")
    created_at: str | None = Field(None, description="收藏时间（ISO 格式）")


__all__ = [
    "FavoriteCreateRequest",
    "FavoriteOut",
    "UserCreate",
    "UserFeedback",
    "UserLogin",
    "UserResponse",
]
