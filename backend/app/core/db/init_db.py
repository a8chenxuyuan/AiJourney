"""
backend/app/db/init_db.py

数据库初始化模块。

作用：
- 在应用启动时创建所有数据库表；
- 为已存在的旧表补建缺失的索引（幂等，CREATE INDEX IF NOT EXISTS）；
- 仅用于开发环境快速初始化；
- 生产环境建议使用 Alembic 进行迁移管理。

对应技术：
- SQLAlchemy：create_all、text DDL 执行
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.db.base import Base
from app.core.db.session import engine

# create_all 不会为"已存在的表"补充新增索引，
# 因此这里显式列出外键/高频查询字段的索引，使用 IF NOT EXISTS 保证幂等。
# 命名与 SQLAlchemy 默认约定 ix_<table>_<column> 一致。
# 说明：plan_collaborators / plan_invites 两张新表（多人协作）与 plan_notifications 一样，
# 由上方 Base.metadata.create_all 直接建表（含索引与唯一约束），无需在此登记。
_IDEMPOTENT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_plan_revisions_parent_revision_id "
    "ON plan_revisions (parent_revision_id)",
    "CREATE INDEX IF NOT EXISTS ix_plan_feedback_revision_id ON plan_feedback (revision_id)",
    "CREATE INDEX IF NOT EXISTS ix_plan_feedback_user_id ON plan_feedback (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_plan_feedback_accepted_revision_id "
    "ON plan_feedback (accepted_revision_id)",
    "CREATE INDEX IF NOT EXISTS ix_plan_feedback_edited_by_feedback_id "
    "ON plan_feedback (edited_by_feedback_id)",
    "CREATE INDEX IF NOT EXISTS ix_trip_plans_user_id ON trip_plans (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_plan_id ON orders (plan_id)",
    "CREATE INDEX IF NOT EXISTS ix_favorites_user_id ON favorites (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_plan_logs_plan_id ON plan_logs (plan_id)",
    "CREATE INDEX IF NOT EXISTS ix_trip_plans_share_token ON trip_plans (share_token)",
    "CREATE INDEX IF NOT EXISTS ix_favorites_city ON favorites (city)",
    "CREATE INDEX IF NOT EXISTS ix_community_posts_zone ON community_posts (zone)",
]

# create_all 同样不会为"已存在的表"补充新增列，
# 这里显式补齐后续版本新增的字段（SQLite 不支持 IF NOT EXISTS，依赖重复列异常吞掉保证幂等）。
# (表名, 列定义 DDL)
_IDEMPOTENT_COLUMNS = [
    ("trip_plans", "ALTER TABLE trip_plans ADD COLUMN share_token VARCHAR(64)"),
    ("trip_plans", "ALTER TABLE trip_plans ADD COLUMN share_expires_at DATETIME"),
    ("trip_plans", "ALTER TABLE trip_plans ADD COLUMN share_view_count INTEGER NOT NULL DEFAULT 0"),
    ("trip_plans", "ALTER TABLE trip_plans ADD COLUMN cities_json JSON"),
    ("favorites", "ALTER TABLE favorites ADD COLUMN city VARCHAR(100)"),
    ("community_posts", "ALTER TABLE community_posts ADD COLUMN zone VARCHAR(10)"),
    ("users", "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"),
    ("users", "ALTER TABLE users ADD COLUMN is_banned BOOLEAN NOT NULL DEFAULT 0"),
]


async def init_db() -> None:
    """
    初始化数据库表结构。

    根据 Base 的子类（即 db_models.py 中定义的所有模型）创建对应的数据库表。
    如果表已存在则不会重复创建（仅创建缺失的表，不修改已有表）。

    随后为旧表补建缺失索引与新增列（幂等，可重复执行）。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 先补列再建索引：索引可能依赖新增列，顺序不能颠倒
        for _table, ddl in _IDEMPOTENT_COLUMNS:
            try:
                await conn.execute(text(ddl))
            except OperationalError as exc:
                # SQLite 对重复添加列会报 duplicate column name，说明列已存在，直接忽略
                if "duplicate column name" not in str(exc).lower():
                    raise
        for ddl in _IDEMPOTENT_INDEXES:
            await conn.execute(text(ddl))
        # 社区双分区回填：只处理 zone IS NULL 的旧行（manual→circle，其余→note），
        # 新帖由 ORM 写入 zone，不会命中这两个 UPDATE，保证幂等
        await conn.execute(
            text(
                "UPDATE community_posts SET zone = 'circle' "
                "WHERE zone IS NULL AND post_type = 'manual'"
            )
        )
        await conn.execute(text("UPDATE community_posts SET zone = 'note' WHERE zone IS NULL"))
