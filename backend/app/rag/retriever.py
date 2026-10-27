"""rag（检索层）：Embedding 与向量检索。嵌入模型不可用时整体降级。"""

import os
import uuid
from typing import Any

from langchain.text_splitter import RecursiveCharacterTextSplitter
from loguru import logger
from qdrant_client.models import PointStruct

from app.core.config import settings
from app.rag.vector_store import VectorStore

# HuggingFace 离线开关的权威设置在 app/__init__.py（包最早钩子）；
# 这里 setdefault 兜底——langchain_core 导入期会连带 transformers -> huggingface_hub，
# 比本模块先执行，导致离线常量被提前锁死。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


class Retriever:
    """文本切分、Embedding、向量写入与检索。"""

    def __init__(self, store: VectorStore | None = None) -> None:
        self.store = store or VectorStore()
        # 延迟加载 embedding 模型，避免服务启动时阻塞
        self._embedding_model: Any | None = None
        # 嵌入模型不可用标记（离线且无本地缓存时置 True），
        # 置 True 后所有向量检索/写入自动降级，规划主流程不受影响
        self._embedding_failed = False
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=100, separators=["\n\n", "\n", "。", "；", " "]
        )

    @property
    def embedding_model(self) -> Any:
        if self._embedding_failed:
            raise RuntimeError("嵌入模型不可用（离线模式且无本地缓存），RAG 已降级")
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedding_model = SentenceTransformer(settings.embedding_model_name)
            except Exception as exc:
                # 标记失败：此后所有向量相关操作快速降级，不再反复尝试联网下载
                self._embedding_failed = True
                logger.warning(
                    f"[Retriever] 嵌入模型({settings.embedding_model_name})加载失败，"
                    f"RAG 缓存降级为直通模式（背景知识改由百度百科实时获取）: {exc}"
                )
                raise
        return self._embedding_model

    def split_text(self, text: str) -> list[str]:
        return self.text_splitter.split_text(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embedding_model.encode(texts).tolist()

    def add_documents(self, documents: list[dict[str, Any]], city: str | None = None) -> None:
        """文档切分→向量化→入库。嵌入模型不可用时跳过（降级，不影响调用方主流程）。"""
        if self._embedding_failed:
            return
        self.store.ensure_collection(lambda: len(self.embed_texts(["维度探测"])[0]))

        points = []
        for doc in documents:
            for chunk in self.split_text(doc["content"]):
                vector = self.embed_texts([chunk])[0]
                points.append(
                    PointStruct(
                        # UUID 作 point id，避免跨批次自增 id 从 0 重叠导致旧文档被覆盖
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload={
                            "title": doc.get("title", ""),
                            "content": chunk,
                            "city": city,
                            "source_type": doc.get("source_type", "manual"),
                        },
                    )
                )
        if points:
            self.store.upsert(points)

    def search(
        self, query: str, city: str | None = None, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """向量检索。嵌入模型不可用时返回空列表（降级）。"""
        if self._embedding_failed:
            logger.warning("[Retriever] 嵌入模型不可用，检索返回空结果（降级模式）")
            return []

        self.store.ensure_collection(lambda: len(self.embed_texts(["维度探测"])[0]))
        top_k = top_k or settings.rag_top_k
        query_vector = self.embed_texts([query])[0]

        filter_condition = None
        if city:
            filter_condition = {"must": [{"key": "city", "match": {"value": city}}]}

        results = self.store.query(query_vector, limit=top_k, query_filter=filter_condition)
        return [
            {
                "content": r.payload.get("content", ""),
                "title": r.payload.get("title", ""),
                "score": r.score,
            }
            for r in results
        ]
