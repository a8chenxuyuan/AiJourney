"""管理员提升脚本：把指定用户名提升为 admin。

用法（backend 目录下）：
    .\\venv\\Scripts\\python.exe promote_admin.py <用户名>

用于初始化第一个管理员（注册接口不会自动产生管理员）。
"""

import asyncio
import sys

from sqlalchemy import select, update

from app.core.db.session import AsyncSessionLocal
from app.models.db_models import User


async def promote(username: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(User).where(User.username == username).values(role="admin")
        )
        await session.commit()
        if result.rowcount == 0:
            user = (
                await session.execute(select(User).where(User.username == username))
            ).scalar_one_or_none()
            if user is None:
                print(f"错误：用户 {username!r} 不存在")
                sys.exit(1)
        else:
            print(f"成功：用户 {username!r} 已提升为管理员")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python promote_admin.py <用户名>")
        sys.exit(1)
    asyncio.run(promote(sys.argv[1]))
