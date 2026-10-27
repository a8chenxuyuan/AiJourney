"""services 层 RAG 门面：组合 rag 层（vector_store/retriever/knowledge_cache）能力。

RAGService 保持拆分前的门面签名；百度百科兜底回源在此注入（services 层专属
依赖），保证 rag 层零 services 依赖。rag 底座实现见 app/rag/ 各模块。
"""

from typing import Any

from app.rag.knowledge_cache import KnowledgeCache
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore


class RAGService:
    """RAG 门面：组合向量库 + 检索器 + 知识缓存，方法签名与拆分前一致。"""

    def __init__(self) -> None:
        self._retriever = Retriever(VectorStore())
        self._cache = KnowledgeCache(self._retriever)

    def split_text(self, text: str) -> list[str]:
        return self._retriever.split_text(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._retriever.embed_texts(texts)

    def add_documents(self, documents: list[dict[str, Any]], city: str | None = None) -> None:
        self._retriever.add_documents(documents, city)

    def search(
        self, query: str, city: str | None = None, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        return self._retriever.search(query, city=city, top_k=top_k)

    async def search_or_fetch(
        self,
        query: str,
        city: str | None = None,
        source_type: str = "attraction",
        external_fetcher: Any | None = None,
        min_score: float = 0.75,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        if external_fetcher is None:
            from app.services.baike_service import get_baike_service

            external_fetcher = get_baike_service().search
        return await self._cache.search_or_fetch(
            query, city, source_type, external_fetcher, min_score, top_k
        )

    async def batch_search_or_fetch(
        self,
        queries: list[str],
        city: str | None = None,
        source_type: str = "attraction",
        external_fetcher: Any | None = None,
        min_score: float = 0.75,
    ) -> list[dict[str, Any]]:
        if external_fetcher is None:
            from app.services.baike_service import get_baike_service

            external_fetcher = get_baike_service().search
        return await self._cache.batch_search_or_fetch(
            queries, city, source_type, external_fetcher, min_score
        )


# RAGService 持有 Qdrant 连接和嵌入模型（内存开销大、初始化慢），必须全局复用同一实例
_rag_service_instance: RAGService | None = None


def get_rag_service() -> RAGService:
    """获取全局唯一的 RAGService 实例（懒加载单例）。"""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService()
    return _rag_service_instance
