"""
backend/app/models/schema_common.py

通用/共享 Pydantic 模型。

作用：
- 定义跨域复用的响应包装、位置、Agent 执行日志等模型；
- 原 schemas.py 按域拆分而来。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StandardResponse(BaseModel):
    """
    通用标准响应模型。

    所有 API 接口成功或失败时都建议使用该结构包装，方便前端统一处理。
    """

    success: bool = Field(description="请求是否成功")
    message: str = Field(default="", description="提示信息")
    data: Any | None = Field(default=None, description="响应数据")


class Location(BaseModel):
    """
    经纬度位置模型。

    用于景点、酒店、POI 等任何需要地图坐标的实体。
    """

    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")
    address: str | None = Field(default=None, description="详细地址")


class AgentLog(BaseModel):
    """
    Agent 执行日志模型。

    用于前端实时展示每个 Agent 的执行过程。
    """

    step: str = Field(..., description="步骤名称")
    agent_name: str = Field(..., description="Agent 名称")
    input_preview: str | None = Field(default=None, description="输入摘要")
    output_preview: str | None = Field(default=None, description="输出摘要")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, description="工具调用记录")
    timestamp: datetime = Field(default_factory=datetime.now, description="执行时间")
    duration_ms: int | None = Field(default=None, description="执行耗时（毫秒）")


__all__ = [
    "AgentLog",
    "Location",
    "StandardResponse",
]
