"""
backend/app/models/schemas.py

Pydantic 数据模型定义模块。

作用：
- 定义所有 API 接口的请求体（Request）和响应体（Response）结构；
- 对输入数据进行自动校验和类型转换；
- 定义 Agent 内部使用的结构化数据模型，如 IntentAnalysis、TripPlan 等；
- 所有 LLM 输出都应解析为这些模型，确保数据一致性。

对应技术：
- Pydantic v2：数据模型、校验、序列化
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# ==================== 通用响应包装 ====================


class StandardResponse(BaseModel):
    """
    通用标准响应模型。

    所有 API 接口成功或失败时都建议使用该结构包装，方便前端统一处理。
    """

    success: bool = Field(description="请求是否成功")
    message: str = Field(default="", description="提示信息")
    data: Optional[Any] = Field(default=None, description="响应数据")


# ==================== 用户相关模型 ====================


class UserCreate(BaseModel):
    """
    用户注册请求模型。
    """

    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱地址")
    password: str = Field(..., min_length=6, description="密码，至少 6 位")


class UserLogin(BaseModel):
    """
    用户登录请求模型。
    """

    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class UserResponse(BaseModel):
    """
    用户信息响应模型。

    注意：响应中不包含 password_hash，避免泄露敏感信息。
    """

    id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱地址")
    created_at: datetime = Field(description="注册时间")

    class Config:
        from_attributes = True


# ==================== 地理位置模型 ====================


class Location(BaseModel):
    """
    经纬度位置模型。

    用于景点、酒店、POI 等任何需要地图坐标的实体。
    """

    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")
    address: Optional[str] = Field(default=None, description="详细地址")


# ==================== 旅行请求与行程模型 ====================


class CityStay(BaseModel):
    """
    多城市联游中的单城市停留安排。

    cities 列表按出发顺序排列，每个元素表示在该城市停留的天数。
    """

    city: str = Field(..., description="城市名称")
    days: int = Field(default=1, ge=1, description="停留天数，至少 1 天")


class TripRequest(BaseModel):
    """
    旅行规划请求模型。

    用户在前端填写表单后提交的数据结构。
    """

    city: str = Field(..., min_length=2, description="目标城市")
    start_date: str = Field(..., description="开始日期，格式 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期，格式 YYYY-MM-DD")
    transportation: str = Field(default="公共交通", description="交通方式偏好")
    accommodation: str = Field(default="酒店", description="住宿类型偏好")
    preferences: List[str] = Field(
        default_factory=list, description="偏好标签，如 ['历史文化', '美食']"
    )
    must_visit: List[str] = Field(default_factory=list, description="必去景点列表")
    budget_level: str = Field(default="standard", description="预算等级：economy/standard/luxury")
    dietary_restrictions: List[str] = Field(default_factory=list, description="饮食禁忌")
    free_text_input: Optional[str] = Field(default=None, description="用户额外补充的自由文本")
    cities: Optional[List[CityStay]] = Field(
        default=None, description="多城市联游：按出发顺序的城市与停留天数；单城可为 null"
    )

    @field_validator("end_date")
    def end_after_start(cls, end_date: str, info) -> str:
        """
        校验结束日期是否不早于开始日期。
        """
        start_date = info.data.get("start_date")
        if start_date and end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        return end_date

    @model_validator(mode="after")
    def validate_cities(self) -> "TripRequest":
        """
        校验多城市联游的天数分配，并保证首城市与 city 一致。

        规则：
        1. cities 非空时，各城市停留天数之和必须等于总旅行天数（含起止日）；
        2. cities 非空且首城市与 city 不一致时，以 cities 为准自动纠正 city。
        """
        if not self.cities:
            return self
        total_days = (
            datetime.strptime(self.end_date, "%Y-%m-%d")
            - datetime.strptime(self.start_date, "%Y-%m-%d")
        ).days + 1
        if sum(stay.days for stay in self.cities) != total_days:
            raise ValueError("各城市停留天数之和必须等于总旅行天数")
        first_city = self.cities[0].city
        if first_city != self.city:
            self.city = first_city
        return self


class Attraction(BaseModel):
    """
    景点模型。
    """

    id: Optional[str] = Field(default=None, description="景点唯一标识")
    name: str = Field(..., description="景点名称")
    location: Location = Field(..., description="景点位置")
    description: Optional[str] = Field(default=None, description="景点简介")
    duration: Optional[str] = Field(default=None, description="建议游玩时长")
    ticket_price: Optional[float] = Field(default=None, description="门票价格")
    rating: Optional[float] = Field(default=None, description="评分（0-5）")
    tags: List[str] = Field(default_factory=list, description="标签")
    image_url: Optional[str] = Field(default=None, description="景点主图 URL")
    photos: List[str] = Field(default_factory=list, description="景点图片列表")
    business_hours: Optional[str] = Field(default=None, description="营业时间")
    phone: Optional[str] = Field(default=None, description="联系电话")
    detail_url: Optional[str] = Field(default=None, description="高德详情页链接")


class Hotel(BaseModel):
    """
    酒店模型。
    """

    id: Optional[str] = Field(default=None, description="酒店唯一标识")
    name: str = Field(..., description="酒店名称")
    location: Location = Field(..., description="酒店位置")
    description: Optional[str] = Field(default=None, description="酒店简介")
    price_per_night: Optional[float] = Field(default=None, description="每晚价格")
    rating: Optional[float] = Field(default=None, description="评分（0-5）")
    image_url: Optional[str] = Field(default=None, description="酒店图片 URL")
    business_hours: Optional[str] = Field(default=None, description="营业时间/入住时间")
    phone: Optional[str] = Field(default=None, description="联系电话")
    detail_url: Optional[str] = Field(default=None, description="高德详情页链接")


class Meal(BaseModel):
    """
    餐饮安排模型。

    当作为候选餐厅（FoodAgent 输出）时，type 可暂为 "restaurant"，
    由 PlannerAgent 根据餐次分配为 breakfast/lunch/dinner。
    """

    type: str = Field(
        ..., description="餐饮类型：breakfast/lunch/dinner，候选餐厅阶段可为 restaurant"
    )
    name: Optional[str] = Field(default=None, description="餐厅名称")
    cuisine: Optional[str] = Field(default=None, description="菜系")
    estimated_cost: Optional[float] = Field(default=None, description="预估人均消费")
    location: Optional[Location] = Field(default=None, description="餐厅位置")
    location_name: Optional[str] = Field(default=None, description="餐厅所在位置名称")
    detail_url: Optional[str] = Field(default=None, description="高德搜索链接")
    image_url: Optional[str] = Field(default=None, description="餐厅主图 URL")
    photos: List[str] = Field(default_factory=list, description="餐厅图片列表")
    rating: Optional[float] = Field(default=None, description="评分（0-5）")
    phone: Optional[str] = Field(default=None, description="联系电话")
    business_hours: Optional[str] = Field(default=None, description="营业时间")
    address: Optional[str] = Field(default=None, description="详细地址")

    @field_validator("estimated_cost", mode="before")
    @classmethod
    def parse_estimated_cost(cls, value):
        """
        兼容 LLM 输出 "20元"、"约30元" 等字符串，提取数字部分。
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            import re

            numbers = re.findall(r"\d+(?:\.\d+)?", value)
            if numbers:
                return float(numbers[0])
            return None
        return value


class WeatherInfo(BaseModel):
    """
    天气信息模型。
    """

    date: str = Field(..., description="日期")
    weather: str = Field(..., description="天气状况，如晴、多云、雨")
    temperature: Optional[str] = Field(default=None, description="温度范围")
    wind: Optional[str] = Field(default=None, description="风力")


class Budget(BaseModel):
    """
    预算模型。

    统计一次旅行的各项费用。
    【注意】所有 float 字段必须 Optional，LLM 在生成 JSON 时经常把字段填成 null，
    Pydantic v2 默认严格模式会把 None 视为非法 float。
    """

    attractions: Optional[float] = Field(default=0.0, description="门票费用")
    meals: Optional[float] = Field(default=0.0, description="餐饮费用")
    hotels: Optional[float] = Field(default=0.0, description="住宿费用")
    transportation: Optional[float] = Field(default=0.0, description="交通费用")
    total: Optional[float] = Field(default=0.0, description="总费用")
    currency: str = Field(default="CNY", description="货币单位")
    notes: Optional[str] = Field(default=None, description="预算说明")


class DayPlan(BaseModel):
    """
    单日行程模型。
    """

    day_index: int = Field(..., description="第几天，从 1 开始")
    date: str = Field(..., description="日期")
    description: Optional[str] = Field(default=None, description="当日主题或概述")
    city: Optional[str] = Field(
        default=None, description="当日所在城市，多城市联游时由 PlannerAgent 填写"
    )
    intercity_note: Optional[str] = Field(
        default=None, description="城际交通说明，如'上午高铁 杭州→苏州（约1.5小时）'，换城日填写"
    )
    attractions: List[Attraction] = Field(default_factory=list, description="当日景点")
    meals: List[Meal] = Field(default_factory=list, description="当日餐饮")
    hotel: Optional[Hotel] = Field(default=None, description="当日推荐酒店")
    transportation: Optional[str] = Field(default=None, description="当日交通建议")
    route_polyline: Optional[str] = Field(
        default=None, description="当天路线 polyline，用于地图画线"
    )
    map_center: Optional[Location] = Field(default=None, description="地图中心点")


class TripPlan(BaseModel):
    """
    完整旅行计划模型。
    """

    plan_id: Optional[str] = Field(default=None, description="计划唯一 ID")
    user_id: Optional[int] = Field(default=None, description="所属用户 ID")
    city: str = Field(..., description="目标城市（多城联游时为首城市）")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    travel_days: int = Field(..., description="旅行天数")
    overall_suggestions: Optional[str] = Field(default=None, description="整体建议")
    day_plans: List[DayPlan] = Field(default_factory=list, description="每日行程")
    budget: Budget = Field(default_factory=Budget, description="预算统计")
    weather: List[WeatherInfo] = Field(default_factory=list, description="天气信息")
    style: Optional[str] = Field(default=None, description="方案风格：compact/relaxed/economy")
    cities: Optional[List[CityStay]] = Field(
        default=None, description="多城市联游：按出发顺序的城市与停留天数；单城为 null"
    )


class TripPlanResponse(BaseModel):
    """
    旅行规划接口响应模型。
    """

    plan_id: str = Field(..., description="计划 ID")
    status: str = Field(..., description="状态：pending/completed/failed")
    plan: Optional[TripPlan] = Field(default=None, description="规划结果")


# ==================== Agent 内部模型 ====================


class IntentAnalysis(BaseModel):
    """
    意图分析结果模型。

    IntentAgent 的输出，用于后续 Agent 决策。
    """

    city: str = Field(..., description="目标城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    travel_days: int = Field(..., description="旅行天数")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿类型")
    preferences: List[str] = Field(default_factory=list, description="偏好标签")
    must_visit: List[str] = Field(default_factory=list, description="必去景点")
    budget_level: str = Field(..., description="预算等级")
    dietary_restrictions: List[str] = Field(default_factory=list, description="饮食禁忌")
    pace: str = Field(default="standard", description="节奏：relaxed/standard/intensive")
    notes: Optional[str] = Field(default=None, description="额外说明")


class AgentLog(BaseModel):
    """
    Agent 执行日志模型。

    用于前端实时展示每个 Agent 的执行过程。
    """

    step: str = Field(..., description="步骤名称")
    agent_name: str = Field(..., description="Agent 名称")
    input_preview: Optional[str] = Field(default=None, description="输入摘要")
    output_preview: Optional[str] = Field(default=None, description="输出摘要")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="工具调用记录")
    timestamp: datetime = Field(default_factory=datetime.now, description="执行时间")
    duration_ms: Optional[int] = Field(default=None, description="执行耗时（毫秒）")


class UserFeedback(BaseModel):
    """
    用户反馈模型。
    """

    plan_id: str = Field(..., description="行程计划 ID")
    overall_score: int = Field(..., ge=1, le=5, description="总体评分 1-5")
    tag_feedback: Dict[str, int] = Field(default_factory=dict, description="各维度评分")
    text_feedback: Optional[str] = Field(default=None, description="文字反馈")
    would_use_again: bool = Field(default=False, description="是否愿意再次使用")


# ==================== 行程反馈与版本迭代模型 ====================


class StructuredFeedbackAction(BaseModel):
    """
    结构化反馈中的单个动作。
    """

    type: str = Field(
        ...,
        description="动作类型：replace_meal/add_attraction/remove_attraction/replace_hotel/change_pace/...",
    )
    day: Optional[int] = Field(default=None, description="目标天数")
    meal: Optional[str] = Field(default=None, description="餐次：breakfast/lunch/dinner")
    name: Optional[str] = Field(default=None, description="要添加或替换的实体名称")
    target_name: Optional[str] = Field(default=None, description="被替换的实体名称")
    reason: Optional[str] = Field(default=None, description="原因")
    constraints: Optional[str] = Field(default=None, description="额外约束，如时间段")


class StructuredFeedback(BaseModel):
    """
    FeedbackExtractorAgent 输出结构。
    """

    scope: str = Field(default="day", description="影响范围：day/whole")
    affected_days: List[int] = Field(default_factory=list, description="受影响的天数列表")
    actions: List[StructuredFeedbackAction] = Field(
        default_factory=list, description="具体修改动作"
    )
    preference_signals: List[Dict[str, Any]] = Field(
        default_factory=list, description="可泛化的偏好信号"
    )
    complexity: str = Field(default="patch", description="复杂度：patch/full")


class PlanFeedbackRequest(BaseModel):
    """
    提交行程修改反馈请求。
    """

    day_index: Optional[int] = Field(default=None, description="针对第几天，null 表示全局")
    tags: List[str] = Field(default_factory=list, description="快捷标签")
    raw_text: str = Field(..., min_length=1, description="用户反馈文本")


class PlanFeedbackResponse(BaseModel):
    """
    行程反馈提交响应。
    """

    feedback_id: int = Field(..., description="反馈 ID")
    revision_id: int = Field(..., description="基于的版本 ID")
    revision_type: str = Field(..., description="采用的修订策略：patch/full")
    new_revision_id: Optional[int] = Field(
        default=None, description="生成的新版本 ID，若为异步生成可能为空"
    )
    status: str = Field(..., description="状态：pending/completed/failed")


class RevisionSummary(BaseModel):
    """
    版本摘要。
    """

    revision_id: int = Field(..., description="版本 ID")
    version: int = Field(..., description="版本号")
    source: str = Field(..., description="来源：initial/patch/full")
    created_at: datetime = Field(..., description="创建时间")
    feedback_preview: Optional[str] = Field(default=None, description="触发该版本的反馈摘要")


class FeedbackRecord(BaseModel):
    """
    单条反馈记录。
    """

    feedback_id: int = Field(..., description="反馈 ID")
    day_index: Optional[int] = Field(default=None, description="针对第几天")
    tags: List[str] = Field(default_factory=list, description="标签")
    raw_text: str = Field(..., description="原始文本")
    structured_feedback: Optional[StructuredFeedback] = Field(
        default=None, description="结构化提取结果"
    )
    revision_type: Optional[str] = Field(default=None, description="实际采用的修订策略")
    is_withdrawn: bool = Field(default=False, description="是否已撤回")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True


# ==================== 请求体模型 ====================


class HumanDecisionRequest(BaseModel):
    """
    人机协同决策请求模型。
    """

    decision_type: str = Field(..., description="决策类型，如 hotel_select")
    decision_value: Any = Field(..., description="用户选择的值")


class RecalculateRequest(BaseModel):
    """
    重新规划请求模型。

    用户调整景点顺序后，提交新的景点列表进行重算。
    """

    day_index: int = Field(..., description="第几天")
    attraction_ids: List[str] = Field(..., description="调整后的景点 ID 顺序")


class RAGUploadRequest(BaseModel):
    """
    知识库文档上传请求模型。
    """

    city: Optional[str] = Field(default=None, description="文档所属城市")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档正文")


class RAGSearchRequest(BaseModel):
    """
    知识库检索请求模型。
    """

    query: str = Field(..., description="查询文本")
    city: Optional[str] = Field(default=None, description="限制城市")
    top_k: int = Field(default=5, description="返回条数")


class RAGSearchResponse(BaseModel):
    """
    知识库检索响应模型。
    """

    query: str = Field(..., description="查询文本")
    results: List[Dict[str, Any]] = Field(default_factory=list, description="检索结果列表")


class PaymentCreateRequest(BaseModel):
    """
    创建支付订单请求模型。
    """

    plan_id: str = Field(..., description="关联的行程计划 ID")
    amount: float = Field(..., gt=0, description="支付金额")
    payment_method: str = Field(default="alipay", description="支付方式")


class PaymentResponse(BaseModel):
    """
    支付订单响应模型。
    """

    order_id: str = Field(..., description="订单 ID")
    amount: float = Field(..., description="订单金额")
    status: str = Field(..., description="订单状态")
    payment_params: Optional[Dict[str, Any]] = Field(default=None, description="第三方支付参数")


class CrawlerTriggerRequest(BaseModel):
    """
    触发爬虫请求模型。
    """

    cities: List[str] = Field(default_factory=list, description="要抓取的城市列表，为空则抓取全部")
    max_pages: Optional[int] = Field(default=None, description="最大抓取页面数")


class PlanChatMessage(BaseModel):
    """
    行程对话历史中的单条消息。
    """

    role: str = Field(..., description="角色：user / assistant")
    content: str = Field(..., description="消息内容")


class PlanChatRequest(BaseModel):
    """
    对话式修改行程请求。

    用户在"AI 修改助手"聊天框中输入自然语言，后端通过 LLM 判断意图：
    - feedback：行程修改意见 → 提取结构化反馈并入库（不立即触发重排）；
    - question：行程相关咨询 → 基于行程上下文直接回答。
    """

    message: str = Field(..., min_length=1, description="用户本轮输入")
    history: List[PlanChatMessage] = Field(
        default_factory=list, description="最近几轮对话历史（可空）"
    )


class ShareCreateRequest(BaseModel):
    """
    开启行程分享请求。

    为指定行程生成分享令牌，持有令牌的任何人可在有效期内只读查看行程。
    """

    expires_days: Optional[int] = Field(
        default=7, ge=1, le=365, description="分享有效天数，1-365；不传默认 7 天"
    )


class ShareInfo(BaseModel):
    """
    行程分享信息。

    token 用于拼接公开访问链接；expires_at 为空表示永久有效。
    """

    plan_id: str = Field(..., description="行程计划 ID")
    share_token: str = Field(..., description="分享令牌")
    share_path: str = Field(..., description="前端分享页路由路径，如 /share/xxx")
    expires_at: Optional[str] = Field(None, description="过期时间（ISO 格式），NULL 表示永久有效")
    share_view_count: int = Field(0, description="分享页累计访问次数")


class FavoriteCreateRequest(BaseModel):
    """
    添加收藏请求。

    收藏行程结果中的景点、酒店、餐厅等对象，item_data 保存完整快照供回显。
    """

    item_type: str = Field(..., description="收藏类型：attraction/hotel/restaurant")
    item_id: str = Field(
        ..., min_length=1, description="收藏对象唯一标识（如景点名/酒店名的 hash）"
    )
    item_name: str = Field(..., min_length=1, description="收藏对象名称")
    city: Optional[str] = Field(None, description="所属城市，用于按城市聚合推荐")
    item_data: Optional[dict] = Field(None, description="收藏对象完整数据快照（JSON）")


class FavoriteOut(BaseModel):
    """
    收藏记录响应。

    与 favorites 表字段对应，item_data 原样返回。
    """

    id: int = Field(..., description="收藏 ID")
    item_type: str = Field(..., description="收藏类型")
    item_id: str = Field(..., description="收藏对象标识")
    item_name: str = Field(..., description="收藏对象名称")
    city: Optional[str] = Field(None, description="所属城市")
    item_data: Optional[dict] = Field(None, description="收藏对象完整数据快照")
    created_at: Optional[str] = Field(None, description="收藏时间（ISO 格式）")


# ==================== 多人协作模型 ====================


class CollaboratorOut(BaseModel):
    """
    行程成员信息响应。

    所有者与协作者统一以成员形式返回：所有者 role=owner，
    协作者 role=editor（可查看行程、提交反馈）。
    """

    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    role: str = Field(..., description="成员角色：owner（所有者）/ editor（协作者）")
    joined_at: Optional[str] = Field(None, description="加入时间（ISO 格式），所有者为行程创建时间")


class InviteOut(BaseModel):
    """
    邀请链接信息响应。

    token 用于拼接前端加入协作路由 /join/{token}。
    """

    plan_id: str = Field(..., description="行程计划 ID")
    token: str = Field(..., description="邀请令牌")
    invite_path: str = Field(..., description="前端加入协作路由路径，如 /join/xxx")
    expires_at: Optional[str] = Field(None, description="邀请过期时间（ISO 格式）")


class CollaboratorJoinOut(BaseModel):
    """
    凭邀请令牌加入协作的响应。

    前端据此跳转到对应行程的结果页。
    """

    plan_id: str = Field(..., description="加入的行程计划 ID")
    city: Optional[str] = Field(None, description="行程目的地城市")
    role: str = Field(default="editor", description="加入后的角色：owner（已是所有者）/ editor")
