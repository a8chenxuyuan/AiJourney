"""
backend/app/models/schema_trip.py

行程规划域 Pydantic 模型。

作用：
- 定义旅行请求、行程结构、意图分析、反馈修订、对话式修改等请求与响应结构；
- 原 schemas.py 按域拆分而来。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.schema_common import Location


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
    preferences: list[str] = Field(
        default_factory=list, description="偏好标签，如 ['历史文化', '美食']"
    )
    must_visit: list[str] = Field(default_factory=list, description="必去景点列表")
    budget_level: str = Field(default="standard", description="预算等级：economy/standard/luxury")
    dietary_restrictions: list[str] = Field(default_factory=list, description="饮食禁忌")
    free_text_input: str | None = Field(default=None, description="用户额外补充的自由文本")
    cities: list[CityStay] | None = Field(
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

    id: str | None = Field(default=None, description="景点唯一标识")
    name: str = Field(..., description="景点名称")
    location: Location = Field(..., description="景点位置")
    description: str | None = Field(default=None, description="景点简介")
    duration: str | None = Field(default=None, description="建议游玩时长")
    ticket_price: float | None = Field(default=None, description="门票价格")
    rating: float | None = Field(default=None, description="评分（0-5）")
    tags: list[str] = Field(default_factory=list, description="标签")
    image_url: str | None = Field(default=None, description="景点主图 URL")
    photos: list[str] = Field(default_factory=list, description="景点图片列表")
    business_hours: str | None = Field(default=None, description="营业时间")
    phone: str | None = Field(default=None, description="联系电话")
    detail_url: str | None = Field(default=None, description="高德详情页链接")


class Hotel(BaseModel):
    """
    酒店模型。
    """

    id: str | None = Field(default=None, description="酒店唯一标识")
    name: str = Field(..., description="酒店名称")
    location: Location = Field(..., description="酒店位置")
    description: str | None = Field(default=None, description="酒店简介")
    price_per_night: float | None = Field(default=None, description="每晚价格")
    rating: float | None = Field(default=None, description="评分（0-5）")
    image_url: str | None = Field(default=None, description="酒店图片 URL")
    business_hours: str | None = Field(default=None, description="营业时间/入住时间")
    phone: str | None = Field(default=None, description="联系电话")
    detail_url: str | None = Field(default=None, description="高德详情页链接")


class Meal(BaseModel):
    """
    餐饮安排模型。

    当作为候选餐厅（FoodAgent 输出）时，type 可暂为 "restaurant"，
    由 PlannerAgent 根据餐次分配为 breakfast/lunch/dinner。
    """

    type: str = Field(
        ..., description="餐饮类型：breakfast/lunch/dinner，候选餐厅阶段可为 restaurant"
    )
    name: str | None = Field(default=None, description="餐厅名称")
    cuisine: str | None = Field(default=None, description="菜系")
    estimated_cost: float | None = Field(default=None, description="预估人均消费")
    location: Location | None = Field(default=None, description="餐厅位置")
    location_name: str | None = Field(default=None, description="餐厅所在位置名称")
    detail_url: str | None = Field(default=None, description="高德搜索链接")
    image_url: str | None = Field(default=None, description="餐厅主图 URL")
    photos: list[str] = Field(default_factory=list, description="餐厅图片列表")
    rating: float | None = Field(default=None, description="评分（0-5）")
    phone: str | None = Field(default=None, description="联系电话")
    business_hours: str | None = Field(default=None, description="营业时间")
    address: str | None = Field(default=None, description="详细地址")

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
    temperature: str | None = Field(default=None, description="温度范围")
    wind: str | None = Field(default=None, description="风力")


class Budget(BaseModel):
    """
    预算模型。

    统计一次旅行的各项费用。
    【注意】所有 float 字段必须 Optional，LLM 在生成 JSON 时经常把字段填成 null，
    Pydantic v2 默认严格模式会把 None 视为非法 float。
    """

    attractions: float | None = Field(default=0.0, description="门票费用")
    meals: float | None = Field(default=0.0, description="餐饮费用")
    hotels: float | None = Field(default=0.0, description="住宿费用")
    transportation: float | None = Field(default=0.0, description="交通费用")
    total: float | None = Field(default=0.0, description="总费用")
    currency: str = Field(default="CNY", description="货币单位")
    notes: str | None = Field(default=None, description="预算说明")


class DayPlan(BaseModel):
    """
    单日行程模型。
    """

    day_index: int = Field(..., description="第几天，从 1 开始")
    date: str = Field(..., description="日期")
    description: str | None = Field(default=None, description="当日主题或概述")
    city: str | None = Field(
        default=None, description="当日所在城市，多城市联游时由 PlannerAgent 填写"
    )
    intercity_note: str | None = Field(
        default=None, description="城际交通说明，如'上午高铁 杭州→苏州（约1.5小时）'，换城日填写"
    )
    attractions: list[Attraction] = Field(default_factory=list, description="当日景点")
    meals: list[Meal] = Field(default_factory=list, description="当日餐饮")
    hotel: Hotel | None = Field(default=None, description="当日推荐酒店")
    transportation: str | None = Field(default=None, description="当日交通建议")
    route_polyline: str | None = Field(
        default=None, description="当天路线 polyline，用于地图画线"
    )
    map_center: Location | None = Field(default=None, description="地图中心点")


class TripPlan(BaseModel):
    """
    完整旅行计划模型。
    """

    plan_id: str | None = Field(default=None, description="计划唯一 ID")
    user_id: int | None = Field(default=None, description="所属用户 ID")
    city: str = Field(..., description="目标城市（多城联游时为首城市）")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    travel_days: int = Field(..., description="旅行天数")
    overall_suggestions: str | None = Field(default=None, description="整体建议")
    day_plans: list[DayPlan] = Field(default_factory=list, description="每日行程")
    budget: Budget = Field(default_factory=Budget, description="预算统计")
    weather: list[WeatherInfo] = Field(default_factory=list, description="天气信息")
    style: str | None = Field(default=None, description="方案风格：compact/relaxed/economy")
    cities: list[CityStay] | None = Field(
        default=None, description="多城市联游：按出发顺序的城市与停留天数；单城为 null"
    )


class TripPlanResponse(BaseModel):
    """
    旅行规划接口响应模型。
    """

    plan_id: str = Field(..., description="计划 ID")
    status: str = Field(..., description="状态：pending/completed/failed")
    plan: TripPlan | None = Field(default=None, description="规划结果")


class ReplicateRequest(BaseModel):
    """
    攻略复刻请求：AI 把攻略转写为用户自己的行程。
    """

    start_date: str | None = Field(default=None, description="出发日期 YYYY-MM-DD，默认一周后")
    travel_days: int | None = Field(default=None, ge=1, le=15, description="目标天数（可选）")


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
    preferences: list[str] = Field(default_factory=list, description="偏好标签")
    must_visit: list[str] = Field(default_factory=list, description="必去景点")
    budget_level: str = Field(..., description="预算等级")
    dietary_restrictions: list[str] = Field(default_factory=list, description="饮食禁忌")
    pace: str = Field(default="standard", description="节奏：relaxed/standard/intensive")
    notes: str | None = Field(default=None, description="额外说明")


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
    attraction_ids: list[str] = Field(..., description="调整后的景点 ID 顺序")


class StructuredFeedbackAction(BaseModel):
    """
    结构化反馈中的单个动作。
    """

    type: str = Field(
        ...,
        description="动作类型：replace_meal/add_attraction/remove_attraction/replace_hotel/change_pace/...",
    )
    day: int | None = Field(default=None, description="目标天数")
    meal: str | None = Field(default=None, description="餐次：breakfast/lunch/dinner")
    name: str | None = Field(default=None, description="要添加或替换的实体名称")
    target_name: str | None = Field(default=None, description="被替换的实体名称")
    reason: str | None = Field(default=None, description="原因")
    constraints: str | None = Field(default=None, description="额外约束，如时间段")


class StructuredFeedback(BaseModel):
    """
    FeedbackExtractorAgent 输出结构。
    """

    scope: str = Field(default="day", description="影响范围：day/whole")
    affected_days: list[int] = Field(default_factory=list, description="受影响的天数列表")
    actions: list[StructuredFeedbackAction] = Field(
        default_factory=list, description="具体修改动作"
    )
    preference_signals: list[dict[str, Any]] = Field(
        default_factory=list, description="可泛化的偏好信号"
    )
    complexity: str = Field(default="patch", description="复杂度：patch/full")


class PlanFeedbackRequest(BaseModel):
    """
    提交行程修改反馈请求。
    """

    day_index: int | None = Field(default=None, description="针对第几天，null 表示全局")
    tags: list[str] = Field(default_factory=list, description="快捷标签")
    raw_text: str = Field(..., min_length=1, description="用户反馈文本")


class PlanFeedbackResponse(BaseModel):
    """
    行程反馈提交响应。
    """

    feedback_id: int = Field(..., description="反馈 ID")
    revision_id: int = Field(..., description="基于的版本 ID")
    revision_type: str = Field(..., description="采用的修订策略：patch/full")
    new_revision_id: int | None = Field(
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
    feedback_preview: str | None = Field(default=None, description="触发该版本的反馈摘要")


class FeedbackRecord(BaseModel):
    """
    单条反馈记录。
    """

    feedback_id: int = Field(..., description="反馈 ID")
    day_index: int | None = Field(default=None, description="针对第几天")
    tags: list[str] = Field(default_factory=list, description="标签")
    raw_text: str = Field(..., description="原始文本")
    structured_feedback: StructuredFeedback | None = Field(
        default=None, description="结构化提取结果"
    )
    revision_type: str | None = Field(default=None, description="实际采用的修订策略")
    is_withdrawn: bool = Field(default=False, description="是否已撤回")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True


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
    history: list[PlanChatMessage] = Field(
        default_factory=list, description="最近几轮对话历史（可空）"
    )


__all__ = [
    "Attraction",
    "Budget",
    "CityStay",
    "DayPlan",
    "FeedbackRecord",
    "Hotel",
    "HumanDecisionRequest",
    "IntentAnalysis",
    "Meal",
    "PlanChatMessage",
    "PlanChatRequest",
    "PlanFeedbackRequest",
    "PlanFeedbackResponse",
    "RecalculateRequest",
    "ReplicateRequest",
    "RevisionSummary",
    "StructuredFeedback",
    "StructuredFeedbackAction",
    "TripPlan",
    "TripPlanResponse",
    "TripRequest",
    "WeatherInfo",
]
