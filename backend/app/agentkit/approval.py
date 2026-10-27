"""
backend/app/agentkit/approval.py

agentkit（框架层）：审批协议（M3 HITL）。

作用：
- 定义人工审批的三态决策常量（pending_approval / approved / rejected）；
- 提供审批请求的统一发布入口 request_approval()——事件经唯一总线发布，
  订阅方（SSE、trace 等）自行决定如何呈现，框架层不做业务落地。

约定：
- 触发暂停的业务节点把审批明细写入 state["approval_required"]，
  编排层检测到该标记后置行程为 pending_approval 并暂停批次执行（断点保留）；
- 审批决策经 API 层写回任务队列，恢复时注入 state["human_decisions"]。
"""

from typing import Any

from app.agentkit.events import APPROVAL_REQUIRED, publish

# ==================== 审批决策三态 ====================
# pending_approval：等待用户决策（行程状态机的暂停态，落 trip_plans.status）
APPROVAL_PENDING = "pending_approval"
# approved：用户同意（从断点续跑收尾批次）
APPROVAL_APPROVED = "approved"
# rejected：用户拒绝（清断点、行程置 failed）
APPROVAL_REJECTED = "rejected"


async def request_approval(plan_id: str, detail: dict[str, Any]) -> None:
    """向总线发布审批请求事件（approval_required）。

    Args:
        plan_id: 行程计划 ID。
        detail: 审批明细（如预算超支的 total/daily_limit/days/ratio）。
    """
    await publish(plan_id, APPROVAL_REQUIRED, **detail)
