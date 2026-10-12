"""
backend/app/db/__init__.py

数据库模块初始化文件。

作用：
- 标识 db 目录为一个 Python 包；
- 可从本包导出常用的数据库对象，方便其他模块引用。
"""

from app.db.base import Base
from app.db.session import AsyncSessionLocal, get_db

__all__ = ["AsyncSessionLocal", "Base", "get_db"]
