"""travel（领域层）：预算模型与阈值校验。M3 HITL 超支判定的领域依据。"""

from app.models.schemas import TripPlan

# 各预算档位的日均总预算上限（元/天），HITL 超支判定基准
DAILY_BUDGET_LIMITS: dict[str, float] = {
    "economy": 300.0,
    "standard": 800.0,
    "luxury": 2000.0,
}

# 总预算超过该档位限额的倍数即视为超支（触发人工审批）
OVERRUN_ALERT_RATIO = 1.2

_BUDGET_FIELDS = ("attractions", "meals", "hotels", "transportation")


def budget_total(plan: TripPlan) -> float:
    """汇总行程预算总额：优先取 total 字段，缺失时逐项求和。"""
    budget = getattr(plan, "budget", None)
    if budget is None:
        return 0.0
    total = getattr(budget, "total", None)
    if isinstance(total, (int, float)) and total > 0:
        return float(total)
    return sum(
        float(v)
        for field in _BUDGET_FIELDS
        if isinstance((v := getattr(budget, field, None)), (int, float))
    )


def check_budget_overrun(plan: TripPlan, budget_level: str | None) -> dict | None:
    """判定行程是否超出预算档位阈值。

    Returns:
        超支明细（total/daily_limit/days/ratio）；未超支或无法判定时返回 None。
    """
    if plan is None:
        return None
    limit = DAILY_BUDGET_LIMITS.get(budget_level or "standard", DAILY_BUDGET_LIMITS["standard"])
    days = max(1, int(getattr(plan, "travel_days", 0) or 1))
    total = budget_total(plan)
    if total <= 0:
        return None
    if total <= limit * days * OVERRUN_ALERT_RATIO:
        return None
    return {
        "total": round(total, 2),
        "daily_limit": limit,
        "days": days,
        "ratio": round(total / (limit * days), 2),
    }
