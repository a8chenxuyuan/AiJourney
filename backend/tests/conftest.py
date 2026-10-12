"""
backend/tests/conftest.py

pytest 共享夹具与配置。

作用：
- 提供指向后端服务的 HTTP 客户端（默认 http://127.0.0.1:8000，
  可通过环境变量 API_BASE_URL 切换到容器化栈，如 http://127.0.0.1:8081）；
- 提供注册+登录的用户工厂，返回带 Authorization 头的请求头。

对应技术：
- pytest fixture
- httpx.Client（同步客户端，便于 SSE 流式读取）
"""

import os
import uuid
from collections.abc import Callable

import httpx
import pytest

# 后端基地址：默认本地开发栈；容器化验证时设 API_BASE_URL=http://127.0.0.1:8081（经 Nginx）
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    """
    会话级 HTTP 客户端，整个测试套件复用连接池。

    禁用 keep-alive 连接复用：uvicorn 默认 5 秒就关闭空闲连接，而 e2e 的
    轮询间隔也是 5 秒，复用旧连接偶发 RemoteProtocolError（服务端已断开）。
    每次请求新建连接对测试场景开销可忽略。
    """
    with httpx.Client(
        base_url=API_BASE_URL,
        timeout=60,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as c:
        yield c


def register_and_login(client: httpx.Client) -> tuple[dict[str, str], str]:
    """
    注册一个随机新用户并登录，返回 (带认证的请求头, 用户名)。

    每次调用生成随机用户名/邮箱，保证用例间互不干扰。
    """
    suffix = uuid.uuid4().hex[:10]
    username = f"e2e_{suffix}"
    email = f"{username}@test.com"
    password = "test123456"

    resp = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert resp.status_code == 200, f"注册失败: {resp.text}"
    assert resp.json()["success"] is True

    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    token = resp.json()["data"]["access_token"]

    return {"Authorization": f"Bearer {token}"}, username


@pytest.fixture(scope="session")
def make_user(client: httpx.Client) -> Callable:
    """用户工厂夹具：调用 make_user() 返回 (认证请求头, 用户名)。"""
    return lambda: register_and_login(client)
