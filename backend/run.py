"""
backend/run.py

后端应用启动入口。

作用：
- 导入 FastAPI 应用实例；
- 使用 Uvicorn 启动 ASGI 服务器；
- 支持本地开发直接运行：python run.py

对应技术：
- Uvicorn：ASGI 服务器
"""

import uvicorn

from app.core.config import settings


def main() -> None:
    """
    主启动函数。

    使用 uvicorn.run 启动 FastAPI 应用：
    - app: 对应 app.api.main:app
    - host: 默认 0.0.0.0，允许局域网访问
    - port: 从 settings.port 读取，默认 8000
    - reload: 开发模式下开启热重载（注意：热重载会中断后台任务）
    """
    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,  # 关闭热重载，避免中断后台 Agent 任务
    )


if __name__ == "__main__":
    main()
