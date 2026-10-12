"""
backend/app/services/memory_service.py

记忆服务模块。

作用：
- 管理行程版本链（PlanRevision）和用户反馈（PlanFeedback）的短期记忆；
- 管理用户长期语义偏好（UserPreferenceDB）和 episodic 记忆（UserMemory）；
- 把 episodic 记忆同步到 Qdrant，支持相似场景回忆；
- 在每次反馈后执行记忆固化（consolidation），把反馈中的偏好信号沉淀下来。

对应技术：
- SQLAlchemy async ORM
- Qdrant 向量库（复用 RAGService 的 embedding 能力）
"""

import asyncio
import json
import uuid
from typing import Any

from loguru import logger
from qdrant_client.models import PointStruct
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import db_models
from app.models.schemas import StructuredFeedback, TripPlan
from app.services.rag_service import RAGService, get_rag_service


class MemoryService:
    """
    记忆服务类。

    封装短期记忆（版本、反馈）和长期记忆（偏好、 episodic 记忆）的所有操作。
    """

    def __init__(self, rag_service: RAGService | None = None):
        """
        初始化记忆服务。

        Args:
            rag_service: 可选的 RAGService 实例，用于 episodic 记忆向量化。
        """
        # 默认使用全局单例，避免重复初始化 Qdrant 连接和嵌入模型
        self.rag = rag_service or get_rag_service()

    # ==================== 短期记忆：行程版本 ====================

    async def create_initial_revision(
        self, session: AsyncSession, plan_id: str, trip_plan: TripPlan
    ) -> db_models.PlanRevision:
        """
        为新建行程创建初始版本 v1。
        """
        # 清理旧的 current 标记（理论上不存在）
        await session.execute(
            update(db_models.PlanRevision)
            .where(db_models.PlanRevision.plan_id == plan_id)
            .values(is_current=False)
        )

        revision = db_models.PlanRevision(
            plan_id=plan_id,
            version=1,
            parent_revision_id=None,
            trip_plan_json=trip_plan.model_dump(mode="json"),
            is_current=True,
            source="initial",
        )
        session.add(revision)
        await session.flush()
        return revision

    async def create_revision(
        self,
        session: AsyncSession,
        plan_id: str,
        parent_revision_id: int,
        trip_plan: TripPlan,
        source: str = "patch",
        diff_summary: dict[str, Any] | None = None,
    ) -> db_models.PlanRevision:
        """
        基于父版本创建新版本，并自动提升版本号、更新 current 标记。

        Args:
            session: 异步数据库会话。
            plan_id: 行程计划 ID。
            parent_revision_id: 父版本 ID。
            trip_plan: 新的 TripPlan 对象。
            source: 版本来源（patch / full / regenerate）。
            diff_summary: 本次修订的差异摘要（可选），由 finalize_node 计算后传入，
                存到 revision 记录的 metadata 字段，前端可基于此展示"修改了 N 处"。
        """
        parent = await session.get(db_models.PlanRevision, parent_revision_id)
        if parent is None:
            raise RuntimeError(f"父版本不存在: {parent_revision_id}")

        next_version = parent.version + 1

        await session.execute(
            update(db_models.PlanRevision)
            .where(db_models.PlanRevision.plan_id == plan_id)
            .values(is_current=False)
        )

        revision = db_models.PlanRevision(
            plan_id=plan_id,
            version=next_version,
            parent_revision_id=parent_revision_id,
            trip_plan_json=trip_plan.model_dump(mode="json"),
            is_current=True,
            source=source,
            diff_summary=diff_summary or {},
        )
        session.add(revision)
        await session.flush()
        return revision

    async def get_current_revision(
        self, session: AsyncSession, plan_id: str
    ) -> db_models.PlanRevision | None:
        """
        获取某 plan_id 当前生效的版本，同时预加载关联反馈。
        """
        result = await session.execute(
            select(db_models.PlanRevision)
            .where(
                db_models.PlanRevision.plan_id == plan_id,
                db_models.PlanRevision.is_current.is_(True),
            )
            .options(selectinload(db_models.PlanRevision.feedbacks))
        )
        return result.scalar_one_or_none()

    async def get_revision_history(
        self, session: AsyncSession, plan_id: str
    ) -> list[db_models.PlanRevision]:
        """
        获取某 plan_id 的版本历史，按版本号升序。
        """
        result = await session.execute(
            select(db_models.PlanRevision)
            .where(db_models.PlanRevision.plan_id == plan_id)
            .options(selectinload(db_models.PlanRevision.feedbacks))
            .order_by(db_models.PlanRevision.version.asc())
        )
        return result.scalars().all()

    # ==================== 短期记忆：用户反馈 ====================

    async def create_feedback(
        self,
        session: AsyncSession,
        plan_id: str,
        revision_id: int,
        user_id: int,
        day_index: int | None,
        tags: list[str],
        raw_text: str,
        structured_feedback: StructuredFeedback | None = None,
    ) -> db_models.PlanFeedback:
        """
        创建一条用户反馈记录。
        """
        feedback = db_models.PlanFeedback(
            plan_id=plan_id,
            revision_id=revision_id,
            user_id=user_id,
            day_index=day_index,
            raw_text=raw_text,
            tags=tags,
            structured_feedback=structured_feedback.model_dump(mode="json")
            if structured_feedback
            else {},
            is_withdrawn=False,
        )
        session.add(feedback)
        await session.flush()
        return feedback

    async def update_feedback_revision_result(
        self, session: AsyncSession, feedback_id: int, revision_type: str, accepted_revision_id: int
    ) -> None:
        """
        反馈处理完成后，回写实际采用的修订策略和生成的版本 ID。
        """
        await session.execute(
            update(db_models.PlanFeedback)
            .where(db_models.PlanFeedback.id == feedback_id)
            .values(revision_type=revision_type, accepted_revision_id=accepted_revision_id)
        )

    async def update_feedback_structured(
        self, session: AsyncSession, feedback_id: int, structured_feedback: dict[str, Any]
    ) -> None:
        """
        回写 FeedbackExtractor 提取的结构化反馈。
        """
        await session.execute(
            update(db_models.PlanFeedback)
            .where(db_models.PlanFeedback.id == feedback_id)
            .values(structured_feedback=structured_feedback)
        )

    async def withdraw_feedback(self, session: AsyncSession, feedback_id: int) -> None:
        """
        撤回一条反馈。

        注意：撤回不会自动回滚已生成的行程版本，仅标记该反馈失效。
        """
        await session.execute(
            update(db_models.PlanFeedback)
            .where(db_models.PlanFeedback.id == feedback_id)
            .values(is_withdrawn=True)
        )

    async def edit_feedback(
        self,
        session: AsyncSession,
        feedback_id: int,
        day_index: int | None,
        tags: list[str],
        raw_text: str,
    ) -> db_models.PlanFeedback:
        """
        编辑反馈：旧记录标记为被替代，新建一条反馈记录。

        返回新的反馈对象。
        """
        old = await session.get(db_models.PlanFeedback, feedback_id)
        if old is None:
            raise RuntimeError(f"反馈不存在: {feedback_id}")

        new_feedback = db_models.PlanFeedback(
            plan_id=old.plan_id,
            revision_id=old.revision_id,
            user_id=old.user_id,
            day_index=day_index,
            raw_text=raw_text,
            tags=tags,
            structured_feedback={},
            is_withdrawn=False,
        )
        session.add(new_feedback)
        await session.flush()

        old.edited_by_feedback_id = new_feedback.id
        old.is_withdrawn = True
        await session.flush()
        return new_feedback

    async def get_active_feedbacks(
        self, session: AsyncSession, plan_id: str
    ) -> list[db_models.PlanFeedback]:
        """
        获取某 plan_id 下未撤回、未被编辑替代的有效反馈列表。
        """
        result = await session.execute(
            select(db_models.PlanFeedback)
            .where(
                db_models.PlanFeedback.plan_id == plan_id,
                db_models.PlanFeedback.is_withdrawn.is_(False),
                db_models.PlanFeedback.edited_by_feedback_id.is_(None),
            )
            .order_by(db_models.PlanFeedback.created_at.asc())
        )
        return result.scalars().all()

    async def aggregate_active_feedbacks(
        self, session: AsyncSession, plan_id: str
    ) -> tuple[str, list[db_models.PlanFeedback]]:
        """
        聚合某 plan_id 下所有有效反馈为一段综合修改意见。

        返回 (aggregated_notes, feedbacks)。
        """
        feedbacks = await self.get_active_feedbacks(session, plan_id)
        if not feedbacks:
            return "", []

        lines = []
        for fb in feedbacks:
            day_label = f"第{fb.day_index}天" if fb.day_index is not None else "整体"
            tags = ", ".join(fb.tags or [])
            prefix = f"[{day_label}]"
            if tags:
                prefix += f"({tags})"
            lines.append(f"{prefix} {fb.raw_text}")

        return "\n".join(lines), feedbacks

    # ==================== 长期记忆：偏好固化 ====================

    async def consolidate_memory(
        self,
        session: AsyncSession,
        user_id: int,
        city: str,
        structured_feedback: StructuredFeedback,
        raw_text: str,
    ) -> None:
        """
        把反馈中提取的偏好信号沉淀为长期记忆。

        同时更新 UserPreference 抽象偏好和 UserMemory 具体事件记忆。
        """
        preference = await self.get_or_create_preference(session, user_id)
        current_prefs = json.loads(preference.preference_data) if preference.preference_data else {}

        signals = structured_feedback.preference_signals or []

        # 1. 更新抽象偏好
        for signal in signals:
            sig_type = signal.get("type")
            value = signal.get("value")
            if sig_type and value is not None:
                # 简单累加策略：同类型覆盖，新类型追加
                current_prefs[sig_type] = value

        # 2. 写入 UserMemory 具体事件记忆
        for action in structured_feedback.actions:
            action_type = action.type if hasattr(action, "type") else action.get("type")
            action_name = action.name if hasattr(action, "name") else action.get("name")
            action_target_name = (
                action.target_name if hasattr(action, "target_name") else action.get("target_name")
            )
            action_reason = action.reason if hasattr(action, "reason") else action.get("reason")

            memory_type = self._action_to_memory_type(action_type)
            if memory_type is None:
                continue

            entity_name = action_name or action_target_name
            reason = action_reason or ""
            context = f"用户反馈：{raw_text}"
            sentiment = (
                "negative" if "dislike" in memory_type or "remove" in memory_type else "positive"
            )

            memory = db_models.UserMemory(
                user_id=user_id,
                memory_type=memory_type,
                entity_name=entity_name,
                city=city,
                sentiment=sentiment,
                reason=reason,
                context=context,
            )
            session.add(memory)
            await session.flush()

            # 3. 同步到 Qdrant
            try:
                await self._sync_memory_to_qdrant(memory)
            except Exception as e:
                # 向量库失败不应阻断主流程
                logger.exception(f"[MemoryService] 同步 episodic 记忆到 Qdrant 失败: {e}")

        preference.preference_data = json.dumps(current_prefs, ensure_ascii=False)
        await session.flush()

    @staticmethod
    async def get_or_create_preference(
        session: AsyncSession, user_id: int
    ) -> db_models.UserPreferenceDB:
        """
        获取或创建用户偏好记录。
        """
        result = await session.execute(
            select(db_models.UserPreferenceDB).where(db_models.UserPreferenceDB.user_id == user_id)
        )
        preference = result.scalar_one_or_none()
        if preference is None:
            preference = db_models.UserPreferenceDB(user_id=user_id)
            session.add(preference)
            await session.flush()
        return preference

    @staticmethod
    def format_preference_for_prompt(preference: db_models.UserPreferenceDB) -> str:
        """
        将用户偏好对象格式化为供 LLM 参考的文本。
        """
        if not preference:
            return "用户暂无历史偏好记录。"

        parts = []
        if preference.favorite_tags:
            parts.append(f"喜欢的标签：{', '.join(preference.favorite_tags)}")
        if preference.disliked_tags:
            parts.append(f"不喜欢的标签：{', '.join(preference.disliked_tags)}")
        if preference.budget_level:
            parts.append(f"预算等级：{preference.budget_level}")
        if preference.transportation:
            parts.append(f"偏好交通：{', '.join(preference.transportation)}")
        if preference.accommodation:
            parts.append(f"偏好住宿：{', '.join(preference.accommodation)}")
        if preference.dietary_restrictions:
            parts.append(f"饮食禁忌：{', '.join(preference.dietary_restrictions)}")
        if preference.visited_cities:
            parts.append(f"去过的城市：{', '.join(preference.visited_cities)}")
        if preference.preference_data:
            try:
                data = json.loads(preference.preference_data)
                if data:
                    items = [f"{k}={v}" for k, v in data.items()]
                    parts.append(f"学习到的偏好：{', '.join(items)}")
            except Exception:
                pass

        return "；".join(parts) if parts else "用户暂无历史偏好记录。"

    @staticmethod
    async def update_preference(
        session: AsyncSession, user_id: int, updates: dict[str, Any]
    ) -> db_models.UserPreferenceDB:
        """
        更新用户偏好记录。
        """
        preference = await MemoryService.get_or_create_preference(session, user_id)

        for key, value in updates.items():
            if hasattr(preference, key) and key != "user_id":
                setattr(preference, key, value)

        await session.flush()
        return preference

    async def _sync_memory_to_qdrant(self, memory: db_models.UserMemory) -> None:
        """
        把 UserMemory 文本写入 Qdrant 向量库，供后续相似场景检索。
        """
        text = (
            f"{memory.memory_type}: {memory.entity_name or ''}. "
            f"{memory.reason or ''}. {memory.context or ''}"
        )
        embedding = (await asyncio.to_thread(self.rag.embed_texts, [text]))[0]
        point_id = str(uuid.uuid4())

        # 确保集合存在，避免首次写入失败
        await asyncio.to_thread(self.rag._ensure_collection)

        await asyncio.to_thread(
            self.rag.client.upsert,
            collection_name=self.rag.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "memory_id": memory.id,
                        "user_id": memory.user_id,
                        "memory_type": memory.memory_type,
                        "entity_name": memory.entity_name,
                        "city": memory.city,
                        "sentiment": memory.sentiment,
                        "reason": memory.reason,
                        "context": memory.context,
                        "source_type": "user_memory",
                    },
                )
            ],
        )

        memory.embedding_id = point_id

    def _action_to_memory_type(self, action_type: str | None) -> str | None:
        """
        把反馈动作映射为记忆类型。
        """
        mapping = {
            "add_attraction": "attraction_like",
            "remove_attraction": "attraction_dislike",
            "replace_meal": "restaurant_preference",
            "replace_hotel": "hotel_preference",
        }
        return mapping.get(action_type)

    async def retrieve_relevant_memories(
        self, query: str, user_id: int, city: str | None = None, top_k: int = 3
    ) -> list[dict[str, Any]]:
        """
        从 Qdrant 检索与当前查询相关的用户 episodic 记忆。
        """
        try:
            embedding = (await asyncio.to_thread(self.rag.embed_texts, [query]))[0]
            filter_condition = {
                "must": [
                    {"key": "user_id", "match": {"value": user_id}},
                    {"key": "source_type", "match": {"value": "user_memory"}},
                ]
            }
            if city:
                filter_condition["must"].append({"key": "city", "match": {"value": city}})

            response = await asyncio.to_thread(
                self.rag.client.query_points,
                collection_name=self.rag.collection_name,
                query=embedding,
                limit=top_k,
                query_filter=filter_condition,
            )
            results = response.points

            return [
                {
                    "memory_type": r.payload.get("memory_type"),
                    "entity_name": r.payload.get("entity_name"),
                    "sentiment": r.payload.get("sentiment"),
                    "reason": r.payload.get("reason"),
                    "score": r.score,
                }
                for r in results
            ]
        except Exception as e:
            logger.exception(f"[MemoryService] 检索 episodic 记忆失败: {e}")
            return []

    async def get_user_preference_dict(self, session: AsyncSession, user_id: int) -> dict[str, Any]:
        """
        获取用户抽象偏好字典。
        """
        preference = await self.get_or_create_preference(session, user_id)
        if preference.preference_data:
            return json.loads(preference.preference_data)
        return {}
