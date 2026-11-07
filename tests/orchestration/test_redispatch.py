"""Tests for ``agent.orchestration.redispatch``（阶段 4 决议 S4-S6）。

函数名按决议 §四固定：``test_redispatch_blocked_at_handoff_cap`` /
``test_route_change_exempts_handoff`` / ``test_cursor_json_survives_redispatch``
/ ``test_plan_does_not_modify_state``。

所有"落 BLOCKED"的前置都走真实路径：``enqueue -> claim -> 租约过期 ->
patrol()``，不直接 UPDATE ``state``——否则测的是自己伪造的状态，patrol 的
CLAIMED -> BLOCKED 语义就没被覆盖到。
"""

from __future__ import annotations

import json

import pytest

from agent.orchestration.contracts import TaskCard, TaskState
from agent.orchestration.redispatch import RedispatchPlan, Redispatcher
from agent.orchestration.state_machine import IllegalTransitionError
from agent.orchestration.store import NotClaimableError, Store


# ------------------------------------------------------------------- helpers


def _card(
    task_id: str = "t1",
    *,
    max_handoffs: int = 2,
    max_retries: int = 1,
) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal="produce a report",
        dod=("report exists",),
        output_path=f"/tmp/out/{task_id}.md",
        pool="solve",
        max_retries=max_retries,
        max_handoffs=max_handoffs,
    )


def _row(store: Store, task_id: str):
    return store._conn.execute(
        "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()


def _set(store: Store, task_id: str, **cols: object) -> None:
    """写派生列。``route_fingerprint`` / ``cursor_json`` 目前没有 store 入口。"""
    assignments = ", ".join(f"{name} = ?" for name in cols)
    store._conn.execute(
        f"UPDATE tasks SET {assignments} WHERE task_id = ?",
        (*cols.values(), task_id),
    )


def _snapshot(store: Store) -> list[tuple]:
    """``tasks`` 全表逐字节快照（S1 用过的同一手法）。"""
    return [
        tuple(row)
        for row in store._conn.execute("SELECT * FROM tasks ORDER BY task_id")
    ]


def _event_count(store: Store) -> int:
    return int(store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


def _block(store: Store, clock: list[float], task_id: str = "t1", *, max_handoffs: int = 2) -> None:
    """enqueue -> claim -> 租约过期 -> patrol()，把任务真正推进 BLOCKED。"""
    store.enqueue(_card(task_id, max_handoffs=max_handoffs))
    claimed = store.claim("solve", lease_seconds=30)
    assert claimed is not None and claimed.task_id == task_id
    clock[0] += 60
    assert store.patrol() == 1
    assert _row(store, task_id)["state"] == TaskState.BLOCKED.value


# ------------------------------------------------------------------ fixtures


@pytest.fixture()
def clock() -> list[float]:
    return [1000.0]


@pytest.fixture()
def store(tmp_path, clock):
    queue = Store(
        str(tmp_path / "orchestration.db"),
        worker_id="w1",
        now=lambda: clock[0],
    )
    try:
        yield queue
    finally:
        queue.close()


@pytest.fixture()
def redispatcher(store, clock) -> Redispatcher:
    return Redispatcher(store, now=lambda: clock[0])


# --------------------------------------------------------------------- tests


def test_redispatch_blocked_at_handoff_cap(store, clock, redispatcher):
    """验收 ④ / S6：``handoff_count == handoff_cap`` 时不得降级放行。"""
    _block(store, clock, max_handoffs=1)
    _set(store, "t1", handoff_count=1)

    plan = redispatcher.plan("t1")
    assert plan.route_changed is False
    assert plan.consumes_handoff is True

    # 异常必须从 transition 的 handoff 守卫冒出来，且不被 apply 吞掉。
    with pytest.raises(IllegalTransitionError, match="转手次数已用尽"):
        redispatcher.apply(plan)

    row = _row(store, "t1")
    assert row["state"] == TaskState.BLOCKED.value
    assert row["handoff_count"] == 1


def test_route_change_exempts_handoff(store, clock, redispatcher):
    """验收 ⑤ / S4：换路线照常重派，但不消耗 handoff 预算。"""
    _block(store, clock, max_handoffs=2)
    _set(store, "t1", route_fingerprint="route-a", handoff_count=1)

    plan = redispatcher.plan("t1", new_route_fingerprint="route-b")
    assert plan.route_changed is True
    assert plan.consumes_handoff is False
    assert "route-b" in plan.reason

    redispatcher.apply(plan)

    row = _row(store, "t1")
    assert row["state"] == TaskState.QUEUED.value
    assert row["handoff_count"] == 1  # 豁免：预算一个没扣
    assert row["block_reason"] is None
    kinds = [
        r["kind"]
        for r in store._conn.execute(
            "SELECT kind FROM events WHERE task_id = 't1'"
        )
    ]
    assert "redispatch_exempt" in kinds  # "这次为什么没扣预算"要能事后查到

    # 对照：指纹不变时同样要重派，但必须扣预算（否则豁免就成了免费通道）。
    clock[0] += 60
    assert store.claim("solve", lease_seconds=30) is not None
    clock[0] += 60
    assert store.patrol() == 1
    same_route = redispatcher.plan("t1")
    assert same_route.route_changed is False
    assert same_route.consumes_handoff is True
    redispatcher.apply(same_route)
    assert _row(store, "t1")["handoff_count"] == 2


def test_cursor_json_survives_redispatch(store, clock, redispatcher):
    """验收 ⑥ / S5：两条重派路径都不得清空续跑点。"""
    cursor = json.dumps({"page": 8, "offset": 42}, sort_keys=True)
    _block(store, clock, "t1", max_handoffs=2)
    _set(store, "t1", cursor_json=cursor, route_fingerprint="route-a")
    _block(store, clock, "t2", max_handoffs=2)
    _set(store, "t2", cursor_json=cursor, route_fingerprint="route-a")

    normal = redispatcher.plan("t1")
    assert normal.resume_from_cursor == cursor
    redispatcher.apply(normal)
    assert _row(store, "t1")["cursor_json"] == cursor

    exempt = redispatcher.plan("t2", new_route_fingerprint="route-b")
    assert exempt.resume_from_cursor == cursor
    redispatcher.apply(exempt)
    assert _row(store, "t2")["cursor_json"] == cursor


def test_plan_does_not_modify_state(store, clock, redispatcher):
    """S1 的同款要求：``plan()`` 是纯读，含 events。"""
    _block(store, clock, max_handoffs=2)
    _set(store, "t1", cursor_json='{"page": 3}', route_fingerprint="route-a")

    before = _snapshot(store)
    events_before = _event_count(store)

    redispatcher.plan("t1")
    redispatcher.plan("t1", new_route_fingerprint="route-b")
    same = redispatcher.plan("t1", new_route_fingerprint="route-a")
    assert same.route_changed is False  # 指纹相同不算换路线

    assert _snapshot(store) == before
    assert _event_count(store) == events_before


def test_apply_persists_new_route_fingerprint(store, clock, redispatcher):
    """新指纹必须落库，否则下一轮 plan() 会把"已换路线"判成"没换"→ 豁免无限重复。"""
    _block(store, clock, max_handoffs=2)
    _set(store, "t1", route_fingerprint="route-a", handoff_count=1)

    plan = redispatcher.plan("t1", new_route_fingerprint="route-b")
    assert plan.new_route_fingerprint == "route-b"
    assert plan.consumes_handoff is False

    redispatcher.apply(plan)

    row = _row(store, "t1")
    assert row["route_fingerprint"] == "route-b"
    assert row["handoff_count"] == 1  # 换路线仍然不记账

    # 关键断言：同一指纹再来一轮，不再是"换路线"，豁免不会重复兑现。
    clock[0] += 60
    assert store.claim("solve", lease_seconds=30) is not None
    clock[0] += 60
    assert store.patrol() == 1

    again = redispatcher.plan("t1", new_route_fingerprint="route-b")
    assert again.route_changed is False
    assert again.consumes_handoff is True
    redispatcher.apply(again)
    assert _row(store, "t1")["handoff_count"] == 2


def test_plan_rejects_task_that_is_not_blocked(store, clock, redispatcher):
    """plan 只对已判死的任务出方案；对 QUEUED 算重派是误用，要吵。"""
    store.enqueue(_card("t1"))
    with pytest.raises(NotClaimableError, match="需要 BLOCKED"):
        redispatcher.plan("t1")


def test_non_exempt_redispatch_keeps_route_fingerprint(store, redispatcher, clock) -> None:
    """非豁免路径（``consumes_handoff=True``）不得改动 ``route_fingerprint``。

    **这条测试的边界要说清楚**：它走的是 ``store.redispatch()`` 那条路，根本不
    碰 ``route_fingerprint``；它验证的是"非豁免重派不会顺手把指纹抹掉"，而不是
    ``_apply_exempt`` 里的 ``COALESCE``。

    ``COALESCE(:fp, route_fingerprint)`` 的 ``None`` 分支**不可达**：豁免路径只在
    ``route_changed=True`` 时进入，而 ``route_changed`` 要求新指纹非 ``None``。
    所以那是防御性代码，无法为它写有效测试——给它写测试只会写出"看起来在测、
    实际没执行到"的假测试。
    """
    _block(store, clock, "t1")
    _set(store, "t1", route_fingerprint="route-a")

    plan = redispatcher.plan("t1")
    assert plan.new_route_fingerprint is None, "没传新指纹，plan 不该凭空造一个"

    redispatcher.apply(plan)

    got = _row(store, "t1")["route_fingerprint"]
    assert got == "route-a", f"指纹被写成 {got!r}；None 分支必须保留原值"
