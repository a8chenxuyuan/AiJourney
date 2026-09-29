"""
backend/app/db/session.py

数据库会话管理模块。

作用：
- 根据配置创建 SQLAlchemy 异步引擎；
- 提供异步会话生成器；
- 提供 FastAPI 依赖注入函数 get_db，用于每个请求获取独立的数据库会话。

对应技术：
- SQLAlchemy：create_async_engine、async_sessionmaker
- FastAPI：Depends 依赖注入
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings


# 创建异步数据库引擎
# echo=False 表示不在控制台打印 SQL，生产环境建议关闭；开发调试可设为 True
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True
)

# 创建异步会话工厂
# expire_on_commit=False 避免提交后对象过期，便于后续继续访问关联属性
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)


async def get_db() -> AsyncSession:
    """
    FastAPI 依赖注入函数：获取数据库会话。

    每个 HTTP 请求都会创建一个独立的 AsyncSession，请求结束后自动关闭。
    如果请求过程中发生异常，会话会回滚事务。

    Yields:
        AsyncSession: 异步数据库会话对象。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
