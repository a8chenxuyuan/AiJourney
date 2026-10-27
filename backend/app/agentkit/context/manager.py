"""
backend/app/agentkit/context/manager.py

agentkit（框架层）：上下文装配唯一入口。

作用：
- assemble() 是所有节点 prompt 注入内容的唯一装配口；
- 可注册 Layer：MemoryLayer（用户记忆）、SkillLayer（技能，M4）、
  RagLayer（攻略上下文）、ArtifactLayer（工具结果摘要）——新上下文一律
  以 Layer 形式注册接入，节点禁止自行拼接注入字符串。

层协议：
    name: str
    async def build(plan_id, agent_name, **ctx) -> str | None
"""

from typing import Any

from loguru import logger

from app.agentkit.memory import MemoryLayer
from app.agentkit.skills import SkillLayer


class ContextManager:
    """Layer 注册表与装配器。"""

    def __init__(self) -> None:
        # dict 保持注册顺序：先注册的层排在注入文本前面
        self._layers: dict[str, Any] = {}

    def register(self, layer: Any) -> None:
        """注册上下文层（同名覆盖）。"""
        self._layers[layer.name] = layer

    async def assemble(
        self,
        plan_id: str,
        agent_name: str,
        layer_names: list[str] | None = None,
        **ctx: Any,
    ) -> str:
        """唯一装配入口：按注册顺序构建启用层并拼接为文本块。

        Args:
            plan_id: 行程计划 ID（层定位上下文用）。
            agent_name: 调用方 Agent 名。
            layer_names: 只装配指定层；None 表示全部已注册层。
            **ctx: 透传给层 build() 的上下文参数（如 user_id）。

        Returns:
            str: 拼接后的注入文本；全部层无内容时返回空串。
        """
        names = list(self._layers) if layer_names is None else layer_names
        chunks: list[str] = []
        for name in names:
            layer = self._layers.get(name)
            if layer is None:
                continue
            try:
                content = await layer.build(plan_id, agent_name, **ctx)
            except Exception as exc:
                # 单层失败不影响其他层与主流程
                logger.warning(f"[context] 层 {name} 构建失败，跳过: {exc}")
                continue
            if content:
                chunks.append(f"【{name}】\n{content}")
        return "\n\n".join(chunks)


# 全局单例：进程内共享层注册表
context_manager = ContextManager()

# 内置层注册；后续 RagLayer / ArtifactLayer 在此追加
context_manager.register(MemoryLayer())
# SkillLayer：按 intent 偏好标签匹配 workspace/skills 技能（M4）
context_manager.register(SkillLayer())
