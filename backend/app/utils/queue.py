"""
backend/app/utils/queue.py

ARQ 任务队列封装模块。

作用：
- API 进程通过本模块把规划/修订任务投递到 Redis 队列（ARQ）；
- 任务由独立的 Worker 进程（backend/worker.py）消费执行，
  实现 API 与 Agent 执行的进程级解耦（CS 架构的消息队列拆分）。

对应技术：
- arq：基于 Redis 的异步任务队列
"""

import asyncio
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus
from loguru import logger

from app.config import settings

# ARQ 连接池单例（懒加载，进程内复用）
_arq_pool: ArqRedis | None = None
_pool_lock = asyncio.Lock()

# Redis 保活补丁是否已应用（幂等标记）
_keepalive_applied = False


def enable_redis_keepalive() -> None:
    """
    给 arq 的 Redis 客户端注入连接保活参数（幂等，进程内调用一次即可）。

    背景：Redis 部署在 WSL2 中，Windows 主机经 localhost 端口转发访问，
    转发层会周期性掐断空闲/长连接（Connection closed by server）。
    两层保活对策：
    - socket_keepalive=True：TCP 层保活探测包，维持 NAT/转发层的连接表项；
    - health_check_interval=15：从连接池取连接时，若空闲超过 15 秒先发 PING，
      已被掐断的"半开连接"会立即报错并自动重建，避免业务命令撞上死连接。

    实现方式：替换 arq.connections 模块内的 ArqRedis 构造入口（create_pool
    运行时引用该模块全局名，进程内 patch 对 API 与 Worker 两个进程均生效）。
    """
    global _keepalive_applied
    if _keepalive_applied:
        return
    import arq.connections as arq_connections

    original_init = arq_connections.ArqRedis.__init__

    def keepalive_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("socket_keepalive", True)
        kwargs.setdefault("health_check_interval", 15)
        original_init(self, *args, **kwargs)

    arq_connections.ArqRedis.__init__ = keepalive_init  # type: ignore[method-assign]
    _keepalive_applied = True
    logger.info("Redis 连接保活已启用（socket_keepalive + health_check_interval=15s）")


async def _get_pool() -> ArqRedis:
    """
    获取（或懒加载创建）ARQ Redis 连接池。

    Returns:
        ArqRedis: ARQ 连接池。

    Raises:
        RuntimeError: REDIS_URL 未配置时抛出，提示部署要求。
    """
    global _arq_pool
    if _arq_pool is None:
        async with _pool_lock:
            if _arq_pool is None:
                if not settings.redis_url:
                    raise RuntimeError(
                        "REDIS_URL 未配置，无法投递后台任务；"
                        "请在 backend/.env 中设置 REDIS_URL，并启动 Worker 进程（python worker.py）"
                    )
                enable_redis_keepalive()
                redis_settings = RedisSettings.from_dsn(settings.redis_url)
                # arq 默认连接超时仅 1 秒，本机环境偶发抖动会不够用，调大到 10 秒
                redis_settings.conn_timeout = 10
                _arq_pool = await create_pool(redis_settings)
    return _arq_pool


async def enqueue_planning_task(plan_id: str, request: dict, user_id: int) -> None:
    """
    投递初始规划任务到队列。

    Args:
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典（保证跨进程序列化）。
        user_id: 用户 ID。
    """
    pool = await _get_pool()
    await pool.enqueue_job("run_planning_task", plan_id, request, user_id)
    logger.info(f"[Queue] 规划任务已入队 plan_id={plan_id} user_id={user_id}")


async def enqueue_revision_task(
    plan_id: str,
    request: dict,
    user_id: int,
    parent_revision_id: int,
    previous_plan: dict,
    revision_notes: str,
    feedback_id: int | None,
    feedback_day_index: int | None,
    feedback_tags: list[str],
    structured_feedback: dict | None = None,
    source: str = "feedback",
) -> None:
    """
    投递行程修订任务到队列。

    Args:
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典。
        user_id: 用户 ID。
        parent_revision_id: 父版本 ID。
        previous_plan: TripPlan.model_dump(mode="json") 的字典（当前生效行程）。
        revision_notes: 聚合后的修改意见文本。
        feedback_id: 单条反馈 ID，聚合反馈（regenerate）时为 None。
        feedback_day_index: 反馈涉及的天序号，可为 None。
        feedback_tags: 反馈标签列表。
        structured_feedback: 预提取的结构化反馈字典，可为 None。
        source: 任务来源标识（feedback/regenerate）。
    """
    pool = await _get_pool()
    await pool.enqueue_job(
        "run_revision_task",
        plan_id,
        request,
        user_id,
        parent_revision_id,
        previous_plan,
        revision_notes,
        feedback_id,
        feedback_day_index,
        feedback_tags,
        structured_feedback,
        source,
    )
    logger.info(f"[Queue] 修订任务已入队 plan_id={plan_id} source={source}")


async def enqueue_recalculate_task(
    plan_id: str,
    request: dict,
    user_id: int,
    parent_revision_id: int,
    previous_plan: dict,
    revision_notes: str,
    day_attractions: list,
) -> None:
    """
    投递行程重算任务到队列（用户手动调整某天景点顺序后触发）。

    Args:
        plan_id: 行程计划 ID。
        request: TripRequest.model_dump(mode="json") 的字典。
        user_id: 用户 ID。
        parent_revision_id: 父版本 ID。
        previous_plan: TripPlan.model_dump(mode="json") 的字典（目标天顺序已重排）。
        revision_notes: 重算说明文本（含用户指定的新顺序）。
        day_attractions: 目标天重排后的景点列表（dict，仅对这些景点算路线矩阵）。
    """
    pool = await _get_pool()
    await pool.enqueue_job(
        "run_recalculate_task",
        plan_id,
        request,
        user_id,
        parent_revision_id,
        previous_plan,
        revision_notes,
        day_attractions,
    )
    logger.info(f"[Queue] 重算任务已入队 plan_id={plan_id}")


async def enqueue_crawler_task(cities: list[str] | None, max_pages: int | None) -> str:
    """
    投递爬虫任务到队列，返回任务 ID 供状态查询。

    Args:
        cities: 目标城市列表，None 表示抓取默认热门城市。
        max_pages: 最大抓取页面数。

    Returns:
        str: arq job ID，可通过 get_job_status 查询执行状态与结果。
    """
    pool = await _get_pool()
    job = await pool.enqueue_job("run_crawler_task", cities, max_pages)
    logger.info(f"[Queue] 爬虫任务已入队 job_id={job.job_id} cities={cities}")
    return job.job_id


async def get_job_status(job_id: str) -> dict[str, Any]:
    """
    查询 arq 任务状态与结果。

    Args:
        job_id: 入队时返回的任务 ID。

    Returns:
        Dict[str, Any]: {job_id, status, result}。status 取值：
        deferred/queued/in_progress/complete/not_found；
        result 仅在 complete 且结果未过期（默认保留 1 小时）时返回。
    """
    pool = await _get_pool()
    job = Job(job_id, pool)
    status = await job.status()
    result: Any = None
    if status == JobStatus.complete:
        try:
            result = await job.result()
        except Exception as exc:
            logger.warning(f"[Queue] 读取任务 {job_id} 结果失败: {exc}")
    return {"job_id": job_id, "status": status.value, "result": result}
