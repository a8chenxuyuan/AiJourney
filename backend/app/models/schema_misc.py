"""
backend/app/models/schema_misc.py

知识库 / 支付 / 杂项 Pydantic 模型。

作用：
- 定义 RAG 知识库、爬虫触发、支付订单、目的地问答等请求与响应结构；
- 原 schemas.py 按域拆分而来。
"""

from typing import Any

from pydantic import BaseModel, Field


class RAGUploadRequest(BaseModel):
    """
    知识库文档上传请求模型。
    """

    city: str | None = Field(default=None, description="文档所属城市")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档正文")


class RAGSearchRequest(BaseModel):
    """
    知识库检索请求模型。
    """

    query: str = Field(..., description="查询文本")
    city: str | None = Field(default=None, description="限制城市")
    top_k: int = Field(default=5, description="返回条数")


class RAGSearchResponse(BaseModel):
    """
    知识库检索响应模型。
    """

    query: str = Field(..., description="查询文本")
    results: list[dict[str, Any]] = Field(default_factory=list, description="检索结果列表")


class PaymentCreateRequest(BaseModel):
    """
    创建支付订单请求模型。
    """

    plan_id: str = Field(..., description="关联的行程计划 ID")
    amount: float = Field(..., gt=0, description="支付金额")
    payment_method: str = Field(default="alipay", description="支付方式")


class PaymentResponse(BaseModel):
    """
    支付订单响应模型。
    """

    order_id: str = Field(..., description="订单 ID")
    amount: float = Field(..., description="订单金额")
    status: str = Field(..., description="订单状态")
    payment_params: dict[str, Any] | None = Field(default=None, description="第三方支付参数")


class CrawlerTriggerRequest(BaseModel):
    """
    触发爬虫请求模型。
    """

    cities: list[str] = Field(default_factory=list, description="要抓取的城市列表，为空则抓取全部")
    max_pages: int | None = Field(default=None, description="最大抓取页面数")


class DestinationAskRequest(BaseModel):
    """目的地 AI 问答请求。"""

    city: str = Field(..., min_length=1, max_length=100, description="目的地城市")
    question: str = Field(..., min_length=1, max_length=500, description="问题内容")


__all__ = [
    "CrawlerTriggerRequest",
    "DestinationAskRequest",
    "PaymentCreateRequest",
    "PaymentResponse",
    "RAGSearchRequest",
    "RAGSearchResponse",
    "RAGUploadRequest",
]
