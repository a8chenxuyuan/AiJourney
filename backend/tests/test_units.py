"""
backend/tests/test_units.py

纯单元测试：不依赖运行中的后端服务，直接测试核心函数。

覆盖：
- graph._merge_update 批次合并语义（logs/messages 追加、其余覆盖）；
- deps.get_owned_plan_for_user 行程归属校验（命中/越权/不存在）；
- trip._calculate_days 天数计算（含起止日）。

对应技术：
- pytest + pytest-asyncio（asyncio_mode=auto，异步用例自动驱动）
- SQLAlchemy StaticPool + aiosqlite 内存库（每个用例独立引擎与事件循环）
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_owned_plan_for_user
from app.api.routes.trip import _calculate_days
from app.db.base import Base
from app.models.db_models import TripPlanDB, User

# ==================== graph._merge_update ====================


def test_merge_update_overwrites_plain_fields():
    """普通字段按覆盖语义合并（与 LangGraph reducer 默认行为一致）。"""
    from app.agents.graph import _merge_update

    state: dict = {"city": "杭州", "status": "pending"}
    _run(_merge_update(state, {"city": "苏州", "status": "completed"}))

    assert state["city"] == "苏州"
    assert state["status"] == "completed"


def test_merge_update_appends_logs_and_messages():
    """logs / messages 采用追加语义，避免并行批次互相覆盖丢日志。"""
    from app.agents.graph import _merge_update

    state: dict = {"logs": ["a"], "messages": [{"m": 1}]}
    _run(_merge_update(state, {"logs": ["b"], "messages": [{"m": 2}]}))

    assert state["logs"] == ["a", "b"]
    assert state["messages"] == [{"m": 1}, {"m": 2}]


def test_merge_update_appends_into_absent_fields():
    """主状态原本没有 logs/messages 时也能正确初始化为列表。"""
    from app.agents.graph import _merge_update

    state: dict = {}
    _run(_merge_update(state, {"logs": ["x"]}))

    assert state["logs"] == ["x"]


def _run(coro):
    """在独立事件循环中驱动协程（_merge_update 无 IO，循环归属无约束）。"""
    import asyncio

    return asyncio.run(coro)


# ==================== deps.get_owned_plan_for_user ====================


async def _make_session():
    """创建内存 SQLite 会话（表结构与业务库一致），返回 (engine, session)。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory()


def _make_user(user_id: int) -> User:
    return User(
        id=user_id,
        username=f"u{user_id}",
        email=f"u{user_id}@test.com",
        password_hash="x",
    )


def _make_plan(plan_id: str, user_id: int) -> TripPlanDB:
    return TripPlanDB(
        id=plan_id,
        user_id=user_id,
        city="杭州",
        start_date="2026-10-01",
        end_date="2026-10-02",
        travel_days=2,
        request_data={},
        status="completed",
    )


async def _seed(session: AsyncSession) -> None:
    """写入两个用户与一个归属用户 1 的行程。"""
    session.add_all([_make_user(1), _make_user(2)])
    session.add(_make_plan("PLAN_TEST_1", user_id=1))
    await session.commit()


@pytest.mark.asyncio
async def test_owned_plan_hit():
    """归属人访问自己的行程：正常返回计划。"""
    engine, session = await _make_session()
    try:
        await _seed(session)
        owner = await session.get(User, 1)

        plan = await get_owned_plan_for_user("PLAN_TEST_1", owner, session)
        assert plan.id == "PLAN_TEST_1"
        assert plan.user_id == 1
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_owned_plan_wrong_owner_returns_404():
    """越权访问他人行程：统一 404，不泄露资源存在性。"""
    engine, session = await _make_session()
    try:
        await _seed(session)
        intruder = await session.get(User, 2)

        with pytest.raises(HTTPException) as exc_info:
            await get_owned_plan_for_user("PLAN_TEST_1", intruder, session)
        assert exc_info.value.status_code == 404
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_owned_plan_missing_returns_404():
    """行程不存在：404。"""
    engine, session = await _make_session()
    try:
        await _seed(session)
        owner = await session.get(User, 1)

        with pytest.raises(HTTPException) as exc_info:
            await get_owned_plan_for_user("PLAN_NOT_EXIST", owner, session)
        assert exc_info.value.status_code == 404
    finally:
        await session.close()
        await engine.dispose()


# ==================== trip._calculate_days ====================


def test_calculate_days_inclusive():
    """天数计算包含起止两天：10-01 至 10-02 为 2 天。"""
    assert _calculate_days("2026-10-01", "2026-10-02") == 2


def test_calculate_days_same_day():
    """单日往返：起止相同为 1 天。"""
    assert _calculate_days("2026-10-01", "2026-10-01") == 1


def test_calculate_days_cross_month():
    """跨月：9-30 至 10-02 为 3 天。"""
    assert _calculate_days("2026-09-30", "2026-10-02") == 3


# ==================== schemas.TripRequest 多城市校验 ====================


def test_trip_request_cities_days_must_match_total():
    """多城联游：各城市停留天数之和 != 总旅行天数时抛 ValidationError。"""
    from pydantic import ValidationError

    from app.models.schemas import TripRequest

    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            city="杭州",
            start_date="2026-10-01",
            end_date="2026-10-03",  # 总天数 3
            cities=[
                {"city": "杭州", "days": 2},
                {"city": "苏州", "days": 2},  # 之和 4 != 3
            ],
        )
    assert "各城市停留天数之和必须等于总旅行天数" in str(exc_info.value)


def test_trip_request_single_city_without_cities_ok():
    """单城兼容：cities 为 null 时正常构造，行为与旧版一致。"""
    from app.models.schemas import TripRequest

    request = TripRequest(city="杭州", start_date="2026-10-01", end_date="2026-10-03")
    assert request.cities is None


def test_trip_request_multi_city_first_city_alignment():
    """多城联游：天数之和匹配时正常构造，且首城市自动与 city 对齐。"""
    from app.models.schemas import TripRequest

    request = TripRequest(
        city="南京",  # 与 cities 首城不一致，应以 cities 为准纠正
        start_date="2026-10-01",
        end_date="2026-10-03",
        cities=[
            {"city": "杭州", "days": 2},
            {"city": "苏州", "days": 1},
        ],
    )
    assert request.city == "杭州"
    assert [c.city for c in request.cities] == ["杭州", "苏州"]
    assert [c.days for c in request.cities] == [2, 1]


# ==================== 天气联动：雨天日期判定 ====================


def test_find_rainy_dates_filters_trip_range():
    """雨天判定：仅白天或夜间含'雨'算雨天，且只保留行程日期范围内的结果。"""
    from app.tasks import _find_rainy_dates

    forecasts = [
        {"date": "2026-10-01", "day_weather": "雨", "night_weather": "小雨"},
        {"date": "2026-10-02", "day_weather": "晴", "night_weather": "多云"},
        {"date": "2026-10-03", "day_weather": "阴", "night_weather": "雨"},
        {"date": "2026-10-04", "day_weather": "雨", "night_weather": "雨"},  # 行程外，应被过滤
        {"date": "2026-09-30", "day_weather": "小雨", "night_weather": "阴"},  # 行程前，应被过滤
    ]
    rainy = _find_rainy_dates(forecasts, "2026-10-01", "2026-10-03")
    assert rainy == ["2026-10-01", "2026-10-03"]


# ==================== 个性化推荐：多来源加权打分 ====================


def test_score_recommendation_cities_weights():
    """推荐打分：收藏+2、正向记忆+2、历史行程+1、知识库+1，按分数降序。"""
    from app.api.routes.trip import _score_recommendation_cities

    scored = _score_recommendation_cities(
        favorite_cities=["杭州", "杭州", "苏州"],  # 杭州 +4、苏州 +2
        memory_cities=["杭州", "南京"],  # 杭州 +2、南京 +2
        history_cities=["苏州"],  # 苏州 +1
        knowledge_cities=["苏州", "北京"],  # 苏州 +1、北京 +1
    )
    info_by_city = dict(scored)
    assert info_by_city["杭州"]["score"] == 6
    assert info_by_city["苏州"]["score"] == 4
    assert info_by_city["南京"]["score"] == 2
    assert info_by_city["北京"]["score"] == 1

    cities = [city for city, _ in scored]
    assert cities.index("杭州") < cities.index("苏州") < cities.index("南京") < cities.index("北京")
