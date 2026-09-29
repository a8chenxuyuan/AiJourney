"""
backend/app/agents/config.py

Agent 运行时配置模块。

作用：
- 集中管理 Agent 专有的运行参数；
- 从全局 Settings 读取 LLM、重试、超时等配置；
- 为 nodes.py 和 graph.py 提供统一的配置入口。

对应技术：
- pydantic-settings：统一配置
"""

from app.config import settings


class AgentConfig:
    """
    Agent 配置类。

    该类只包含类属性，用于在 Agent 节点内部快速读取配置，
    避免在多个节点中重复引用 settings。
    """

    # LLM 温度参数，越低输出越稳定
    llm_temperature: float = settings.llm_temperature

    # Agent 调用失败后的最大重试次数
    max_retries: int = settings.agent_max_retries

    # LLM 单次调用超时时间（秒）
    timeout: int = settings.agent_timeout

    # 默认生成候选方案数量（紧凑、休闲、省钱等）
    candidate_plan_count: int = 1

    # 每天建议安排的景点数量上限
    max_attractions_per_day: int = 4

    # 每天建议安排的景点数量下限
    min_attractions_per_day: int = 2
