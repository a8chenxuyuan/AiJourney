"""
backend/app/agentkit/tool_registry.py

agentkit（框架层）：工具注册与治理（M4）。

作用：
- @register_tool 装饰器注册工具元信息（名称、描述、默认权限），注册表
  进程内共享；工具函数本体不受装饰影响（原样返回，行为零侵入）；
- 工具权限三态：ALLOW（直接放行）/ APPROVE（需先走 agentkit.approval
  审批协议再执行）/ DENY（直接拒绝）；注册时的 permission 为默认值，
  可经 workspace/tool_permissions.json 配置覆盖（{"tool_name": "allow"}），
  配置文件 mtime 缓存、改文件即生效；
- 本层只定协议与登记，不感知具体工具语义；工具的执行仍由业务节点直接
  调用函数本体，权限检查点在业务侧调用 effective_permission()。

设计原则：一切皆插件——新工具加 @register_tool 即入册，无需改框架代码。
"""

import json
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from app.agentkit.prompt_loader import WORKSPACE_DIR

# 权限配置文件（可选；缺失时全部按注册默认 ALLOW 生效）
PERMISSIONS_PATH = WORKSPACE_DIR / "tool_permissions.json"

# ==================== 权限三态 ====================
PERM_ALLOW = "allow"  # 允许：直接执行
PERM_APPROVE = "approve"  # 审批：执行前需人工确认（走 approval 协议）
PERM_DENY = "deny"  # 拒绝：禁用该工具


@dataclass
class ToolMeta:
    """工具注册元信息。"""

    name: str
    description: str
    default_permission: str
    func: Callable[..., Any]


# 进程内工具注册表：name -> ToolMeta
_TOOL_REGISTRY: dict[str, ToolMeta] = {}

# 权限配置缓存：mtime → 覆盖表
_perm_cache: tuple[float, dict[str, str]] | None = None


def register_tool(
    name: str, description: str = "", permission: str = PERM_ALLOW
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """工具注册装饰器：登记元信息后原样返回函数（行为零侵入）。

    Args:
        name: 工具唯一名称（权限配置按此名覆盖）。
        description: 工具用途一句话描述。
        permission: 默认权限（allow / approve / deny）。
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in _TOOL_REGISTRY:
            logger.warning(f"[tool_registry] 工具 {name} 重复注册，后者覆盖前者")
        _TOOL_REGISTRY[name] = ToolMeta(
            name=name, description=description, default_permission=permission, func=func
        )
        return func

    return decorator


def _load_permissions() -> dict[str, str]:
    """读取权限覆盖配置（mtime 缓存，文件缺失/损坏视为空覆盖）。"""
    global _perm_cache
    if not PERMISSIONS_PATH.exists():
        return {}
    try:
        mtime = PERMISSIONS_PATH.stat().st_mtime
        if _perm_cache is not None and _perm_cache[0] == mtime:
            return _perm_cache[1]
        data = json.loads(PERMISSIONS_PATH.read_text(encoding="utf-8"))
        perms = {str(k): str(v).lower() for k, v in data.items()} if isinstance(data, dict) else {}
        _perm_cache = (mtime, perms)
        return perms
    except Exception as exc:
        logger.warning(f"[tool_registry] tool_permissions.json 解析失败，忽略覆盖: {exc}")
        return {}


def effective_permission(name: str) -> str:
    """查询工具当前生效权限：配置覆盖优先，未配置回退注册默认值。"""
    meta = _TOOL_REGISTRY.get(name)
    override = _load_permissions().get(name)
    return override or (meta.default_permission if meta else PERM_DENY)


def get_tool(name: str) -> ToolMeta | None:
    """按名称取工具元信息；未注册返回 None。"""
    return _TOOL_REGISTRY.get(name)


def list_tools() -> list[ToolMeta]:
    """列出全部已注册工具（供治理视图/调试）。"""
    return list(_TOOL_REGISTRY.values())
