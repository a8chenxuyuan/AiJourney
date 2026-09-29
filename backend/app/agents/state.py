"""
backend/app/agents/state.py

【模块作用】
LangGraph 共享状态定义模块。

这是整个 Agent 流程的"公共记事本"。
所有 Agent 节点（IntentAgent、AttractionAgent、WeatherAgent 等）都通过这个状态对象来：
1. 读取上一个节点的输出
2. 写入自己的产出结果
3. 传递给下一个节点继续处理

【核心概念】
- TypedDict：用 Python 类型注解定义状态结构，IDE 可以提示字段类型
- Annotated + reducer：控制列表字段如何合并（比如日志要追加，而不是覆盖）

【对应技术】
- LangGraph StateGraph：状态驱动执行
- TypedDict：类型安全的状态定义
- Annotated + reducer：字段级状态合并策略
"""

from operator import add
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.schemas import (
    AgentLog,
    Attraction,
    Hotel,
    IntentAnalysis,
    Meal,
    StructuredFeedback,
    TripPlan,
    TripRequest,
    WeatherInfo,
)


class TravelPlanningState(TypedDict):
    """
    【核心类】旅行规划状态对象。

    这是整条 Agent 流水线的"公共记事本"，包含以下几类数据：

    1. 任务标识：plan_id、user_id（唯一标识这次规划任务）
    2. 用户输入：request（前端提交的表单数据）
    3. 中间产物：intent_analysis、attractions、hotels、weather、route_matrix、rag_context
    4. 规划输出：candidate_plans、final_plan（最终行程）
    5. 控制与日志：messages、logs、error（用于调试和前端展示）

    【数据流转示例】
    用户填表 → request 初始化 → intent_agent 读 request，写 intent_analysis
    → attraction_agent 读 intent_analysis.city，写 attractions
    → weather_agent 读 intent_analysis.city，写 weather
    → planner_agent 读 attractions + weather + hotels + route_matrix，写 final_plan

    整个流程围绕这个状态对象流转：
    - 起始时由用户请求初始化；
    - 每个 Agent 节点读取所需字段、写入产出字段；
    - 最终由 finalize 节点持久化到数据库。
    """

    # ==================== 第一类：任务标识 ====================
    # 这两个字段在流程开始时就固定，用于标识这次规划任务

    plan_id: str
    """
    【字段作用】行程计划唯一 ID。

    【谁写入】入口函数 run_planning_graph() 初始化时写入
    【谁读取】finalize_node（保存到数据库时使用）、前端 SSE（追踪进度时使用）
    【来源】由 backend/app/api/routes/trip.py 的 create_trip_plan 生成
    """

    user_id: int
    """
    【字段作用】当前用户 ID。

    【谁写入】入口函数初始化
    【谁读取】intent_agent_node（读取用户偏好时使用）、finalize_node（保存时使用）
    【来源】JWT Token 解析后的用户 ID
    """

    # ==================== 第二类：用户输入 ====================
    # 这是前端提交的原始请求，是整条流水线的起点

    request: TripRequest
    """
    【字段作用】用户提交的旅行规划请求（Pydantic 模型）。

    【包含内容】
    - city：目标城市（如"湛江"）
    - start_date / end_date：旅行日期
    - transportation：交通方式（自驾/公共交通）
    - accommodation：住宿偏好（酒店/民宿）
    - preferences：偏好标签（美食/购物/文化等）
    - must_visit：必去景点列表
    - budget_level：预算等级（economy/standard/luxury）
    - dietary_restrictions：饮食禁忌
    - free_text_input：自由文本补充

    【谁写入】入口函数初始化
    【谁读取】几乎所有节点都会读取，它是原始需求
    """

    # ==================== 第三类：中间产物 ====================
    # 这些字段由各个 Agent 节点逐步填充，是规划过程的关键数据

    intent_analysis: Optional[IntentAnalysis]
    """
    【字段作用】IntentAgent 输出的结构化意图分析。

    【包含内容】
    - 把用户表单 + 自由文本解析成结构化字段
    - 推断用户隐含偏好（比如提到"孩子"→亲子；"省钱"→economy）

    【谁写入】intent_agent_node
    【谁读取】attraction_agent_node、weather_agent_node、hotel_agent_node、planner_agent_node
    """

    # 以下列表字段每个节点会整体替换为新结果，因此不使用 reducer（追加策略）
    attractions: List[Attraction]
    """
    【字段作用】候选景点列表。

    【数据来源】高德地图 POI 搜索的真实结果
    【包含内容】每个景点有 id、name、location（经纬度）、description、duration（建议时长）、ticket_price、rating、tags

    【谁写入】attraction_agent_node（调用 search_attractions 工具）
    【谁读取】route_agent_node（计算景点间距离）、planner_agent_node（编排每日行程）
    """

    hotels: List[Hotel]
    """
    【字段作用】候选酒店列表。

    【数据来源】高德地图 POI 搜索的真实结果
    【包含内容】每个酒店有 id、name、location、price_per_night、rating

    【谁写入】hotel_agent_node（调用 search_hotels 工具）
    【谁读取】planner_agent_node（安排住宿）、budget_agent_node（计算住宿费用）
    """

    restaurants: List[Meal]
    """
    【字段作用】候选餐厅列表。

    【数据来源】高德地图 POI 搜索的真实结果
    【包含内容】每个餐厅有 name、location、rating、image_url、phone、business_hours

    【谁写入】food_agent_node（调用 search_restaurants 工具）
    【谁读取】planner_agent_node（为每日三餐选择真实餐厅）
    """

    weather: List[WeatherInfo]
    """
    【字段作用】旅行期间每日天气信息。

    【数据来源】高德天气接口
    【包含内容】每天有 date、weather（晴/雨）、temperature、wind

    【谁写入】weather_agent_node（调用 get_weather 工具）
    【谁读取】planner_agent_node（雨天安排室内景点）、前端展示
    """

    route_matrix: Dict[str, Any]
    """
    【字段作用】景点间路线矩阵。

    【结构】键为 "景点A|景点B"，值为路线信息（distance 米、duration 秒、polyline 坐标点）
    【用途】planner_agent_node 根据距离决定每天安排哪些景点（相近的放同一天）

    【谁写入】route_agent_node（调用 plan_route 工具，或 Haversine 直线估算）
    【谁读取】planner_agent_node（参考距离编排行程）
    """

    rag_context: str
    """
    【字段作用】RAGAgent 检索到的城市攻略/景点背景上下文。

    【数据来源】Qdrant 向量库（目前可能为空，知识库未导入数据）
    【用途】为 planner_agent_node 提供额外的玩法建议、注意事项等

    【谁写入】rag_agent_node（调用 search_rag_context 工具）
    【谁读取】planner_agent_node（作为 LLM prompt 的背景知识）
    """

    # ==================== 第四类：规划输出 ====================
    # 这是最终产出的行程计划

    candidate_plans: List[TripPlan]
    """
    【字段作用】PlannerAgent 生成的 1~N 个候选方案。

    【当前状态】只生成一个方案，后续可扩展为多方案供用户选择
    【谁写入】planner_agent_node
    【谁读取】human_in_the_loop_node（用户选择）、finalize_node
    """

    selected_plan_index: int
    """
    【字段作用】用户或系统选中的方案索引。

    【当前状态】默认为 0（选第一个方案）
    【用途】多方案场景下标识用户选中了哪个
    """

    final_plan: Optional[TripPlan]
    """
    【字段作用】最终选定的行程计划。

    【包含内容】完整的 TripPlan 对象：
    - plan_id、user_id、city、start_date、end_date、travel_days
    - day_plans：每天行程（景点、餐饮、酒店、交通）
    - budget：各项费用统计
    - weather：天气信息
    - overall_suggestions：整体建议

    【谁写入】planner_agent_node（生成）、budget_agent_node（补充预算）、finalize_node（保存）
    【谁读取】finalize_node（保存到数据库）、前端展示
    """

    # ==================== 第五类：控制与日志 ====================
    # 用于流程控制和前端实时展示

    messages: Annotated[List[BaseMessage], add_messages]
    """
    【字段作用】LangChain 消息列表，供 LLM 上下文使用。

    【特殊处理】使用 add_messages reducer，新消息追加到列表末尾而不是覆盖
    【用途】LLM 调用时需要上下文（比如 intent_agent 和 planner_agent 都会写入）
    """

    current_step: str
    """
    【字段作用】当前执行的步骤名称，用于前端展示。

    【取值】start、intent_agent、attraction_agent、weather_agent、...、finalize
    【用途】前端 SSE 显示"正在分析意图..."、"正在搜索景点..."等
    """

    logs: Annotated[List[AgentLog], add]
    """
    【字段作用】Agent 执行日志，前端 SSE 实时展示。

    【特殊处理】使用 add reducer，每个节点的日志追加到列表
    【包含内容】每条日志有 agent_name、step、input_preview、output_preview、tool_calls、timestamp、duration_ms
    【用途】前端 Planning.vue 页面实时显示进度
    """

    error: Optional[str]
    """
    【字段作用】如果工作流失败，记录错误信息。

    【用途】调试和前端错误提示
    """

    human_decisions: Dict[str, Any]
    """
    【字段作用】人机协同节点的用户决策缓存。

    【当前状态】自动放行，值为 {"auto_approved": True}
    【用途】预留扩展：用户可以修改行程、选择方案等
    """

    # ==================== 第六类：行程迭代修订专用字段 ====================
    # 用于支持用户基于已有行程提交反馈并生成新版本

    previous_plan: Optional[TripPlan]
    """
    【字段作用】当前修订所基于的上一个版本行程。

    【谁写入】run_revision_graph 初始化时传入
    【谁读取】planner_agent_node、patch_plan_node
    """

    revision_notes: str
    """
    【字段作用】用户的自然语言修改要求。

    【谁写入】run_revision_graph 初始化时传入
    【谁读取】planner_agent_node、patch_plan_node
    """

    structured_feedback: Optional[StructuredFeedback]
    """
    【字段作用】FeedbackExtractorAgent 提取的结构化约束。

    【谁写入】feedback_extractor_node
    【谁读取】patch_plan_node、run_revision_graph（判断 patch/full）
    """

    revision_type: str
    """
    【字段作用】本次修订采用的策略。

    【取值】"initial" / "patch" / "full"
    """

    parent_revision_id: Optional[int]
    """
    【字段作用】本次修订所基于的父版本 ID。

    【谁写入】run_revision_graph 初始化时传入
    【谁读取】finalize_node（创建新版本时）
    """

    feedback_day_index: Optional[int]
    """
    【字段作用】用户提交反馈时针对的天数。

    【谁写入】run_revision_graph 初始化时传入
    【谁读取】feedback_extractor_node
    """

    feedback_tags: List[str]
    """
    【字段作用】用户提交反馈时选择的快捷标签。

    【谁写入】run_revision_graph 初始化时传入
    【谁读取】feedback_extractor_node
    """

    # ==================== 第七类：多城市联游专用字段 ====================
    # 支持"一次旅行游览多个城市"的场景：城市序列与停留天数由入口拆分，
    # 信息收集节点按城市 fan-out 后归并到 *_by_city 字典；
    # 原有单数字段（attractions/hotels/restaurants/weather/rag_context/route_matrix）
    # 仍保留并填主城市数据，保证单城链路与修订链路行为不变。

    cities: List[str]
    """
    【字段作用】按出发顺序排列的有序城市名列表。

    【谁写入】split_cities_node（从 request.cities 解析；无 cities 时 = [request.city]）
    【谁读取】city_gather_node（按城市 fan-out）、route_multi_node、planner_agent_node（多城分支）
    """

    city_days: Dict[str, int]
    """
    【字段作用】城市 → 停留天数的映射。

    【谁写入】split_cities_node
    【谁读取】planner_agent_node（多城分支按天数分段编排 day_plans）
    """

    attractions_by_city: Dict[str, List[Attraction]]
    """
    【字段作用】城市 → 候选景点列表。

    【谁写入】city_gather_node（归并各城市 attraction_agent_node 的产出）
    【谁读取】route_multi_node（注入该城景点算路线）、planner_agent_node（多城分支）
    """

    hotels_by_city: Dict[str, List[Hotel]]
    """
    【字段作用】城市 → 候选酒店列表。

    【谁写入】city_gather_node（归并各城市 hotel_agent_node 的产出）
    【谁读取】planner_agent_node（多城分支）
    """

    restaurants_by_city: Dict[str, List[Meal]]
    """
    【字段作用】城市 → 候选餐厅列表。

    【谁写入】city_gather_node（归并各城市 food_agent_node 的产出）
    【谁读取】planner_agent_node（多城分支）
    """

    weather_by_city: Dict[str, List[WeatherInfo]]
    """
    【字段作用】城市 → 旅行期间每日天气列表。

    【谁写入】city_gather_node（归并各城市 weather_agent_node 的产出）
    【谁读取】planner_agent_node（多城分支按天映射城市天气）
    """

    rag_by_city: Dict[str, str]
    """
    【字段作用】城市 → RAG 检索到的城市攻略上下文。

    【谁写入】city_gather_node（归并各城市 rag_agent_node 的产出）
    【谁读取】planner_agent_node（多城分支提示词）
    """

    route_matrix_by_city: Dict[str, Dict[str, Any]]
    """
    【字段作用】城市 → 该城景点间路线矩阵（结构与单城 route_matrix 一致）。

    【谁写入】route_multi_node（逐城执行 route_agent_node 后归并）
    【谁读取】planner_agent_node（多城分支按天所在城市取矩阵补地图数据）
    """

    intercity_legs: List[Dict[str, Any]]
    """
    【字段作用】相邻城市对的大交通信息，按出发顺序排列。

    【结构】每项包含 from_city、to_city、distance_m（米）、duration_s（秒）、
    advice（建议文案，如"高铁约 1.5 小时"）
    【谁写入】route_multi_node（高德方向 API，失败时 Haversine 估算）
    【谁读取】planner_agent_node（多城分支提示词与换城日 intercity_note 兜底）
    """