"""
backend/app/api/routes/messaging.py

用户间私聊路由 + 全局通知 WebSocket。

作用：
- 会话列表（按对端聚合最后一条 + 未读数）、历史消息游标分页、发送、已读置位；
- 红点徽标聚合（聊天未读 + 好友申请待处理 + 互动通知未读）；
- WS /ws/notify：登录后全局长连（只推不收，发送统一走 HTTP 保证事务），
  推送事件：chat（新消息）/ notification（好友与互动通知）。

对应技术：FastAPI WebSocket、JWT query 鉴权（浏览器 WS 无法自定义请求头）。
"""

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.core.utils.security import decode_access_token
from app.models.db_models import ChatMessage, Friendship, Notification, User
from app.services.notification_service import to_dict, unread_count
from app.services.ws_manager import manager

router = APIRouter()


class MessageSendRequest(BaseModel):
    """发送私聊消息请求体。"""

    receiver_id: int = Field(description="接收人用户 ID")
    content: str = Field(min_length=1, max_length=2000, description="消息内容")
    # text=纯文本（含 emoji）/ image|video=媒体 URL / call=通话卡片（content 为 voice|video）
    content_type: str = Field(default="text", description="消息类型：text/image/video/call")


class NotificationReadRequest(BaseModel):
    """通知已读请求体（ids 缺省=全部已读）。"""

    ids: list[int] | None = None


class CallSignalRequest(BaseModel):
    """WebRTC 通话信令中继请求体：signal 原样转发给对端。"""

    to_user_id: int = Field(description="对端用户 ID")
    signal: dict = Field(
        description="信令负载：event=invite/accept/reject/hangup/offer/answer/ice + 各阶段数据",
    )


async def _require_friend(
    session: AsyncSession, me_id: int, peer_id: int
) -> None:
    """校验双方为已同意好友，否则 403（微信式：仅好友可私聊）。"""
    if me_id == peer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能和自己私信")
    result = await session.execute(
        select(Friendship).where(
            Friendship.status == "accepted",
            or_(
                (Friendship.requester_id == me_id) & (Friendship.addressee_id == peer_id),
                (Friendship.requester_id == peer_id) & (Friendship.addressee_id == me_id),
            ),
        )
    )
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅好友之间可以私信")


def _msg_dict(msg: ChatMessage) -> dict[str, Any]:
    """消息记录 -> 展示字典。"""
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "content": msg.content,
        "content_type": msg.content_type,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.get("/conversations", response_model=Any)
async def list_conversations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """会话列表：按对端聚合最后一条消息与未读数（沙箱规模内存聚合）。"""
    me = current_user.id
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(or_(ChatMessage.sender_id == me, ChatMessage.receiver_id == me))
            .order_by(ChatMessage.id.desc())
            .limit(500)
        )
    ).scalars().all()

    peers: dict[int, ChatMessage] = {}
    unread: dict[int, int] = {}
    for msg in rows:
        peer = msg.receiver_id if msg.sender_id == me else msg.sender_id
        peers.setdefault(peer, msg)  # id 倒序，首个即最新
        if msg.receiver_id == me and not msg.is_read:
            unread[peer] = unread.get(peer, 0) + 1

    items = []
    for peer_id, msg in peers.items():
        peer = await session.get(User, peer_id)
        items.append(
            {
                "peer_id": peer_id,
                "peer_name": peer.username if peer else "（已注销）",
                "is_online": manager.is_online(peer_id),
                "last_content": msg.content,
                "last_type": msg.content_type,
                "last_time": msg.created_at.isoformat() if msg.created_at else None,
                "unread": unread.get(peer_id, 0),
            }
        )
    # 先按最后消息时间倒序，再稳定地让有未读的会话置顶
    items.sort(key=lambda c: c["last_time"] or "", reverse=True)
    items.sort(key=lambda c: 0 if c["unread"] else 1)
    return {"success": True, "message": "查询成功", "data": {"conversations": items}}


@router.get("/badge", response_model=Any)
async def get_badge(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """侧边栏红点聚合：聊天未读数 + 待处理好友申请数 + 未读互动通知数。"""
    me = current_user.id
    chat_unread = (
        await session.execute(
            select(func.count()).select_from(ChatMessage).where(
                ChatMessage.receiver_id == me, ChatMessage.is_read.is_(False)
            )
        )
    ).scalar() or 0
    request_count = (
        await session.execute(
            select(func.count()).select_from(Friendship).where(
                Friendship.addressee_id == me,
                Friendship.status == "pending",
            )
        )
    ).scalar() or 0
    notification_unread = await unread_count(session, me)

    return {
        "success": True,
        "message": "查询成功",
        "data": {
            "chat_unread": int(chat_unread),
            "request_count": int(request_count),
            "notification_unread": int(notification_unread),
            "total": int(chat_unread) + int(request_count) + int(notification_unread),
        },
    }


@router.get("/{peer_id}/messages", response_model=Any)
async def list_messages(
    peer_id: int,
    before_id: int | None = Query(default=None, description="游标：取该 ID 之前的更早消息"),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """与某好友的历史消息（游标分页，返回升序列表供聊天窗直接渲染）。"""
    me = current_user.id
    await _require_friend(session, me, peer_id)

    conditions = [
        or_(
            (ChatMessage.sender_id == me) & (ChatMessage.receiver_id == peer_id),
            (ChatMessage.sender_id == peer_id) & (ChatMessage.receiver_id == me),
        )
    ]
    if before_id:
        conditions.append(ChatMessage.id < before_id)
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(*conditions)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    rows = list(reversed(rows))

    # 拉取即置位：对方发给我的未读消息标记已读
    unread_ids = [m.id for m in rows if m.receiver_id == me and not m.is_read]
    if unread_ids:
        for m in rows:
            if m.id in unread_ids:
                m.is_read = True

    return {
        "success": True,
        "message": "查询成功",
        "data": {
            "messages": [_msg_dict(m) for m in rows],
            "has_more": len(rows) == limit,
        },
    }


@router.post("", response_model=Any)
async def send_message(
    request: MessageSendRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """发送私聊消息（仅好友；成功后 WS 实时推送接收方）。"""
    me = current_user.id
    if request.content_type not in {"text", "image", "video", "call"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的消息类型")
    if request.content_type == "call" and request.content not in {"voice", "video"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通话类型无效")
    await _require_friend(session, me, request.receiver_id)

    msg = ChatMessage(
        sender_id=me,
        receiver_id=request.receiver_id,
        content=request.content,
        content_type=request.content_type,
    )
    session.add(msg)
    await session.flush()

    payload = {
        "type": "chat",
        "message": {**_msg_dict(msg), "sender_name": current_user.username},
    }
    sent = await manager.send_to_user(request.receiver_id, payload)
    return {
        "success": True,
        "message": "发送成功",
        "data": {"message": _msg_dict(msg), "delivered_realtime": sent > 0},
    }


@router.get("/notifications", response_model=Any)
async def list_notifications(
    only_unread: bool = Query(default=False, description="仅未读"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """互动通知列表（赞/评/回复/好友事件，联触发者昵称，时间倒序）。"""
    conditions = [Notification.user_id == current_user.id]
    if only_unread:
        conditions.append(Notification.is_read.is_(False))
    total = (
        await session.execute(
            select(func.count()).select_from(Notification).where(*conditions)
        )
    ).scalar() or 0
    rows = (
        await session.execute(
            select(Notification, User.username)
            .join(User, User.id == Notification.actor_id, isouter=True)
            .where(*conditions)
            .order_by(Notification.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return {
        "success": True,
        "message": "查询成功",
        "data": {
            "items": [to_dict(n, username) for n, username in rows],
            "total": int(total),
            "has_more": page * size < total,
        },
    }


@router.post("/notifications/read", response_model=Any)
async def read_notifications(
    payload: NotificationReadRequest | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """标记通知已读：传 ids 按条置位，不传全读（微信式一键清除）。"""
    ids = payload.ids if payload else None
    conditions = [Notification.user_id == current_user.id, Notification.is_read.is_(False)]
    if ids:
        conditions.append(Notification.id.in_(ids))
    result = await session.execute(
        select(Notification).where(*conditions)
    )
    count = 0
    for n in result.scalars().all():
        n.is_read = True
        count += 1
    return {"success": True, "message": "已读", "data": {"marked": count}}


@router.post("/call/signal")
async def relay_call_signal(
    payload: CallSignalRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    通话信令中继：把 WebRTC 信令（邀请/接听/SDP/ICE）经 WS 推给对端。

    复用「只推不收」架构：信令发送走 HTTP 保证顺序与鉴权，
    到达对端靠 WS 实时推送；仅好友之间允许发起。

    Args:
        payload: 对端 ID + 信令负载。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: data.delivered=是否实时送达（0=对方离线）。
    """
    await _require_friend(session, current_user.id, payload.to_user_id)
    sent = await manager.send_to_user(
        payload.to_user_id,
        {
            "type": "call",
            "from": current_user.id,
            "from_name": current_user.username,
            "signal": payload.signal,
        },
    )
    return {
        "success": True,
        "message": "已送达" if sent else "对方当前不在线",
        "data": {"delivered": sent > 0},
    }


@router.websocket("/ws/notify")
async def ws_notify(websocket: WebSocket, token: str = Query(default="")):
    """全局通知长连（浏览器 WS 无法带请求头，token 走 query 参数鉴权）。"""
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except Exception:
        # 未 accept 的连接不能直接 close(自定义码)，先 accept 再以 4401 拒绝
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await manager.connect(user_id, websocket)
    try:
        # 只推不收：循环读取仅为保活与感知断开（客户端可发 ping）
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user_id, websocket)
