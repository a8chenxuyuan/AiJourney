"""
backend/app/services/auth_service.py

用户认证服务模块。

作用：
- 封装用户注册、登录、信息查询等认证相关业务逻辑；
- 将路由层与数据库操作解耦。

对应技术：
- SQLAlchemy 异步 ORM
- passlib / python-jose（通过 utils/security 间接使用）
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import User
from app.models.schemas import UserCreate, UserResponse
from app.utils.security import create_access_token, get_password_hash, verify_password


class AuthService:
    """
    认证服务类。

    提供用户注册、登录校验、Token 生成等方法。
    """

    @staticmethod
    async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
        """
        根据用户名查询用户。

        Args:
            session: 数据库会话。
            username: 用户名。

        Returns:
            Optional[User]: 用户对象，未找到返回 None。
        """
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
        """
        根据邮箱查询用户。

        Args:
            session: 数据库会话。
            email: 邮箱地址。

        Returns:
            Optional[User]: 用户对象，未找到返回 None。
        """
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """
        根据用户 ID 查询用户。

        Args:
            session: 数据库会话。
            user_id: 用户 ID。

        Returns:
            Optional[User]: 用户对象，未找到返回 None。
        """
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(session: AsyncSession, user_create: UserCreate) -> User:
        """
        创建新用户。

        流程：
        1. 密码哈希加密；
        2. 创建 User 数据库对象；
        3. 写入数据库。

        Args:
            session: 数据库会话。
            user_create: 用户注册请求数据。

        Returns:
            User: 创建成功的用户对象。
        """
        hashed_password = get_password_hash(user_create.password)
        db_user = User(
            username=user_create.username, email=user_create.email, password_hash=hashed_password
        )
        session.add(db_user)
        await session.flush()  # 立即刷新，获取自增 ID
        await session.refresh(db_user)
        return db_user

    @staticmethod
    async def authenticate_user(
        session: AsyncSession, username: str, password: str
    ) -> Optional[User]:
        """
        校验用户名和密码是否匹配。

        Args:
            session: 数据库会话。
            username: 用户名。
            password: 明文密码。

        Returns:
            Optional[User]: 校验成功返回用户对象；失败返回 None。
        """
        user = await AuthService.get_user_by_username(session, username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    @staticmethod
    def create_user_token(user: User) -> str:
        """
        为用户生成 JWT Access Token。

        Args:
            user: 已认证用户对象。

        Returns:
            str: JWT Token 字符串。
        """
        return create_access_token(data={"sub": str(user.id)})

    @staticmethod
    def to_user_response(user: User) -> UserResponse:
        """
        将 User 数据库对象转换为 UserResponse Pydantic 模型。

        Args:
            user: 用户数据库对象。

        Returns:
            UserResponse: 用于 API 响应的用户信息。
        """
        return UserResponse.model_validate(user)
