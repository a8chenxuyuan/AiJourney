"""公开游记路由：精选游记流（免登录）、token 公开分享、复刻线路。

公开链路：游记发布（trip/{plan_id}/journal/publish 置 is_public+public_token）
→ 本模块按 token 免登录读取 → 他人登录后一键复刻原行程到自己账户。
"""

import copy
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.community import _shift_dates
from app.core.db.session import get_db
from app.models.db_models import TripJournal, TripPlanDB, User
from app.models.schemas import StandardResponse

router = APIRouter()

# 分享页摘要截断长度
EXCERPT_LEN = 120


def _journal_cover(sections: list[dict] | None) -> str | None:
    """取游记分节中的第一张照片作为封面。"""
    for section in sections or []:
        for photo in section.get("photos") or []:
            if photo:
                return photo
    return None


def _journal_text(sections: list[dict] | None) -> str:
    """拼接游记分节正文。"""
    return "".join(s.get("text") or "" for s in sections or [])


async def _get_public_journal_by_token(
    token: str, session: AsyncSession
) -> TripJournal:
    """按 token 取公开游记：不存在/未公开/未生成完成统一 404（不泄露存在性）。"""
    journal = (
        await session.execute(select(TripJournal).where(TripJournal.public_token == token))
    ).scalar_one_or_none()
    if not journal or not journal.is_public or journal.status != "done":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="游记不存在或未公开")
    return journal


@router.get("/featured", response_model=StandardResponse)
async def featured_journals(
    limit: int = Query(default=12, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
):
    """
    精选公开游记流（免登录）：真实用户游记，按生成时间倒序。

    Args:
        limit: 返回条数上限。
        session: 数据库会话。

    Returns:
        StandardResponse: 游记卡片列表（含 public_token 供跳转分享页）。
    """
    rows = (
        await session.execute(
            select(TripJournal, User.username, TripPlanDB)
            .join(User, User.id == TripJournal.user_id)
            .join(TripPlanDB, TripPlanDB.id == TripJournal.plan_id)
            .where(TripJournal.is_public.is_(True), TripJournal.status == "done")
            .order_by(TripJournal.created_at.desc())
            .limit(limit)
        )
    ).all()

    items = []
    for journal, author, plan in rows:
        sections = journal.content or []
        items.append(
            {
                "id": journal.id,
                "public_token": journal.public_token,
                "title": journal.title or f"{plan.city}游记",
                "author": author,
                "city": plan.city,
                "travel_days": plan.travel_days,
                "cover_url": _journal_cover(sections),
                "excerpt": _journal_text(sections)[:EXCERPT_LEN],
                "created_at": journal.created_at.isoformat() if journal.created_at else None,
            }
        )

    return StandardResponse(success=True, message="获取成功", data={"items": items})


@router.get("/share/{token}", response_model=StandardResponse)
async def shared_journal(token: str, session: AsyncSession = Depends(get_db)):
    """
    公开游记分享页数据（免登录，无登录可看）。

    返回分节全文 + 作者 + 原行程概要（不含 plan_id，防内部 ID 外泄）。

    Args:
        token: 公开访问令牌。
        session: 数据库会话。

    Returns:
        StandardResponse: 游记分享视图。
    """
    journal = await _get_public_journal_by_token(token, session)
    author = (await session.get(User, journal.user_id)).username
    plan = await session.get(TripPlanDB, journal.plan_id)

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "id": journal.id,
            "title": journal.title,
            "author": author,
            "sections": journal.content or [],
            "cover_url": _journal_cover(journal.content),
            "plan": {
                "city": plan.city,
                "start_date": plan.start_date,
                "end_date": plan.end_date,
                "travel_days": plan.travel_days,
            }
            if plan
            else None,
            "generated_at": journal.generated_at.isoformat() if journal.generated_at else None,
        },
    )


@router.post("/share/{token}/fork", response_model=StandardResponse)
async def fork_shared_journal(
    token: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    复刻这条线路：把公开游记的原行程深拷贝为当前用户的新行程。

    复制逻辑与社区"照着走"一致：原行程开始日期已过去则整体平移到
    明天开始，否则保持原日期；只读快照复制，不影响原作者行程。

    Args:
        token: 公开访问令牌。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: 新行程 plan_id 与起止日期。
    """
    journal = await _get_public_journal_by_token(token, session)
    plan = await session.get(TripPlanDB, journal.plan_id)
    if not plan or plan.status != "completed" or not plan.plan_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="原行程已不可用，无法复刻"
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
    logger.info(
        f"[Journals] 用户 {current_user.id} 复刻游记 {journal.id} 的线路 → 新行程 {new_id}"
    )

    return StandardResponse(
        success=True,
        message="线路已复刻到我的账户",
        data={
            "plan_id": new_id,
            "city": new_plan.city,
            "start_date": new_plan.start_date,
            "end_date": new_plan.end_date,
        },
    )
