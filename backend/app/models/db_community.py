"""
backend/app/models/db_community.py

社区/社交域数据库模型。

作用：
- 定义帖子、点赞、评论、好友、聊天、互动通知相关的表结构；
- 原 db_models.py 按域拆分而来，所有模型继承自 app.db.base.Base。
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.db.base import Base


class CommunityPost(Base):
    """
    社区帖子表。

    统一承载三种内容来源：journal（游记转发）/ manual（手动图文）/ route（纯路线），
    plan_id / journal_id 均可空，feed 无需 UNION。冗余计数与 summary 让列表页零 JOIN、
    不拉 content JSON；点赞/评论接口用 UPDATE x = x + 1 原子增减。
    plan_id 被删时由删行程逻辑置 NULL（帖子仍可浏览，「照着走」按钮消失）。
    """

    __tablename__ = "community_posts"

    id = Column(String(64), primary_key=True, index=True, comment="帖子 ID（CP_{uuid}）")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="作者 ID")
    plan_id = Column(
        String(64),
        ForeignKey("trip_plans.id"),
        nullable=True,
        index=True,
        comment="来源行程 ID（游记转发/路线帖有值，「照着走」依赖）",
    )
    journal_id = Column(
        String(64),
        ForeignKey("trip_journals.id"),
        nullable=True,
        comment="来源游记 ID（游记转发时有值，详情页可回跳）",
    )
    post_type = Column(
        String(20), nullable=False, comment="帖子类型：journal/manual/route"
    )
    zone = Column(
        String(10),
        nullable=False,
        default="note",
        index=True,
        comment="分区：circle=旅行圈 / note=旅行笔记",
    )
    title = Column(String(100), nullable=False, comment="标题")
    summary = Column(
        String(200), nullable=False, default="", comment="feed 卡片摘要（发布时从内容截取）"
    )
    content = Column(JSON, nullable=True, comment="分节图文 [{day_index,title,text,photos}]")
    cover_url = Column(String(255), nullable=True, comment="封面图 URL")
    tags = Column(JSON, nullable=True, comment="标签列表 [\"美食\", \"亲子\"]")
    like_count = Column(Integer, nullable=False, default=0, comment="点赞数（冗余）")
    comment_count = Column(Integer, nullable=False, default=0, comment="评论数（冗余）")
    view_count = Column(Integer, nullable=False, default=0, comment="浏览数（冗余）")
    status = Column(
        String(20), nullable=False, default="published", comment="状态：published/hidden"
    )
    created_at = Column(DateTime, default=func.now(), index=True, comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")


class PostLike(Base):
    """帖子点赞表。唯一约束防重复点赞，冲突即幂等返回。"""

    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_like"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(
        String(64), ForeignKey("community_posts.id"), nullable=False, index=True, comment="帖子 ID"
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="点赞人 ID"
    )
    created_at = Column(DateTime, default=func.now(), comment="点赞时间")


class PostComment(Base):
    """
    帖子评论表。仅支持二级评论：顶级评论 parent_id 为 NULL，回复指向顶级评论，
    不做无限嵌套（前端一次全拉按 parent_id 分组展示）。
    """

    __tablename__ = "post_comments"

    id = Column(String(64), primary_key=True, index=True, comment="评论 ID（CM_{uuid}）")
    post_id = Column(
        String(64), ForeignKey("community_posts.id"), nullable=False, index=True, comment="帖子 ID"
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="评论人 ID"
    )
    parent_id = Column(String(64), nullable=True, comment="父评论 ID（仅二级：指向顶级评论）")
    content = Column(String(500), nullable=False, comment="评论内容")
    created_at = Column(DateTime, default=func.now(), comment="评论时间")


class Friendship(Base):
    """
    好友关系表（微信式强好友：申请-验证-同意）。

    requester 主动发起，addressee 待处理；status 仅 pending/accepted 两态，
    拒绝即删行（可再次申请），不做黑名单（YAGNI）。
    """

    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("requester_id", "addressee_id", name="uq_friend_pair"),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="关系 ID")
    requester_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="发起人 ID"
    )
    addressee_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="接收人 ID"
    )
    status = Column(String(20), default="pending", comment="状态：pending/accepted")
    verify_message = Column(String(200), nullable=True, comment="验证消息")
    created_at = Column(DateTime, default=func.now(), comment="发起时间")
    accepted_at = Column(DateTime, nullable=True, comment="同意时间")


class ChatMessage(Base):
    """
    用户间单聊消息表。无 conversations 表（YAGNI）：单聊按 (sender, receiver)
    对聚合即可；is_read 由接收方拉取会话/消息时批量置位。
    """

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="消息 ID")
    sender_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="发送人 ID"
    )
    receiver_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="接收人 ID"
    )
    content = Column(Text, nullable=False, comment="消息内容")
    content_type = Column(String(20), default="text", comment="类型：text（预留 image）")
    is_read = Column(Boolean, default=False, index=True, comment="接收方是否已读")
    created_at = Column(DateTime, default=func.now(), index=True, comment="发送时间")


class Notification(Base):
    """
    站内互动通知表（赞/评/回复/好友事件）。

    actor 为触发者；payload 存业务定位字段（post_id/post_title/摘要等），
    聊天未读不走此表（会话列表自带未读数）。
    """

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="通知 ID")
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True, comment="接收人 ID"
    )
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, comment="触发人 ID")
    type = Column(
        String(30),
        nullable=False,
        comment="类型：like/comment/reply/friend_request/friend_accepted",
    )
    payload = Column(JSON, nullable=True, comment="业务字段：post_id/post_title/excerpt 等")
    is_read = Column(Boolean, default=False, index=True, comment="是否已读")
    created_at = Column(DateTime, default=func.now(), index=True, comment="创建时间")


__all__ = [
    "ChatMessage",
    "CommunityPost",
    "Friendship",
    "Notification",
    "PostComment",
    "PostLike",
]
