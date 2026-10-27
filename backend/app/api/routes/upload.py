"""通用媒体上传路由：社区发帖/打卡/游记/私聊共用，文件落盘 backend/uploads，经 /uploads 访问。"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from loguru import logger

from app.api.deps import get_current_user
from app.models.db_models import User
from app.models.schemas import StandardResponse

router = APIRouter()

# 上传目录：backend/uploads（app/api/routes/upload.py 向上三级为 backend/）
UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 扩展名 + content_type 双白名单，uuid 文件名防路径穿越；不做任何服务端转码
# 图片 5MB、视频 50MB（私聊短视频/社区晒图共用一个端点）
IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
VIDEO_EXT = {"mp4", "webm", "mov"}
VIDEO_MIME = {"video/mp4", "video/webm", "video/quicktime"}
MAX_IMAGE = 5 * 1024 * 1024
MAX_VIDEO = 50 * 1024 * 1024


@router.post("", response_model=StandardResponse)
async def upload_media(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
):
    """
    上传图片或视频，返回相对 URL（/uploads/IMG_x.jpg 或 VID_x.mp4），前端负责拼接后端 origin。

    Args:
        file: multipart 文件字段。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: data={"url": "/uploads/IMG_xxx.jpg", "media_type": "image"|"video"}。
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    mime = (file.content_type or "").lower()
    if ext in IMAGE_EXT and mime in IMAGE_MIME:
        prefix, limit, media_type = "IMG", MAX_IMAGE, "image"
    elif ext in VIDEO_EXT and mime in VIDEO_MIME:
        prefix, limit, media_type = "VID", MAX_VIDEO, "video"
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 jpg/png/webp/gif 图片或 mp4/webm/mov 视频",
        )
    data = await file.read()
    if len(data) > limit:
        kind_label = "图片" if media_type == "image" else "视频"
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{kind_label}大小不能超过 {limit // 1024 // 1024}MB",
        )
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / filename).write_bytes(data)
    kind_label = "视频" if media_type == "video" else "图片"
    logger.info(f"[Upload] 用户 {current_user.id} 上传{kind_label} {filename}（{len(data)}B）")
    return StandardResponse(
        success=True,
        message="上传成功",
        data={"url": f"/uploads/{filename}", "media_type": media_type},
    )
