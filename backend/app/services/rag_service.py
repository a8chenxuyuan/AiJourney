"""
backend/app/services/rag_service.py

RAG（检索增强生成）服务模块。

作用：
- 管理文本向量化模型和 Qdrant 向量库客户端；
- 提供文档切分、Embedding、存储、检索等能力；
- 支持搜索优先、渐进积累模式：先查缓存，未命中则外部搜索；
- 为 RAGAgent 和其他模块提供检索接口。

对应技术：
- SentenceTransformers：文本 Embedding
- Qdrant：向量数据库
- LangChain：文本切分器
- BaikeService：百度百科外部搜索
"""

import asyncio
import os
import uuid
from typing import Callable, List, Dict, Any, Optional

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.config import settings

# 注意：HuggingFace 离线开关的权威设置位置在 app/__init__.py（包最早钩子）。
# 此处再设置一次作为兜底（setdefault），单靠这里已不够——
# langchain_core 导入期会连带导入 transformers -> huggingface_hub，
# 比 rag_service 先执行，导致离线常量被提前锁死。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


class RAGService:
    """
    RAG 服务类。

    封装了从原始文档到向量检索的完整流程。
    """

    def __init__(self):
        """
        初始化 RAG 服务。

        - 连接 Qdrant 向量库（远程不可用时自动回退到内存模式）；
        - 加载 Embedding 模型（首次会下载，可能较慢）。
        """
        try:
            # 设置较短超时，避免远程服务未启动时阻塞应用启动
            self.client = QdrantClient(url=settings.qdrant_url, timeout=3.0)
            # 验证远程服务是否可用
            self.client.get_collections()
        except Exception as exc:
            logger.warning(f"[RAGService] 远程 Qdrant ({settings.qdrant_url}) 连接失败: {exc}，回退到内存模式")
            self.client = QdrantClient(":memory:")
        self.collection_name = settings.qdrant_collection
        # 延迟加载 embedding 模型，避免服务启动时阻塞
        self._embedding_model: Optional[Any] = None
        # 嵌入模型不可用标记（离线且无本地缓存时置 True），
        # 置 True 后所有向量检索/写入自动降级，规划主流程不受影响
        self._embedding_failed = False
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=["\n\n", "\n", "。", "；", " "]
        )

    @property
    def embedding_model(self) -> Any:
        """
        延迟加载 Embedding 模型。

        加载失败（离线且无本地缓存）时标记 _embedding_failed 并抛出异常，
        后续调用直接快速失败，不再反复尝试联网下载。

        Returns:
            SentenceTransformer: 加载好的 Embedding 模型。

        Raises:
            RuntimeError: 模型不可用时抛出。
        """
        if self._embedding_failed:
            raise RuntimeError("嵌入模型不可用（离线模式且无本地缓存），RAG 已降级")
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer(settings.embedding_model_name)
            except Exception as exc:
                # 标记失败：此后所有向量相关操作快速降级，不再阻塞流程
                self._embedding_failed = True
                logger.warning(
                    f"[RAGService] 嵌入模型({settings.embedding_model_name})加载失败，"
                    f"RAG 缓存降级为直通模式（背景知识改由百度百科实时获取）: {exc}"
                )
                raise
        return self._embedding_model

    def _ensure_collection(self) -> None:
        """
        确保 Qdrant 集合存在。

        如果集合不存在则创建，向量维度由模型决定。
        嵌入模型不可用时直接跳过（缓存写入降级）。
        """
        if self._embedding_failed:
            return
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            # 获取向量维度
            sample_embedding = self.embedding_model.encode("示例文本")
            vector_size = len(sample_embedding)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
            )

    def split_text(self, text: str) -> List[str]:
        """
        将长文本切分为适合向量化的片段。

        Args:
            text: 原始长文本。

        Returns:
            List[str]: 切分后的文本片段列表。
        """
        return self.text_splitter.split_text(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        将文本列表编码为向量。

        Args:
            texts: 文本列表。

        Returns:
            List[List[float]]: 向量列表。
        """
        return self.embedding_model.encode(texts).tolist()

    def add_documents(
        self,
        documents: List[Dict[str, Any]],
        city: Optional[str] = None
    ) -> None:
        """
        将文档添加到向量库。

        Args:
            documents: 文档列表，每个文档包含 title 和 content。
            city: 文档所属城市，用于过滤。
        """
        # 嵌入模型不可用时跳过缓存写入（降级，不影响调用方主流程）
        if self._embedding_failed:
            return
        self._ensure_collection()

        points = []
        for doc in documents:
            chunks = self.split_text(doc["content"])
            for chunk in chunks:
                vector = self.embed_texts([chunk])[0]
                points.append(PointStruct(
                    # 用 UUID 作为 point id，避免跨批次自增 id 从 0 重叠导致旧文档被覆盖
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "title": doc.get("title", ""),
                        "content": chunk,
                        "city": city,
                        "source_type": doc.get("source_type", "manual")
                    }
                ))

        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        query: str,
        city: Optional[str] = None,
        top_k: int = None
    ) -> List[Dict[str, Any]]:
        """
        根据查询文本检索相关文档片段。

        Args:
            query: 查询文本。
            city: 可选的城市过滤条件。
            top_k: 返回条数，默认使用配置值。

        Returns:
            List[Dict[str, Any]]: 检索结果；嵌入模型不可用时返回空列表（降级）。
        """
        # 与 add_documents 对齐：嵌入模型不可用时优雅降级为空结果，
        # 避免检索接口 500（背景知识由百度百科实时获取兜底）
        if self._embedding_failed:
            logger.warning("[RAGService] 嵌入模型不可用，检索返回空结果（降级模式）")
            return []

        self._ensure_collection()
        top_k = top_k or settings.rag_top_k

        query_vector = self.embed_texts([query])[0]

        filter_condition = None
        if city:
            filter_condition = {"must": [{"key": "city", "match": {"value": city}}]}

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=filter_condition
        )
        results = response.points

        return [
            {
                "content": r.payload.get("content", ""),
                "title": r.payload.get("title", ""),
                "score": r.score
            }
            for r in results
        ]

    async def search_or_fetch(
        self,
        query: str,
        city: Optional[str] = None,
        source_type: str = "attraction",
        external_fetcher: Optional[Callable] = None,
        min_score: float = 0.75,
        top_k: int = None
    ) -> Dict[str, Any]:
        """
        先查缓存，未命中则调外部搜索，结果存入缓存后返回。

        这是"搜索优先，渐进积累"模式的核心方法：
        - 优先从向量库缓存检索；
        - 缓存未命中或置信度低时，调用外部搜索；
        - 外部搜索结果自动存入向量库，供下次复用。

        Args:
            query: 搜索关键词（如景点名称）。
            city: 城市名（可选）。
            source_type: 数据类型，如 "attraction" / "hotel" / "food"。
            external_fetcher: 外部搜索函数，签名为 async (query, city) -> Dict。
            min_score: 缓存命中的最小相似度阈值，低于此值则调外部搜索。
            top_k: 返回条数。

        Returns:
            Dict[str, Any]: 包含以下字段：
                - content: 检索到的文本内容
                - title: 标题
                - score: 相似度分数
                - from_cache: 是否来自缓存
                - source_type: 数据类型
        """
        top_k = top_k or settings.rag_top_k

        # 1. 先查本地缓存
        # search 内部会触发嵌入模型编码（同步重操作），
        # 必须放入线程池执行，避免阻塞 asyncio 事件循环导致 SSE 假死
        cached_results = await asyncio.to_thread(
            self.search, query, city=city, top_k=top_k
        )

        # 检查是否有高置信度的缓存结果
        if cached_results:
            best = cached_results[0]
            if best.get("score", 0) >= min_score:
                best["from_cache"] = True
                best["source_type"] = source_type
                return best

        # 2. 缓存未命中，调外部搜索
        if external_fetcher is None:
            # 默认使用百度百科搜索
            from app.services.baike_service import get_baike_service
            baike = get_baike_service()
            external_fetcher = baike.search

        try:
            # 调用外部搜索
            if asyncio.iscoroutinefunction(external_fetcher):
                external_result = await external_fetcher(query, city)
            else:
                # 同步函数包装为异步
                external_result = await asyncio.to_thread(external_fetcher, query, city)

            # 3. 存入缓存（encode + upsert 为同步操作，同样放入线程池）
            if external_result and external_result.get("summary"):
                await asyncio.to_thread(
                    self.add_documents,
                    documents=[{
                        "title": external_result.get("title", query),
                        "content": external_result.get("summary", ""),
                        "source_type": source_type
                    }],
                    city=city
                )

                return {
                    "content": external_result.get("summary", ""),
                    "title": external_result.get("title", query),
                    "score": 1.0,  # 外部搜索结果默认高置信度
                    "from_cache": False,
                    "source_type": source_type,
                    "url": external_result.get("url", "")
                }

        except Exception as e:
            logger.warning(f"[RAGService] 外部搜索失败: {e}")

        # 4. 外部搜索失败，返回缓存中的次优结果
        if cached_results:
            best = cached_results[0]
            best["from_cache"] = True
            best["source_type"] = source_type
            return best

        # 5. 完全无结果
        return {
            "content": "",
            "title": query,
            "score": 0.0,
            "from_cache": False,
            "source_type": source_type
        }

    async def batch_search_or_fetch(
        self,
        queries: List[str],
        city: Optional[str] = None,
        source_type: str = "attraction",
        external_fetcher: Optional[Callable] = None,
        min_score: float = 0.75
    ) -> List[Dict[str, Any]]:
        """
        批量搜索：先查缓存，未命中则外部搜索。

        Args:
            queries: 搜索关键词列表。
            city: 城市名。
            source_type: 数据类型。
            external_fetcher: 外部搜索函数。
            min_score: 缓存命中阈值。

        Returns:
            List[Dict[str, Any]]: 搜索结果列表。
        """
        tasks = [
            self.search_or_fetch(q, city, source_type, external_fetcher, min_score)
            for q in queries
        ]
        return await asyncio.gather(*tasks)


# ==================== 全局单例 ====================
# RAGService 持有 Qdrant 连接和嵌入模型（内存开销大、初始化慢），
# 必须全局复用同一个实例：
# - 避免每次调用都重复尝试连接 Qdrant（远程不可用时每次白等 3 秒超时）；
# - 避免内存模式 Qdrant 每个实例各一份空缓存，导致缓存永不生效。
_rag_service_instance: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """
    获取全局唯一的 RAGService 实例（懒加载单例）。

    Returns:
        RAGService: 全局共享的 RAG 服务实例。
    """
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService()
    return _rag_service_instance
