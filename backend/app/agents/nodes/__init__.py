"""
backend/app/agents/nodes 包

【模块作用】
LangGraph 各 Agent 节点实现，按职责拆分为单文件模块：

- _helpers.py：多节点共享的通用工具函数（非 LangGraph 节点）
- intent.py：意图理解
- attraction.py：景点检索
- weather.py：天气查询
- hotel.py：酒店推荐
- food.py：餐厅推荐
- rag.py：知识检索
- route.py：路线规划
- planner.py：行程编排（含多城联游与修订重排，最核心）
- budget.py：预算统计
- finalize.py：人机协同 + 收尾保存
- patch.py：反馈提取 + 行程局部修改

本 __init__ 统一 re-export 全部节点函数，外部保持
`from app.agents.nodes import xxx` 的原有用法不变。

【对应技术】
- LangGraph StateGraph 节点
- LangChain LLM 调用
- 高德地图 MCP / RAG / SQLAlchemy
"""

from app.agents.nodes.attraction import attraction_agent_node
from app.agents.nodes.budget import budget_agent_node
from app.agents.nodes.finalize import finalize_node, human_in_the_loop_node
from app.agents.nodes.food import food_agent_node
from app.agents.nodes.hotel import hotel_agent_node
from app.agents.nodes.intent import intent_agent_node
from app.agents.nodes.patch import feedback_extractor_node, patch_plan_node
from app.agents.nodes.planner import planner_agent_node
from app.agents.nodes.rag import rag_agent_node
from app.agents.nodes.route import route_agent_node
from app.agents.nodes.weather import weather_agent_node

__all__ = [
    "attraction_agent_node",
    "budget_agent_node",
    "feedback_extractor_node",
    "finalize_node",
    "food_agent_node",
    "hotel_agent_node",
    "human_in_the_loop_node",
    "intent_agent_node",
    "patch_plan_node",
    "planner_agent_node",
    "rag_agent_node",
    "route_agent_node",
    "weather_agent_node",
]
