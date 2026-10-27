"""
脚本：scripts/check_layers.py
作用：七层单向依赖检查（ruff 覆盖不到的条款）。

依赖方向（自上而下，只准上层 import 下层）：
    api / tasks（接口层）
      ↑  planning（业务编排层；迁移期旧 agents 目录视同 planning）
      ↑  services / crawler（应用服务层）
      ↑  travel（行程领域层）
      ↑  agentkit（Agent 框架层，零业务感知）
      ↑  rag / llm（检索层 / 模型层，两者平行互不依赖）
      ↑  core（基建层）  models（模型层）

用法：venv\\Scripts\\python.exe scripts/check_layers.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# 下层目录 → 禁止 import 的上层包前缀
BANNED: dict[str, tuple[str, ...]] = {
    # 基建层 / 模型层：禁止依赖一切上层
    "app/core": (
        "app.services", "app.crawler", "app.planning", "app.travel",
        "app.agentkit", "app.rag", "app.llm", "app.agents", "app.tasks", "app.api",
    ),
    "app/models": (
        "app.services", "app.crawler", "app.planning", "app.travel",
        "app.agentkit", "app.rag", "app.llm", "app.agents", "app.tasks", "app.api",
    ),
    # 检索层 / 模型层（平行，互不依赖）
    "app/rag": (
        "app.agentkit", "app.travel", "app.services", "app.crawler",
        "app.planning", "app.agents", "app.tasks", "app.api", "app.llm",
    ),
    "app/llm": (
        "app.agentkit", "app.travel", "app.services", "app.crawler",
        "app.planning", "app.agents", "app.tasks", "app.api", "app.rag",
    ),
    # Agent 框架层（零业务感知）
    "app/agentkit": (
        "app.travel", "app.services", "app.crawler",
        "app.planning", "app.agents", "app.tasks", "app.api",
    ),
    # 行程领域层
    "app/travel": (
        "app.services", "app.crawler", "app.planning", "app.agents", "app.tasks", "app.api",
    ),
    # 应用服务层
    "app/services": ("app.planning", "app.agents", "app.tasks", "app.api"),
    "app/crawler": ("app.services", "app.planning", "app.agents", "app.tasks", "app.api"),
    # 业务编排层（app/agents 为迁移期垫片，视同 planning）
    "app/planning": ("app.tasks", "app.api"),
    "app/agents": ("app.tasks", "app.api"),
    # 接口层
    "app/tasks.py": ("app.api",),
}

findings: list[str] = []


def layer_of(rel: str) -> tuple[str, ...] | None:
    """返回该文件所属层的禁令，非受管文件返回 None。"""
    if rel in BANNED:
        return BANNED[rel]
    for prefix, banned in BANNED.items():
        if prefix.endswith(".py"):
            continue
        if rel.startswith(prefix + "/"):
            return banned
    return None


def check_file(path: Path) -> None:
    rel = path.relative_to(BASE).as_posix()
    banned = layer_of(rel)
    if banned is None:
        return
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        findings.append(f"[parse] {rel}: 语法错误 {exc}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            targets = [node.module]
        else:
            continue
        for target in targets:
            for bad in banned:
                if target == bad or target.startswith(bad + "."):
                    findings.append(f"[分层] {rel}:{node.lineno} {rel.split('/')[1]} 层 import {target}")


def main() -> None:
    app_dir = BASE / "app"
    for path in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        check_file(path)
    if not findings:
        print("LAYER PASS：七层依赖方向全部合规")
        return
    print(f"=== 分层违规 {len(findings)} 处 ===")
    for f in findings:
        print(f"  {f}")
    sys.exit(1)


if __name__ == "__main__":
    main()
