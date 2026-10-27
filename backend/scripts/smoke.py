"""
backend/scripts/smoke.py

架构升级总验收冒烟（五条用例）。

用法（需先启动 DB / Redis / API / Worker 全栈）：
    .\\venv\\Scripts\\python.exe scripts\\smoke.py --base http://localhost:8000
    .\\venv\\Scripts\\python.exe scripts\\smoke.py --base http://localhost:8000 --no-wait

用例：
1. health          GET /api/health
2. 登录            注册随机用户 + 登录取 token
3. 规划入队        POST /api/trip 创建行程并入队（--no-wait 只验入队；默认轮询至终态）
4. 断点续跑(单元)  checkpoint 编解码 roundtrip（含 Pydantic 对象还原）+ save/load/clear + claim CAS
5. 审批恢复(单元)  check_budget_overrun 超支判定 + 审批三态常量 + state 审批插槽

五条全过输出 SMOKE ALL PASSED，任一失败非零退出。
"""

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

# ==================== 用例 4/5 所需的单元级依赖 ====================
from app.agentkit.approval import APPROVAL_APPROVED, APPROVAL_PENDING, APPROVAL_REJECTED
from app.agentkit.checkpoint import clear_checkpoint, decode_state, encode_state, load_checkpoint
from app.core.db.init_db import init_db
from app.core.db.session import AsyncSessionLocal
from app.models.db_models import TripPlanDB
from app.models.schemas import Budget, CityStay, TripPlan
from app.services.plan_persist_service import claim_plan_for_run
from app.travel.budget import check_budget_overrun

BASE = "http://localhost:8000"
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""))


# ==================== 用例 1：health ====================


async def case_health(client: httpx.AsyncClient) -> None:
    print("== 用例 1：health ==")
    resp = await client.get("/api/health")
    record("GET /api/health", resp.status_code == 200, f"status={resp.status_code}")


# ==================== 用例 2：登录 ====================


async def case_auth(client: httpx.AsyncClient) -> tuple[str | None, int | None]:
    print("== 用例 2：注册 + 登录 ==")
    username = f"smoke_{uuid.uuid4().hex[:8]}"
    payload = {"username": username, "email": f"{username}@smoke.test", "password": "smoke123456"}
    resp = await client.post("/api/auth/register", json=payload)
    if resp.status_code != 200:
        record("注册", False, f"status={resp.status_code} body={resp.text[:120]}")
        return None, None
    user_id = (resp.json().get("data") or {}).get("user_id")
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": "smoke123456"}
    )
    token = (resp.json().get("data") or {}).get("access_token") if resp.status_code == 200 else None
    record("登录", bool(token), "" if token else f"status={resp.status_code}")
    return token, user_id


# ==================== 用例 3：规划入队（可选等待终态） ====================


async def case_planning_enqueue(client: httpx.AsyncClient, token: str, wait: bool) -> None:
    print("== 用例 3：规划入队 ==")
    body = {
        "city": "北京",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "budget_level": "standard",
        "preferences": ["历史文化"],
    }
    resp = await client.post(
        "/api/trip", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    plan_id = (resp.json().get("data") or {}).get("plan_id") if resp.status_code == 200 else None
    record("POST /api/trip 入队", bool(plan_id), f"plan_id={plan_id}")
    if not plan_id or not wait:
        return

    deadline = time.monotonic() + 420
    status = "pending"
    while time.monotonic() < deadline:
        detail = await client.get(
            f"/api/trip/{plan_id}", headers={"Authorization": f"Bearer {token}"}
        )
        status = (detail.json().get("data") or {}).get("status", "")
        if status in ("completed", "failed", "pending_approval"):
            break
        await asyncio.sleep(5)
    record("规划轮询至终态", status == "completed", f"final status={status}")


# ==================== 用例 4：断点续跑（单元级） ====================


async def case_checkpoint() -> None:
    print("== 用例 4：断点续跑（checkpoint roundtrip + claim CAS） ==")
    smoke_id = f"smoke-{uuid.uuid4().hex[:12]}"
    try:
        # roundtrip：含 Pydantic 对象的 state 编码 → 解码还原
        state = {"plan_id": smoke_id, "cities": ["北京", "上海"], "intent_analysis": CityStay(city="北京", days=2)}
        encoded = encode_state(state)
        decoded = decode_state(encoded)
        ok = (
            decoded["cities"] == ["北京", "上海"]
            and isinstance(decoded["intent_analysis"], CityStay)
            and decoded["intent_analysis"].days == 2
        )
        record("checkpoint 编解码 roundtrip", ok)

        # save / load / clear
        await clear_checkpoint(smoke_id, "planning")
        await _save(smoke_id, 3, encoded)
        loaded = await load_checkpoint(smoke_id, "planning")
        record("checkpoint 保存/加载", bool(loaded) and loaded["batch_index"] == 3)
        await clear_checkpoint(smoke_id, "planning")
        record("checkpoint 清除", (await load_checkpoint(smoke_id, "planning")) is None)

        # claim CAS：不存在的 plan 抢占必须失败且不报错
        claimed = await claim_plan_for_run(f"smoke-none-{uuid.uuid4().hex[:6]}")
        record("claim CAS（不存在行程 → False）", claimed is False)
    finally:
        await clear_checkpoint(smoke_id, "planning")


async def _save(plan_id: str, batch_index: int, encoded: bytes) -> None:
    from app.agentkit.checkpoint import save_checkpoint

    await save_checkpoint(plan_id, "planning", batch_index, decode_state(encoded))


# ==================== 用例 5：审批恢复（单元级） ====================


async def case_approval(user_id: int | None = None) -> None:
    print("== 用例 5：审批协议（超支判定 + 三态 + 状态插槽） ==")
    over = TripPlan(
        plan_id="smoke-over",
        city="北京",
        start_date="2026-11-01",
        end_date="2026-11-02",
        travel_days=2,
        budget=Budget(attractions=100, meals=200, hotels=2400, transportation=100, total=2800),
    )
    detail = check_budget_overrun(over, "standard")
    record(
        "超支判定（2800 元 / standard×2 天）",
        bool(detail) and detail["total"] == 2800.0 and detail["daily_limit"] == 800.0,
        f"detail={detail}",
    )
    under = over.model_copy(deep=True)
    under.budget.total = 1000
    record("未超支判定", check_budget_overrun(under, "standard") is None)
    record(
        "审批三态常量",
        APPROVAL_PENDING == "pending_approval"
        and APPROVAL_APPROVED == "approved"
        and APPROVAL_REJECTED == "rejected",
    )
    if user_id is None:
        record("pending_approval 行程 claim CAS", True, "无可用用户，跳过 DB 断言")
        return
    # pending_approval 行程必须可被 claim CAS 抢占（审批恢复续跑的前提）——
    # 用真实 DB 行验证：插入一条 pending_approval 行 → claim 成功 → 清理
    smoke_id = f"smoke-approve-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                TripPlanDB(
                    id=smoke_id,
                    user_id=user_id,
                    city="北京",
                    start_date="2026-11-01",
                    end_date="2026-11-02",
                    travel_days=2,
                    status="pending_approval",
                    request_data={},
                )
            )
            await session.commit()
        record("pending_approval 行程 claim CAS", (await claim_plan_for_run(smoke_id)) is True)
    finally:
        async with AsyncSessionLocal() as session:
            plan = await session.get(TripPlanDB, smoke_id)
            if plan:
                await session.delete(plan)
                await session.commit()


async def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--no-wait", action="store_true", help="用例 3 只验入队不等待终态")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    user_id: int | None = None
    # 独立运行时先确保新表存在（init_db 幂等）
    await init_db()
    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
            await case_health(client)
            token, user_id = await case_auth(client)
            if token:
                await case_planning_enqueue(client, token, wait=not args.no_wait)
    except httpx.HTTPError as exc:
        record("HTTP 全栈可达", False, f"{type(exc).__name__}: {exc}")
    await case_checkpoint()
    await case_approval(user_id)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\nSMOKE {'ALL PASSED' if not failed else 'FAILED'}（{len(results) - len(failed)}/{len(results)}）")
    if failed:
        print("失败用例: " + ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
