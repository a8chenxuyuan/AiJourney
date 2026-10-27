"""社区路由：发帖（游记转发/手动图文/纯路线）、广场 feed、帖子详情、点赞、评论、照着走。

帖子内容发布时全量拷贝（游记 sections / 行程 plan_data），后续原游记或行程
被删仅置空回链，帖子本身不受影响。冗余计数用原子 UPDATE 增减，feed 分页零 JOIN。
"""

import copy
import uuid
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.models.db_models import (
    CommunityPost,
    PlanCollaborator,
    PostComment,
    PostLike,
    TripJournal,
    TripPlanDB,
    User,
)
from app.models.schemas import (
    CommentCreateRequest,
    FeedOut,
    PostCreateRequest,
    StandardResponse,
)
from app.services.notification_service import push_notification

router = APIRouter()

# 热门权重：like 3 分 / comment 2 分 / view 0.1 分（阶段 B 再做时间衰减）
HOT_SCORE = (
    CommunityPost.like_count * 3
    + CommunityPost.comment_count * 2
    + CommunityPost.view_count * 0.1
)


def _shift_dates(plan_dict: dict, delta_days: int) -> None:
    """将行程整体日期向后平移 delta_days 天（原地修改，delta_days<=0 不动）。

    所有日期均为 YYYY-MM-DD 字符串，必须经 date 解析后再平移，不能字符串拼接
    （跨月/跨年会出错）。plan_data.day_plans[].date 与 request_data 的起止日期同步平移，
    保证后续 feedback/regenerate 链路日期一致。

    Args:
        plan_dict: 含 start_date / end_date / plan_data / request_data 的行程 dict。
        delta_days: 平移天数。
    """
    if delta_days <= 0:
        return

    def _shift(s: str) -> str:
        return (date.fromisoformat(s) + timedelta(days=delta_days)).isoformat()

    plan_dict["start_date"] = _shift(plan_dict["start_date"])
    plan_dict["end_date"] = _shift(plan_dict["end_date"])
    for day in (plan_dict.get("plan_data") or {}).get("day_plans") or []:
        if day.get("date"):
            day["date"] = _shift(day["date"])
    request_data = plan_dict.get("request_data")
    if isinstance(request_data, dict):
        for key in ("start_date", "end_date"):
            if request_data.get(key):
                request_data[key] = _shift(request_data[key])


def _build_summary(sections: list[dict] | None) -> str:
    """拼接分节正文生成 feed 摘要：去换行、去首尾空白、截前 80 字。"""
    if not sections:
        return ""
    text = "".join(s.get("text") or "" for s in sections)
    return text.replace("\r", "").replace("\n", "").strip()[:80]


def _full_text(sections: list[dict] | None) -> str:
    """拼接分节正文全文（不截断），供旅行圈 MomentCard 展开全文。"""
    return "".join(s.get("text") or "" for s in sections or []).strip()


def _collect_photos(sections: list[dict] | None) -> list[str]:
    """从分节内容收集照片 URL（去重保序），供旅行圈 MomentCard 九宫格渲染。"""
    seen: dict[str, None] = {}
    for section in sections or []:
        for p in section.get("photos") or []:
            if p and p not in seen:
                seen[p] = None
    return list(seen)


def _post_out(post: CommunityPost, author: str) -> dict:
    """帖子行 → feed 卡片 dict（不含 content JSON，照片单独提平）。"""
    return {
        "id": post.id,
        "user_id": post.user_id,
        "author": author,
        "post_type": post.post_type,
        "zone": post.zone or "note",
        "title": post.title,
        "summary": post.summary,
        "text": _full_text(post.content),
        "cover_url": post.cover_url,
        "photos": _collect_photos(post.content),
        "tags": post.tags or [],
        "plan_id": post.plan_id,
        "like_count": post.like_count,
        "comment_count": post.comment_count,
        "view_count": post.view_count,
        "created_at": post.created_at,
    }


async def _get_published_post(post_id: str, session: AsyncSession) -> CommunityPost:
    """按 ID 取已发布帖子，不存在或已隐藏统一 404。"""
    post = await session.get(CommunityPost, post_id)
    if not post or post.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="帖子不存在")
    return post


async def _validate_link_plan(
    plan_id: str, current_user: User, session: AsyncSession
) -> TripPlanDB:
    """校验帖子关联行程：存在、completed，且属当前用户或其为协作者（防挂别人行程）。"""
    plan = await session.get(TripPlanDB, plan_id)
    if not plan or plan.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="关联行程不存在或尚未完成"
        )
    if plan.user_id != current_user.id:
        collab = await session.execute(
            select(PlanCollaborator).where(
                PlanCollaborator.plan_id == plan_id, PlanCollaborator.user_id == current_user.id
            )
        )
        if collab.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="无权关联该行程"
            )
    return plan


@router.post("/posts", response_model=StandardResponse)
async def create_post(
    payload: PostCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    发布帖子，一个接口兼容三种来源：

    - journal_id 有值：游记转发（校验游记存在且属当前用户、status=done），
      sections/cover_url/plan_id 缺省从游记取，同步置游记 is_public=True；
    - text/sections 有值：manual 手动图文（text 包装为单 section）；
    - 仅 plan_id：route 纯路线帖。
    """
    sections = [s.model_dump() for s in payload.sections] if payload.sections else None
    cover_url = payload.cover_url
    plan_id = payload.plan_id
    journal = None

    if payload.journal_id:
        journal = await session.get(TripJournal, payload.journal_id)
        if not journal or journal.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游记不存在")
        if journal.status != "done":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="游记尚未生成完成，无法转发"
            )
        post_type = "journal"
        if sections is None:
            sections = copy.deepcopy(journal.content) if journal.content else []
        if not cover_url:
            cover_url = next(
                (p for s in (journal.content or []) for p in (s.get("photos") or [])), None
            )
        plan_id = plan_id or journal.plan_id
    elif sections or payload.text:
        post_type = "manual"
    else:
        post_type = "route"

    if payload.text and not sections:
        sections = [
            {"day_index": None, "title": payload.title, "text": payload.text, "photos": []}
        ]

    if plan_id:
        await _validate_link_plan(plan_id, current_user, session)

    post = CommunityPost(
        id=f"CP_{uuid.uuid4().hex}",
        user_id=current_user.id,
        plan_id=plan_id,
        journal_id=payload.journal_id,
        post_type=post_type,
        zone=payload.zone,
        title=payload.title,
        summary=_build_summary(sections),
        content=sections,
        cover_url=cover_url,
        tags=payload.tags or None,
        status="published",
    )
    if journal is not None:
        journal.is_public = True
    session.add(post)
    await session.commit()
    await session.refresh(post)
    logger.info(
        f"[Community] 用户 {current_user.id} 发布{post_type}帖 {post.id}（plan={plan_id}）"
    )
    return StandardResponse(
        success=True, message="发布成功", data=_post_out(post, current_user.username)
    )


@router.get("/feed", response_model=StandardResponse)
async def get_feed(
    sort: str = Query(default="latest", pattern="^(latest|hot)$", description="排序方式"),
    zone: str | None = Query(
        default=None, pattern="^(circle|note)$", description="分区过滤（不传=全部）"
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """广场 feed：只返回 published 帖子，latest 按时间倒序，hot 按加权热度倒序。

    zone 可选过滤分区（circle/note），不传返回全部分区，旧调用兼容。
    """
    published = CommunityPost.status == "published"
    if zone:
        published = published & (CommunityPost.zone == zone)
    total = (
        await session.execute(select(func.count()).select_from(CommunityPost).where(published))
    ).scalar_one()
    order = (
        [HOT_SCORE.desc(), CommunityPost.created_at.desc()]
        if sort == "hot"
        else [CommunityPost.created_at.desc()]
    )
    rows = await session.execute(
        select(CommunityPost, User.username)
        .join(User, User.id == CommunityPost.user_id)
        .where(published)
        .order_by(*order)
        .offset((page - 1) * size)
        .limit(size)
    )
    data = FeedOut(
        posts=[_post_out(p, name) for p, name in rows.all()],
        total=total,
        page=page,
        size=size,
        has_more=page * size < total,
    )
    return StandardResponse(success=True, message="获取成功", data=data.model_dump())


@router.get("/posts/{post_id}", response_model=StandardResponse)
async def get_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """帖子详情：浏览数 +1，附带 liked（当前用户是否已赞）与作者昵称。"""
    post = await _get_published_post(post_id, session)
    author = (await session.get(User, post.user_id)).username
    liked = (
        await session.execute(
            select(PostLike.id).where(
                PostLike.post_id == post_id, PostLike.user_id == current_user.id
            )
        )
    ).scalar_one_or_none() is not None
    post.view_count += 1
    await session.commit()
    data = _post_out(post, author)
    data["sections"] = post.content or []
    data["liked"] = liked
    return StandardResponse(success=True, message="获取成功", data=data)


@router.delete("/posts/{post_id}", response_model=StandardResponse)
async def delete_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """删除帖子（仅作者本人，非作者 403），同步删除点赞与评论行。"""
    post = await _get_published_post(post_id, session)
    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅作者可以删除帖子"
        )
    await session.execute(delete(PostComment).where(PostComment.post_id == post_id))
    await session.execute(delete(PostLike).where(PostLike.post_id == post_id))
    await session.delete(post)
    await session.commit()
    logger.info(f"[Community] 帖子 {post_id} 已被作者 {current_user.id} 删除")
    return StandardResponse(success=True, message="帖子已删除", data={"post_id": post_id})


@router.post("/posts/{post_id}/like", response_model=StandardResponse)
async def like_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """点赞：uq_post_like 唯一约束防重复，冲突即幂等返回；计数原子 +1。"""
    post = await _get_published_post(post_id, session)
    liked_new = True
    try:
        session.add(PostLike(post_id=post_id, user_id=current_user.id))
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == post_id)
            .values(like_count=CommunityPost.like_count + 1)
        )
        await session.commit()
    except IntegrityError:
        # 重复点赞：唯一约束冲突，回滚后幂等返回
        await session.rollback()
        liked_new = False
    # 回读真实计数：重复点赞场景 update 已回滚，不能用加载值自增
    await session.refresh(post)
    # 新点赞且非自赞：通知作者（flush 即可，请求结束 get_db 自动 commit）
    if liked_new and post.user_id != current_user.id:
        await push_notification(
            session,
            post.user_id,
            current_user.id,
            "like",
            {"post_id": post_id, "post_title": (post.title or "")[:30]},
        )
    return StandardResponse(
        success=True, message="已点赞", data={"liked": True, "like_count": post.like_count}
    )


@router.delete("/posts/{post_id}/like", response_model=StandardResponse)
async def unlike_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """取消点赞：无记录幂等返回；计数原子 -1 且下限 0。"""
    post = await _get_published_post(post_id, session)
    result = await session.execute(
        delete(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == current_user.id)
    )
    if result.rowcount:
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == post_id, CommunityPost.like_count > 0)
            .values(like_count=CommunityPost.like_count - 1)
        )
        await session.commit()
    await session.refresh(post)
    return StandardResponse(
        success=True, message="已取消点赞", data={"liked": False, "like_count": post.like_count}
    )


@router.get("/posts/{post_id}/comments", response_model=StandardResponse)
async def get_comments(
    post_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """评论列表：一次全拉，按 parent_id 分两层（顶级评论 + replies 楼中楼）。"""
    await _get_published_post(post_id, session)
    rows = (
        await session.execute(
            select(PostComment, User.username)
            .join(User, User.id == PostComment.user_id)
            .where(PostComment.post_id == post_id)
            .order_by(PostComment.created_at)
        )
    ).all()

    def _comment_out(comment: PostComment, username: str) -> dict:
        return {
            "id": comment.id,
            "user_id": comment.user_id,
            "author": username,
            "content": comment.content,
            "created_at": comment.created_at,
            "replies": [],
        }

    replies_by_parent: dict[str, list[dict]] = defaultdict(list)
    top_level: list[dict] = []
    for comment, username in rows:
        item = _comment_out(comment, username)
        if comment.parent_id:
            replies_by_parent[comment.parent_id].append(item)
        else:
            top_level.append(item)
    for top in top_level:
        top["replies"] = replies_by_parent.get(top["id"], [])
    return StandardResponse(success=True, message="获取成功", data={"comments": top_level})


@router.post("/posts/{post_id}/comments", response_model=StandardResponse)
async def create_comment(
    post_id: str,
    payload: CommentCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """发评论：parent 必须是本帖顶级评论（仅二级，不做无限嵌套）；计数原子 +1。"""
    post = await _get_published_post(post_id, session)
    parent = None
    if payload.parent_id:
        parent = await session.get(PostComment, payload.parent_id)
        if not parent or parent.post_id != post_id or parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="回复目标无效（仅支持回复顶级评论）",
            )
    comment = PostComment(
        id=f"CM_{uuid.uuid4().hex}",
        post_id=post_id,
        user_id=current_user.id,
        parent_id=payload.parent_id,
        content=payload.content,
    )
    session.add(comment)
    await session.execute(
        update(CommunityPost)
        .where(CommunityPost.id == post_id)
        .values(comment_count=CommunityPost.comment_count + 1)
    )
    await session.commit()
    # 通知：评论通知帖作者；回复另通知被回复人（都排除自己触发）
    excerpt = payload.content[:30]
    if post.user_id != current_user.id:
        await push_notification(
            session,
            post.user_id,
            current_user.id,
            "comment",
            {"post_id": post_id, "post_title": (post.title or "")[:30], "excerpt": excerpt},
        )
    if parent and parent.user_id not in (current_user.id, post.user_id):
        await push_notification(
            session,
            parent.user_id,
            current_user.id,
            "reply",
            {"post_id": post_id, "post_title": (post.title or "")[:30], "excerpt": excerpt},
        )
    return StandardResponse(
        success=True,
        message="评论成功",
        data={
            "id": comment.id,
            "user_id": current_user.id,
            "author": current_user.username,
            "content": comment.content,
            "created_at": comment.created_at,
            "replies": [],
        },
    )


@router.post("/posts/{post_id}/fork", response_model=StandardResponse)
async def fork_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    照着走：把帖子关联的行程深拷贝为当前用户的新行程（status=completed）。

    关键体验：若原行程开始日期已过去，整体平移到从明天开始；
    原行程在未来则保持原日期。只读快照复制，不影响原作者行程。
    """
    post = await _get_published_post(post_id, session)
    if not post.plan_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该帖子未关联可复制的行程"
        )
    plan = await session.get(TripPlanDB, post.plan_id)
    if not plan or plan.status != "completed" or not plan.plan_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="原行程已删除或未完成，无法复制"
        )

    new_id = f"PLAN_{uuid.uuid4().hex}"
    start = date.fromisoformat(plan.start_date)
    tomorrow = date.today() + timedelta(days=1)
    delta = (tomorrow - start).days if start < tomorrow else 0
    plan_dict = {
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "plan_data": copy.deepcopy(plan.plan_data),
        "request_data": copy.deepcopy(plan.request_data),
    }
    _shift_dates(plan_dict, delta)

    new_plan = TripPlanDB(
        id=new_id,
        user_id=current_user.id,
        city=plan.city,
        start_date=plan_dict["start_date"],
        end_date=plan_dict["end_date"],
        travel_days=plan.travel_days,
        plan_data=plan_dict["plan_data"],
        request_data=plan_dict["request_data"],
        cities_json=copy.deepcopy(plan.cities_json),
        status="completed",
    )
    # 行程 JSON 内冗余的归属信息同步指向新行程
    if isinstance(new_plan.plan_data, dict):
        new_plan.plan_data["plan_id"] = new_id
        new_plan.plan_data["user_id"] = current_user.id
    session.add(new_plan)
    await session.commit()
    logger.info(f"[Community] 用户 {current_user.id} 照着走 帖子 {post_id} → 新行程 {new_id}")
    return StandardResponse(
        success=True,
        message="行程已复制到我的账户",
        data={
            "plan_id": new_id,
            "start_date": new_plan.start_date,
            "end_date": new_plan.end_date,
        },
    )
