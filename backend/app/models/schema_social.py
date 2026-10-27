"""
backend/app/models/schema_social.py

行中内容与社区社交域 Pydantic 模型。

作用：
- 定义打卡、游记、帖子、评论、feed 等请求与响应结构；
- 原 schemas.py 按域拆分而来。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CheckinCreateRequest(BaseModel):
    """
    创建打卡请求。

    longitude/latitude 来自浏览器定位；定位失败时前端降级为
    行程内地点坐标（对应 spot_type/spot_name）。
    """

    day_index: int = Field(..., ge=1, description="行程第几天，从 1 开始")
    spot_type: str = Field(
        default="attraction", description="地点类型：attraction/meal/hotel"
    )
    spot_name: str = Field(..., min_length=1, max_length=255, description="地点名称")
    longitude: float = Field(default=0.0, description="经度（高德坐标）")
    latitude: float = Field(default=0.0, description="纬度（高德坐标）")
    note: str | None = Field(default=None, max_length=500, description="一句话感想")
    photo_urls: list[str] = Field(default_factory=list, description="照片 URL 列表")
    checkin_at: datetime | None = Field(
        default=None, description="打卡时间，不传默认服务器当前时间"
    )


class CheckinOut(BaseModel):
    """单条打卡记录响应。"""

    id: str = Field(..., description="打卡 ID")
    plan_id: str = Field(..., description="行程计划 ID")
    day_index: int = Field(..., description="行程第几天")
    spot_type: str = Field(..., description="地点类型")
    spot_name: str = Field(..., description="地点名称")
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")
    checkin_at: datetime | None = Field(None, description="打卡时间")
    photo_urls: list[str] = Field(default_factory=list, description="照片 URL 列表")
    note: str | None = Field(None, description="一句话感想")


class JournalSection(BaseModel):
    """
    游记分节结构（content JSON 的元素）。

    LLM 生成后用户可编辑；photos 为该节配图 URL（打卡照片或行程景点图）。
    """

    day_index: int | None = Field(None, description="对应行程第几天，序章/尾声可为 None")
    title: str = Field(..., description="节标题")
    text: str = Field(..., description="节正文")
    photos: list[str] = Field(
        default_factory=list, description="节配图（当日打卡照片），编辑时原样回传"
    )


class JournalUpdateRequest(BaseModel):
    """游记编辑请求（标题与分节均可选，只更新传入字段）。"""

    title: str | None = Field(None, min_length=1, max_length=255, description="游记标题")
    sections: list[JournalSection] | None = Field(None, description="分节内容")


class JournalOut(BaseModel):
    """游记响应（GET 轮询 status 与 PATCH 编辑后均返回该结构）。"""

    id: str = Field(..., description="游记 ID")
    plan_id: str = Field(..., description="行程计划 ID")
    title: str = Field(default="", description="游记标题")
    status: str = Field(..., description="状态：generating/done/failed")
    sections: list[JournalSection] = Field(default_factory=list, description="分节内容")
    is_public: bool = Field(default=False, description="是否公开")
    public_token: str | None = Field(None, description="公开访问令牌")
    generated_at: datetime | None = Field(None, description="生成完成时间")


class PostCreateRequest(BaseModel):
    """
    发布帖子请求（一个接口兼容三种来源）。

    - journal_id 有值：游记转发，sections/cover_url/plan_id 缺省从游记取；
    - text 有值：包装为单 section 的 manual 帖；
    - 仅 plan_id 无正文：route 纯路线帖。
    """

    title: str = Field(..., min_length=1, max_length=100, description="标题")
    zone: str = Field(
        "note", pattern="^(circle|note)$", description="发布分区：circle=旅行圈 / note=旅行笔记"
    )
    tags: list[str] = Field(default_factory=list, max_length=5, description="标签（最多 5 个）")
    cover_url: str | None = Field(None, max_length=255, description="封面图 URL")
    sections: list[JournalSection] | None = Field(None, description="分节图文内容")
    text: str | None = Field(None, max_length=5000, description="纯文本正文（快速发帖）")
    journal_id: str | None = Field(None, description="来源游记 ID（游记转发时传入）")
    plan_id: str | None = Field(None, description="关联行程 ID（供「照着走」）")


class PostOut(BaseModel):
    """帖子 feed 卡片响应（不含 content JSON，列表页免拉全量）。"""

    id: str = Field(..., description="帖子 ID")
    user_id: int = Field(..., description="作者用户 ID")
    author: str = Field(..., description="作者昵称")
    post_type: str = Field(..., description="帖子类型：journal/manual/route")
    zone: str = Field("note", description="分区：circle=旅行圈 / note=旅行笔记")
    title: str = Field(..., description="标题")
    summary: str = Field(default="", description="摘要")
    text: str = Field("", description="正文全文（旅行圈卡片展开用，列表免拉详情）")
    photos: list[str] = Field(default_factory=list, description="照片 URL 列表（旅行圈九宫格用）")
    cover_url: str | None = Field(None, description="封面图 URL")
    tags: list[str] = Field(default_factory=list, description="标签")
    plan_id: str | None = Field(None, description="关联行程 ID（有值可「照着走」）")
    like_count: int = Field(default=0, description="点赞数")
    comment_count: int = Field(default=0, description="评论数")
    view_count: int = Field(default=0, description="浏览数")
    created_at: datetime = Field(..., description="发布时间")


class PostDetailOut(PostOut):
    """帖子详情响应（含分节内容与当前用户点赞状态）。"""

    sections: list[JournalSection] = Field(default_factory=list, description="分节图文内容")
    liked: bool = Field(default=False, description="当前用户是否已点赞")


class CommentCreateRequest(BaseModel):
    """发评论请求。parent_id 有值表示回复某条顶级评论（仅支持二级）。"""

    content: str = Field(..., min_length=1, max_length=500, description="评论内容")
    parent_id: str | None = Field(None, description="父评论 ID（须为本帖顶级评论）")


class CommentOut(BaseModel):
    """单条评论响应（顶级评论携带 replies 楼中楼，仅一层）。"""

    id: str = Field(..., description="评论 ID")
    user_id: int = Field(..., description="评论人用户 ID")
    author: str = Field(..., description="评论人昵称")
    content: str = Field(..., description="评论内容")
    created_at: datetime = Field(..., description="评论时间")
    replies: list["CommentOut"] = Field(default_factory=list, description="回复列表")


class FeedOut(BaseModel):
    """广场 feed 分页响应。"""

    posts: list[PostOut] = Field(default_factory=list, description="帖子卡片列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    size: int = Field(default=10, description="每页条数")
    has_more: bool = Field(default=False, description="是否还有下一页")


__all__ = [
    "CheckinCreateRequest",
    "CheckinOut",
    "CommentCreateRequest",
    "CommentOut",
    "FeedOut",
    "JournalOut",
    "JournalSection",
    "JournalUpdateRequest",
    "PostCreateRequest",
    "PostDetailOut",
    "PostOut",
]
