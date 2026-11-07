"""``agent.orchestration.supervisor`` 的测试（阶段 4，决议 S1-S3/S6）。

每条测试点名它钉住的决议。``redispatch.py`` 的验收（④⑤⑥）由并行任务负责，
这里只覆盖监督层：扫描、去重、TTL、三指标。

时钟：``Store`` 与 ``Supervisor`` 共用同一个可变时钟，租约过期与小时分桶都可
复现。任务一律走真实的 ``enqueue/claim/start/patrol`` 路径造出来，``lease_epoch``
与 ``state`` 才是真的——直接 UPDATE 造状态会让测试钉住一个不存在的现场。
"""

from __future__ import annotations

import hashlib
import json

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.state_machine import IllegalTransitionError
from agent.orchestration.store import Store
from agent.orchestration.supervisor import Finding, Severity, Supervisor


# ------------------------------------------------------------------- helpers


def _card(
    task_id: str = "t1", *, max_retries: int = 1, max_handoffs: int = 2
) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"goal of {task_id}",
        dod=("done",),
        output_path=f"/tmp/out/{task_id}.md",
        max_retries=max_retries,
        max_handoffs=max_handoffs,
    )


@pytest.fixture()
def ctx(tmp_path):
    """``(store, supervisor, clock)``：两者共用同一个可变时钟。"""
    clock = [1000.0]
    store = Store(
        str(tmp_path / "orchestration.db"),
        worker_id="w1",
        now=lambda: clock[0],
    )
    supervisor = Supervisor(store, now=lambda: clock[0])
    try:
        yield store, supervisor, clock
    finally:
        store.close()


def _running(store: Store, task_id: str = "t1", *, lease_seconds: int = 10):
    """造一个 ``RUNNING`` 任务，返回 ``ClaimedTask``。"""
    store.enqueue(_card(task_id))
    claimed = store.claim("solve", lease_seconds=lease_seconds)
    assert claimed is not None and claimed.task_id == task_id
    store.start(claimed.task_id, claimed.lease_epoch)
    return claimed


def _state(store: Store, task_id: str) -> str:
    row = store._conn.execute(
        "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    assert row is not None, f"任务不存在：{task_id}"
    return str(row[0])


def _snapshot(store: Store) -> list[tuple]:
    """``tasks`` 全表快照：列序由 DDL 固定，逐行逐列可比。"""
    return [
        tuple(row)
        for row in store._conn.execute(
            "SELECT * FROM tasks ORDER BY task_id ASC"
        ).fetchall()
    ]


def _digest(rows: list[tuple]) -> str:
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _event_count(store: Store, kind: str) -> int:
    row = store._conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind = ?", (kind,)
    ).fetchone()
    return int(row[0])


def _insert_event(
    store: Store, kind: str, created_at: float, payload: dict | None = None
) -> None:
    store._conn.execute(
        "INSERT INTO events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
        (None, kind, json.dumps(payload or {}, sort_keys=True), created_at),
    )


def _insert_worker(
    store: Store,
    worker_id: str,
    *,
    state: str = "busy",
    last_heartbeat: float = 0.0,
    current_task_id: str | None = None,
) -> None:
    """直接写一行 ``workers``：本阶段还没有任何代码会登记 worker。"""
    store._conn.execute(
        "INSERT INTO workers (worker_id, pool, pid, host, state, capability, "
        "current_task_id, started_at, last_heartbeat) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            worker_id,
            "solve",
            1234,
            "test-host",
            state,
            None,
            current_task_id,
            last_heartbeat,
            last_heartbeat,
        ),
    )

# --------------------------------------------------------------------- tests


def test_scan_detects_stale_lease(ctx) -> None:
    """验收 ① / S1：租约过期的 RUNNING 产出 ``stale_lease``，且**不**改状态。"""
    store, supervisor, clock = ctx
    _running(store, "t1", lease_seconds=10)  # expires 1010
    clock[0] += 11

    findings = supervisor.scan()

    assert {f.kind for f in findings} == {"stale_lease"}, findings
    finding = findings[0]
    assert isinstance(finding, Finding)
    assert finding.task_id == "t1"
    assert finding.severity is Severity.CRITICAL
    assert finding.actioned is False
    assert finding.detected_at == clock[0]
    assert "lease_epoch=1" in finding.detail
    assert "过期 1s" in finding.detail

    # S2：id 必须能从 (kind, task_id, bucket) 独立复算出来，否则去重不成立。
    bucket = int(clock[0] // 3600)
    expected = hashlib.sha1(f"stale_lease:t1:{bucket}".encode("utf-8")).hexdigest()[:16]
    assert finding.finding_id == expected

    # 只告警不裁决：任务仍是 RUNNING，判死是 store.patrol 的事。
    assert _state(store, "t1") == "RUNNING"


def test_scan_does_not_modify_tasks(ctx) -> None:
    """S1 / 验收 ②：扫描前后 ``tasks`` 全表逐字节相同，且没有一条写语句。"""
    store, supervisor, clock = ctx

    # 三种现场：已 BLOCKED、租约过期的 RUNNING、排队中。
    store.enqueue(_card("b-blocked"))
    blocked = store.claim("solve", lease_seconds=5)  # expires 1005
    assert blocked is not None
    store.start(blocked.task_id, blocked.lease_epoch)
    clock[0] += 6
    assert store.patrol() == 1
    assert _state(store, "b-blocked") == "BLOCKED"

    _running(store, "a-stale", lease_seconds=2)  # expires 1008
    clock[0] += 4
    store.enqueue(_card("c-queued"))

    before = _snapshot(store)
    before_digest = _digest(before)

    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    try:
        findings = supervisor.scan()
    finally:
        store._conn.set_trace_callback(None)

    # 扫描必须真的干活，否则"没写"是空断言。
    assert [f.task_id for f in findings] == ["a-stale"], findings

    after = _snapshot(store)
    assert _digest(after) == before_digest, "scan() 改动了 tasks 表"
    assert after == before, "scan() 改动了 tasks 表"

    writes = [
        sql
        for sql in statements
        if sql.lstrip().split(None, 1)[0].upper()
        in {"UPDATE", "INSERT", "DELETE", "REPLACE", "BEGIN"}
    ]
    assert writes == [], f"scan() 发出了写语句：{writes}"


def test_record_deduplicates_within_bucket(ctx) -> None:
    """S2 / 验收 ③：同一小时内重复扫描只落一条，跨桶才是新的一条。"""
    store, supervisor, clock = ctx
    _running(store, "t1", lease_seconds=10)
    clock[0] += 11

    first = supervisor.scan()
    assert len(first) == 1
    assert supervisor.record(first) == 1
    assert _event_count(store, "supervisor_finding") == 1

    # 同一桶内再扫一次：id 不变，record 不刷屏。
    clock[0] += 60
    second = supervisor.scan()
    assert second[0].finding_id == first[0].finding_id
    assert supervisor.record(second) == 0
    assert _event_count(store, "supervisor_finding") == 1

    # 空输入不写。
    assert supervisor.record([]) == 0

    # 跨桶：新的一条。
    clock[0] += 3600
    third = supervisor.scan()
    assert third[0].finding_id != first[0].finding_id
    assert supervisor.record(third) == 1
    assert _event_count(store, "supervisor_finding") == 2


def test_sweep_events_respects_ttl(ctx) -> None:
    """S6 / 验收 ⑦：普通事件按 TTL 删，指标事件保留双倍时长。"""
    store, supervisor, clock = ctx  # now == 1000.0

    _insert_event(store, "task_succeeded", 850.0)  # 普通，已过 150s -> 删
    _insert_event(store, "task_failed", 950.0)  # 普通，未过 -> 留
    _insert_event(store, "supervisor_finding", 850.0, {"finding_id": "f-old"})  # 2x 内 -> 留
    _insert_event(store, "supervisor_finding", 750.0, {"finding_id": "f-gone"})  # 超 2x -> 删
    _insert_event(store, "supervisor_actioned", 850.0, {"finding_id": "f-old"})  # 同 finding -> 留

    deleted = supervisor.sweep_events(older_than=100.0)

    assert deleted == 2
    remaining = [
        (str(row[0]), float(row[1]))
        for row in store._conn.execute(
            "SELECT kind, created_at FROM events ORDER BY kind ASC"
        ).fetchall()
    ]
    assert remaining == [
        ("supervisor_actioned", 850.0),
        ("supervisor_finding", 850.0),
        ("task_failed", 950.0),
    ]
    # 双倍保留：指标事件仍在，普通事件已走。
    assert _event_count(store, "supervisor_finding") == 1
    assert _event_count(store, "task_succeeded") == 0


def test_metrics_returns_three_ratios(ctx) -> None:
    """S3 / 验收 ⑧：三个键、取值在 [0,1]，且数值可手工复算。"""
    store, supervisor, clock = ctx
    _running(store, "t1", lease_seconds=10)  # expires 1011
    _running(store, "t2", lease_seconds=10)  # expires 1012
    clock[0] += 20

    findings = supervisor.scan()
    assert len(findings) == 2
    assert supervisor.record(findings) == 2

    # 处置其中一条：precision = 1/2。
    supervisor.mark_actioned(findings[0].finding_id, note="人工确认")

    metrics = supervisor.metrics()
    assert set(metrics) == {"precision", "actionable_rate", "repeat_rate"}
    assert metrics["precision"] == pytest.approx(0.5)
    assert metrics["actionable_rate"] == pytest.approx(0.5)
    # 每个 (kind, task_id) 目前只有一个 bucket -> 没有重复。
    assert metrics["repeat_rate"] == pytest.approx(0.0)

    # 跨桶再扫一轮：两个分组都出现第二个 bucket -> repeat_rate = 1.0，
    # 分子不变（仍是 1 条已处置）、分母变 4 -> precision = 0.25。
    clock[0] += 3600
    again = supervisor.scan()
    assert len(again) == 2
    assert supervisor.record(again) == 2

    metrics = supervisor.metrics()
    assert metrics["precision"] == pytest.approx(0.25)
    assert metrics["actionable_rate"] == pytest.approx(0.25)
    assert metrics["repeat_rate"] == pytest.approx(1.0)
    for key, value in metrics.items():
        assert 0.0 <= value <= 1.0, (key, value)

    # 窗口内无样本：三个键都在，取 0.0（不是 NaN）。
    clock[0] += 100
    empty = supervisor.metrics(window_seconds=1.0)
    assert set(empty) == {"precision", "actionable_rate", "repeat_rate"}
    assert all(value == 0.0 for value in empty.values())


def test_mark_actioned_is_idempotent_and_rejects_unknown(ctx) -> None:
    """``mark_actioned`` 只追加一条反馈事件；未知 id 抛错而不是静默成功。"""
    store, supervisor, clock = ctx
    _running(store, "t1", lease_seconds=10)
    clock[0] += 11
    findings = supervisor.scan()
    supervisor.record(findings)

    supervisor.mark_actioned(findings[0].finding_id)
    supervisor.mark_actioned(findings[0].finding_id)  # 幂等
    assert _event_count(store, "supervisor_actioned") == 1

    with pytest.raises(LookupError):
        supervisor.mark_actioned("does-not-exist")
    assert _event_count(store, "supervisor_actioned") == 1

    with pytest.raises(ValueError):
        supervisor.mark_actioned("")


def test_scan_detects_retry_exhausted(ctx) -> None:
    """``attempts > max_retries`` 的 FAILED 必须报出来：自动重试已经用尽。"""
    store, supervisor, _clock = ctx
    store.enqueue(_card("t1", max_retries=1))

    first = store.claim("solve", lease_seconds=300)
    assert first is not None and first.attempts == 1
    store.start(first.task_id, first.lease_epoch)
    store.fail(first.task_id, first.lease_epoch, reason="第一次")
    assert _state(store, "t1") == "QUEUED"  # attempts=1 <= max_retries=1，还有一次

    second = store.claim("solve", lease_seconds=300)
    assert second is not None and second.attempts == 2
    store.start(second.task_id, second.lease_epoch)
    store.fail(second.task_id, second.lease_epoch, reason="第二次")
    assert _state(store, "t1") == "FAILED"  # attempts=2 > 1，不再回队

    findings = supervisor.scan()

    assert [f.kind for f in findings] == ["retry_exhausted"], findings
    finding = findings[0]
    assert finding.task_id == "t1"
    assert finding.severity is Severity.WARN
    assert "attempts=2 > max_retries=1" in finding.detail
    assert finding.actioned is False


def test_scan_detects_handoff_exhausted(ctx) -> None:
    """``handoff_count >= max_handoffs`` 的 BLOCKED：再重派必被状态机拒绝。"""
    store, supervisor, clock = ctx
    store.enqueue(_card("t1", max_handoffs=1))

    claimed = store.claim("solve", lease_seconds=10)
    assert claimed is not None
    store.start(claimed.task_id, claimed.lease_epoch)
    clock[0] += 11
    assert store.patrol() == 1
    assert _state(store, "t1") == "BLOCKED"

    store.redispatch("t1")  # handoff_count: 0 -> 1，cap=1 已到顶
    again = store.claim("solve", lease_seconds=10)
    assert again is not None
    store.start(again.task_id, again.lease_epoch)
    clock[0] += 11
    assert store.patrol() == 1
    assert _state(store, "t1") == "BLOCKED"

    findings = supervisor.scan()

    assert [f.kind for f in findings] == ["handoff_exhausted"], findings
    finding = findings[0]
    assert finding.task_id == "t1"
    assert finding.severity is Severity.WARN
    assert "handoff_count=1 >= max_handoffs=1" in finding.detail

    # 告警说的必须是真的：此刻重派确实会被拒。
    with pytest.raises(IllegalTransitionError):
        store.redispatch("t1")


def test_scan_detects_orphan_worker(ctx) -> None:
    """登记还在、心跳早停的 worker 要报；活着的登记不许误报。"""
    store, supervisor, clock = ctx
    _insert_worker(store, "w-zombie", state="busy", last_heartbeat=clock[0] - 10000.0)
    _insert_worker(store, "w-live", state="busy", last_heartbeat=clock[0] - 5.0)

    findings = supervisor.scan()

    assert [f.kind for f in findings] == ["orphan_worker"], findings
    finding = findings[0]
    assert finding.task_id is None  # 空闲僵尸 worker：没有任务可归属
    assert finding.severity is Severity.WARN
    assert "w-zombie" in finding.detail
    assert "心跳已停" in finding.detail
    assert "w-live" not in finding.detail


def test_orphan_findings_do_not_collapse_across_workers(ctx) -> None:
    """多个空闲僵尸必须各报一条，不能被去重折叠成一条。

    空闲僵尸 worker 的 ``current_task_id`` 是 ``None``。若 ``finding_id`` 只由
    ``kind:task_id:bucket`` 组成，同一小时内所有空闲僵尸会算出**同一个 id**，
    ``record()`` 去重后 10 个死 worker 只报 1 条——告警数量不随故障规模增长，
    运维会以为"只有一台机器挂了"。

    修法是给 ``_finding_id`` 加 ``subject``，worker 级告警传 ``worker_id``。
    """
    store, supervisor, clock = ctx
    _insert_worker(store, "w-zombie-a", state="idle", last_heartbeat=clock[0] - 10000.0)
    _insert_worker(store, "w-zombie-b", state="idle", last_heartbeat=clock[0] - 10000.0)

    findings = supervisor.scan()
    orphans = [f for f in findings if f.kind == "orphan_worker"]

    assert len(orphans) == 2, (
        f"两个空闲僵尸应各报一条，实际 {len(orphans)} 条；"
        "折叠成一条说明 finding_id 没有区分 worker"
    )
    assert len({f.finding_id for f in orphans}) == 2, "两条告警的 finding_id 必须不同"
    details = " ".join(f.detail for f in orphans)
    assert "w-zombie-a" in details and "w-zombie-b" in details


def test_orphan_forms_do_not_collide_for_same_worker(ctx) -> None:
    """同一个 worker 命中两种 orphan 形态时，两条告警必须有不同 id。

    构造：worker 以为自己持有 ``gone``，但该任务不存在（``stale_worker``），
    同时它的心跳也早停了（``stale_heartbeat``）。

    如果 ``subject`` 只取 ``worker_id``，两条 finding 会算出同一个 id：
    ``record()`` 写 2 行同 id，``metrics()`` 按 id 去重只计 1（分母失真），
    ``mark_actioned`` 一次命中两条。带上 form 后各自独立。
    """
    store, supervisor, clock = ctx
    _insert_worker(
        store,
        "w-dup",
        state="busy",
        last_heartbeat=clock[0] - 10000.0,
        current_task_id="gone",
    )

    findings = supervisor.scan()
    orphans = [f for f in findings if f.kind == "orphan_worker"]

    assert len(orphans) == 2, (
        f"应同时报出 stale_worker 与 stale_heartbeat 两条，实际 {len(orphans)}"
    )
    ids = [f.finding_id for f in orphans]
    assert len(set(ids)) == 2, (
        f"两条 orphan 告警的 finding_id 撞了：{ids}；"
        "subject 必须带上形态（dead_holder/stale_worker/stale_heartbeat）"
    )
