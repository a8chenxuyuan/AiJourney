"""llm（模型层）：统一 LLM 客户端，普通/流式两种调用形态。"""

from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_llm(
    temperature: float | None = None,
    model_id: str | None = None,
    timeout: int | None = None,
    streaming: bool = False,
) -> ChatOpenAI:
    """获取配置好的 ChatModel 实例；streaming=True 用于 token 级流式输出。"""
    if not settings.llm_api_key:
        raise ValueError("未配置 LLM_API_KEY，请在 .env 文件中设置百炼 API Key")

    return ChatOpenAI(
        model=model_id or settings.llm_model_id,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature if temperature is not None else settings.llm_temperature,
        timeout=timeout if timeout is not None else settings.agent_timeout,
        max_retries=settings.agent_max_retries,
        streaming=streaming,
    )
