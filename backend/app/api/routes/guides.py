"""内容中心路由：攻略库（crawled_documents）+ 目的地聚合页 + 目的地 AI 问答。

攻略流优先合入公开游记（trip_journals.is_public），形成
"用户游记回流 → 他人浏览 → 复刻线路" 的内容闭环。
公开游记/攻略浏览为免登录接口（内容中心是公域流量入口）。
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db.session import get_db
from app.llm.client import get_llm
from app.models.db_models import (
    CommunityPost,
    CrawledDocument,
    TripJournal,
    TripPlanDB,
    User,
)
from app.models.schemas import DestinationAskRequest, ReplicateRequest, StandardResponse
from app.services.baike_service import get_baike_service
from app.services.rag_service import get_rag_service
from app.services.replicate_service import build_plan_from_text

router = APIRouter()

# feed 卡片摘要截断长度
EXCERPT_LEN = 120
# 游记/攻略合流上限：沙箱数据量小，内存合流分页足够（两端各限一次查询量）
JOURNAL_SCAN_LIMIT = 50
GUIDE_SCAN_LIMIT = 200


def _excerpt(text: str | None, limit: int = EXCERPT_LEN) -> str:
    """正文压成单行摘要（去换行、截断）。"""
    return (text or "").replace("\r", "").replace("\n", " ").strip()[:limit]


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


async def _fetch_public_journals(
    session: AsyncSession,
    city: str | None = None,
    keyword: str | None = None,
    limit: int = JOURNAL_SCAN_LIMIT,
) -> list[dict]:
    """查询公开游记（status=done 且 is_public），联用户名与行程城市/天数。"""
    stmt = (
        select(TripJournal, User.username, User.id, TripPlanDB)
        .join(User, User.id == TripJournal.user_id)
        .join(TripPlanDB, TripPlanDB.id == TripJournal.plan_id)
        .where(TripJournal.is_public.is_(True), TripJournal.status == "done")
        .order_by(TripJournal.created_at.desc())
        .limit(limit)
    )
    if city:
        stmt = stmt.where(TripPlanDB.city == city)
    if keyword:
        stmt = stmt.where(TripJournal.title.like(keyword))

    items = []
    for journal, author, user_id, plan in (await session.execute(stmt)).all():
        sections = journal.content or []
        generated = journal.generated_at or journal.created_at
        items.append(
            {
                "item_type": "journal",
                "id": journal.id,
                "public_token": journal.public_token,
                "title": journal.title or f"{plan.city}游记",
                "excerpt": _excerpt(_journal_text(sections)),
                "city": plan.city,
                "travel_days": plan.travel_days,
                "author": author,
                "user_id": user_id,
                "cover_url": _journal_cover(sections),
                "created_at": generated.isoformat() if generated else None,
            }
        )
    return items


async def _fetch_guides(
    session: AsyncSession,
    city: str | None = None,
    keyword: str | None = None,
    limit: int = GUIDE_SCAN_LIMIT,
) -> list[dict]:
    """查询爬虫攻略文档。"""
    stmt = select(CrawledDocument).order_by(CrawledDocument.crawled_at.desc()).limit(limit)
    if city:
        stmt = stmt.where(CrawledDocument.city == city)
    if keyword:
        stmt = stmt.where(
            or_(CrawledDocument.title.like(keyword), CrawledDocument.content.like(keyword))
        )

    items = []
    for doc in (await session.execute(stmt)).scalars():
        items.append(
            {
                "item_type": "guide",
                "id": doc.id,
                "title": doc.title,
                "excerpt": _excerpt(doc.content),
                "city": doc.city,
                "source": doc.source_type,
                "created_at": doc.crawled_at.isoformat() if doc.crawled_at else None,
            }
        )
    return items


async def _fetch_note_posts(
    session: AsyncSession,
    city: str | None = None,
    keyword: str | None = None,
    limit: int = JOURNAL_SCAN_LIMIT,
) -> list[dict]:
    """社区笔记帖（posts.zone=note：手动笔记 + 游记转发帖），联作者与行程城市。

    城市取关联行程 plan.city（无关联行程的笔记 city=None，仅「全部」可见），
    故先限量取回再内存过滤，避免 outerjoin + where 的分页歧义。
    """
    stmt = (
        select(CommunityPost, User.username, User.id, TripPlanDB)
        .join(User, User.id == CommunityPost.user_id)
        .outerjoin(TripPlanDB, TripPlanDB.id == CommunityPost.plan_id)
        .where(CommunityPost.zone == "note", CommunityPost.status == "published")
        .order_by(CommunityPost.created_at.desc())
        .limit(limit)
    )
    if keyword:
        stmt = stmt.where(
            or_(CommunityPost.title.like(keyword), CommunityPost.summary.like(keyword))
        )

    items = []
    for post, author, user_id, plan in (await session.execute(stmt)).all():
        if city and (not plan or plan.city != city):
            continue
        items.append(
            {
                "item_type": "note",
                "id": post.id,
                "title": post.title,
                "excerpt": post.summary or "",
                "city": plan.city if plan else None,
                "travel_days": plan.travel_days if plan else None,
                "author": author,
                "user_id": user_id,
                "cover_url": post.cover_url,
                "like_count": post.like_count,
                "comment_count": post.comment_count,
                "view_count": post.view_count,
                "post_type": post.post_type,
                "created_at": post.created_at.isoformat() if post.created_at else None,
            }
        )
    return items


# 智能排序的源权重：真实经验（游记/笔记）优先，爬虫攻略不被沉底
_SOURCE_WEIGHT = {"journal": 1.2, "note": 1.0, "guide": 0.8}


def _feed_score(item: dict, journal_heat: dict[str, int], now: datetime) -> float:
    """智能混合排序分：源权重 × 热度 × 温和时间衰减。

    - 热度：笔记用自身赞/评/浏览；游记借其转发帖的点赞数；攻略给固定基础分；
    - 衰减：(1 + 天数)^0.3，7 天约降 30%，避免旧采集攻略长期霸屏。
    """
    itype = item["item_type"]
    days = 30.0
    if item.get("created_at"):
        try:
            delta = now - datetime.fromisoformat(item["created_at"])
            days = max(0.0, delta.total_seconds() / 86400)
        except ValueError:
            pass
    if itype == "note":
        heat = item["like_count"] * 3 + item["comment_count"] * 2 + item["view_count"] * 0.05
        base = 2.0
    elif itype == "journal":
        base, heat = 2.0, journal_heat.get(item["id"], 0) * 3
    else:
        base, heat = 5.0, 0.0
    return (base + heat) * _SOURCE_WEIGHT[itype] / ((1 + days) ** 0.3)


@router.get("/guides", response_model=StandardResponse)
async def list_guides(
    city: str | None = Query(default=None, description="按城市筛选"),
    q: str | None = Query(default=None, max_length=50, description="关键词搜索（标题/正文）"),
    type: str | None = Query(
        default=None, pattern="^(journal|note|guide)$", description="按内容类型筛选"
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    max_days: int | None = Query(default=None, ge=1, le=30, description="按行程天数筛选（≤N 天）"),
    session: AsyncSession = Depends(get_db),
):
    """
    攻略流：真实游记 + 社区笔记帖 + 爬虫攻略三源合流，智能排序后按 page/size 分页。

    排序为加权混合：源权重（游记 1.2 / 笔记 1.0 / 攻略 0.8）× 热度 × 温和时间衰减；
    type 可切单一来源。同时返回去重后的城市列表，供前端筛选 chips。
    """
    keyword = f"%{q.strip()}%" if q and q.strip() else None

    journal_items = await _fetch_public_journals(session, city=city, keyword=keyword)
    note_items = await _fetch_note_posts(session, city=city, keyword=keyword)
    guide_items = await _fetch_guides(session, city=city, keyword=keyword)

    # 游记热度：借其转发帖（journal_id 关联）的点赞数
    journal_ids = [j["id"] for j in journal_items]
    journal_heat: dict[str, int] = {}
    if journal_ids:
        heat_rows = await session.execute(
            select(CommunityPost.journal_id, CommunityPost.like_count).where(
                CommunityPost.journal_id.in_(journal_ids)
            )
        )
        journal_heat = {jid: like or 0 for jid, like in heat_rows.all() if jid}

    # 城市 chips：双来源去重
    guide_cities = (
        await session.execute(
            select(CrawledDocument.city).where(CrawledDocument.city.isnot(None)).distinct()
        )
    ).scalars().all()
    journal_cities = (
        await session.execute(
            select(TripPlanDB.city)
            .join(TripJournal, TripJournal.plan_id == TripPlanDB.id)
            .where(TripJournal.is_public.is_(True))
            .distinct()
        )
    ).scalars().all()
    cities = sorted(
        {c for c in [*guide_cities, *journal_cities, *[n["city"] for n in note_items]] if c}
    )

    # 三源合流 → 智能排序 → 类型筛选 → 内存分页
    merged = journal_items + note_items + guide_items
    now = datetime.now()
    merged.sort(key=lambda it: _feed_score(it, journal_heat, now), reverse=True)
    if type:
        merged = [it for it in merged if it["item_type"] == type]
    # 天数筛选：仅保留携带天数信息且 ≤ max_days 的内容（游记/带行程的笔记）
    if max_days:
        merged = [it for it in merged if it.get("travel_days") and it["travel_days"] <= max_days]
    total = len(merged)
    items = merged[(page - 1) * size : page * size]

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "has_more": page * size < total,
            "cities": cities,
        },
    )


@router.get("/guides/{guide_id}", response_model=StandardResponse)
async def get_guide(guide_id: int, session: AsyncSession = Depends(get_db)):
    """
    攻略详情：正文 + 同城相关攻略（最多 3 篇）。

    Args:
        guide_id: 攻略文档 ID。
        session: 数据库会话。

    Returns:
        StandardResponse: 攻略详情。
    """
    guide = await session.get(CrawledDocument, guide_id)
    if not guide:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="攻略不存在")

    related_rows = (
        await session.execute(
            select(CrawledDocument)
            .where(
                CrawledDocument.city == guide.city,
                CrawledDocument.id != guide.id,
            )
            .order_by(CrawledDocument.crawled_at.desc())
            .limit(3)
        )
    ).scalars().all()

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "id": guide.id,
            "title": guide.title,
            "content": guide.content,
            "city": guide.city,
            "source": guide.source_type,
            "url": guide.url,
            "crawled_at": guide.crawled_at.isoformat() if guide.crawled_at else None,
            "related": [
                {"id": r.id, "title": r.title, "city": r.city} for r in related_rows
            ],
        },
    )


@router.get("/destination/{city}", response_model=StandardResponse)
async def get_destination(city: str, session: AsyncSession = Depends(get_db)):
    """
    目的地聚合页：百科简介（超时降级）+ 精选攻略 + 公开游记 + 热门行程模板。

    行程模板取自社区公开帖（关联已完成行程且城市匹配，按点赞排序），
    复用照着走逻辑可一键复制。
    """
    city = city.strip()

    # 百科简介：外部抓取可能很慢，整体 10s 封顶，超时降级为无简介
    summary, summary_url = "", ""
    try:
        baike = await asyncio.wait_for(
            get_baike_service().search(city, city), timeout=10
        )
        if baike and not baike.get("summary", "").startswith("未找到"):
            summary = baike.get("summary", "")
            summary_url = baike.get("url", "")
    except Exception as e:
        logger.warning(f"[Guides] 目的地百科获取失败 city={city}: {e}")

    guides = (await _fetch_guides(session, city=city, limit=50))[:6]
    journals = (await _fetch_public_journals(session, city=city, limit=50))[:4]
    notes = (await _fetch_note_posts(session, city=city, limit=50))[:4]

    # 热门行程模板：社区公开帖 → 关联已完成行程（同城市），点赞排序
    template_rows = (
        await session.execute(
            select(CommunityPost, User.username, User.id, TripPlanDB)
            .join(User, User.id == CommunityPost.user_id)
            .join(TripPlanDB, TripPlanDB.id == CommunityPost.plan_id)
            .where(
                CommunityPost.status == "published",
                CommunityPost.plan_id.isnot(None),
                TripPlanDB.status == "completed",
                TripPlanDB.city == city,
            )
            .order_by(CommunityPost.like_count.desc(), CommunityPost.created_at.desc())
            .limit(3)
        )
    ).all()
    templates = [
        {
            "post_id": post.id,
            "title": post.title,
            "author": author,
            "user_id": user_id,
            "like_count": post.like_count,
            "travel_days": plan.travel_days,
            "start_date": plan.start_date,
        }
        for post, author, user_id, plan in template_rows
    ]

    return StandardResponse(
        success=True,
        message="获取成功",
        data={
            "city": city,
            "summary": summary,
            "summary_url": summary_url,
            "guides": guides,
            "journals": journals,
            "notes": notes,
            "templates": templates,
        },
    )


# 目的地问答系统提示词：基于参考资料回答，简短口语化
ASK_SYSTEM_PROMPT = """你是一位资深的旅行目的地顾问。请基于给定的参考资料回答用户关于目的地的问题。
要求：
1. 回答用中文，口语化、具体、实用，控制在 150 字以内；
2. 优先使用参考资料中的信息，资料没有的内容可以凭常识补充，但不要编造具体价格/班次等细节；
3. 若资料与问题无关，直接按常识回答。
"""


@router.post("/destination/ask", response_model=StandardResponse)
async def destination_ask(
    payload: DestinationAskRequest,
    current_user: User = Depends(get_current_user),
):
    """
    目的地 AI 问答：RAG 检索（未命中回源百科）→ LLM 组织回答。

    检索 8s 封顶、LLM 25s 超时；任何一步失败都降级返回兜底文案，不抛 500。

    Args:
        payload: 城市 + 问题。
        current_user: 当前登录用户（问答消耗 LLM 资源，须登录）。

    Returns:
        StandardResponse: reply 回答文本。
    """
    city = payload.city.strip()
    question = payload.question.strip()

    # 1. RAG 检索（缓存优先，未命中外部百科补源并回写缓存）
    context = ""
    try:
        hit = await asyncio.wait_for(
            get_rag_service().search_or_fetch(question, city=city, source_type="destination_qa"),
            timeout=8,
        )
        context = (hit or {}).get("content") or ""
    except Exception as e:
        logger.warning(f"[Guides] 目的地问答检索失败 city={city}: {e}")

    # 2. LLM 组织回答
    try:
        llm = get_llm(temperature=0.3, timeout=25)
        result = await llm.ainvoke(
            [
                {"role": "system", "content": ASK_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"【目的地】{city}\n\n【参考资料】\n{context or '（无）'}\n\n"
                        f"【用户问题】\n{question}"
                    ),
                },
            ]
        )
        reply = (getattr(result, "content", "") or "").strip()
    except Exception as e:
        logger.warning(f"[Guides] 目的地问答 LLM 失败 city={city}: {e}")
        reply = _excerpt(context, 200) or "AI 顾问暂时开小差了，请稍后再问一次。"

    return StandardResponse(success=True, message="ok", data={"city": city, "reply": reply})


@router.post("/guides/{guide_id}/replicate", response_model=StandardResponse)
async def replicate_guide(
    guide_id: int,
    body: ReplicateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    照着走（攻略版）：AI 把爬虫攻略转写为当前用户自己的行程。

    与游记 fork（快照复制）不同，攻略没有原行程，需 LLM 生成同构 TripPlan。
    同步调用约 10-20s，前端以 loading 呈现。

    Args:
        guide_id: 攻略文档 ID。
        body: 出发日期（默认一周后）与目标天数（可选）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: {plan_id, city, travel_days}。
    """
    guide = await session.get(CrawledDocument, guide_id)
    if not guide:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="攻略不存在或已下架")

    start_date = body.start_date or (date.today() + timedelta(days=7)).isoformat()
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="出发日期格式应为 YYYY-MM-DD"
        ) from exc

    source_text = f"【攻略标题】{guide.title}\n\n【攻略正文】\n{guide.content or ''}"
    plan = await build_plan_from_text(source_text, start_date, body.travel_days)

    plan_id = f"PLAN_{uuid.uuid4().hex}"
    travel_days = len(plan.day_plans)
    try:
        end_dt = date.fromisoformat(plan.start_date) + timedelta(days=travel_days - 1)
        end_date = end_dt.isoformat()
    except ValueError:
        end_date = plan.end_date

    db_plan = TripPlanDB(
        id=plan_id,
        user_id=current_user.id,
        city=plan.city,
        start_date=plan.start_date,
        end_date=end_date,
        travel_days=travel_days,
        plan_data=plan.model_dump(mode="json"),
        status="completed",
    )
    session.add(db_plan)
    await session.commit()

    logger.info(
        f"[Guides] 攻略复刻成功 user={current_user.username} guide={guide_id} plan={plan_id}"
    )
    return StandardResponse(
        success=True,
        message="攻略已复刻为你的行程",
        data={"plan_id": plan_id, "city": plan.city, "travel_days": travel_days},
    )
