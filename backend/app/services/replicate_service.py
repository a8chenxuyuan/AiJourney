"""内容复刻服务：攻略文本 → 行程 JSON（单次 LLM 调用，不走规划 graph）。

攻略没有原行程可拷（不同于游记 fork 的快照复制），需要 AI 把攻略内容
转写为与规划引擎同构的 TripPlan。之所以不用多智能体 graph：源内容已确定、
无需实时搜集，单次调用延迟低、失败点少；本函数保持独立，未来若要
"复刻时实时比价/查天气"，可作为规划 graph 的一个入口节点直接复用。
"""

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.core.utils.json_parser import parse_llm_json
from app.llm.client import get_llm
from app.models.schemas import TripPlan

# 源内容截断长度（控制 token，超出部分丢弃不影响主行程骨架）
_SOURCE_LIMIT = 6000

_SYSTEM_PROMPT = """你是资深旅行规划师。把用户提供的旅行攻略/游记转写为结构化行程 JSON，
直接输出 JSON，不要输出任何其他文字。

输出 schema：
{
  "city": "主城市名",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "travel_days": 天数,
  "overall_suggestions": "整体建议（100字内）",
  "style": "relaxed",
  "day_plans": [
    {
      "day_index": 1,
      "date": "YYYY-MM-DD",
      "description": "当日主题（一句话）",
      "attractions": [
        {"name": "景点名", "location": {"longitude": 经度, "latitude": 纬度},
         "description": "一句话简介", "duration": "建议游玩时长", "ticket_price": 门票数字或null}
      ],
      "meals": [
        {"type": "breakfast|lunch|dinner", "name": "餐厅或美食名", "estimated_cost": 人均数字或null}
      ],
      "hotel": {"name": "酒店名", "location": {"longitude": 0, "latitude": 0},
                "price_per_night": 价格数字或null},
      "transportation": "当日交通建议（一句话）"
    }
  ],
  "budget": {"attractions": 0, "meals": 0, "hotels": 0, "transportation": 0,
             "total": 0, "currency": "CNY"}
}

硬性要求：
1. day_plans 按攻略实际天数拆分；攻略无明确天数则按内容量拆 2-4 天；
2. 景点/餐厅/酒店必须来自攻略原文，不得凭空捏造；每天至少 1 个景点，三餐尽量给出；
3. 每个景点和酒店必须带 location 字段，经纬度知道大致值就填，不知道填 0 和 0，绝不能省略；
4. date 从 start_date 起逐日递增，end_date = start_date + (travel_days - 1) 天；
5. 金额一律为数字不带单位。"""


async def build_plan_from_text(
    source_text: str, start_date: str, travel_days: int | None = None
) -> TripPlan:
    """
    把攻略/游记文本转写为 TripPlan（带一次重试）。

    Args:
        source_text: 攻略/游记正文。
        start_date: 出发日期 YYYY-MM-DD。
        travel_days: 目标天数（可选，不传由 LLM 按内容决定）。

    Returns:
        TripPlan: 解析校验后的完整行程。

    Raises:
        ValueError: 两次生成均无法解析为有效行程。
    """
    days_line = f"目标天数：{travel_days} 天" if travel_days else "天数：由攻略内容决定"
    human = (
        f"出发日期：{start_date}\n{days_line}\n\n"
        f"攻略/游记原文：\n{source_text[:_SOURCE_LIMIT]}"
    )
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]

    last_error: Exception | None = None
    for attempt, (temperature, timeout) in enumerate(((0.3, 180), (0.3, 120)), start=1):
        try:
            llm = get_llm(temperature=temperature, timeout=timeout)
            response = await llm.ainvoke(messages)
            plan = parse_llm_json(str(response.content), TripPlan)
            if plan is None:
                raise ValueError("LLM 输出无法解析为 TripPlan")
            if not plan.day_plans:
                raise ValueError("生成的行程没有任何 day_plans")
            return plan
        except Exception as exc:
            last_error = exc
            logger.warning(f"[Replicate] 行程生成第 {attempt} 次失败: {exc}")

    raise ValueError(f"AI 未能从该攻略生成有效行程，请稍后重试（{last_error}）")
