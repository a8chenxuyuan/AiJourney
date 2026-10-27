"""
backend/app/services/ws_manager.py

WebSocket 连接管理器。

作用：
- 维护 user_id -> WebSocket 连接集合，支撑多标签页同账号在线；
- 提供向单个用户推送 JSON 事件的统一入口（不在线静默丢弃，
  前端靠重连后 HTTP 全量对账保证最终一致）。

对应技术：FastAPI WebSocket、asyncio.Lock 保护并发连接表。
"""

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """用户级 WS 连接管理器（只推不收：发送统一走 HTTP 端点）。"""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        """接受连接并登记。"""
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        """移除连接（断开/异常时调用，幂等）。"""
        async with self._lock:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                self._connections.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        """是否在线（存在任一活动连接）。"""
        return bool(self._connections.get(user_id))

    async def send_to_user(self, user_id: int, payload: dict) -> int:
        """向该用户所有连接推送事件，返回成功送达的连接数。"""
        conns = list(self._connections.get(user_id, ()))
        sent = 0
        for ws in conns:
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception:
                await self.disconnect(user_id, ws)
        return sent


# 全局单例：路由模块直接导入使用
manager = ConnectionManager()
