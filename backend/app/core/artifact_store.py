"""
backend/app/core/artifact_store.py

core（基建层）：工具全量结果落盘。

作用：
- M1 上下文瘦身：收集节点的全量工具结果写入 Redis（key=artifact:{plan_id}:{kind}，
  TTL 7 天），执行状态 state 只保留评分加权精选的 top-N；
- 保存成功返回 artifact key，失败返回 None——落盘是尽力而为，
  Redis 不可用时节点行为退化为"不落盘、state 保留现有列表"，主流程不受影响。

对应技术：
- redis.asyncio：异步 Redis 客户端（懒加载单例）
"""

import json
from typing import Any

from loguru import logger

from app.core.config import settings

# 全量结果保留 7 天：覆盖一次规划可能的多次修订/重跑周期
ARTIFACT_TTL_SECONDS = 7 * 24 * 3600

# 懒加载的 Redis 客户端；False 是"已尝试但不可用"的哨兵，避免每次请求都重连
_redis: Any | None | bool = None


async def _get_redis() -> Any | None:
    """获取 Redis 客户端；未配置或连接失败时返回 None（降级模式）。"""
    global _redis
    if _redis is False:
        return None
    if _redis is None:
        if not settings.redis_url:
            logger.info("[artifact_store] 未配置 redis_url，artifact 落盘关闭")
            _redis = False
            return None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _redis = client
        except Exception as exc:
            logger.warning(f"[artifact_store] Redis 连接失败，artifact 落盘降级关闭: {exc}")
            _redis = False
            return None
    return _redis


def artifact_key(plan_id: str, kind: str) -> str:
    """构造 artifact key；kind 建议形如 attractions:{city}，多城场景天然隔离。"""
    return f"artifact:{plan_id}:{kind}"


async def save_artifact(plan_id: str, kind: str, data: Any) -> str | None:
    """全量结果写入 Redis，返回 artifact key；失败返回 None。"""
    redis = await _get_redis()
    if redis is None:
        return None
    key = artifact_key(plan_id, kind)
    try:
        await redis.set(
            key, json.dumps(data, ensure_ascii=False, default=str), ex=ARTIFACT_TTL_SECONDS
        )
        return key
    except Exception as exc:
        logger.warning(f"[artifact_store] 写入失败 {key}: {exc}")
        return None


async def load_artifact(plan_id: str, kind: str) -> Any | None:
    """按 kind 读取全量结果；不存在或 Redis 不可用时返回 None。"""
    redis = await _get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(artifact_key(plan_id, kind))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning(f"[artifact_store] 读取失败 {kind}: {exc}")
        return None
