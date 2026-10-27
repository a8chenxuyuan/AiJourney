"""
backend/app/services/__init__.py

服务模块初始化文件。

作用：
- 标识 services 目录为一个 Python 包；
- 可在此导出常用的服务类或函数。
"""

from app.llm.client import get_llm
from app.services.amap_service import AmapService
from app.services.auth_service import AuthService
from app.services.crawler_service import CrawlerService
from app.services.memory_service import MemoryService
from app.services.payment_service import PaymentService
from app.services.rag_service import RAGService

__all__ = [
    "AmapService",
    "AuthService",
    "CrawlerService",
    "MemoryService",
    "PaymentService",
    "RAGService",
    "get_llm",
]
