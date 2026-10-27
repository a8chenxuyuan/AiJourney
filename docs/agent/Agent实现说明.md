# agent1旅行 — Agent 实现说明

## 1. 技术栈总览

Agent 部分基于 **LangGraph** 构建，底层使用 **LangChain** 调用 LLM 和工具，LLM 接入 **百炼（DashScope）** 的 OpenAI 兼容接口，外部工具通过 **MCP** 协议接入高德地图服务，输出结果用 **Pydantic** 严格校验，状态持久化通过 LangGraph 的 **Checkpointer** 实现。

| 技术 | 作用 |
|------|------|
| LangGraph | Agent 工作流编排框架，提供 StateGraph、Node、Edge、Checkpointer、interrupt |
| LangChain | LLM 调用、工具定义、Prompt 模板、消息抽象 |
| 百炼（DashScope） | LLM 提供商，接口地址 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| MCP | 标准协议，接入高德地图 MCP Server |
| Pydantic | Agent 输出结构化校验 |
| Qdrant | 向量数据库，供 RAGAgent 检索 |
| SentenceTransformers | 生成查询和文档的 Embedding |

---

## 2. 目录与文件规划

```
agent1旅行/backend/app/
├── planning/             # 编排层
│   ├── graph.py          # 图构建（节点/边注册）+ 多城联游编排 + 运行入口
│   ├── state.py          # TravelPlanningState 共享状态
│   ├── agents/           # 各 Agent 节点函数实现（一个节点一个文件）
│   │   ├── intent.py / attraction.py / weather.py / hotel.py
│   │   ├── food.py / rag.py / route.py / planner.py
│   │   ├── budget.py / patch.py / finalize.py
│   │   └── _helpers.py   # 节点间共享辅助函数
│   └── tools/            # 高德 POI / 天气 / 路线 / RAG / 酒店等工具封装（amap_tools.py 等）
├── agentkit/             # Agent 框架层
│   ├── executor.py       # 批次执行核心（NodeFunc/_merge_update/_run_node/_run_batches）
│   ├── events.py         # 事件总线（实时日志，SSE 传输在 core/sse.py）
│   ├── context.py / checkpoint.py / approval.py / skills.py
│   ├── tool_registry.py / memory.py
│   └── prompt_loader.py  # 惰性加载 workspace/prompts/*.md 各 Agent 系统提示词
└── llm/
    └── client.py         # LLM 客户端封装（get_llm，百炼）
```

---

## 3. 各文件作用与技术对应关系

### 3.1 planning/graph.py + agentkit/executor.py

| 项目 | 说明 |
|------|------|
| **对应技术** | 手动顺序/批次编排 + Python asyncio |
| **作用** | `graph.py` 是整个 Agent 系统的「总控」：注册所有节点与批次、做多城联游的拆分/合并编排；批次内节点的实际执行与状态合并在 `executor.py`（`_run_node` / `_run_batches`） |
| **核心内容** | 1. 按批次注册各 Agent 节点（`get_planning_graph`）；2. 多城联游：`split_cities_node` 拆分城市、各城子图并行、`city_gather_node` / `route_multi_node` 合并城际交通；3. 对外入口 `run_planning_graph` / `run_revision_graph` / `run_recalculate_graph` |

### 3.2 planning/state.py

| 项目 | 说明 |
|------|------|
| **对应技术** | Python `TypedDict` / Pydantic BaseModel |
| **作用** | 定义整个工作流中所有节点共享的状态结构 |
| **核心内容** | `TravelPlanningState`，包含用户请求、中间产物（景点、酒店、天气、路线矩阵、RAG 上下文）、候选方案、最终方案、日志、错误、人机决策、反馈 |

### 3.3 planning/agents/（节点包）

| 项目 | 说明 |
|------|------|
| **对应技术** | LangChain + Pydantic |
| **作用** | 实现每一个 Agent 节点的具体逻辑，每个节点接收 State，返回对 State 的更新；一个节点一个文件 |
| **核心内容** | `intent.py`、`attraction.py`、`weather.py`、`hotel.py`、`rag.py`、`food.py`、`route.py`、`planner.py`、`budget.py`、`patch.py`、`finalize.py`，公共辅助在 `_helpers.py` |

### 3.4 planning/tools/

| 项目 | 说明 |
|------|------|
| **对应技术** | LangChain Tools + MCP |
| **作用** | 定义和注册 Agent 可调用的所有工具，包括 MCP 加载的高德地图工具和自定义工具 |
| **核心内容** | `load_mcp_tools`、`search_poi_tool`、`get_weather_tool`、`plan_route_tool`、`retrieve_city_guide_tool`、`cluster_attractions_tool` |

### 3.5 提示词（workspace/prompts/*.md + agentkit/prompt_loader.py）

| 项目 | 说明 |
|------|------|
| **对应技术** | Markdown 文件 + 惰性加载器 |
| **作用** | 所有 Agent 的系统提示词外置为 `backend/workspace/prompts/*.md`（按 Agent 一个文件），由 `app/agentkit/prompt_loader.py` 惰性加载，修改 md 即生效，方便统一调整 |
| **核心内容** | 按 Agent 命名的提示词 md 文件（intent / planner / attraction 等） |

### 3.6 config.py

| 项目 | 说明 |
|------|------|
| **对应技术** | Python 配置类 |
| **作用** | 管理 Agent 运行参数，如模型名称、温度、最大重试次数、超时时间、最大步数 |
| **核心内容** | `AgentConfig` 类，从环境变量或默认值读取 |

---

## 4. 共享状态 State 详解

```python
class TravelPlanningState(TypedDict):
    # 用户原始请求
    request: TripRequest

    # 意图理解结果
    intent_analysis: Optional[IntentAnalysis]

    # 信息检索结果
    attractions: List[Attraction]
    hotels: List[Hotel]
    weather: List[WeatherInfo]
    rag_context: str

    # 路线计算结果
    route_matrix: Dict[str, RouteInfo]

    # 规划输出
    candidate_plans: List[TripPlan]
    selected_plan_index: int
    final_plan: Optional[TripPlan]

    # 控制与日志
    messages: List[BaseMessage]
    current_step: str
    logs: List[AgentLog]
    error: Optional[str]
    human_decisions: Dict[str, Any]
    feedback: Optional[UserFeedback]
```

### State 各字段含义

| 字段 | 含义 | 由谁写入 |
|------|------|----------|
| `request` | 用户提交的旅行请求 | 初始传入 |
| `intent_analysis` | 结构化意图分析结果 | IntentAgent |
| `attractions` | 候选景点列表 | AttractionAgent |
| `hotels` | 候选酒店列表 | HotelAgent |
| `weather` | 天气信息列表 | WeatherAgent |
| `rag_context` | RAG 检索到的攻略上下文 | RAGAgent |
| `route_matrix` | 景点间路线距离/时间矩阵 | RouteAgent |
| `candidate_plans` | 2-3 个候选行程方案 | PlannerAgent |
| `selected_plan_index` | 用户选择的方案索引 | 用户或默认 |
| `final_plan` | 最终行程方案 | Finalize 节点 |
| `messages` | LLM 对话历史 | 各 Agent |
| `current_step` | 当前执行步骤名 | 各节点 |
| `logs` | Agent 执行日志 | 各节点 |
| `error` | 错误信息 | 异常处理节点 |
| `human_decisions` | 人机协同决策结果 | HumanInLoopNode |
| `feedback` | 用户反馈 | Feedback 节点 |

---

## 5. 各 Agent 节点实现说明

### 5.1 IntentAgent（意图理解 Agent）

| 项 | 说明 |
|----|------|
| **输入** | `request: TripRequest` |
| **输出** | `intent_analysis: IntentAnalysis` |
| **工具** | 无，纯 LLM 推理 |
| **实现要点** | 1. 把用户表单和 `free_text_input` 拼接成 Prompt；2. 调用 LLM；3. 用 Pydantic 解析输出为 `IntentAnalysis`；4. 识别隐含偏好（亲子、老人、穷游等） |

```python
def intent_node(state: TravelPlanningState):
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", INTENT_AGENT_PROMPT),
        ("human", "{user_input}")
    ])
    chain = prompt | llm.with_structured_output(IntentAnalysis)
    intent = chain.invoke({"user_input": build_intent_input(state["request"])})
    return {
        "intent_analysis": intent,
        "current_step": "intent_analysis",
        "logs": [AgentLog(...)]
    }
```

### 5.2 AttractionAgent（景点检索 Agent）

| 项 | 说明 |
|----|------|
| **输入** | `intent_analysis` |
| **输出** | `attractions: List[Attraction]` |
| **工具** | `amap_maps_text_search`、`amap_maps_search_detail` |
| **实现要点** | 1. 按偏好标签发起多次检索；2. 去重、过滤无坐标数据；3. 调用详情工具补充地址、票价、描述；4. 输出结构化景点列表 |

### 5.3 WeatherAgent（天气查询 Agent）

| 项 | 说明 |
|----|------|
| **输入** | 城市、日期范围 |
| **输出** | `weather: List[WeatherInfo]` |
| **工具** | `amap_maps_weather` |
| **实现要点** | 1. 调用天气工具；2. 若旅行天数超过 4 天，后续日期用历史气候说明；3. 输出标准化天气结构 |

### 5.4 HotelAgent（酒店推荐 Agent）

| 项 | 说明 |
|----|------|
| **输入** | 城市、住宿类型、景点中心坐标 |
| **输出** | `hotels: List[Hotel]` |
| **工具** | `amap_maps_text_search` |
| **实现要点** | 1. 计算景点中心点；2. 搜索目标区域酒店；3. 按距离、价格、评分排序 |

### 5.5 RAGAgent（知识检索 Agent）

| 项 | 说明 |
|----|------|
| **输入** | 城市、偏好、候选景点 |
| **输出** | `rag_context: str` |
| **工具** | `retrieve_city_guide`（自定义工具，调用 Qdrant） |
| **实现要点** | 1. 构造查询文本；2. 生成 Embedding；3. Qdrant 检索 Top-K；4. 重排序并拼接上下文 |

### 5.6 RouteAgent（路线规划 Agent）

| 项 | 说明 |
|----|------|
| **输入** | `attractions`、交通方式 |
| **输出** | `route_matrix: Dict[str, RouteInfo]` |
| **工具** | `amap_maps_direction_*_by_address` |
| **实现要点** | 1. K-Means/DBSCAN 按地理位置聚类；2. 同组景点安排同一天；3. 组内使用 TSP 近似算法排序；4. 调用高德路线工具计算景点间距离和时间 |

### 5.7 PlannerAgent（行程规划 Agent）

| 项 | 说明 |
|----|------|
| **输入** | 所有前置结果 |
| **输出** | `candidate_plans: List[TripPlan]` |
| **工具** | 无 |
| **实现要点** | 1. 把所有信息注入 Prompt；2. 要求 LLM 输出 2-3 个不同风格的候选方案；3. 输出严格 JSON Schema；4. 用 Pydantic 校验 |

### 5.8 BudgetAgent（预算核算 Agent）

| 项 | 说明 |
|----|------|
| **输入** | `candidate_plans` |
| **输出** | 补全每个方案的 `Budget` |
| **工具** | 无 |
| **实现要点** | 1. 根据景点票价、酒店均价、餐饮均价、交通距离估算；2. 标注不确定性；3. 若超支写入 `error` 或触发 ReflectAgent |

### 5.9 HumanInLoopNode（人机协同节点）

| 项 | 说明 |
|----|------|
| **输入** | `candidate_plans` 或酒店选择 |
| **输出** | `human_decisions` |
| **工具** | LangGraph `interrupt` |
| **实现要点** | 1. 调用 `interrupt({"options": ...})` 暂停图；2. 前端收到事件后弹窗；3. 用户提交决策后 `graph.invoke(None, resume=True)` 恢复 |

### 5.10 ReflectAgent（反思优化 Agent）

| 项 | 说明 |
|----|------|
| **输入** | `feedback` 或 `error` |
| **输出** | 更新后的用户偏好或重试节点 |
| **工具** | `save_user_preference` |
| **实现要点** | 1. 分析失败或不满意原因；2. 生成改进建议；3. 更新 `UserPreferenceDB`；4. 返回需要重跑的节点名 |

---

## 6. LangGraph 工作流实现

### 6.1 图的构建

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

builder = StateGraph(TravelPlanningState)

# 添加节点
builder.add_node("intent_agent", intent_node)
builder.add_node("info_gathering", info_gathering_node)  # 内部并行
builder.add_node("route_agent", route_node)
builder.add_node("planner_agent", planner_node)
builder.add_node("budget_agent", budget_node)
builder.add_node("human_in_loop", human_node)
builder.add_node("reflect_agent", reflect_node)
builder.add_node("finalize_plan", finalize_node)

# 添加边
builder.add_edge(START, "intent_agent")
builder.add_edge("intent_agent", "info_gathering")
builder.add_edge("info_gathering", "route_agent")
builder.add_edge("route_agent", "planner_agent")
builder.add_edge("planner_agent", "budget_agent")
builder.add_conditional_edges("budget_agent", route_after_budget)
builder.add_edge("human_in_loop", "finalize_plan")
builder.add_edge("reflect_agent", "planner_agent")  # 循环优化
builder.add_edge("finalize_plan", END)

# 编译
memory = SqliteSaver.from_conn_string(":memory:")
graph = builder.compile(checkpointer=memory)
```

### 6.2 并行信息收集

`info_gathering` 节点内部使用 LangGraph 的 `Send` 或并行节点实现：

```python
def info_gathering_node(state: TravelPlanningState):
    # 使用 asyncio.gather 并行执行多个 Agent
    results = await asyncio.gather(
        attraction_agent.ainvoke(state),
        weather_agent.ainvoke(state),
        hotel_agent.ainvoke(state),
        rag_agent.ainvoke(state)
    )
    return merge_info_results(results)
```

### 6.3 条件分支

```python
def route_after_budget(state: TravelPlanningState):
    if state.get("error"):
        return "reflect_agent"
    if need_human_confirm(state):
        return "human_in_loop"
    return "finalize_plan"
```

### 6.4 循环优化

当 `reflect_agent` 发现预算超支或输出格式错误时，可以返回 `planner_agent` 重新生成，形成闭环。

---

## 7. 工具层实现

### 7.1 MCP 工具加载

```python
from mcp import ClientSession, StdioServerParameters
from langchain_mcp_adapters.tools import load_mcp_tools

async def get_amap_tools():
    params = StdioServerParameters(
        command="uvx",
        args=["amap-mcp-server"],
        env={"AMAP_MAPS_API_KEY": settings.amap_api_key}
    )
    async with ClientSession(params) as session:
        await session.initialize()
        tools = await load_mcp_tools(session)
    return tools
```

### 7.2 自定义工具

| 工具名 | 作用 | 实现 |
|--------|------|------|
| `cluster_attractions` | 景点地理位置聚类 | scikit-learn K-Means |
| `estimate_meal_cost` | 估算餐饮费用 | 基于城市和餐厅类型的规则 + LLM |
| `retrieve_city_guide` | RAG 检索城市攻略 | Qdrant + Embedding |
| `save_user_preference` | 保存用户偏好 | SQLAlchemy 写入 UserPreferenceDB |
| `load_user_preference` | 读取用户偏好 | SQLAlchemy 查询 |

---

## 8. 提示词设计原则

1. **角色明确**：每个 Agent 都有明确的专家身份；
2. **强制工具**：检索类 Agent 必须调用工具，禁止编造；
3. **输出格式**：要求输出严格 JSON，并提供完整 Schema 示例；
4. ** few-shot**：在 PlannerAgent 中提供 1-2 个行程示例；
5. **约束条件**：每天景点数量、必须包含三餐、考虑距离、根据天气调整等；
6. **RAG 注入**：把检索到的攻略上下文作为背景知识写入 Prompt。

---

## 9. 状态持久化与人机协同

### 9.1 Checkpointer

- 使用 `SqliteSaver` 或 `PostgresSaver`；
- 每个节点执行后自动保存 State；
- 通过 `thread_id`（即 plan_id）区分不同规划任务；
- 支持重新加载历史状态、断点续跑。

### 9.2 interrupt 机制

```python
def human_node(state: TravelPlanningState):
    options = build_human_options(state)
    response = interrupt({"type": "hotel_select", "options": options})
    return {"human_decisions": {"hotel_select": response}}
```

恢复执行：

```python
graph.invoke(None, config={"thread_id": plan_id}, resume=True)
```

---

## 10. 异常处理与兜底

| 异常场景 | 处理策略 |
|----------|----------|
| MCP 工具超时 | 重试 2 次，失败后返回缓存或占位数据 |
| LLM 输出非 JSON | JSON 修复 Agent 尝试提取；失败使用兜底模板 |
| Pydantic 校验失败 | 返回错误给 ReflectAgent 重跑 |
| 景点数量不足 | 放宽关键词，扩大检索范围 |
| 预算超支 | ReflectAgent 调整偏好或选择低价方案 |
| 用户未响应人机协同 | 默认选择第一个选项继续 |

---

## 11. 与后端其他模块的协作

| Agent 层 | 后端其他模块 |
|----------|--------------|
| `graph.py` 被行程域路由（`api/routes/trip/`）与 arq 任务（`app/tasks.py` → `services/trip_task_service.py`）调用 | 接收 HTTP 请求/任务入队并返回 plan_id |
| `api/routes/agent.py` 读取 State | 提供 SSE 流和人机协同接口 |
| `tools.py` 调用 `services/amap_service.py` | 通过 MCP 获取高德数据 |
| `RAGAgent` 调用 `services/rag_service.py` | 从 Qdrant 检索知识库 |
| `ReflectAgent` 调用 `services/memory_service.py` | 持久化用户偏好 |
| `planning/agents/` 各节点使用 `llm/client.py` | 统一调用百炼 LLM |

Agent 层不直接操作数据库，所有持久化都通过 Service 层完成，保持职责清晰。
