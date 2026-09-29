"""
backend/app/services/llm_service.py

LLM 服务封装模块。

作用：
- 统一创建和配置 LangChain ChatModel；
- 屏蔽底层 LLM 提供商差异，项目主要使用百炼（DashScope）OpenAI 兼容接口；
- 为所有 Agent 提供统一的 LLM 实例。

对应技术：
- LangChain：ChatOpenAI
- 百炼：OpenAI 兼容接口
"""

from langchain_openai import ChatOpenAI
from app.config import settings


def get_llm(temperature: float = None, model_id: str = None, timeout: int = None) -> ChatOpenAI:
    """
    获取配置好的 LangChain ChatModel 实例。

    Args:
        temperature: 温度参数，控制输出随机性。不传则使用配置默认值。
        model_id: 模型 ID。不传则使用配置默认值。
        timeout: 超时时间（秒）。不传则使用配置默认值。

    Returns:
        ChatOpenAI: 配置好的聊天模型实例。

    Raises:
        ValueError: 当未配置 LLM API Key 时抛出异常。
    """
    if not settings.llm_api_key:
        raise ValueError("未配置 LLM_API_KEY，请在 .env 文件中设置百炼 API Key")

    return ChatOpenAI(
        model=model_id or settings.llm_model_id,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature if temperature is not None else settings.llm_temperature,
        timeout=timeout if timeout is not None else settings.agent_timeout,
        max_retries=settings.agent_max_retries
    )
