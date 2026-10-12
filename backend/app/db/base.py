"""
backend/app/db/base.py

SQLAlchemy 模型基类定义。

作用：
- 定义所有数据库模型继承的 Base 对象；
- 通过 declarative_base 创建基类；
- 配合 Alembic 进行数据库迁移。

对应技术：
- SQLAlchemy ORM：declarative_base
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类。

    所有数据库模型（User、TripPlanDB 等）都继承自此类。
    SQLAlchemy 会根据这些子类自动映射数据库表。
    """

    pass
