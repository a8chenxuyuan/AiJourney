"""
backend/app/api/main.py

FastAPI 应用入口模块。

作用：
- 创建 FastAPI 应用实例；
- 注册所有路由（auth、user、trip、agent、map 等）；
- 配置 CORS、全局异常处理、启动/关闭事件；
- 启动时自动初始化数据库表（开发模式）。

对应技术：
- FastAPI：FastAPI、APIRouter、CORSMiddleware
- SQLAlchemy：异步数据库初始化
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.init_db import init_db
from app.utils.logger import setup_logging
from app.api.routes import auth, user, trip, agent, map, poi, rag, memory, crawler, payment, collab


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理函数。

    在应用启动时执行日志初始化与数据库初始化，在关闭时释放资源。

    Args:
        app: FastAPI 应用实例。
    """
    # 启动阶段：初始化日志系统（后续所有日志走 loguru）
    setup_logging()
    # 启动阶段：初始化数据库表
    await init_db()
    yield
    # 关闭阶段：可在此释放连接池、停止调度器等


# 创建 FastAPI 应用实例
app = FastAPI(
    title=settings.app_name,
    description="基于 LangGraph + MCP 的智能多智能体旅行规划助手",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan
)

# 配置跨域资源共享（CORS）
# 允许前端开发服务器访问后端 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# 注册 API 路由
# 所有接口统一以 /api 为前缀
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(user.router, prefix="/api/users", tags=["用户"])
# 协作路由必须先于 trip 路由挂载：固定路径 /api/trip/collab/join/{token}
# 要先于 trip 的 /{plan_id} 动态路由匹配，避免被误解析为 plan_id
app.include_router(collab.router, prefix="/api/trip", tags=["行程协作"])
app.include_router(trip.router, prefix="/api/trip", tags=["旅行规划"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(map.router, prefix="/api/map", tags=["地图"])
app.include_router(poi.router, prefix="/api/poi", tags=["POI"])
app.include_router(rag.router, prefix="/api/rag", tags=["知识库"])
app.include_router(memory.router, prefix="/api/memory", tags=["记忆"])
app.include_router(crawler.router, prefix="/api/crawler", tags=["爬虫"])
app.include_router(payment.router, prefix="/api/payment", tags=["支付"])


@app.get("/api/health", tags=["健康检查"])
async def health_check():
    """
    健康检查接口。

    用于确认后端服务是否正常运行。

    Returns:
        dict: 包含状态信息的字典。
    """
    return {"status": "ok", "app": settings.app_name}
