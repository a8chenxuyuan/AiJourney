"""planning（编排层）提示词包：M4 起模板外置 workspace/prompts/*.md，本包惰性加载。

历史形态（一 agent 一文件的 Python 常量）已迁移到 backend/workspace/prompts/，
改 prompt 改 md 文件即生效（mtime 缓存热加载，见 agentkit/prompt_loader）。
节点调用方式不变（prompts.PLANNER_SYSTEM_PROMPT 等），经包级 __getattr__
在访问时从 md 文件装载，保持 .format() 渲染口径不变。
"""

from typing import Any

from app.agentkit.prompt_loader import get_prompt

# 模板键清单（= workspace/prompts/ 下的 md 文件名去后缀）
__all__ = [
    "INTENT_SYSTEM_PROMPT",
    "INTENT_HUMAN_TEMPLATE",
    "PLANNER_SYSTEM_PROMPT",
    "PLANNER_HUMAN_TEMPLATE",
    "MULTI_CITY_PLANNER_SYSTEM_PROMPT",
    "MULTI_CITY_HUMAN_TEMPLATE",
    "REFLECT_SYSTEM_PROMPT",
    "MEMORY_CONSOLIDATOR_SYSTEM_PROMPT",
    "MEMORY_CONSOLIDATOR_HUMAN_TEMPLATE",
    "FEEDBACK_EXTRACTOR_SYSTEM_PROMPT",
    "FEEDBACK_EXTRACTOR_HUMAN_TEMPLATE",
    "PATCH_PLANNER_SYSTEM_PROMPT",
    "PATCH_PLANNER_HUMAN_TEMPLATE",
]


def __getattr__(name: str) -> Any:
    """PEP 562：模板常量在属性访问时才从外置 md 文件装载。"""
    if name in __all__:
        return get_prompt(name.lower())
    raise AttributeError(f"模块 {__name__} 无属性 {name}（模板键见 __all__）")
