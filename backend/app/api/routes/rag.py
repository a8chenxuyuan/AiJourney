"""
backend/app/api/routes/rag.py

知识库（RAG）路由模块。

作用：
- 提供文档上传/添加接口；
- 提供知识库检索接口；
- 调用 RAGService 完成向量化存储和检索。

对应技术：
- FastAPI：APIRouter、Depends
- Qdrant：向量检索
- SentenceTransformers：文本 Embedding
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.db_models import User
from app.models.schemas import (
    RAGUploadRequest,
    RAGSearchRequest,
    StandardResponse
)
from app.services.rag_service import RAGService, get_rag_service


router = APIRouter()


def _get_rag_service() -> RAGService:
    """
    获取 RAGService 实例（全局单例）。

    Returns:
        RAGService: RAG 服务实例。
    """
    return get_rag_service()


@router.post("/upload", response_model=StandardResponse)
async def upload_document(
    upload_request: RAGUploadRequest,
    current_user: User = Depends(get_current_user)
):
    """
    上传文档到知识库。

    文档会被切分、Embedding 后存入 Qdrant 向量库。

    Args:
        upload_request: 文档上传请求。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: 上传结果。
    """
    service = _get_rag_service()
    service.add_documents(
        documents=[{"title": upload_request.title, "content": upload_request.content}],
        city=upload_request.city
    )

    return StandardResponse(
        success=True,
        message="文档上传成功",
        data={"title": upload_request.title, "city": upload_request.city}
    )


@router.post("/search", response_model=StandardResponse)
async def search_knowledge(
    search_request: RAGSearchRequest,
    current_user: User = Depends(get_current_user)
):
    """
    检索知识库。

    Args:
        search_request: 检索请求。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: 检索结果。
    """
    service = _get_rag_service()
    results = service.search(
        query=search_request.query,
        city=search_request.city,
        top_k=search_request.top_k
    )

    return StandardResponse(
        success=True,
        message="检索成功",
        data={"query": search_request.query, "results": results}
    )
