"""
backend/app/api/routes/friends.py

好友关系路由（微信式：申请-验证-同意）。

作用：
- 发起好友申请（附验证消息）、同意/拒绝申请；
- 好友列表（含在线状态）、待处理申请列表；
- 指定用户与当前用户的关系态查询（用户主页按钮态驱动）。

对应技术：FastAPI、SQLAlchemy 异步 ORM、notification_service 联动通知。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.models.db_models import Friendship, User
from app.services.notification_service import push_notification
from app.services.ws_manager import manager

router = APIRouter()


class FriendApplyRequest(BaseModel):
    """好友申请请求体。"""

    user_id: int = Field(description="目标用户 ID")
    verify_message: str = Field(default="", max_length=200, description="验证消息")


def _relation_of(
    other_id: int,
    outgoing: dict[int, Friendship],
    incoming: dict[int, Friendship],
) -> str:
    """由出向/入向关系映射主页按钮态（dict 的 key 均为对方用户 ID）。"""
    if other_id in outgoing:
        rel = outgoing[other_id]
        return "accepted" if rel.status == "accepted" else "pending_out"
    if other_id in incoming:
        rel = incoming[other_id]
        return "accepted" if rel.status == "accepted" else "pending_in"
    return "none"


async def _load_relations(
    session: AsyncSession, me_id: int, other_id: int
) -> tuple[dict[int, Friendship], dict[int, Friendship]]:
    """查询我与对方之间的出向/入向关系（各最多一条，按方向分组）。"""
    result = await session.execute(
        select(Friendship).where(
            or_(
                (Friendship.requester_id == me_id) & (Friendship.addressee_id == other_id),
                (Friendship.requester_id == other_id) & (Friendship.addressee_id == me_id),
            )
        )
    )
    outgoing: dict[int, Friendship] = {}
    incoming: dict[int, Friendship] = {}
    for rel in result.scalars().all():
        if rel.requester_id == me_id:
            outgoing[rel.addressee_id] = rel
        else:
            incoming[rel.requester_id] = rel
    return outgoing, incoming


@router.post("/apply", response_model=Any)
async def apply_friend(
    request: FriendApplyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """发起好友申请（不能加自己；已 pending/accepted 时拒绝重复申请）。"""
    if request.user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能添加自己为好友")
    target = await session.get(User, request.user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    outgoing, incoming = await _load_relations(session, current_user.id, request.user_id)
    if request.user_id in outgoing:
        rel = outgoing[request.user_id]
        if rel.status == "accepted":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="你们已经是好友")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="已发送过申请，等待对方处理"
        )
    if request.user_id in incoming:
        rel = incoming[request.user_id]
        if rel.status == "accepted":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="你们已经是好友")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="对方已向你发送好友申请，请在消息页处理"
        )

    friendship = Friendship(
        requester_id=current_user.id,
        addressee_id=request.user_id,
        verify_message=request.verify_message or f"我是{current_user.username}",
    )
    session.add(friendship)
    await session.flush()

    # 通知接收人（落库 + WS 实时推送）
    await push_notification(
        session,
        request.user_id,
        current_user.id,
        "friend_request",
        {"friendship_id": friendship.id, "verify_message": friendship.verify_message},
    )

    return {"success": True, "message": "好友申请已发送"}


@router.get("/requests", response_model=Any)
async def list_requests(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """我收到的待处理好友申请（新朋友卡列表）。"""
    result = await session.execute(
        select(Friendship, User.username)
        .join(User, User.id == Friendship.requester_id)
        .where(Friendship.addressee_id == current_user.id, Friendship.status == "pending")
        .order_by(Friendship.created_at.desc())
    )
    requests = [
        {
            "friendship_id": rel.id,
            "user_id": rel.requester_id,
            "username": username,
            "verify_message": rel.verify_message,
            "created_at": rel.created_at.isoformat() if rel.created_at else None,
        }
        for rel, username in result.all()
    ]
    return {"success": True, "message": "查询成功", "data": {"requests": requests}}


@router.post("/{friendship_id}/accept", response_model=Any)
async def accept_friend(
    friendship_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """同意好友申请（仅接收人可操作）。"""
    rel = await session.get(Friendship, friendship_id)
    if not rel or rel.addressee_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请不存在")
    if rel.status == "accepted":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该申请已处理")

    rel.status = "accepted"
    rel.accepted_at = rel.accepted_at or rel.created_at
    await session.flush()

    # 通知发起人：申请已通过
    await push_notification(
        session,
        rel.requester_id,
        current_user.id,
        "friend_accepted",
        {"friend_id": current_user.id},
    )

    return {"success": True, "message": "已添加好友"}


@router.post("/{friendship_id}/reject", response_model=Any)
async def reject_friend(
    friendship_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """拒绝好友申请（删行，允许对方日后再次申请）。"""
    rel = await session.get(Friendship, friendship_id)
    if not rel or rel.addressee_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请不存在")
    if rel.status == "accepted":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已是好友，无法拒绝")

    await session.delete(rel)
    return {"success": True, "message": "已拒绝"}


@router.get("", response_model=Any)
async def list_friends(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """好友列表（双向已 accepted，含在线状态与成为好友时间）。"""
    me = current_user.id
    result = await session.execute(
        select(Friendship, User.id, User.username)
        .join(User, User.id == Friendship.requester_id)
        .where(Friendship.addressee_id == me, Friendship.status == "accepted")
        .order_by(Friendship.created_at.desc())
    )
    friends = [
        {
            "user_id": uid,
            "username": username,
            "is_online": manager.is_online(uid),
        }
        for rel, uid, username in result.all()
    ]
    result = await session.execute(
        select(Friendship, User.id, User.username)
        .join(User, User.id == Friendship.addressee_id)
        .where(Friendship.requester_id == me, Friendship.status == "accepted")
        .order_by(Friendship.created_at.desc())
    )
    friends += [
        {
            "user_id": uid,
            "username": username,
            "is_online": manager.is_online(uid),
        }
        for rel, uid, username in result.all()
    ]
    return {"success": True, "message": "查询成功", "data": {"friends": friends}}


@router.get("/status/{user_id}", response_model=Any)
async def friend_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """与指定用户的关系态（用户主页按钮：self/none/pending_out/pending_in/accepted）。"""
    if user_id == current_user.id:
        return {"success": True, "message": "查询成功", "data": {"relation": "self"}}
    outgoing, incoming = await _load_relations(session, current_user.id, user_id)
    relation = _relation_of(user_id, outgoing, incoming)
    rel = outgoing.get(user_id) or incoming.get(user_id)
    return {
        "success": True,
        "message": "查询成功",
        "data": {
            "relation": relation,
            "friendship_id": rel.id if rel else None,
        },
    }
