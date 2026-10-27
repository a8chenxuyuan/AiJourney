"""管理后台路由：数据看板、用户管理（封禁/授权）、内容审核、系统公告。

所有接口统一 Depends(get_current_admin) 鉴权，非 admin 一律 403。
角色/封禁规则：不能操作自己；不能封禁或降级其他管理员；收权前校验剩余管理员数。
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.db.session import get_db
from app.core.utils.security import get_password_hash
from app.models.db_models import (
    CommunityPost,
    Friendship,
    Notification,
    Order,
    TripJournal,
    TripPlanDB,
    User,
)
from app.models.schemas import StandardResponse
from app.services.ws_manager import manager

router = APIRouter()

# 趋势统计天数
TREND_DAYS = 7


def _user_row(u: User, plans: int, posts: int) -> dict:
    """用户行 → 管理列表 dict。"""
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "is_banned": bool(u.is_banned),
        "plans_count": plans,
        "posts_count": posts,
        "created_at": u.created_at,
    }


def _post_row(p: CommunityPost, author: str) -> dict:
    """帖子行 → 审核列表 dict。"""
    return {
        "id": p.id,
        "author": author,
        "title": p.title,
        "zone": p.zone or "note",
        "post_type": p.post_type,
        "status": p.status,
        "like_count": p.like_count,
        "comment_count": p.comment_count,
        "created_at": p.created_at,
    }


async def _get_target_user(user_id: int, admin: User, session: AsyncSession) -> User:
    """取目标用户并校验操作权限：不能操作自己，不能操作其他管理员。"""
    target = await session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能操作自己的账号")
    if target.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="不能对其他管理员执行该操作"
        )
    return target


async def _guard_last_admin(session: AsyncSession) -> None:
    """收权保护：收权后至少还要剩一名管理员。"""
    admins = (
        await session.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    ).scalar_one()
    if admins <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="系统至少需要保留一名管理员"
        )


@router.get("/stats", response_model=StandardResponse)
async def get_stats(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """数据看板：核心实体总量 + 今日新增（UTC 今日，演示项目足够）。"""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    async def _count(model) -> int:
        return (
            await session.execute(select(func.count()).select_from(model))
        ).scalar_one()

    async def _count_today(model) -> int:
        return (
            await session.execute(
                select(func.count()).select_from(model).where(model.created_at >= today_start)
            )
        ).scalar_one()

    # 帖子状态/分区分布（可视化用）
    status_map = dict(
        (await session.execute(
            select(CommunityPost.status, func.count()).group_by(CommunityPost.status)
        )).all()
    )
    zone_map = dict(
        (await session.execute(
            select(CommunityPost.zone, func.count()).group_by(CommunityPost.zone)
        )).all()
    )
    # 发帖最活跃用户 TOP5（可视化用）
    top_rows = (
        await session.execute(
            select(CommunityPost.user_id, User.username, func.count().label("cnt"))
            .join(User, User.id == CommunityPost.user_id)
            .group_by(CommunityPost.user_id, User.username)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()

    data = {
        "users": await _count(User),
        "users_today": await _count_today(User),
        "plans": await _count(TripPlanDB),
        "posts": await _count(CommunityPost),
        "posts_today": await _count_today(CommunityPost),
        "journals": await _count(TripJournal),
        "admins": (
            await session.execute(
                select(func.count()).select_from(User).where(User.role == "admin")
            )
        ).scalar_one(),
        "posts_published": status_map.get("published", 0),
        "posts_hidden": status_map.get("hidden", 0),
        "posts_circle": zone_map.get("circle", 0),
        "posts_note": zone_map.get("note", 0),
        "top_users": [
            {"user_id": uid, "username": name, "count": int(cnt)} for uid, name, cnt in top_rows
        ],
        # 今日动态补充：行程 / 游记
        "plans_today": (
            await session.execute(
                select(func.count())
                .select_from(TripPlanDB)
                .where(TripPlanDB.created_at >= today_start)
            )
        ).scalar_one(),
        "journals_today": (
            await session.execute(
                select(func.count())
                .select_from(TripJournal)
                .where(TripJournal.created_at >= today_start)
            )
        ).scalar_one(),
        # 运营指标：互动 / 社交 / 公开内容 / 支付
        "like_total": (
            await session.execute(select(func.sum(CommunityPost.like_count)))
        ).scalar_one()
        or 0,
        "comment_total": (
            await session.execute(select(func.sum(CommunityPost.comment_count)))
        ).scalar_one()
        or 0,
        "friend_pairs": (
            await session.execute(
                select(func.count()).select_from(Friendship).where(Friendship.status == "accepted")
            )
        ).scalar_one(),
        "pending_requests": (
            await session.execute(
                select(func.count()).select_from(Friendship).where(Friendship.status == "pending")
            )
        ).scalar_one(),
        "journals_public": (
            await session.execute(
                select(func.count()).select_from(TripJournal).where(TripJournal.is_public)
            )
        ).scalar_one(),
        "orders_paid": (
            await session.execute(
                select(func.count()).select_from(Order).where(Order.status == "paid")
            )
        ).scalar_one(),
        "revenue_paid": (
            await session.execute(
                select(func.sum(Order.amount)).select_from(Order).where(Order.status == "paid")
            )
        ).scalar_one()
        or 0.0,
        # 近 7 天新增趋势（用户 / 帖子，按日补零）
        "trends_7d": await _trend_7d(session),
    }
    return StandardResponse(success=True, message="获取成功", data=data)


async def _trend_7d(session: AsyncSession) -> list[dict]:
    """近 7 天每日新增用户/帖子数（按日分组，缺失日期补零）。"""
    today = datetime.now(UTC).date()
    start = today - timedelta(days=TREND_DAYS - 1)

    async def _daily(model):
        rows = await session.execute(
            select(func.date(model.created_at), func.count())
            .where(model.created_at >= datetime.combine(start, datetime.min.time()))
            .group_by(func.date(model.created_at))
        )
        return dict(rows.all())

    users_map, posts_map = await _daily(User), await _daily(CommunityPost)
    trends = []
    for i in range(TREND_DAYS):
        d = (start + timedelta(days=i)).isoformat()
        trends.append(
            {"date": d, "users": int(users_map.get(d, 0)), "posts": int(posts_map.get(d, 0))}
        )
    return trends


@router.get("/users", response_model=StandardResponse)
async def list_users(
    search: str = Query(default="", max_length=50, description="按用户名/邮箱模糊搜索"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """用户列表：分页 + 关键词搜索，附行程/发帖数量。"""
    count_stmt = select(func.count()).select_from(User)
    if search:
        count_stmt = count_stmt.where(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = select(User).order_by(User.created_at.desc()).offset((page - 1) * size).limit(size)
    if search:
        stmt = stmt.where(User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%"))
    rows = (await session.execute(stmt)).scalars().all()

    plan_counts = dict(
        (await session.execute(
            select(TripPlanDB.user_id, func.count()).group_by(TripPlanDB.user_id)
        )).all()
    )
    post_counts = dict(
        (await session.execute(
            select(CommunityPost.user_id, func.count()).group_by(CommunityPost.user_id)
        )).all()
    )
    users = [
        _user_row(u, plan_counts.get(u.id, 0), post_counts.get(u.id, 0)) for u in rows
    ]
    return StandardResponse(
        success=True,
        message="获取成功",
        data={"users": users, "total": total, "page": page, "size": size},
    )


@router.post("/users/{user_id}/ban", response_model=StandardResponse)
async def ban_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """封禁用户：token 层立即拦截其所有请求。"""
    target = await _get_target_user(user_id, admin, session)
    target.is_banned = True
    logger.info(f"[Admin] 管理员 {admin.id} 封禁用户 {target.id}")
    return StandardResponse(success=True, message=f"已封禁用户 {target.username}")


@router.post("/users/{user_id}/unban", response_model=StandardResponse)
async def unban_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """解封用户。"""
    target = await _get_target_user(user_id, admin, session)
    target.is_banned = False
    logger.info(f"[Admin] 管理员 {admin.id} 解封用户 {target.id}")
    return StandardResponse(success=True, message=f"已解封用户 {target.username}")


class RoleRequest(BaseModel):
    """授权/收权请求体。"""

    role: str = Field(pattern="^(admin|user)$", description="目标角色")


@router.post("/users/{user_id}/role", response_model=StandardResponse)
async def set_user_role(
    user_id: int,
    payload: RoleRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """授权/收权：把用户提升为管理员或降为普通用户（收权受最后一名管理员保护）。"""
    target = await _get_target_user(user_id, admin, session)
    if target.role == payload.role:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户已是该角色")
    if payload.role == "user":
        await _guard_last_admin(session)
    target.role = payload.role
    logger.info(f"[Admin] 管理员 {admin.id} 将用户 {target.id} 角色改为 {payload.role}")
    return StandardResponse(
        success=True,
        message=f"已将 {target.username} 设为{'管理员' if payload.role == 'admin' else '普通用户'}",
    )


class AdminUserUpdateRequest(BaseModel):
    """编辑用户资料请求体：两字段均可选，至少改一项。"""

    username: str | None = Field(default=None, min_length=2, max_length=32, description="新用户名")
    email: str | None = Field(default=None, max_length=100, description="新邮箱")


class AdminPasswordResetRequest(BaseModel):
    """重置密码请求体：管理员直接设置新密码。"""

    new_password: str = Field(min_length=6, max_length=64, description="新密码（6-64 位）")


@router.patch("/users/{user_id}", response_model=StandardResponse)
async def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """编辑用户资料（用户名/邮箱）：仅普通用户可编辑，用户名/邮箱全库唯一。"""
    target = await _get_target_user(user_id, admin, session)
    new_name = (payload.username or "").strip()
    new_email = (payload.email or "").strip().lower()
    if not new_name and not new_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请至少填写一项修改内容"
        )
    if new_email and ("@" not in new_email or "." not in new_email.split("@")[-1]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱格式不正确")
    # 唯一性校验：排除自身后查重
    if new_name and new_name != target.username:
        dup = await session.execute(
            select(User).where(User.username == new_name, User.id != target.id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已被占用")
    if new_email and new_email != target.email:
        dup = await session.execute(
            select(User).where(User.email == new_email, User.id != target.id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已被占用")
    if new_name:
        target.username = new_name
    if new_email:
        target.email = new_email
    logger.info(f"[Admin] 管理员 {admin.id} 编辑用户 {target.id} 资料")
    return StandardResponse(success=True, message=f"已更新用户 {target.username} 的资料")


@router.post("/users/{user_id}/password", response_model=StandardResponse)
async def reset_user_password(
    user_id: int,
    payload: AdminPasswordResetRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """重置用户密码：管理员直接设置新密码，无需旧密码。"""
    target = await _get_target_user(user_id, admin, session)
    target.password_hash = get_password_hash(payload.new_password)
    logger.info(f"[Admin] 管理员 {admin.id} 重置了用户 {target.id} 的密码")
    return StandardResponse(success=True, message=f"已重置 {target.username} 的密码")


@router.get("/posts", response_model=StandardResponse)
async def list_posts(
    status_filter: str = Query(
        default="all", alias="status", pattern="^(all|published|hidden)$", description="状态过滤"
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """全量帖子列表（含隐藏帖），供内容审核。"""
    stmt = select(CommunityPost, User.username).join(User, User.id == CommunityPost.user_id)
    count_stmt = select(func.count()).select_from(CommunityPost)
    if status_filter != "all":
        cond = CommunityPost.status == status_filter
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = await session.execute(
        stmt.order_by(CommunityPost.created_at.desc()).offset((page - 1) * size).limit(size)
    )
    posts = [_post_row(p, name) for p, name in rows.all()]
    return StandardResponse(
        success=True,
        message="获取成功",
        data={"posts": posts, "total": total, "page": page, "size": size},
    )


@router.post("/posts/{post_id}/hide", response_model=StandardResponse)
async def hide_post(
    post_id: str,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """下架帖子：广场/攻略流立即不可见（status=hidden）。"""
    post = await session.get(CommunityPost, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="帖子不存在")
    post.status = "hidden"
    logger.info(f"[Admin] 管理员 {admin.id} 下架帖子 {post_id}")
    return StandardResponse(success=True, message="帖子已下架")


@router.post("/posts/{post_id}/restore", response_model=StandardResponse)
async def restore_post(
    post_id: str,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """恢复帖子为已发布。"""
    post = await session.get(CommunityPost, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="帖子不存在")
    post.status = "published"
    logger.info(f"[Admin] 管理员 {admin.id} 恢复帖子 {post_id}")
    return StandardResponse(success=True, message="帖子已恢复")


class AnnouncementRequest(BaseModel):
    """系统公告请求体。"""

    title: str = Field(min_length=1, max_length=50, description="公告标题")
    content: str = Field(min_length=1, max_length=500, description="公告内容")


@router.get("/announcements", response_model=StandardResponse)
async def list_announcements(
    _admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """历史公告列表：同一条公告每用户存一行，按标题+内容聚合去重，取最新发送时间倒序。"""
    title_col = Notification.payload["title"].as_string()
    content_col = Notification.payload["content"].as_string()
    rows = (
        await session.execute(
            select(
                title_col,
                content_col,
                func.max(Notification.created_at).label("sent_at"),
                func.count().label("receivers"),
            )
            .where(Notification.type == "system")
            .group_by(title_col, content_col)
            .order_by(func.max(Notification.created_at).desc())
            .limit(50)
        )
    ).all()
    return StandardResponse(
        success=True,
        message="获取成功",
        data=[
            {"title": t, "content": c, "sent_at": s, "receivers": int(n)}
            for t, c, s, n in rows
        ],
    )


@router.post("/announcements", response_model=StandardResponse)
async def create_announcement(
    payload: AnnouncementRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """发系统公告：给全站用户写入通知（复用 Notification 表），在线用户实时推送。"""
    user_ids = (await session.execute(select(User.id))).scalars().all()
    session.add_all(
        Notification(
            user_id=uid,
            actor_id=None,
            type="system",
            payload={"title": payload.title, "content": payload.content},
            is_read=False,
        )
        for uid in user_ids
    )
    await session.flush()
    # 在线用户实时推送（失败静默，HTTP 通知列表兜底）
    text = f"📢 {payload.title}：{payload.content}"
    for uid in user_ids:
        await manager.send_to_user(uid, {"type": "notification", "text": text, "ntype": "system"})
    logger.info(f"[Admin] 管理员 {admin.id} 发布系统公告，覆盖 {len(user_ids)} 名用户")
    return StandardResponse(success=True, message=f"公告已发送给 {len(user_ids)} 名用户")


@router.delete("/announcements", response_model=StandardResponse)
async def clear_system_announcements(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """清空全部系统公告（管理端演示用，不影响互动通知）。"""
    result = await session.execute(
        delete(Notification).where(Notification.type == "system")
    )
    logger.info(f"[Admin] 管理员 {admin.id} 清空系统公告 {result.rowcount} 条")
    return StandardResponse(success=True, message=f"已清空 {result.rowcount} 条系统公告")
