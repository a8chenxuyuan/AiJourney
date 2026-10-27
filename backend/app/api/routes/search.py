"""全站搜索：社区帖子 + 公开游记 + 爬虫攻略 + 用户 四源统一检索。

免登录可搜公开内容；结果带 result_type 供前端分类渲染与跳转。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.models.db_models import CommunityPost, CrawledDocument, TripJournal, TripPlanDB, User
from app.models.schemas import StandardResponse

router = APIRouter()

EXCERPT_LEN = 120


def _excerpt(text: str | None, limit: int = EXCERPT_LEN) -> str:
    """截断摘要，统一空白。"""
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _journal_first(sections: list[dict] | None) -> tuple[str | None, str]:
    """从游记分节结构取（首图, 首段文字）。"""
    for sec in sections or []:
        photos = sec.get("photos") or []
        text = (sec.get("text") or "").strip()
        if text or photos:
            return (photos[0] if photos else None), text
    return None, ""


@router.get("/search", response_model=StandardResponse)
async def global_search(
    q: str = Query(min_length=1, max_length=50, description="搜索关键词"),
    limit: int = Query(default=30, ge=1, le=50, description="每源结果上限"),
    session: AsyncSession = Depends(get_db),
):
    """
    全站搜索：按关键词并行检索四类公开内容，合并返回。

    - post：社区帖子（旅行圈/笔记，仅 published）
    - journal：公开游记（联行程拿城市/天数，跳公开分享页）
    - guide：爬虫攻略文档
    - user：用户（按用户名匹配，跳用户主页）
    """
    kw = f"%{q.strip()}%"
    items: list[dict] = []
    counts = {"post": 0, "journal": 0, "guide": 0, "user": 0}

    # 1) 社区帖子（标题/摘要匹配，按点赞排序）
    post_rows = (
        await session.execute(
            select(CommunityPost, User.username)
            .join(User, User.id == CommunityPost.user_id)
            .where(
                CommunityPost.status == "published",
                or_(CommunityPost.title.like(kw), CommunityPost.summary.like(kw)),
            )
            .order_by(CommunityPost.like_count.desc())
            .limit(limit)
        )
    ).all()
    for p, author in post_rows:
        counts["post"] += 1
        items.append(
            {
                "result_type": "post",
                "id": p.id,
                "title": p.title,
                "excerpt": _excerpt(p.summary),
                "cover_url": p.cover_url,
                "author": author,
                "user_id": p.user_id,
                "like_count": p.like_count,
                "comment_count": p.comment_count,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )

    # 2) 公开游记（标题或城市匹配）
    journal_rows = (
        await session.execute(
            select(TripJournal, TripPlanDB, User.username)
            .join(TripPlanDB, TripPlanDB.id == TripJournal.plan_id)
            .join(User, User.id == TripJournal.user_id)
            .where(
                TripJournal.is_public.is_(True),
                TripJournal.status == "done",
                or_(TripJournal.title.like(kw), TripPlanDB.city.like(kw)),
            )
            .order_by(TripJournal.created_at.desc())
            .limit(limit)
        )
    ).all()
    for j, plan, author in journal_rows:
        counts["journal"] += 1
        cover, text = _journal_first(j.content)
        items.append(
            {
                "result_type": "journal",
                "id": j.id,
                "public_token": j.public_token,
                "title": j.title or f"{plan.city}游记",
                "excerpt": _excerpt(text),
                "cover_url": cover,
                "city": plan.city,
                "travel_days": plan.travel_days,
                "author": author,
                "user_id": j.user_id,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
        )

    # 3) 爬虫攻略（标题/正文匹配）
    guide_rows = (
        (
            await session.execute(
                select(CrawledDocument)
                .where(
                    or_(CrawledDocument.title.like(kw), CrawledDocument.content.like(kw))
                )
                .order_by(CrawledDocument.crawled_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for doc in guide_rows:
        counts["guide"] += 1
        items.append(
            {
                "result_type": "guide",
                "id": doc.id,
                "title": doc.title,
                "excerpt": _excerpt(doc.content),
                "city": doc.city,
                "source": doc.source_type,
                "created_at": doc.crawled_at.isoformat() if doc.crawled_at else None,
            }
        )

    # 4) 用户（用户名匹配，排除封禁号）
    user_rows = (
        (
            await session.execute(
                select(User)
                .where(User.username.like(kw), User.is_banned.is_(False))
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    for u in user_rows:
        counts["user"] += 1
        items.append(
            {
                "result_type": "user",
                "id": u.id,
                "title": u.username,
                "excerpt": "查看 TA 的旅行圈与游记",
            }
        )

    # 用户结果置顶（找人意图最明确），其余按 帖子 → 游记 → 攻略
    items.sort(key=lambda it: {"user": 0, "post": 1, "journal": 2, "guide": 3}[it["result_type"]])

    return StandardResponse(
        success=True,
        message="获取成功",
        data={"q": q, "total": len(items), "counts": counts, "items": items},
    )
