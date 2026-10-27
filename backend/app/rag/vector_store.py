"""rag（检索层）：Qdrant 向量库客户端封装。"""

from collections.abc import Callable
from typing import Any

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import settings


class VectorStore:
    """Qdrant 连接与集合操作。远程不可用时自动回退内存模式。"""

    def __init__(self) -> None:
        try:
            # 短超时：远程 Qdrant 未启动时不阻塞应用启动
            self.client = QdrantClient(url=settings.qdrant_url, timeout=3.0)
            self.client.get_collections()
        except Exception as exc:
            logger.warning(
                f"[VectorStore] 远程 Qdrant ({settings.qdrant_url}) 连接失败: {exc}，回退到内存模式"
            )
            self.client = QdrantClient(":memory:")
        self.collection_name = settings.qdrant_collection

    def ensure_collection(self, vector_size_provider: Callable[[], int]) -> None:
        """集合不存在时创建；向量维度惰性获取，避免每次调用白跑一次编码。"""
        collections = self.client.get_collections().collections
        if any(c.name == self.collection_name for c in collections):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size_provider(), distance=Distance.COSINE),
        )

    def upsert(self, points: list[PointStruct]) -> None:
        self.client.upsert(collection_name=self.collection_name, points=points)

    def query(
        self, vector: list[float], limit: int, query_filter: dict[str, Any] | None = None
    ) -> list[Any]:
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=limit,
            query_filter=query_filter,
        )
        return response.points
