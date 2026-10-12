"""
backend/worker.py

ARQ Worker 独立进程入口。

作用：
- 消费 Redis 队列中的规划/修订任务（任务定义见 app/tasks.py）；
- 与 API 进程（run.py）分离部署，实现 Agent 执行与 Web 服务的解耦；
- Agent 执行日志写入 plan_logs 表，由 API 进程的 SSE 接口读取推送。

启动方式（在 backend 目录下）：
    .\\venv\\Scripts\\python.exe worker.py

对应技术：
- arq：基于 Redis 的异步任务队列
"""

from arq import cron, run_worker
from arq.connections import RedisSettings
from loguru import logger

from app.config import settings
from app.db.init_db import init_db
from app.tasks import (
    run_crawler_task,
    run_planning_task,
    run_recalculate_task,
    run_revision_task,
    run_weather_check_task,
)
from app.utils.logger import setup_logging
from app.utils.queue import enable_redis_keepalive

# 进程级 Redis 保活补丁：必须在 arq 建池之前应用（对 run_worker 内部的建池同样生效）
enable_redis_keepalive()


async def startup(ctx: dict) -> None:
    """
    Worker 启动钩子：初始化日志系统与数据库表结构（均为幂等操作），
    并立即执行一次出发前天气检查（与每日 8 点定时任务互补，保证重启不漏检）。

    Args:
        ctx: arq Worker 上下文。
    """
    setup_logging()
    await init_db()
    try:
        await run_weather_check_task(ctx)
    except Exception as exc:
        # 启动期天气检查失败不应阻断 Worker 运行，定时任务会在次日 8 点兜底
        logger.warning(f"启动时天气检查失败（不影响 Worker 运行）: {exc}")


if not settings.redis_url:
    raise RuntimeError("REDIS_URL 未配置，Worker 无法启动；请在 backend/.env 中设置 REDIS_URL")

# arq 默认连接超时仅 1 秒，本机环境偶发抖动会不够用，调大到 10 秒
_redis_settings = RedisSettings.from_dsn(settings.redis_url)
_redis_settings.conn_timeout = 10


class WorkerSettings:
    """
    arq Worker 配置。

    functions：注册的任务函数，与 queue.py 中 enqueue_job 的任务名一一对应；
    cron_jobs：定时任务（每日 8 点执行出发前天气检查）；
    redis_settings：Redis 连接配置，来自 .env 的 REDIS_URL；
    max_jobs：Worker 并发执行的最大任务数；
    job_timeout：单任务超时（规划链路含多次 LLM 调用，耗时较长）；
    health_check_interval：心跳写入间隔。心跳 key 为 arq:queue:health-check
      （queue_name + ':health-check'），外部可用 arq check 命令据此判活；
      arq 默认 3600 秒才写一次，观测性差，这里改为 30 秒。
    """

    functions = [
        run_planning_task,
        run_revision_task,
        run_recalculate_task,
        run_crawler_task,
        run_weather_check_task,
    ]
    cron_jobs = [cron(run_weather_check_task, hour=8, minute=0)]
    redis_settings = _redis_settings
    max_jobs = 4
    job_timeout = 3600
    health_check_interval = 30


if __name__ == "__main__":
    # 兜底自愈：Redis 抖动（如 WSL2 端口转发周期性断连）导致 Worker 退出时，自动重启继续消费
    import time

    while True:
        try:
            run_worker(WorkerSettings)  # type: ignore[arg-type]
            break  # 正常退出（如 Ctrl+C）
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.exception(f"Worker 异常退出，3 秒后自动重启: {exc}")
            time.sleep(3)
