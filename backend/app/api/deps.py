"""
backend/app/api/deps.py

FastAPI 依赖注入模块。

作用：
- 提供路由层常用的依赖函数；
- 包括：获取数据库会话、获取当前登录用户；
- 通过依赖注入实现认证鉴权和数据库事务管理。

对应技术：
- FastAPI：Depends、HTTPBearer、HTTPException
- SQLAlchemy：AsyncSession
"""

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import AuthService
from app.models.db_models import User, TripPlanDB
from app.utils.security import decode_access_token


# HTTP Bearer 认证方案，用于从请求头中提取 Authorization: Bearer <token>
oauth2_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db)
) -> User:
    """
    获取当前登录用户。

    流程：
    1. 从 HTTP Authorization 头中提取 Bearer Token；
    2. 解码 JWT，获取用户 ID；
    3. 查询数据库验证用户是否存在；
    4. 返回用户对象。

    Args:
        credentials: HTTP Bearer 凭证。
        session: 数据库会话。

    Returns:
        User: 当前登录用户对象。

    Raises:
        HTTPException: Token 缺失、无效或用户不存在时抛出 401。
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 负载无效",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 用户 ID 格式错误",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user = await AuthService.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return user


async def get_owned_plan_for_user(
    plan_id: str,
    current_user: User,
    session: AsyncSession
) -> TripPlanDB:
    """
    核心归属校验逻辑：按 plan_id 查询行程并校验属于 current_user。

    独立成普通函数（非依赖），供 get_owned_plan 依赖和
    其他自定义认证场景（如 SSE 查询参数认证）复用，避免校验逻辑重复。

    Args:
        plan_id: 行程计划 ID。
        current_user: 已完成认证的用户对象。
        session: 数据库会话。

    Returns:
        TripPlanDB: 归属校验通过的行程计划记录。

    Raises:
        HTTPException: 行程不存在或不属于当前用户时抛出 404。
    """
    plan = await session.get(TripPlanDB, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="行程计划不存在"
        )
    return plan


async def get_owned_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db)
) -> TripPlanDB:
    """
    FastAPI 依赖：获取指定行程计划并校验归属权。

    供需要按 plan_id 访问行程的路由复用，替代各路由中重复的
    "查询 + 归属校验" 样板代码。

    归属校验失败时统一返回 404，不区分"不存在"与"无权访问"，
    避免向越权请求者泄露资源存在性。

    Args:
        plan_id: 路径参数中的行程计划 ID。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        TripPlanDB: 归属校验通过的行程计划记录。

    Raises:
        HTTPException: 行程不存在或不属于当前用户时抛出 404。
    """
    return await get_owned_plan_for_user(plan_id, current_user, session)
