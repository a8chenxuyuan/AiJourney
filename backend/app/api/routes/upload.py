"""通用图片上传路由：社区发帖/打卡/游记共用，文件落盘 backend/uploads，经 /uploads 静态访问。"""

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

# 扩展名 + content_type 双白名单，uuid 文件名防路径穿越；不做任何服务端图像处理
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024


@router.post("", response_model=StandardResponse)
async def upload_image(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
):
    """
    上传图片，返回相对 URL（/uploads/IMG_{uuid}.{ext}），前端负责拼接后端 origin。

    Args:
        file: multipart 文件字段。
        current_user: 当前登录用户。

    Returns:
        StandardResponse: data={"url": "/uploads/IMG_xxx.jpg"}。
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT or (file.content_type or "").lower() not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 jpg/png/webp/gif 图片",
        )
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="图片大小不能超过 5MB"
        )
    filename = f"IMG_{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / filename).write_bytes(data)
    logger.info(f"[Upload] 用户 {current_user.id} 上传图片 {filename}（{len(data)}B）")
    return StandardResponse(success=True, message="上传成功", data={"url": f"/uploads/{filename}"})
