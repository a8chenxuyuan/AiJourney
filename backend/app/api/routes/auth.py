"""
backend/app/api/routes/auth.py

用户认证路由模块。

作用：
- 提供用户注册、登录、获取当前用户信息等接口；
- 调用 AuthService 完成业务逻辑。

对应技术：
- FastAPI：APIRouter、Depends
- SQLAlchemy：AsyncSession
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.models.db_models import User
from app.models.schemas import StandardResponse, UserCreate, UserLogin
from app.services.auth_service import AuthService

# 创建认证路由
router = APIRouter()


@router.post("/register", response_model=StandardResponse)
async def register(user_create: UserCreate, session: AsyncSession = Depends(get_db)):
    """
    用户注册接口。

    流程：
    1. 校验用户名是否已存在；
    2. 校验邮箱是否已存在；
    3. 创建新用户并写入数据库；
    4. 返回注册成功信息。

    Args:
        user_create: 用户注册请求数据。
        session: 数据库会话。

    Returns:
        StandardResponse: 注册结果。
    """
    # 检查用户名是否已存在
    existing_user = await AuthService.get_user_by_username(session, user_create.username)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    # 检查邮箱是否已存在
    existing_email = await AuthService.get_user_by_email(session, user_create.email)
    if existing_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已存在")

    # 创建用户
    new_user = await AuthService.create_user(session, user_create)

    return StandardResponse(
        success=True,
        message="注册成功",
        data={"user_id": new_user.id, "username": new_user.username},
    )


@router.post("/login", response_model=StandardResponse)
async def login(user_login: UserLogin, session: AsyncSession = Depends(get_db)):
    """
    用户登录接口。

    流程：
    1. 校验用户名和密码；
    2. 生成 JWT Access Token；
    3. 返回 Token 和用户信息。

    Args:
        user_login: 用户登录请求数据。
        session: 数据库会话。

    Returns:
        StandardResponse: 包含 access_token 和 user 的登录结果。
    """
    user = await AuthService.authenticate_user(session, user_login.username, user_login.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁，如有疑问请联系管理员"
        )

    access_token = AuthService.create_user_token(user)

    return StandardResponse(
        success=True,
        message="登录成功",
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "user": AuthService.to_user_response(user).model_dump(),
        },
    )


@router.get("/me", response_model=StandardResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    获取当前登录用户信息。

    Args:
        current_user: 通过 JWT 校验获取的当前用户。

    Returns:
        StandardResponse: 当前用户信息。
    """
    return StandardResponse(
        success=True,
        message="获取成功",
        data=AuthService.to_user_response(current_user).model_dump(),
    )
