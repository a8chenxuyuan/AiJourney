"""
backend/app/agentkit/memory.py

agentkit（框架层）：跨会话记忆框架（读写接口）。

作用：
- 写：finalize 成功后提取用户规划事实（去过城市/预算档位/行程节奏），
  落 user_facts 表（规划事实流水账，区别于 user_memories 的实体好恶记忆）；
- 读：MemoryLayer 按用户取最近 top-k 事实，经 context_manager 装配注入后续规划的 prompt。

对应技术：
- SQLAlchemy：异步读写 user_facts 表
"""

from loguru import logger
from sqlalchemy import select

from app.core.db.session import AsyncSessionLocal
from app.models.db_models import UserFactDB


async def save_user_facts(
    user_id: int | None, facts: list[dict[str, str]], source_plan_id: str | None = None
) -> int:
    """写入用户规划事实；与该用户已有事实内容重复的自动去重。

    Args:
        user_id: 用户 ID；为空时直接跳过（匿名场景不落记忆）。
        facts: 事实列表，每项 {"kind": 类型, "content": 内容}。
        source_plan_id: 来源行程 ID，用于回溯。

    Returns:
        int: 实际新增条数。
    """
    if not user_id or not facts:
        return 0
    async with AsyncSessionLocal() as session:
        existing = {
            c.strip()
            for c in (
                await session.execute(
                    select(UserFactDB.content).where(UserFactDB.user_id == user_id)
                )
            ).scalars()
        }
        rows = []
        for fact in facts:
            content = str(fact.get("content", "")).strip()
            kind = str(fact.get("kind", "fact")).strip() or "fact"
            if not content or content in existing:
                continue
            existing.add(content)
            rows.append(
                UserFactDB(
                    user_id=user_id, kind=kind, content=content, source_plan_id=source_plan_id
                )
            )
        if not rows:
            return 0
        session.add_all(rows)
        await session.commit()
        return len(rows)


async def load_user_facts(
    user_id: int | None, limit: int = 10, kinds: list[str] | None = None
) -> list[UserFactDB]:
    """读取用户最近的规划事实（可按 kind 过滤，按时间倒序取 limit 条）。"""
    if not user_id:
        return []
    async with AsyncSessionLocal() as session:
        query = select(UserFactDB).where(UserFactDB.user_id == user_id)
        if kinds:
            query = query.where(UserFactDB.kind.in_(kinds))
        query = query.order_by(UserFactDB.id.desc()).limit(limit)
        return list((await session.execute(query)).scalars().all())


class MemoryLayer:
    """上下文装配的记忆层：把跨会话规划事实格式化为注入文本块。

    层协议：name 属性 + async build(plan_id, agent_name, **ctx) -> str | None。
    """

    name = "memory"

    def __init__(self, limit: int = 10) -> None:
        self.limit = limit

    async def build(
        self, plan_id: str, agent_name: str, user_id: int | None = None, **ctx: object
    ) -> str | None:
        """构建记忆文本块；无记忆时返回 None（不注入）。"""
        facts = await load_user_facts(user_id, limit=self.limit)
        if not facts:
            return None
        lines = [f"- [{fact.kind}] {fact.content}" for fact in facts]
        logger.info(f"[MemoryLayer] 为 {agent_name}(plan={plan_id}) 注入 {len(facts)} 条历史规划记忆")
        return "用户历史规划记忆（跨会话事实，供参考）：\n" + "\n".join(lines)
