"""
backend/app/api/routes/__init__.py

路由模块初始化文件。

作用：
- 标识 routes 目录为一个 Python 包；
- 可从本包导出各路由模块（可选）。
"""

from app.api.routes import auth, user, trip, agent, map, poi, rag, memory, crawler, payment

__all__ = ["auth", "user", "trip", "agent", "map", "poi", "rag", "memory", "crawler", "payment"]
