"""
backend/app/agentkit/skills.py

agentkit（框架层）：技能仓库运行时（M4）。

作用：
- 技能以 workspace/skills/*.md + index.json 的形式沉淀：放一个 md 文件并在
  index.json 登记条目即生效（半自动沉淀入口），无需改代码；
- SkillRepository 按 tags 匹配加载技能全文（mtime 缓存，改文件热生效）；
- SkillLayer 是技能的上下文层封装：经 context_manager.assemble 注入
  prompt，节点侧传 intent 偏好标签（**ctx["tags"]）即完成按需装配；
- 自动沉淀（从会话中提炼新技能）只留 add_skill() 协议插槽，不自动触发。

index.json 条目结构：
    {"name": "skill_family", "file": "family.md", "tags": ["亲子", "带孩子"], "summary": "..."}
"""

import json
from typing import Any

from loguru import logger

from app.agentkit.prompt_loader import WORKSPACE_DIR

SKILLS_DIR = WORKSPACE_DIR / "skills"
INDEX_PATH = SKILLS_DIR / "index.json"


class SkillRepository:
    """技能仓库：index.json 登记 + md 全文加载（tags 匹配、mtime 缓存）。"""

    def __init__(self) -> None:
        self._content_cache: dict[str, tuple[float, str]] = {}

    def _load_index(self) -> list[dict[str, Any]]:
        """读取 index.json；文件缺失视为空仓库（技能功能静默关闭）。"""
        if not INDEX_PATH.exists():
            return []
        try:
            entries = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            return entries if isinstance(entries, list) else []
        except Exception as exc:
            logger.warning(f"[skills] index.json 解析失败，技能仓库关闭: {exc}")
            return []

    def _load_content(self, file_name: str) -> str | None:
        """按 mtime 缓存读取技能 md 全文；文件缺失返回 None。"""
        path = SKILLS_DIR / file_name
        if not path.exists():
            logger.warning(f"[skills] 技能文件缺失: {path}")
            return None
        mtime = path.stat().st_mtime
        cached = self._content_cache.get(file_name)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        content = path.read_text(encoding="utf-8")
        self._content_cache[file_name] = (mtime, content)
        return content

    def match_skills(self, tags: list[str] | None) -> list[tuple[str, str]]:
        """按 intent 偏好标签匹配技能，返回 [(技能名, 全文)]。

        匹配规则：index 条目的任一 tag 出现在用户标签中（或用户标签出现在
        条目 tag 中）即命中，保持大小写不敏感。
        """
        user_tags = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
        if not user_tags:
            return []
        matched: list[tuple[str, str]] = []
        for entry in self._load_index():
            entry_tags = {str(t).strip().lower() for t in entry.get("tags", [])}
            if user_tags & entry_tags or entry_tags & user_tags:
                content = self._load_content(str(entry.get("file", "")))
                if content:
                    matched.append((str(entry.get("name", entry.get("file", ""))), content))
        return matched

    def add_skill(self, name: str, file: str, tags: list[str], summary: str = "") -> None:
        """自动沉淀协议插槽（M4 不触发）：登记新技能到 index.json。"""
        entries = self._load_index()
        entries.append({"name": name, "file": file, "tags": tags, "summary": summary})
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class SkillLayer:
    """技能上下文层：assemble 时按 ctx["tags"] 匹配注入技能全文。"""

    name = "skills"

    def __init__(self, repository: SkillRepository | None = None) -> None:
        self._repo = repository or SkillRepository()

    async def build(self, plan_id: str, agent_name: str, **ctx: Any) -> str | None:
        tags = ctx.get("tags")
        matched = self._repo.match_skills(tags if isinstance(tags, list) else None)
        if not matched:
            return None
        logger.info(f"[skills] plan={plan_id} 命中 {len(matched)} 条技能: {[n for n, _ in matched]}")
        return "\n\n".join(f"### 技能：{name}\n{content}" for name, content in matched)
