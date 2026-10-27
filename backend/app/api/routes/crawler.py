"""
backend/app/api/routes/crawler.py

爬虫路由模块。

作用：
- 提供手动触发爬虫、查询爬虫任务状态接口；
- 爬虫属于长耗时任务，与规划任务一致走 ARQ 消息队列：
  trigger 接口只负责入队并返回 job_id，实际抓取由 Worker 进程执行。

对应技术：
- FastAPI：APIRouter、Depends
- arq：任务队列（入队 + Job 状态查询）
"""


from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.core.utils.queue import enqueue_crawler_task, get_job_status
from app.models.db_models import User
from app.models.schemas import CrawlerTriggerRequest, StandardResponse

router = APIRouter()


@router.post("/trigger", response_model=StandardResponse)
async def trigger_crawler(
    trigger_request: CrawlerTriggerRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    手动触发爬虫任务（异步）。

    接口立即返回任务 ID，抓取由 Worker 进程在后台执行，
    通过 /status/{job_id} 查询进度与结果。

    Args:
        trigger_request: 爬虫触发请求（城市列表、最大页数）。
        current_user: 当前登录用户。
        session: 数据库会话（保持依赖一致性，未直接使用）。

    Returns:
        StandardResponse: 任务 ID 与初始状态。
    """
    job_id = await enqueue_crawler_task(
        cities=trigger_request.cities, max_pages=trigger_request.max_pages
    )

    return StandardResponse(
        success=True, message="爬虫任务已入队", data={"job_id": job_id, "status": "queued"}
    )


@router.get("/status/{job_id}", response_model=StandardResponse)
async def get_crawler_status(job_id: str, current_user: User = Depends(get_current_user)):
    """
    查询爬虫任务状态与结果。

    Args:
        job_id: 触发时返回的任务 ID。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: 任务状态（queued/in_progress/complete 等），
        complete 时附带抓取结果统计。
    """
    status = await get_job_status(job_id)

    return StandardResponse(success=True, message="查询成功", data=status)
