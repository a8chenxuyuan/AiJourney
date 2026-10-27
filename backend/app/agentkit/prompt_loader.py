"""
backend/app/agentkit/prompt_loader.py

agentkit（框架层）：prompt 外置加载器（M4）。

作用：
- 提示词模板统一外置到 backend/workspace/prompts/{key}.md，代码中不再
  维护大段 prompt 字符串——改 prompt 改文件即生效，无需改代码重启；
- get_prompt(key) 按文件 mtime 做缓存：文件未变直接命中缓存，文件被修改
  自动重新加载（热生效）；
- 框架层不感知业务模板语义，只负责"键 → 文件内容"的装载与缓存。

约定：
- {key}.md 与 Python 侧常量名小写一一对应（如 PLANNER_SYSTEM_PROMPT
  → planner_system.md）；
- 模板中的占位符仍由业务侧 .format() 填充，本层不做任何渲染。
"""

from pathlib import Path

# workspace 根目录：backend/workspace（本文件位于 backend/app/agentkit/）
WORKSPACE_DIR = Path(__file__).resolve().parents[2] / "workspace"
PROMPTS_DIR = WORKSPACE_DIR / "prompts"

# mtime 缓存：key → (mtime, content)，进程内复用避免每次读盘
_cache: dict[str, tuple[float, str]] = {}


def get_prompt(key: str) -> str:
    """读取外置提示词模板（mtime 缓存，文件修改后自动热加载）。

    Args:
        key: 模板键（即 workspace/prompts/ 下的文件名去 .md 后缀）。

    Returns:
        str: 模板全文（含占位符，由调用方渲染）。

    Raises:
        FileNotFoundError: 模板文件不存在时抛出，提示补齐 md 文件。
    """
    path = PROMPTS_DIR / f"{key}.md"
    mtime = path.stat().st_mtime
    cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    content = path.read_text(encoding="utf-8")
    _cache[key] = (mtime, content)
    return content
