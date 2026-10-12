"""
backend/app/utils/security.py

安全相关工具函数模块。

作用：
- 用户密码加密与校验；
- JWT Access Token 的生成与解码；
- 提供 FastAPI 认证相关的底层工具。

对应技术：
- passlib[bcrypt]：密码哈希
- python-jose[cryptography]：JWT 编码/解码
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# 创建密码上下文，指定使用 bcrypt 算法
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    校验明文密码是否与哈希密码匹配。

    Args:
        plain_password: 用户输入的明文密码。
        hashed_password: 数据库存储的哈希密码。

    Returns:
        bool: 是否匹配。
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    对明文密码进行 bcrypt 哈希。

    Args:
        password: 明文密码。

    Returns:
        str: 哈希后的密码字符串。
    """
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    生成 JWT Access Token。

    Args:
        data: 需要编码到 Token 中的数据，通常包含 {"sub": user_id}。
        expires_delta: 过期时间增量，不传则使用配置的默认过期时间。

    Returns:
        str: 编码后的 JWT 字符串。
    """
    to_encode = data.copy()

    # 计算过期时间
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)

    # 将过期时间加入 Token 负载
    to_encode.update({"exp": expire})

    # 使用 JWT 密钥和算法编码
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码并校验 JWT Access Token。

    Args:
        token: 前端传入的 JWT 字符串。

    Returns:
        Optional[Dict[str, Any]]: 解码成功返回负载字典；失败（签名错误、过期等）返回 None。
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        # JWT 签名无效、Token 过期、格式错误等都返回 None
        return None
