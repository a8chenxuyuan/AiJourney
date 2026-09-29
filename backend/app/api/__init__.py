"""
backend/app/api/__init__.py

API 模块初始化文件。

作用：
- 标识 api 目录为一个 Python 包；
- 可在此导出 FastAPI 应用实例。
"""

from app.api.main import app

__all__ = ["app"]
