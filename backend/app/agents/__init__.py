"""
backend/app/agents/__init__.py

Agent 包入口模块。

作用：
- 将 agents 目录标记为 Python 包；
- 对外暴露 LangGraph 规划入口 `run_planning_graph`，供路由层调用；
- 隐藏内部 state、nodes、graph 等实现细节。

对应技术：
- Python 包管理
- LangGraph：状态图编排
"""

from .graph import run_planning_graph

__all__ = ["run_planning_graph"]
