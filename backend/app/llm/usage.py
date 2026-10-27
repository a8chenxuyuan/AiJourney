"""llm（模型层）：token 用量统计。prompt 瘦身效果的度量地基（进程内聚合，不落库）。"""

from dataclasses import dataclass
from threading import Lock


@dataclass
class UsageRecord:
    plan_id: str
    agent: str
    prompt_tokens: int
    completion_tokens: int


class UsageRecorder:
    """按 agent 记录 token 用量，支持按 plan_id 汇总。"""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = Lock()

    def record(self, plan_id: str, agent: str, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            self._records.append(
                UsageRecord(plan_id, agent, int(prompt_tokens), int(completion_tokens))
            )

    def summary(self, plan_id: str | None = None) -> dict[str, dict[str, int]]:
        """按 agent 汇总 token 用量；传 plan_id 只统计该次规划。"""
        with self._lock:
            records = [r for r in self._records if plan_id is None or r.plan_id == plan_id]
        result: dict[str, dict[str, int]] = {}
        for r in records:
            agg = result.setdefault(r.agent, {"prompt_tokens": 0, "completion_tokens": 0})
            agg["prompt_tokens"] += r.prompt_tokens
            agg["completion_tokens"] += r.completion_tokens
        return result


usage_recorder = UsageRecorder()


def record_llm_usage(plan_id: str, agent: str, message: object) -> None:
    """从 LangChain AIMessage 的 usage_metadata 提取并记录用量（无用量信息时静默跳过）。"""
    meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return
    usage_recorder.record(plan_id, agent, meta.get("input_tokens", 0), meta.get("output_tokens", 0))
