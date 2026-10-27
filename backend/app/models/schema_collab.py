"""
backend/app/models/schema_collab.py

行程分享与多人协作域 Pydantic 模型。

作用：
- 定义行程分享、协作者、邀请令牌相关的请求与响应结构；
- 原 schemas.py 按域拆分而来。
"""

from pydantic import BaseModel, Field


class ShareCreateRequest(BaseModel):
    """
    开启行程分享请求。

    为指定行程生成分享令牌，持有令牌的任何人可在有效期内只读查看行程。
    """

    expires_days: int | None = Field(
        default=7, ge=1, le=365, description="分享有效天数，1-365；不传默认 7 天"
    )


class ShareInfo(BaseModel):
    """
    行程分享信息。

    token 用于拼接公开访问链接；expires_at 为空表示永久有效。
    """

    plan_id: str = Field(..., description="行程计划 ID")
    share_token: str = Field(..., description="分享令牌")
    share_path: str = Field(..., description="前端分享页路由路径，如 /share/xxx")
    expires_at: str | None = Field(None, description="过期时间（ISO 格式），NULL 表示永久有效")
    share_view_count: int = Field(0, description="分享页累计访问次数")


class CollaboratorOut(BaseModel):
    """
    行程成员信息响应。

    所有者与协作者统一以成员形式返回：所有者 role=owner，
    协作者 role=editor（可查看行程、提交反馈）。
    """

    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    role: str = Field(..., description="成员角色：owner（所有者）/ editor（协作者）")
    joined_at: str | None = Field(None, description="加入时间（ISO 格式），所有者为行程创建时间")


class InviteOut(BaseModel):
    """
    邀请链接信息响应。

    token 用于拼接前端加入协作路由 /join/{token}。
    """

    plan_id: str = Field(..., description="行程计划 ID")
    token: str = Field(..., description="邀请令牌")
    invite_path: str = Field(..., description="前端加入协作路由路径，如 /join/xxx")
    expires_at: str | None = Field(None, description="邀请过期时间（ISO 格式）")


class CollaboratorJoinOut(BaseModel):
    """
    凭邀请令牌加入协作的响应。

    前端据此跳转到对应行程的结果页。
    """

    plan_id: str = Field(..., description="加入的行程计划 ID")
    city: str | None = Field(None, description="行程目的地城市")
    role: str = Field(default="editor", description="加入后的角色：owner（已是所有者）/ editor")


__all__ = [
    "CollaboratorJoinOut",
    "CollaboratorOut",
    "InviteOut",
    "ShareCreateRequest",
    "ShareInfo",
]
