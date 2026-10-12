"""
backend/app/config.py

全局配置管理模块。

作用：
- 使用 pydantic-settings 从 .env 文件和环境变量中读取配置；
- 集中管理数据库、LLM、JWT、高德地图、RAG、爬虫、支付等所有配置项；
- 提供统一的 Settings 单例，供整个后端使用。

对应技术：
- pydantic-settings：类型安全的配置加载
- python-dotenv：自动读取 .env 文件
"""

from pathlib import Path
from typing import List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend 目录），用于定位 .env 文件
_BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    应用配置类。

    所有配置项都从这里读取，支持环境变量覆盖和 .env 文件。
    配置项按功能分组：应用、数据库、认证、LLM、地图、RAG、爬虫、支付。
    """

    # ------------------- 应用基础配置 -------------------
    app_name: str = Field(default="agent1旅行", description="应用名称")
    environment: str = Field(default="development", description="运行环境")
    port: int = Field(default=8000, description="服务监听端口")
    debug: bool = Field(default=True, description="是否开启调试模式")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="允许跨域的前端地址，逗号分隔",
    )

    # ------------------- 数据库配置 -------------------
    database_url: str = Field(
        default="sqlite+aiosqlite:///./agent1travel.db", description="数据库连接 URL"
    )

    # ------------------- JWT 认证配置 -------------------
    jwt_secret_key: str = Field(
        default="your-super-secret-jwt-key-change-this-in-production", description="JWT 签名密钥"
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT 签名算法")
    jwt_expire_minutes: int = Field(default=1440, description="JWT 过期时间（分钟）")

    # ------------------- LLM 配置（百炼） -------------------
    llm_api_key: str = Field(default="", description="百炼 API Key")
    llm_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="OpenAI 兼容接口地址",
    )
    llm_model_id: str = Field(default="qwen-max-latest", description="默认模型 ID")
    llm_temperature: float = Field(default=0.3, description="LLM 温度参数")
    agent_max_retries: int = Field(default=3, description="Agent 最大重试次数")
    agent_timeout: int = Field(default=60, description="Agent 调用超时（秒）")

    # ------------------- 高德地图 MCP 配置 -------------------
    amap_api_key: str = Field(default="", description="高德地图 API Key")

    # ------------------- RAG / 向量库配置 -------------------
    qdrant_url: str = Field(default="http://localhost:6333", description="Qdrant 地址")
    qdrant_collection: str = Field(default="agent1travel_knowledge", description="Qdrant 集合名称")
    embedding_model_name: str = Field(
        default="BAAI/bge-large-zh-v1.5", description="Embedding 模型名称"
    )
    rag_top_k: int = Field(default=5, description="RAG 检索 Top-K")

    # ------------------- Redis 缓存配置（可选） -------------------
    redis_url: Optional[str] = Field(default=None, description="Redis 连接 URL")

    # ------------------- 爬虫配置 -------------------
    crawler_enabled: bool = Field(default=False, description="是否启用定时爬虫")
    crawler_schedule: str = Field(default="0 3 * * 1", description="爬虫定时 cron 表达式")
    crawler_delay: int = Field(default=2, description="爬虫请求间隔（秒）")
    crawler_max_pages: int = Field(default=100, description="单次最大抓取页面数")

    # ------------------- 支付配置（沙箱） -------------------
    payment_sandbox: bool = Field(default=True, description="是否启用支付沙箱")
    alipay_app_id: Optional[str] = Field(default=None, description="支付宝沙箱 APP ID")
    alipay_public_key: Optional[str] = Field(default=None, description="支付宝沙箱公钥")
    alipay_private_key: Optional[str] = Field(default=None, description="支付宝沙箱私钥")

    # 配置 pydantic-settings 从 .env 文件读取
    # 使用相对于当前配置文件的绝对路径，确保无论从哪个工作目录启动都能找到 backend/.env
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略未定义的环境变量，避免启动失败
    )

    @validator("cors_origins", pre=True)
    def parse_cors_origins(cls, v: str) -> str:
        """
        校验 CORS _ORIGINS 是否为字符串。

        后续 api/main.py 会将其按逗号拆分为列表。
        """
        return v

    def get_cors_origins(self) -> List[str]:
        """
        将 cors_origins 字符串拆分为列表。

        Returns:
            List[str]: 允许跨域的前端地址列表。
        """
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


# 全局 Settings 单例
# 在应用启动时创建一次，后续所有模块通过 from app.config import settings 引用
settings = Settings()
