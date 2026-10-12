"""
backend/tests/test_e2e.py

端到端回归测试：固化此前人工验证过的 17 项 e2e 用例。

前置条件（缺一会让本模块整体跳过或失败）：
- 后端 API 运行中（run.py），默认 http://127.0.0.1:8000（API_BASE_URL 可覆盖）；
- ARQ Worker 运行中（worker.py），负责消费规划/修订/爬虫任务；
- Redis（db1）与 Qdrant 可用。

运行方式（backend 目录下）：
    venv\\Scripts\\python.exe -m pytest tests/test_e2e.py -v

容器化栈验证：
    API_BASE_URL=http://127.0.0.1:8080 python -m pytest tests/test_e2e.py -v
"""

import json
import time
import uuid
from datetime import datetime, timedelta

import httpx
import pytest

from tests.conftest import API_BASE_URL, register_and_login

# ==================== 模块级前置检查 ====================
# 收集阶段即探测后端；服务未启动时整模块跳过，单测不受影响
try:
    _probe = httpx.get(f"{API_BASE_URL}/api/health", timeout=3)
    _probe.raise_for_status()
except Exception:  # noqa: BLE001 - 连接失败/超时等一律视为服务不可用
    pytest.skip(
        f"后端服务未运行于 {API_BASE_URL}，跳过 e2e 测试（请先启动 run.py 与 worker.py）",
        allow_module_level=True,
    )

# 轮询参数
PLAN_TIMEOUT_SECONDS = 900      # 规划链路含多次 LLM 调用，留足超时
REVISION_TIMEOUT_SECONDS = 600  # 反馈修订（patch/full 策略含 LLM）
CRAWLER_TIMEOUT_SECONDS = 180   # 爬虫抓取外站，页数=1 时一般 1 分钟内
POLL_INTERVAL_SECONDS = 5


def _wait_until(check, timeout: float, interval: float = POLL_INTERVAL_SECONDS):
    """
    通用轮询：每 interval 秒执行一次 check()，返回首个真值结果，超时返回 None。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval)
    return None


# ==================== 会话级夹具 ====================


@pytest.fixture(scope="session")
def user_headers(client) -> dict:
    """注册并登录一个专属用户，返回认证请求头（整条 e2e 链路共用）。"""
    headers, username = register_and_login(client)
    return headers


@pytest.fixture(scope="session")
def plan_ctx(client, user_headers) -> dict:
    """
    核心链路夹具：创建规划任务 → SSE 监听直至完成。

    返回 {"plan_id", "sse_events", "sse_done"}；后续结果/支付/分享/收藏用例复用。
    """
    start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    resp = client.post(
        "/api/trip/plan",
        headers=user_headers,
        json={
            "city": "杭州",
            "start_date": start,
            "end_date": end,
            "preferences": ["美食", "历史文化"],
            "budget_level": "standard",
        },
    )
    assert resp.status_code == 200, f"创建规划失败: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    plan_id = body["data"]["plan_id"]

    # SSE 流式读取（token 走查询参数），收到最终状态或超时为止
    token = user_headers["Authorization"].removeprefix("Bearer ")
    events: list = []
    sse_done = False
    deadline = time.monotonic() + PLAN_TIMEOUT_SECONDS
    try:
        with client.stream(
            "GET",
            f"/api/agent/trip/{plan_id}/stream",
            params={"token": token},
            timeout=httpx.Timeout(10, read=60),
        ) as resp:
            for line in resp.iter_lines():
                if time.monotonic() > deadline:
                    break
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[len("data: "):])
                events.append(payload)
                status = payload.get("status")
                if status in ("completed", "failed"):
                    sse_done = True
                    break
    except httpx.HTTPError:
        pass  # SSE 中断时回退到下面的轮询兜底

    # 兜底：SSE 异常断开时直接轮询任务状态
    if not sse_done:
        def _finished() -> bool:
            r = client.get(f"/api/trip/{plan_id}", headers=user_headers)
            return r.json().get("data", {}).get("status") in ("completed", "failed")

        _wait_until(_finished, max(0, deadline - time.monotonic()))

    final_status = client.get(f"/api/trip/{plan_id}", headers=user_headers).json()["data"]["status"]
    assert final_status == "completed", (
        f"规划未在 {PLAN_TIMEOUT_SECONDS}s 内完成（当前: {final_status}）；"
        "请确认 worker.py 正在运行且 Redis/LLM 配置可用"
    )

    return {"plan_id": plan_id, "sse_events": events, "sse_done": sse_done}


@pytest.fixture(scope="session")
def revisioned_plan(client, user_headers, plan_ctx) -> str:
    """提交反馈并等待生成 v2 修订版本，返回 plan_id。"""
    plan_id = plan_ctx["plan_id"]

    resp = client.post(
        f"/api/trip/{plan_id}/feedback",
        headers=user_headers,
        json={"raw_text": "把第二天的行程安排得轻松一些，少安排一个景点", "tags": ["节奏轻松"]},
    )
    assert resp.status_code == 200, f"提交反馈失败: {resp.text}"
    assert resp.json()["success"] is True

    # 触发重新生成：POST /feedback 仅保存反馈（revision_type=pending，与前端交互一致），
    # 需调用 regenerate 聚合全部有效反馈并投递修订任务
    resp = client.post(f"/api/trip/{plan_id}/regenerate", headers=user_headers)
    assert resp.status_code == 200, f"触发重新生成失败: {resp.text}"

    def _has_v2() -> bool:
        r = client.get(f"/api/trip/{plan_id}/revisions", headers=user_headers)
        versions = [rev["version"] for rev in r.json()["data"]["revisions"]]
        return max(versions) >= 2 if versions else False

    assert _wait_until(_has_v2, REVISION_TIMEOUT_SECONDS), (
        f"反馈修订未在 {REVISION_TIMEOUT_SECONDS}s 内生成 v2 版本，请确认 worker.py 正在运行"
    )
    return plan_id


# ==================== 用户链路（1-2） ====================


def test_01_register(client):
    """用例1：注册新用户成功。"""
    resp = client.post(
        "/api/auth/register",
        json={
            "username": f"reg_{uuid.uuid4().hex[:8]}",
            "email": f"reg_{uuid.uuid4().hex[:8]}@test.com",
            "password": "test123456",
        },
    )
    assert resp.status_code == 200 and resp.json()["success"] is True


def test_02_login_and_me(client, user_headers):
    """用例2：登录获取 token，且能访问 /me 拿到用户信息。"""
    resp = client.get("/api/auth/me", headers=user_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True
    assert resp.json()["data"]["username"].startswith("e2e_")


# ==================== 规划链路（3-6） ====================


def test_03_plan_created(plan_ctx):
    """用例3：创建规划任务返回 plan_id。"""
    assert plan_ctx["plan_id"]


def test_04_sse_stream_has_events(plan_ctx):
    """用例4：SSE 流式收到 Agent 执行事件且正常收尾。"""
    assert len(plan_ctx["sse_events"]) > 0, "SSE 未收到任何事件"
    assert plan_ctx["sse_done"], "SSE 未收到完成标记"


def test_05_plan_completed(client, user_headers, plan_ctx):
    """用例5：规划完成后可查询到完整行程数据。"""
    resp = client.get(f"/api/trip/{plan_ctx['plan_id']}", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["plan"] is not None


def test_06_feedback_creates_revision_v2(client, user_headers, revisioned_plan):
    """用例6：提交反馈后 Worker 生成 v2 修订版本。"""
    resp = client.get(f"/api/trip/{revisioned_plan}/revisions", headers=user_headers)
    versions = [rev["version"] for rev in resp.json()["data"]["revisions"]]
    assert max(versions) >= 2


# ==================== 支付链路（7-10） ====================


def test_07_payment_create(client, user_headers, plan_ctx):
    """用例7：创建支付订单（沙箱）。"""
    resp = client.post(
        "/api/payment/create",
        headers=user_headers,
        json={"plan_id": plan_ctx["plan_id"], "amount": 199.0, "payment_method": "alipay"},
    )
    assert resp.status_code == 200 and resp.json()["success"] is True
    order = resp.json()["data"]
    assert order["order_id"] and order["status"] in ("pending", "created", "unpaid")


def test_08_payment_notify_marks_paid(client, user_headers, plan_ctx):
    """用例8：支付回调后订单状态变为已支付。"""
    create = client.post(
        "/api/payment/create",
        headers=user_headers,
        json={"plan_id": plan_ctx["plan_id"], "amount": 88.0, "payment_method": "alipay"},
    ).json()["data"]
    order_id = create["order_id"]

    resp = client.post(
        f"/api/payment/notify?order_id={order_id}",
        json={"trade_status": "TRADE_SUCCESS", "out_trade_no": order_id},
    )
    assert resp.status_code == 200 and resp.json()["success"] is True


def test_09_payment_get_order_paid(client, user_headers, plan_ctx):
    """用例9：回调后查询订单详情为已支付。"""
    create = client.post(
        "/api/payment/create",
        headers=user_headers,
        json={"plan_id": plan_ctx["plan_id"], "amount": 88.0, "payment_method": "alipay"},
    ).json()["data"]
    order_id = create["order_id"]
    client.post(
        f"/api/payment/notify?order_id={order_id}",
        json={"trade_status": "TRADE_SUCCESS", "out_trade_no": order_id},
    )

    detail = client.get(f"/api/payment/{order_id}", headers=user_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "paid"


def test_10_payment_orders_list(client, user_headers, plan_ctx):
    """用例10：按行程查询订单列表非空。"""
    resp = client.get("/api/payment/orders", headers=user_headers, params={"plan_id": plan_ctx["plan_id"]})
    assert resp.status_code == 200
    assert len(resp.json()["data"]["orders"]) >= 1


# ==================== 爬虫链路（11） ====================


def test_11_crawler_queue_and_complete(client, user_headers):
    """用例11：爬虫任务入队后由 Worker 执行完成。"""
    resp = client.post(
        "/api/crawler/trigger",
        headers=user_headers,
        json={"cities": ["杭州"], "max_pages": 1},
    )
    assert resp.status_code == 200 and resp.json()["success"] is True
    job_id = resp.json()["data"]["job_id"]

    def _done():
        r = client.get(f"/api/crawler/status/{job_id}", headers=user_headers)
        status = r.json()["data"].get("status")
        if status in ("complete", "completed"):
            return status
        if status == "failed":
            return False
        return None

    assert _wait_until(_done, CRAWLER_TIMEOUT_SECONDS) is not None, (
        f"爬虫任务未在 {CRAWLER_TIMEOUT_SECONDS}s 内完成，请确认 worker.py 正在运行"
    )


# ==================== RAG 知识库链路（12-13） ====================


def test_12_rag_upload(client, user_headers):
    """用例12：上传攻略文档到知识库。"""
    resp = client.post(
        "/api/rag/upload",
        headers=user_headers,
        json={
            "city": "杭州",
            "title": f"杭州美食攻略-{uuid.uuid4().hex[:6]}",
            "content": "杭州西湖附近的楼外楼以西湖醋鱼闻名，河坊街汇聚定胜糕、葱包桧等传统小吃。",
        },
    )
    assert resp.status_code == 200 and resp.json()["success"] is True


def test_13_rag_search_hits(client, user_headers):
    """用例13：检索知识库能命中已上传的攻略（向量库降级时此用例失败）。"""
    resp = client.post(
        "/api/rag/search",
        headers=user_headers,
        json={"query": "西湖附近有什么好吃的", "city": "杭州", "top_k": 3},
    )
    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    assert len(results) >= 1, "RAG 检索无结果：请确认 Qdrant 运行且 Embedding 模型可用"


# ==================== 分享链路（14-17） ====================


@pytest.fixture(scope="session")
def share_token(client, user_headers, revisioned_plan) -> str:
    """用例14：开启行程分享，返回分享令牌。"""
    resp = client.post(
        f"/api/trip/{revisioned_plan}/share",
        headers=user_headers,
        json={"expires_days": 7},
    )
    assert resp.status_code == 200 and resp.json()["success"] is True
    return resp.json()["data"]["share_token"]


def test_15_share_public_view(client, share_token):
    """用例15：免登录通过分享链接访问只读行程。"""
    resp = client.get(f"/api/trip/share/{share_token}")
    assert resp.status_code == 200 and resp.json()["success"] is True
    assert resp.json()["data"]["plan"] is not None


def test_16_share_view_count_is_1(client, user_headers, revisioned_plan, share_token):
    """用例16：公开访问后，所有者侧的分享访问计数应为 1。"""
    resp = client.post(
        f"/api/trip/{revisioned_plan}/share",
        headers=user_headers,
        json={"expires_days": 7},
    )
    data = resp.json()["data"]
    assert data["share_token"] == share_token, "未过期分享应复用同一令牌"
    assert data["share_view_count"] == 1


def test_17_share_close_invalidates(client, user_headers, revisioned_plan, share_token):
    """用例17：关闭分享后原链接立即失效（404）。"""
    resp = client.delete(f"/api/trip/{revisioned_plan}/share", headers=user_headers)
    assert resp.status_code == 200

    public = client.get(f"/api/trip/share/{share_token}")
    assert public.status_code == 404


# ==================== 收藏扩展 ====================


def test_18_favorite_add_and_idempotent(client, user_headers, plan_ctx):
    """用例18：收藏景点幂等——重复收藏返回同一条记录。"""
    item = {
        "city": "杭州",
        "item_type": "attraction",
        "item_id": f"poi_e2e_{uuid.uuid4().hex[:8]}",
        "item_name": "断桥残雪",
        "item_data": {"address": "西湖区北山街"},
    }
    first = client.post("/api/trip/favorites", headers=user_headers, json=item).json()["data"]
    second = client.post("/api/trip/favorites", headers=user_headers, json=item).json()["data"]
    assert first["id"] == second["id"], "重复收藏应幂等返回同一记录"


def test_19_favorite_multi_type_and_list(client, user_headers, plan_ctx):
    """用例19：酒店/餐厅可收藏，列表包含全部类型，按城市筛选生效。"""
    plan_id = plan_ctx["plan_id"]
    suffix = uuid.uuid4().hex[:8]
    client.post("/api/trip/favorites", headers=user_headers, json={
        "city": "杭州", "item_type": "hotel",
        "item_id": f"hotel_e2e_{suffix}", "item_name": "西湖国宾馆", "item_data": {},
    })
    client.post("/api/trip/favorites", headers=user_headers, json={
        "city": "杭州", "item_type": "restaurant",
        "item_id": f"rest_e2e_{suffix}", "item_name": "知味观", "item_data": {},
    })

    resp = client.get("/api/trip/favorites", headers=user_headers)
    items = resp.json()["data"]["favorites"]
    types = {i["item_type"] for i in items}
    assert {"attraction", "hotel", "restaurant"} <= types

    # 收藏涉及的城市列表（去重），供首页"你可能想去"入口使用
    resp = client.get("/api/trip/favorites/cities", headers=user_headers)
    assert "杭州" in resp.json()["data"]["cities"]


def test_20_favorite_delete(client, user_headers, plan_ctx):
    """用例20：取消收藏后列表中不再出现。"""
    item = {
        "city": "杭州",
        "item_type": "attraction",
        "item_id": f"del_e2e_{uuid.uuid4().hex[:8]}",
        "item_name": "临时景点",
        "item_data": {},
    }
    fav_id = client.post("/api/trip/favorites", headers=user_headers, json=item).json()["data"]["id"]

    assert client.delete(f"/api/trip/favorites/{fav_id}", headers=user_headers).status_code == 200
    remaining = client.get("/api/trip/favorites", headers=user_headers).json()["data"]["favorites"]
    assert all(f["id"] != fav_id for f in remaining)


# ==================== 多城市联游 ====================


@pytest.fixture(scope="session")
def multicity_ctx(client, user_headers) -> dict:
    """创建 3 天两城（杭州2天+苏州1天）规划并等待完成。"""
    start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    resp = client.post(
        "/api/trip/plan",
        headers=user_headers,
        json={
            "city": "杭州",
            "start_date": start,
            "end_date": end,
            "cities": [{"city": "杭州", "days": 2}, {"city": "苏州", "days": 1}],
            "preferences": ["历史文化"],
            "budget_level": "standard",
        },
    )
    assert resp.status_code == 200, f"多城规划创建失败: {resp.text}"
    plan_id = resp.json()["data"]["plan_id"]

    def _finished():
        r = client.get(f"/api/trip/{plan_id}", headers=user_headers)
        data = r.json()["data"]
        if data["status"] in ("completed", "failed"):
            return data
        return None

    data = _wait_until(_finished, PLAN_TIMEOUT_SECONDS)
    assert data is not None, f"多城规划未在 {PLAN_TIMEOUT_SECONDS}s 内完成"
    assert data["status"] == "completed", "多城规划失败"
    return {"plan_id": plan_id, "data": data}


def test_21_multicity_plan_completed(multicity_ctx):
    """用例21：多城规划完成，行程数据与城市列表正确返回。"""
    data = multicity_ctx["data"]
    assert data["plan"] is not None
    day_plans = data["plan"]["day_plans"]
    assert len(day_plans) == 3
    assert data["plan"]["cities"] == [{"city": "杭州", "days": 2}, {"city": "苏州", "days": 1}]


def test_22_multicity_day_city_tags(multicity_ctx):
    """用例22：多城行程每天标注所在城市，换城日有城际交通说明。"""
    day_plans = multicity_ctx["data"]["plan"]["day_plans"]
    cities = [d.get("city") for d in day_plans]
    assert cities[0] == "杭州" and cities[1] == "杭州", f"前两天应在杭州，实际: {cities}"
    assert cities[2] == "苏州", f"第三天应在苏州，实际: {cities}"
    transfer_days = [d for d in day_plans if d.get("intercity_note")]
    assert transfer_days, "换城日应包含城际交通说明"


# ==================== 通知与推荐 ====================


def test_23_notifications_api(client, user_headers):
    """用例23：站内通知接口可用（列表+未读数，空也返回结构完整）。"""
    resp = client.get("/api/trip/notifications", headers=user_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True
    data = resp.json()["data"]
    assert "notifications" in data and "unread_count" in data

    marked = client.post("/api/trip/notifications/read-all", headers=user_headers)
    assert marked.status_code == 200 and "marked" in marked.json()["data"]


def test_24_recommendations_api(client, user_headers):
    """用例24：个性化推荐接口可用（收藏过杭州，应有杭州推荐或为空列表）。"""
    resp = client.get("/api/trip/recommendations", headers=user_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True
    items = resp.json()["data"]["items"]
    assert isinstance(items, list)
    for item in items:
        assert item["city"] and item["reason"] and item["source"]


# ==================== 多人协作 ====================


def test_25_collaboration_flow(client, user_headers, make_user, plan_ctx):
    """
    用例25：多人协作链路。

    覆盖：所有者生成邀请 → 用户 B 加入（含重复加入幂等）→ B 查看行程详情 →
    B 查看成员列表 → B 提交反馈（仅保存不 regenerate）→ B 删除行程被 403 拦截 →
    所有者移除 B → B 再访问行程详情被拒绝。

    复用会话级 plan_ctx 规划结果，避免再跑一次慢速规划链路。
    """
    plan_id = plan_ctx["plan_id"]

    # 1. 所有者 A 生成邀请链接
    resp = client.post(f"/api/trip/{plan_id}/collaborators/invite", headers=user_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True, f"生成邀请失败: {resp.text}"
    token = resp.json()["data"]["token"]
    assert token, "邀请响应缺少 token"
    assert resp.json()["data"]["invite_path"] == f"/join/{token}"

    # 2. 用户 B 注册并凭令牌加入协作
    b_headers, b_username = make_user()
    resp = client.post(f"/api/trip/collab/join/{token}", headers=b_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True, f"B 加入协作失败: {resp.text}"
    assert resp.json()["data"]["plan_id"] == plan_id

    # 3. B 重复加入应幂等成功
    resp = client.post(f"/api/trip/collab/join/{token}", headers=b_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True

    # 4. B 可查看行程详情，且 is_owner=False
    resp = client.get(f"/api/trip/{plan_id}", headers=b_headers)
    assert resp.status_code == 200, f"协作者查看行程失败: {resp.text}"
    assert resp.json()["data"]["plan"] is not None
    assert resp.json()["data"]["is_owner"] is False

    # 5. B 可查看成员列表：应同时包含所有者与协作者
    resp = client.get(f"/api/trip/{plan_id}/collaborators", headers=b_headers)
    assert resp.status_code == 200, f"协作者查看成员列表失败: {resp.text}"
    members = resp.json()["data"]["collaborators"]
    assert {m["role"] for m in members} == {"owner", "editor"}
    assert any(m["username"] == b_username and m["role"] == "editor" for m in members)

    # 6. B 提交一条反馈（仅保存，不触发 regenerate）
    resp = client.post(
        f"/api/trip/{plan_id}/feedback",
        headers=b_headers,
        json={"raw_text": "协作者建议：整体节奏可以更轻松一些", "tags": ["其他"]},
    )
    assert resp.status_code == 200 and resp.json()["success"] is True, f"协作者提交反馈失败: {resp.text}"

    # 7. B 尝试删除行程：删除仅限所有者，协作者应被 403 拦截
    resp = client.delete(f"/api/trip/{plan_id}", headers=b_headers)
    assert resp.status_code == 403, f"协作者删除行程应返回 403，实际: {resp.status_code}"

    # 8. 所有者 A 移除协作者 B
    b_user_id = client.get("/api/auth/me", headers=b_headers).json()["data"]["id"]
    resp = client.delete(f"/api/trip/{plan_id}/collaborators/{b_user_id}", headers=user_headers)
    assert resp.status_code == 200 and resp.json()["success"] is True, f"移除协作者失败: {resp.text}"

    # 9. 移除后 B 再查看详情应被拒绝。注意：沿用现有归属校验语义，
    #    无权限统一返回 404（不区分"不存在"与"无权访问"，避免泄露行程存在性）
    resp = client.get(f"/api/trip/{plan_id}", headers=b_headers)
    assert resp.status_code == 404, f"移除后协作者仍可访问行程，实际: {resp.status_code}"
