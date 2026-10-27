"""rag（检索层）：知识缓存——搜索优先、渐进积累模式。"""

import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger

from app.rag.retriever import Retriever


class KnowledgeCache:
    """先查向量库缓存，未命中回源外部搜索并回填缓存。"""

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    async def search_or_fetch(
        self,
        query: str,
        city: str | None = None,
        source_type: str = "attraction",
        external_fetcher: Callable | None = None,
        min_score: float = 0.75,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """检索内部触发 embedding 编码（同步重操作），必须放线程池避免阻塞事件循环。"""
        cached_results = await asyncio.to_thread(
            self.retriever.search, query, city=city, top_k=top_k
        )

        if cached_results:
            best = cached_results[0]
            if best.get("score", 0) >= min_score:
                best["from_cache"] = True
                best["source_type"] = source_type
                return best

        if external_fetcher is not None:
            try:
                if asyncio.iscoroutinefunction(external_fetcher):
                    external_result = await external_fetcher(query, city)
                else:
                    external_result = await asyncio.to_thread(external_fetcher, query, city)

                if external_result and external_result.get("summary"):
                    await asyncio.to_thread(
                        self.retriever.add_documents,
                        documents=[
                            {
                                "title": external_result.get("title", query),
                                "content": external_result.get("summary", ""),
                                "source_type": source_type,
                            }
                        ],
                        city=city,
                    )
                    return {
                        "content": external_result.get("summary", ""),
                        "title": external_result.get("title", query),
                        "score": 1.0,  # 外部搜索结果默认高置信度
                        "from_cache": False,
                        "source_type": source_type,
                        "url": external_result.get("url", ""),
                    }
            except Exception as exc:
                logger.warning(f"[KnowledgeCache] 外部搜索失败: {exc}")

        # 回源失败/无回源通道：返回缓存中的次优结果
        if cached_results:
            best = cached_results[0]
            best["from_cache"] = True
            best["source_type"] = source_type
            return best

        return {
            "content": "",
            "title": query,
            "score": 0.0,
            "from_cache": False,
            "source_type": source_type,
        }

    async def batch_search_or_fetch(
        self,
        queries: list[str],
        city: str | None = None,
        source_type: str = "attraction",
        external_fetcher: Callable | None = None,
        min_score: float = 0.75,
    ) -> list[dict[str, Any]]:
        tasks = [
            self.search_or_fetch(q, city, source_type, external_fetcher, min_score)
            for q in queries
        ]
        return await asyncio.gather(*tasks)
