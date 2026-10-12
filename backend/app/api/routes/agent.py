"""
backend/app/api/routes/agent.py

Agent 执行过程路由模块。

作用：
- 提供 SSE 流式接口，实时推送 LangGraph 各 Agent 节点执行状态；
- 提供人机协同决策接收接口；
- 查询 Agent 执行日志和历史状态。

对应技术：
- FastAPI：APIRouter、StreamingResponse
- LangGraph：Checkpointer、astream_events、interrupt
"""

import asyncio
import json
import time
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.streaming import get_logs_after
from app.api.deps import get_owned_plan, get_owned_plan_for_user
from app.db.session import AsyncSessionLocal, get_db
from app.models.db_models import TripPlanDB, User
from app.models.schemas import HumanDecisionRequest, StandardResponse
from app.utils.security import decode_access_token

router = APIRouter()


# SSE 认证解析器：auto_error=False 表示缺失 Authorization 头时不抛异常，
# 让后续逻辑可以回退到 URL 查询参数的 token
_sse_bearer_scheme = HTTPBearer(auto_error=False)


async def _get_current_user_for_sse(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_sse_bearer_scheme),
    token: Optional[str] = Query(
        None, description="SSE 无法设置请求头时，可通过 URL 查询参数传入 JWT Token"
    ),
    session: AsyncSession = Depends(get_db),
) -> User:
    """
    为 SSE 接口获取当前用户。

    由于浏览器 EventSource 无法自定义 Authorization 请求头，
    允许前端通过 ?token=<jwt> 查询参数传递 Token；
    如果查询参数未提供，则回退到标准 Bearer Token 认证。

    Args:
        request: 当前请求对象。
        credentials: 通过 HTTPBearer 从头信息中获取的凭证（可选）。
        token: URL 查询参数中的 JWT Token（可选）。
        session: 数据库会话。

    Returns:
        User: 当前登录用户对象。

    Raises:
        HTTPException: 认证失败时抛出 401。
    """
    # 优先使用标准 Bearer Token
    raw_token = credentials.credentials if credentials else None

    # 其次尝试从查询参数解析 token
    if not raw_token:
        raw_token = token

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(raw_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 负载无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 用户 ID 格式错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def _get_owned_plan_for_sse(
    plan_id: str,
    current_user: User = Depends(_get_current_user_for_sse),
    session: AsyncSession = Depends(get_db),
) -> TripPlanDB:
    """
    为 SSE 接口校验行程归属权。

    SSE 无法自定义请求头，认证走 _get_current_user_for_sse（支持 ?token= 查询参数）；
    归属校验复用 deps.get_owned_plan_for_user，与普通接口保持同一套逻辑。
    """
    return await get_owned_plan_for_user(plan_id, current_user, session)


@router.get("/trip/{plan_id}/stream")
async def stream_agent_events(plan: TripPlanDB = Depends(_get_owned_plan_for_sse)):
    """
    SSE 流式接口：实时推送 Agent 执行过程。

    前端连接后，后端会逐步推送每个 Agent 节点的执行事件，
    包括节点名称、工具调用、输入输出摘要等。

    Args:
        plan: 归属校验通过的行程计划（SSE 认证 + 归属校验依赖注入）。

    Returns:
        StreamingResponse: text/event-stream 格式的流式响应。
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        """
        生成真实 SSE 事件。

        Agent 执行日志由 Worker 进程写入 plan_logs 表（跨进程可见），
        这里按日志 ID 递增轮询数据库，增量推送给前端；
        收到结束标记或任务状态变为 completed/failed 时发送最终事件并断开。
        """
        # 如果任务已经完成或失败，直接发送结束标记，不再等待
        if plan.status in ("completed", "failed"):
            final_status = "completed" if plan.status == "completed" else "failed"
            yield f"data: {json.dumps({'status': final_status}, ensure_ascii=False)}\n\n"
            return

        last_log_id = 0  # 增量轮询游标：已推送的最大日志 ID
        last_event_at = time.monotonic()  # 上次向前端发送事件的时间（心跳计时）
        last_status_check = time.monotonic()  # 上次兜底检查 plan 状态的时间

        while True:
            # 增量拉取新日志（首次轮询会取到全部历史日志，页面刷新重连时有用）
            log_rows = await get_logs_after(plan.id, last_log_id)
            for row in log_rows:
                log = row.log_json or {}
                # 收到结束标记：发送最终状态并结束推送
                if log.get("done"):
                    yield f"data: {json.dumps({'status': log.get('status', 'completed')}, ensure_ascii=False)}\n\n"
                    return
                last_log_id = row.id
                data = json.dumps(log, ensure_ascii=False)
                yield f"data: {data}\n\n"
                last_event_at = time.monotonic()

            now = time.monotonic()

            # 兜底：定期检查 plan 状态，防止结束标记写入失败导致 SSE 永久轮询
            if now - last_status_check >= 10.0:
                async with AsyncSessionLocal() as session:
                    fresh_plan = await session.get(TripPlanDB, plan.id)
                if fresh_plan and fresh_plan.status in ("completed", "failed"):
                    yield f"data: {json.dumps({'status': fresh_plan.status}, ensure_ascii=False)}\n\n"
                    return
                last_status_check = now

            # 超过 30 秒没有新日志时发送一次心跳，保持 SSE 连接
            if now - last_event_at >= 30.0:
                yield f"data: {json.dumps({'status': 'waiting', 'agent_name': 'System', 'step': 'heartbeat'}, ensure_ascii=False)}\n\n"
                last_event_at = now

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/trip/{plan_id}/human_decision", response_model=StandardResponse)
async def submit_human_decision(
    decision: HumanDecisionRequest, plan: TripPlanDB = Depends(get_owned_plan)
):
    """
    提交人机协同节点的用户决策。

    当前端收到 human_interrupt 事件并展示弹窗后，
    用户选择结果通过此接口提交，后端恢复 LangGraph 执行。

    Args:
        decision: 用户决策内容。
        plan: 归属校验通过的行程计划（get_owned_plan 依赖注入）。

    Returns:
        StandardResponse: 决策提交结果。
    """
    # TODO: 将决策写入 LangGraph State，恢复图执行
    return StandardResponse(
        success=True,
        message="决策已提交",
        data={"plan_id": plan.id, "decision": decision.model_dump()},
    )
