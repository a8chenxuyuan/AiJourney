"""对话式修改助手：意图提取、上下文组装与反馈落库。"""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_accessible_plan, get_current_user
from app.db.session import get_db
from app.models.db_models import (
    TripPlanDB,
    User,
)
from app.models.schemas import (
    PlanChatRequest,
    StandardResponse,
)
from app.services.llm_service import get_llm
from app.services.memory_service import MemoryService

router = APIRouter()

# ==================== 对话式修改助手 ====================

# 对话意图提取的系统提示词：让 LLM 输出严格 JSON，
# intent=feedback（修改意见）时附带 day_index/tags；intent=question（咨询）时 reply 直接回答。
CHAT_SYSTEM_PROMPT = """你是一个旅行行程助手的意图分析模块。
用户会针对已有的旅行行程输入一句话，你需要：
1. 判断意图：
   - "feedback"：用户提出了对行程的修改意见
     （如换景点/换餐厅/换酒店/行程太满/太赶/想加某地/想删某地/嫌贵等）；
   - "question"：用户在咨询行程相关信息（如天气、路线、建议、某个景点介绍等），不构成修改意见。
2. 若是 feedback，提取：
   - day_index：针对第几天（整数）；无法确定则为 null（表示整体意见）；
   - tags：从这些标签中选择最匹配的若干个：
     ["餐饮不满意","景点不喜欢","行程太满","想加某地","想删某地","换酒店","其他"]；
3. reply：用中文给用户一句自然、友好的回复
   （feedback 时要复述你理解到的意见以便用户确认；question 时直接基于行程上下文回答，
   回答要具体、简洁，不超过 120 字）。
4. 参考最近的对话历史理解指代（如"第二天也这样"）。

只输出如下 JSON，不要输出其他任何内容：
{"intent": "feedback|question", "day_index": null, "tags": [], "reply": "..."}"""


def _build_plan_digest(plan_data: dict) -> str:
    """
    _build_plan_digest：把行程 JSON 压缩成 LLM 可读的紧凑文本摘要。

    只保留 天数/景点名/餐饮名/酒店名/整体建议，避免超长 prompt。

    Args:
        plan_data: 行程结果 JSON（TripPlan 结构）。

    Returns:
        str: 多行文本摘要。
    """
    if not plan_data:
        return "（暂无行程数据）"

    lines: list[str] = []
    city = plan_data.get("city", "")
    days = plan_data.get("day_plans") or []
    lines.append(f"目的地：{city}，共 {plan_data.get('travel_days', len(days))} 天")

    for day in days:
        spots = "、".join([a.get("name", "?") for a in (day.get("attractions") or [])]) or "无"
        meals = (
            "、".join(
                [
                    f"{m.get('type', '')}{m.get('name', '')}"
                    for m in (day.get("meals") or [])
                    if m.get("name")
                ]
            )
            or "无"
        )
        hotel = (day.get("hotel") or {}).get("name", "无")
        lines.append(
            f"第{day.get('day_index', '?')}天：景点[{spots}]；餐饮[{meals}]；酒店[{hotel}]"
        )

    if plan_data.get("overall_suggestions"):
        lines.append(f"整体建议：{plan_data['overall_suggestions']}")
    return "\n".join(lines)


def _parse_chat_llm_output(text: str) -> dict | None:
    """
    _parse_chat_llm_output：解析 LLM 输出的意图 JSON（带容错）。

    处理两种常见情况：纯 JSON 字符串、被 ```json ... ``` 包裹的字符串。

    Args:
        text: LLM 原始输出。

    Returns:
        Optional[dict]: 解析成功返回字典，失败返回 None。
    """
    if not text:
        return None
    cleaned = text.strip()
    # 去掉 markdown 代码围栏
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def _load_chat_context(
    session: AsyncSession, plan_id: str, plan: TripPlanDB, chat: PlanChatRequest
) -> dict:
    """
    加载对话修改助手所需的上下文。

    汇总：当前生效版本行程数据、已有有效反馈、最近对话历史。

    Args:
        session: 数据库会话。
        plan_id: 行程计划 ID。
        plan: 行程计划记录。
        chat: 对话请求。

    Returns:
        dict: {"plan_data": 行程 JSON, "feedback_context": 已提交意见文本,
        "history_context": 对话历史文本}。
    """
    memory_service = MemoryService()
    # 行程摘要 + 当前生效版本
    current_revision = await memory_service.get_current_revision(session, plan_id)
    plan_data = current_revision.trip_plan_json if current_revision else plan.plan_data

    # 已有有效反馈（写入 prompt 让 LLM 知道用户已经提过什么，避免重复确认）
    active_feedbacks = await memory_service.get_active_feedbacks(session, plan_id)
    feedback_lines = [
        f"- 第{fb.day_index if fb.day_index else '整体'}天：{fb.raw_text}"
        for fb in active_feedbacks[-10:]  # 最多带最近 10 条，防止 prompt 过长
    ]
    feedback_context = "\n".join(feedback_lines) if feedback_lines else "（暂无）"

    # 对话历史（只取最近 6 轮，且保证是 user/assistant 两种角色）
    history_lines = [
        f"{('用户' if m.role == 'user' else '助手')}：{m.content}" for m in chat.history[-6:]
    ]
    history_context = "\n".join(history_lines) if history_lines else "（无）"

    return {
        "plan_data": plan_data,
        "feedback_context": feedback_context,
        "history_context": history_context,
    }


async def _extract_chat_intent(
    message: str, plan_data: dict, feedback_context: str, history_context: str
) -> dict:
    """
    调用 LLM 识别对话意图并提取结构化信息，失败时走关键词降级。

    Args:
        message: 用户本轮输入。
        plan_data: 行程 JSON。
        feedback_context: 已提交意见文本。
        history_context: 对话历史文本。

    Returns:
        dict: {"intent": "feedback|question", "day_index": Optional[int],
               "tags": List[str], "reply": str}。
    """
    # 组装 prompt 并调用 LLM
    user_prompt = (
        f"【当前行程】\n{_build_plan_digest(plan_data)}\n\n"
        f"【用户已提交的修改意见】\n{feedback_context}\n\n"
        f"【最近对话历史】\n{history_context}\n\n"
        f"【用户本轮输入】\n{message}"
    )

    parsed: dict | None = None
    try:
        llm = get_llm(temperature=0.3)
        result = await llm.ainvoke(
            [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        parsed = _parse_chat_llm_output(getattr(result, "content", "") or "")
    except Exception as e:
        logger.exception(f"[chat_with_plan] LLM 调用失败: {e}")

    if parsed and parsed.get("intent") in ("feedback", "question"):
        raw_day = parsed.get("day_index")
        raw_tags = parsed.get("tags")
        return {
            "intent": parsed["intent"],
            "day_index": raw_day if isinstance(raw_day, int) and raw_day >= 1 else None,
            "tags": [str(t) for t in raw_tags if t][:4] if isinstance(raw_tags, list) else [],
            "reply": str(parsed.get("reply") or "").strip(),
        }

    # 降级策略：JSON 解析失败时用关键词判断是否保存为整体意见
    modify_keywords = (
        "换",
        "删",
        "去掉",
        "添加",
        "加个",
        "加一",
        "太贵",
        "太满",
        "太赶",
        "不喜欢",
        "不想",
        "改成",
    )
    if any(k in message for k in modify_keywords):
        return {
            "intent": "feedback",
            "day_index": None,
            "tags": ["其他"],
            "reply": (
                "已记录你的意见（本次未识别到具体天数，将作为整体调整参与下次重新生成）。"
                "你可以继续补充，或点下方按钮重新生成行程。"
            ),
        }
    return {
        "intent": "question",
        "day_index": None,
        "tags": [],
        "reply": (
            "抱歉，我暂时没能理解这条消息。"
            "你可以试着描述想怎么修改行程，例如：'第二天太赶了，去掉一个景点'。"
        ),
    }


async def _persist_chat_feedback(
    session: AsyncSession, plan_id: str, user_id: int, message: str, intent_result: dict
) -> tuple[int | None, bool]:
    """
    feedback 意图时把对话内容写入反馈表（与手动反馈同表，不触发重排）。

    Args:
        session: 数据库会话。
        plan_id: 行程计划 ID。
        user_id: 当前用户 ID。
        message: 用户原始输入（作为反馈正文）。
        intent_result: _extract_chat_intent 的返回结果。

    Returns:
        Tuple[Optional[int], bool]: (feedback_id, 是否写入失败)。
        非 feedback 意图或无当前版本时返回 (None, False)；写库异常时返回 (None, True)。
    """
    if intent_result.get("intent") != "feedback":
        return None, False

    memory_service = MemoryService()
    try:
        current_revision = await memory_service.get_current_revision(session, plan_id)
        if not current_revision:
            return None, False
        feedback_record = await memory_service.create_feedback(
            session=session,
            plan_id=plan_id,
            revision_id=current_revision.id,
            user_id=user_id,
            day_index=intent_result.get("day_index"),
            tags=intent_result.get("tags") or [],
            raw_text=message,
        )
        await session.commit()
        return feedback_record.id, False
    except Exception as e:
        await session.rollback()
        logger.exception(f"[chat_with_plan] 反馈写入失败: {e}")
        return None, True


@router.post("/{plan_id}/chat", response_model=StandardResponse)
async def chat_with_plan(
    plan_id: str,
    chat: PlanChatRequest,
    plan: TripPlanDB = Depends(get_accessible_plan),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    对话式修改行程助手。

    流程：
    1. 校验行程计划存在、属于当前用户且已完成；
    2. 组装行程摘要 + 已有反馈 + 对话历史，调用 LLM 做意图识别与信息提取；
    3. intent=feedback → 提取结构化反馈写入数据库（与手动反馈同表，不立即触发重排）；
       intent=question → 直接返回 LLM 回答；
    4. 返回 reply 与反馈元信息（pending_count 供前端提示"已积累 N 条意见"）。

    LLM 调用失败时的降级策略：
    - 若用户消息包含明显修改关键词，按"整体意见"保存，回复确认语；
    - 否则返回兜底话术，不写库。

    Args:
        plan_id: 行程计划 ID。
        chat: 对话请求（message + history）。
        plan: 归属校验通过的行程计划（get_owned_plan 依赖注入）。
        current_user: 当前登录用户。
        session: 数据库会话。

    Returns:
        StandardResponse: reply、intent、day_index、tags、feedback_id、pending_count。

    职责拆分：
    - _load_chat_context：加载行程/反馈/对话历史上下文；
    - _extract_chat_intent：LLM 意图识别 + 关键词降级；
    - _persist_chat_feedback：feedback 意图落库。
    """
    if plan.status == "revising":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="行程正在修订中，请等待当前任务完成后再使用修改助手",
        )
    if plan.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"行程当前状态为 {plan.status}，暂无法使用修改助手",
        )

    context = await _load_chat_context(session, plan_id, plan, chat)
    intent = await _extract_chat_intent(
        message=chat.message,
        plan_data=context["plan_data"],
        feedback_context=context["feedback_context"],
        history_context=context["history_context"],
    )

    feedback_id, persist_failed = await _persist_chat_feedback(
        session=session,
        plan_id=plan_id,
        user_id=current_user.id,
        message=chat.message,
        intent_result=intent,
    )
    if persist_failed:
        intent["reply"] = "（意见记录失败，请稍后重试或使用手动反馈表单）" + intent["reply"]

    # 待处理反馈数（含本次）
    memory_service = MemoryService()
    active_feedbacks = await memory_service.get_active_feedbacks(session, plan_id)

    return StandardResponse(
        success=True,
        message="ok",
        data={
            "reply": intent["reply"],
            "intent": intent["intent"],
            "day_index": intent["day_index"],
            "tags": intent["tags"],
            "feedback_id": feedback_id,
            "pending_count": len(active_feedbacks),
        },
    )
