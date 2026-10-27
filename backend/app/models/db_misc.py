"""
backend/app/models/db_misc.py

杂项（知识库/爬虫）数据库模型。

作用：
- 定义爬虫文档等知识库相关的表结构；
- 原 db_models.py 按域拆分而来，所有模型继承自 app.db.base.Base。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.db.base import Base


class CrawledDocument(Base):
    """
    爬虫文档表。

    存储爬虫抓取的原始文档内容，用于后续切分和向量化。
    """

    __tablename__ = "crawled_documents"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="文档 ID")
    url = Column(String(512), unique=True, index=True, nullable=True, comment="来源 URL")
    title = Column(String(255), nullable=False, comment="文档标题")
    content = Column(Text, nullable=False, comment="文档正文")
    city = Column(String(100), index=True, nullable=True, comment="所属城市")
    source_type = Column(String(50), default="crawler", comment="来源类型：crawler/manual")
    crawled_at = Column(DateTime, default=func.now(), comment="抓取时间")


__all__ = ["CrawledDocument"]
