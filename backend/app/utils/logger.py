"""
backend/app/utils/logger.py

loguru 日志配置模块。

作用：
- 统一配置 loguru：控制台彩色输出 + 按天滚动文件日志 + 错误单独归档；
- 提供 setup_logging() 在应用启动时调用一次；
- 通过 InterceptHandler 接管标准 logging（uvicorn/sqlalchemy 等三方库），
  让全项目日志格式统一。

使用方式：
    from app.utils.logger import logger
    logger.info("...")
    logger.exception("...")  # 在 except 块中自动附带堆栈

对应技术：
- loguru：logger.add、logger.remove、opt(depth, exception)
"""

import logging
import sys
from pathlib import Path

from loguru import logger

# 日志目录：backend/logs
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

# 统一输出格式（不含颜色版）
_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)


class InterceptHandler(logging.Handler):
    """
    标准 logging -> loguru 转发处理器。

    让 uvicorn、sqlalchemy 等基于标准 logging 的三方库日志
    也走 loguru 的格式与落盘通道。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """
    初始化日志配置（应用启动时调用一次，幂等）。

    输出通道：
    1. 控制台：INFO 及以上，彩色简洁格式；
    2. backend/logs/app_YYYY-MM-DD.log：全量日志，按天滚动，保留 30 天；
    3. backend/logs/error_YYYY-MM-DD.log：仅 ERROR 及以上，便于排障。

    enqueue=True 保证多线程/协程环境写入安全。
    """
    logger.remove()

    logger.add(
        sys.stdout,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        level="INFO",
    )

    logger.add(
        LOG_DIR / "app_{time:YYYY-MM-DD}.log",
        format=_LOG_FORMAT,
        level="INFO",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )

    logger.add(
        LOG_DIR / "error_{time:YYYY-MM-DD}.log",
        format=_LOG_FORMAT,
        level="ERROR",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )

    # 接管标准 logging，统一三方库日志格式
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 收敛过噪的三方库日志
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # SQLAlchemy echo=True 时自带 stdout 处理器，关闭向 root 传播，
    # 避免 SQL 日志被 loguru 重复输出一份
    logging.getLogger("sqlalchemy.engine").propagate = False

    logger.info("日志系统初始化完成，日志目录：{}", LOG_DIR)
