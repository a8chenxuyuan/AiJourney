"""
backend/app/api/routes/profiles.py

用户主页路由（只读聚合）。

作用：
- 用户资料卡：基本信息 + 统计（旅行圈动态/获赞/公开游记/好友数）+ 与当前用户的关系态；
- TA 的旅行圈：TA 发布的社区动态（晒图 + 笔记，仅 published）；
- TA 的游记：TA 设为公开的行程游记（封面从分节内容首图推导）。

对应技术：FastAPI、SQLAlchemy 异步聚合查询。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.friends import _load_relations, _relation_of
from app.core.db.session import get_db
from app.models.db_models import CommunityPost, Friendship, TripJournal, User

router = APIRouter()


@router.get("/creators", response_model=Any)
async def list_creators(session: AsyncSession = Depends(get_db)):
    """
    同路人达人榜：按获赞总数、发帖数排序的活跃创作者（免登录可看）。

    口径：已发布帖子数、帖子获赞合计（like_count 冗余字段求和）、公开游记数；
    附最近 3 张已发布帖子封面，供前端达人卡展示内容质感。
    """
    rows = (
        await session.execute(
            select(
                User.id,
                User.username,
                User.created_at,
                func.count(CommunityPost.id).label("posts_count"),
                func.coalesce(func.sum(CommunityPost.like_count), 0).label("likes_total"),
            )
            .join(
                CommunityPost,
                (CommunityPost.user_id == User.id) & (CommunityPost.status == "published"),
            )
            .where(User.is_banned.is_(False))
            .group_by(User.id)
            .order_by(
                func.sum(CommunityPost.like_count).desc(), func.count(CommunityPost.id).desc()
            )
            .limit(24)
        )
    ).all()

    if not rows:
        return {"success": True, "message": "查询成功", "data": {"items": []}}

    uid_list = [r.id for r in rows]

    # 每人最近 3 张已发布帖子封面（按发布时间倒序回填）
    cover_rows = (
        await session.execute(
            select(CommunityPost.user_id, CommunityPost.cover_url)
            .where(
                CommunityPost.user_id.in_(uid_list),
                CommunityPost.status == "published",
                CommunityPost.cover_url.isnot(None),
            )
            .order_by(CommunityPost.created_at.desc())
            .limit(200)
        )
    ).all()
    covers_by_user: dict[int, list[str]] = {}
    for uid, cover in cover_rows:
        if cover and len(covers_by_user.setdefault(uid, [])) < 3:
            covers_by_user[uid].append(cover)

    # 公开游记数
    journal_rows = (
        await session.execute(
            select(TripJournal.user_id, func.count(TripJournal.id))
            .where(
                TripJournal.user_id.in_(uid_list),
                TripJournal.is_public.is_(True),
                TripJournal.status == "done",
            )
            .group_by(TripJournal.user_id)
        )
    ).all()
    journals_by_user = dict(journal_rows)

    items = [
        {
            "user_id": r.id,
            "username": r.username,
            "posts_count": int(r.posts_count),
            "likes_total": int(r.likes_total),
            "journals_count": int(journals_by_user.get(r.id, 0)),
            "joined_at": r.created_at.isoformat() if r.created_at else None,
            "covers": covers_by_user.get(r.id, []),
        }
        for r in rows
    ]
    return {"success": True, "message": "查询成功", "data": {"items": items}}


@router.get("/{user_id}/profile", response_model=Any)
async def get_profile(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """用户资料卡：基本信息 + 统计 + 关系态（self/none/pending_out/pending_in/accepted）。"""
    target = await session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    posts_count = (
        await session.execute(
            select(func.count()).select_from(CommunityPost).where(
                CommunityPost.user_id == user_id, CommunityPost.status == "published"
            )
        )
    ).scalar() or 0
    likes_received = (
        await session.execute(
            select(func.coalesce(func.sum(CommunityPost.like_count), 0)).where(
                CommunityPost.user_id == user_id, CommunityPost.status == "published"
            )
        )
    ).scalar() or 0
    journals_count = (
        await session.execute(
            select(func.count()).select_from(TripJournal).where(
                TripJournal.user_id == user_id, TripJournal.is_public.is_(True)
            )
        )
    ).scalar() or 0
    friends_count = (
        await session.execute(
            select(func.count()).select_from(Friendship).where(
                Friendship.status == "accepted",
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id,
                ),
            )
        )
    ).scalar() or 0
    # 发帖分区细分（旅行圈/笔记），可视化与个人中心统计条用
    zone_counts = dict(
        (
            await session.execute(
                select(CommunityPost.zone, func.count()).where(
                    CommunityPost.user_id == user_id, CommunityPost.status == "published"
                ).group_by(CommunityPost.zone)
            )
        ).all()
    )

    relation = "none"
    friendship_id = None
    if user_id == current_user.id:
        relation = "self"
    else:
        outgoing, incoming = await _load_relations(session, current_user.id, user_id)
        relation = _relation_of(user_id, outgoing, incoming)
        rel = outgoing.get(user_id) or incoming.get(user_id)
        friendship_id = rel.id if rel else None

    return {
        "success": True,
        "message": "查询成功",
        "data": {
            "user_id": target.id,
            "username": target.username,
            "created_at": target.created_at.isoformat() if target.created_at else None,
            "stats": {
                "posts_count": int(posts_count),
                "posts_circle": int(zone_counts.get("circle", 0)),
                "posts_note": int(zone_counts.get("note", 0)),
                "likes_received": int(likes_received),
                "journals_count": int(journals_count),
                "friends_count": int(friends_count),
            },
            "relation": relation,
            "friendship_id": friendship_id,
        },
    }


@router.get("/{user_id}/posts", response_model=Any)
async def list_user_posts(
    user_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """TA 的旅行圈：TA 发布的社区动态（含晒图与笔记两种 zone）。

    本人查看返回全部状态（含被下架帖，前端打「已下架」标签）；他人仅可见已发布。
    """
    is_self = user_id == current_user.id
    stmt = select(CommunityPost).where(CommunityPost.user_id == user_id)
    if not is_self:
        stmt = stmt.where(CommunityPost.status == "published")
    stmt = stmt.order_by(CommunityPost.created_at.desc())
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0
    rows = (
        await session.execute(stmt.offset((page - 1) * size).limit(size))
    ).scalars().all()

    items = [
        {
            "id": p.id,
            "zone": p.zone,
            "title": p.title,
            "summary": p.summary,
            "cover_url": p.cover_url,
            "status": p.status,
            "like_count": p.like_count,
            "comment_count": p.comment_count,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]
    return {
        "success": True,
        "message": "查询成功",
        "data": {"items": items, "total": int(total), "has_more": page * size < total},
    }


@router.get("/{user_id}/journals", response_model=Any)
async def list_user_journals(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """TA 的游记：TA 设为公开的行程游记（封面取分节内容首图）。"""
    rows = (
        await session.execute(
            select(TripJournal)
            .where(TripJournal.user_id == user_id, TripJournal.is_public.is_(True))
            .order_by(TripJournal.created_at.desc())
        )
    ).scalars().all()

    items = []
    for j in rows:
        cover = None
        for section in j.content or []:
            if section.get("photos"):
                cover = section["photos"][0]
                break
        items.append(
            {
                "id": j.id,
                "title": j.title or "（未命名游记）",
                "cover_url": cover,
                "travel_days": len(j.content or []) or None,
                "public_token": j.public_token,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
        )
    return {"success": True, "message": "查询成功", "data": {"items": items}}
