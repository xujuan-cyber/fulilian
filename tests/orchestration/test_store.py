"""Tests for ``agent.orchestration.store`` (phase 2a, decisions D1-D10).

Each test names the decision it pins down. The two acceptance tests that need
multiple processes (``test_concurrent_claim_single_winner`` and
``test_end_to_end_absorption``) live in ``test_store_multiprocess.py`` -- they
cannot be written here because ``:memory:`` is not shareable across processes.
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.schema import SCHEMA_VERSION
from agent.orchestration.state_machine import IllegalTransitionError
from agent.orchestration.store import (
    ClaimedTask,
    FencedOutError,
    NotClaimableError,
    SchemaMismatchError,
    Store,
)


# ------------------------------------------------------------------- helpers


def _card(
    task_id: str = "t1",
    *,
    pool: str = "solve",
    max_retries: int = 1,
    max_handoffs: int = 2,
) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal="produce a report",
        dod=("report exists",),
        output_path=f"/tmp/out/{task_id}.md",
        pool=pool,
        max_retries=max_retries,
        max_handoffs=max_handoffs,
    )


def _row(store: Store, task_id: str) -> sqlite3.Row:
    """Read a task row. ``_conn`` is private, but tests need the raw state."""
    return store._conn.execute(
        "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()


def _count_writes(conn: sqlite3.Connection) -> dict[str, int]:
    """Count ``BEGIN``/write statements via the SQLite trace hook.

    This is the measurement behind acceptance gate (3): the gate counts *write
    transactions*, so ``BEGIN`` and the mutating statements are what matter.
    """
    seen = {"begin": 0, "write": 0}

    def _trace(sql: str) -> None:
        head = sql.split(None, 1)[0].upper() if sql.strip() else ""
        if head == "BEGIN":
            seen["begin"] += 1
        elif head in {"UPDATE", "INSERT", "DELETE", "REPLACE"}:
            seen["write"] += 1

    conn.set_trace_callback(_trace)
    return seen


@pytest.fixture()
def store(tmp_path):
    queue = Store(str(tmp_path / "orchestration.db"), worker_id="w1")
    try:
        yield queue
    finally:
        queue.close()


def _expiring_store(tmp_path, clock: list[float]) -> Store:
    return Store(
        str(tmp_path / "orchestration.db"),
        worker_id="w1",
        now=lambda: clock[0],
    )


# --------------------------------------------------------------------- tests


def test_claim_increments_attempts_atomically(store: Store) -> None:
    """D3/D4: ``attempts`` and ``lease_epoch`` both move inside ONE UPDATE."""
    card = _card()
    store.enqueue(card)
    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)

    first = store.claim("solve")
    assert isinstance(first, ClaimedTask)
    assert (first.attempts, first.lease_epoch) == (1, 1)
    assert first.worker_id == "w1"
    assert first.card == card

    updates = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1, f"claim 必须是单条 UPDATE，实际 {updates}"
    assert "attempts = attempts + 1" in updates[0]
    assert "lease_epoch = lease_epoch + 1" in updates[0]

    # Second round: the increments must be cumulative, not reset.
    store.start(first.task_id, first.lease_epoch)
    store.fail(first.task_id, first.lease_epoch, reason="boom")
    second = store.claim("solve")
    assert second is not None
    assert (second.attempts, second.lease_epoch) == (2, 2)


def test_claim_returns_none_without_write_when_queue_empty(store: Store) -> None:
    """D2: an empty queue must not open a single write transaction.

    Acceptance gate (3) folds 15 workers x 10 minutes down to 60 seconds and
    requires < 10 write transactions per worker; the only way to meet that is
    for the empty-queue path to write nothing at all.
    """
    seen = _count_writes(store._conn)

    for _ in range(20):
        assert store.claim("solve") is None
    assert seen == {"begin": 0, "write": 0}

    # The backoff path (max_wait_seconds > 0) must not write either.
    assert store.claim("solve", max_wait_seconds=0.05) is None
    assert seen == {"begin": 0, "write": 0}

    # A task in another pool is still "empty" for this pool.
    store.enqueue(_card(pool="review"))
    seen = _count_writes(store._conn)  # reset: enqueue's own INSERT is expected
    assert store.claim("solve") is None
    assert seen == {"begin": 0, "write": 0}


def test_stale_epoch_write_is_fenced(store: Store) -> None:
    """D5: a replaced worker's write-back must fail, never silently overwrite."""
    card = _card(max_retries=2)
    store.enqueue(card)

    stale = store.claim("solve")
    assert stale is not None
    store.start(stale.task_id, stale.lease_epoch)
    store.fail(stale.task_id, stale.lease_epoch, reason="worker died")

    fresh = store.claim("solve")
    assert fresh is not None
    assert fresh.lease_epoch == stale.lease_epoch + 1

    with pytest.raises(FencedOutError):
        store.complete(stale.task_id, stale.lease_epoch, output_path=card.output_path)
    with pytest.raises(FencedOutError):
        store.heartbeat(stale.task_id, stale.lease_epoch)
    with pytest.raises(FencedOutError):
        store.start(stale.task_id, stale.lease_epoch)

    # Structural assertion: D5 wants the epoch *in the SQL predicate*, not only
    # in a Python branch -- so the trace of a healthy write-back is checked too.
    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    store.start(fresh.task_id, fresh.lease_epoch)
    store.complete(fresh.task_id, fresh.lease_epoch, output_path=card.output_path)
    writes = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert len(writes) == 2, writes
    assert all("lease_epoch =" in s for s in writes), writes
    assert _row(store, card.task_id)["state"] == "SUCCEEDED"


def test_patrol_lands_in_blocked_not_interrupted(tmp_path) -> None:
    """D7: a crash is BLOCKED (recoverable), never INTERRUPTED (a sink)."""
    clock = [1000.0]
    store = _expiring_store(tmp_path, clock)
    try:
        card = _card()
        store.enqueue(card)
        claimed = store.claim("solve", lease_seconds=10)
        assert claimed is not None
        store.start(claimed.task_id, claimed.lease_epoch)

        clock[0] += 11  # lease expired
        assert store.patrol() == 1

        row = _row(store, card.task_id)
        assert row["state"] == "BLOCKED"
        assert row["state"] != "INTERRUPTED"
        assert row["block_reason"] == "lease_expired"

        # Acceptance (4) in miniature: BLOCKED -> redispatch -> claimable again.
        store.redispatch(card.task_id)
        again = store.claim("solve")
        assert again is not None
        assert again.task_id == card.task_id
        assert again.lease_epoch == claimed.lease_epoch + 1
    finally:
        store.close()


def test_patrol_ignores_live_lease(tmp_path) -> None:
    """D7: patrol must not touch a task whose lease is still valid."""
    clock = [1000.0]
    store = _expiring_store(tmp_path, clock)
    try:
        card = _card()
        store.enqueue(card)
        claimed = store.claim("solve", lease_seconds=300)
        assert claimed is not None
        assert store.patrol() == 0
        assert _row(store, card.task_id)["state"] == "CLAIMED"

        store.start(claimed.task_id, claimed.lease_epoch)
        clock[0] += 299  # still inside the lease
        assert store.patrol() == 0
        assert _row(store, card.task_id)["state"] == "RUNNING"

        # A heartbeat keeps it alive past the original expiry.
        clock[0] += 100
        store.heartbeat(claimed.task_id, claimed.lease_epoch, lease_seconds=300)
        assert store.patrol() == 0
        assert _row(store, card.task_id)["state"] == "RUNNING"
    finally:
        store.close()


def test_redispatch_rejected_at_handoff_cap(tmp_path) -> None:
    """D8: ``handoff_count`` is bumped in the UPDATE and bounded by the cap."""
    clock = [1000.0]
    store = _expiring_store(tmp_path, clock)
    try:
        card = _card(max_handoffs=1)
        store.enqueue(card)
        claimed = store.claim("solve", lease_seconds=10)
        assert claimed is not None
        store.start(claimed.task_id, claimed.lease_epoch)
        clock[0] += 11
        assert store.patrol() == 1
        assert _row(store, card.task_id)["state"] == "BLOCKED"

        with pytest.raises(IllegalTransitionError):
            store.redispatch(card.task_id, handoff_cap=0)
        assert _row(store, card.task_id)["state"] == "BLOCKED"
        assert _row(store, card.task_id)["handoff_count"] == 0

        store.redispatch(card.task_id)
        row = _row(store, card.task_id)
        assert row["state"] == "QUEUED"
        assert row["handoff_count"] == 1
        assert row["block_reason"] is None

        # Cap now exhausted: handoff_count=1 >= card.max_handoffs=1.
        again = store.claim("solve", lease_seconds=10)
        assert again is not None
        store.start(again.task_id, again.lease_epoch)
        clock[0] += 11
        assert store.patrol() == 1
        with pytest.raises(IllegalTransitionError):
            store.redispatch(card.task_id)
        assert _row(store, card.task_id)["state"] == "BLOCKED"
        assert _row(store, card.task_id)["handoff_count"] == 1
    finally:
        store.close()


def test_fail_retries_then_absorbs(store: Store) -> None:
    """D9: RUNNING -> FAILED -> QUEUED while attempts <= max_retries, else FAILED."""
    card = _card(max_retries=1)
    store.enqueue(card)

    first = store.claim("solve")
    assert first is not None and first.attempts == 1
    store.start(first.task_id, first.lease_epoch)
    store.fail(first.task_id, first.lease_epoch, reason="boom")
    assert _row(store, card.task_id)["state"] == "QUEUED"

    second = store.claim("solve")
    assert second is not None and second.attempts == 2
    store.start(second.task_id, second.lease_epoch)
    store.fail(second.task_id, second.lease_epoch, reason="boom again")

    row = _row(store, card.task_id)
    assert row["state"] == "FAILED"  # absorbed: attempts(2) > max_retries(1)
    assert row["completed_at"] is not None
    assert store.claim("solve") is None


def test_schema_mismatch_raises(tmp_path) -> None:
    """D10: no migration branch, no silent downgrade, no ``except: pass``."""
    path = str(tmp_path / "orchestration.db")
    Store(path, worker_id="w1").close()

    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION + 1, 0.0),
    )
    conn.commit()
    conn.close()
    with pytest.raises(SchemaMismatchError):
        Store(path, worker_id="w1")

    # Older than the code is a mismatch too -- we refuse to guess a migration.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM schema_version")
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION - 1, 0.0),
    )
    conn.commit()
    conn.close()
    with pytest.raises(SchemaMismatchError):
        Store(path, worker_id="w1")


# --------------------------------------------------------------------- cancel


def test_cancel_claimed_task(store: Store) -> None:
    """W4 + 阶段 4 补边：``CLAIMED -> CANCELLED`` 现在是合法边。

    补边前这条路径不可达——``_ALLOWED[CLAIMED]`` 没有 ``CANCELLED``，
    ``cancel()`` 只能拒绝。那时靠"worker 在 claim 后立即 start"把窗口压小，
    但那是约定，不是约束。补边后 stop 落在 claim 与 start 之间也能生效。
    """
    store.enqueue(_card())
    claimed = store.claim("solve")
    assert claimed is not None
    assert _row(store, "t1")["state"] == "CLAIMED"

    store.cancel("t1", claimed.lease_epoch)

    row = _row(store, "t1")
    assert row["state"] == "CANCELLED"
    assert row["completed_at"] is not None, "取消是终态，必须写 completed_at"
    assert row["claimed_by"] is None, "取消后不该还挂着持有者"


def test_cancel_running_task(store: Store) -> None:
    """``RUNNING -> CANCELLED``：worker 跑到一半被 stop。"""
    store.enqueue(_card())
    claimed = store.claim("solve")
    assert claimed is not None
    store.start("t1", claimed.lease_epoch)
    assert _row(store, "t1")["state"] == "RUNNING"

    store.cancel("t1", claimed.lease_epoch)

    assert _row(store, "t1")["state"] == "CANCELLED"


def test_cancel_is_fenced_by_epoch(store: Store) -> None:
    """取消也必须带 fencing：拿着过期 epoch 的僵尸不能取消别人的任务。"""
    store.enqueue(_card())
    claimed = store.claim("solve")
    assert claimed is not None
    store.start("t1", claimed.lease_epoch)

    with pytest.raises(FencedOutError):
        store.cancel("t1", claimed.lease_epoch + 1)

    assert _row(store, "t1")["state"] == "RUNNING", "fenced 的取消不得改变状态"


def test_cancel_terminal_task_raises(store: Store) -> None:
    """终态任务再取消必须报错，不能假装成功。"""
    store.enqueue(_card())
    claimed = store.claim("solve")
    assert claimed is not None
    store.start("t1", claimed.lease_epoch)
    store.complete("t1", claimed.lease_epoch, output_path="/tmp/out/t1.md")
    assert _row(store, "t1")["state"] == "SUCCEEDED"

    with pytest.raises(NotClaimableError):
        store.cancel("t1", claimed.lease_epoch)


# ------------------------------------------------- 阶段 4.5 公开只读接口


def test_query_accepts_select_only(store: Store) -> None:
    """``query()`` 只放行 SELECT——这是 S1"纯只读"从约定变成约束的地方。"""
    store.enqueue(_card())

    rows = store.query("SELECT task_id FROM tasks WHERE task_id = ?", ("t1",))
    assert [r["task_id"] for r in rows] == ["t1"]

    for bad in (
        "UPDATE tasks SET state = 'CANCELLED'",
        "DELETE FROM tasks",
        "INSERT INTO events (task_id, kind, payload, created_at) VALUES ('t1','x','{}',1)",
        "WITH x AS (SELECT 1) DELETE FROM tasks",
        "  ",
    ):
        with pytest.raises(ValueError):
            store.query(bad)


def test_query_returns_rows_with_cursor_helpers(store: Store) -> None:
    """``Rows`` 同时是 list 和游标形状，迁移时才不用重写调用点。"""
    store.enqueue(_card())

    rows = store.query("SELECT task_id FROM tasks")
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows.fetchall() == list(rows)
    assert rows.fetchone()["task_id"] == "t1"
    assert store.query("SELECT task_id FROM tasks WHERE 0").fetchone() is None


def test_now_property_exposes_injected_clock(store: Store) -> None:
    """跨模块必须共用同一个时钟，否则注入的假时钟只对 store 生效。"""
    assert callable(store.now)


def test_write_tx_rolls_back_on_exception(store: Store) -> None:
    """公开的 ``write_tx`` 与内部实现同语义：异常必须整体回滚。"""
    store.enqueue(_card())

    with pytest.raises(RuntimeError):
        with store.write_tx() as conn:
            conn.execute("UPDATE tasks SET state = 'CANCELLED' WHERE task_id = 't1'")
            raise RuntimeError("boom")

    assert _row(store, "t1")["state"] == "QUEUED", "异常后必须回滚"


def test_record_event_writes_in_caller_transaction(store: Store) -> None:
    """``record_event`` 用的是调用方的事务连接，所以能和状态变更同生共死。"""
    store.enqueue(_card())

    with pytest.raises(RuntimeError):
        with store.write_tx() as conn:
            conn.execute("UPDATE tasks SET state = 'CANCELLED' WHERE task_id = 't1'")
            store.record_event(conn, "t1", "test_marker", {"k": "v"})
            raise RuntimeError("boom")

    events = store.query("SELECT kind FROM events WHERE kind = 'test_marker'")
    assert len(events) == 0, "事务回滚后事件也必须消失——同事务是这条 API 的意义"


def test_orchestration_modules_do_not_touch_store_internals() -> None:
    """防回归：四个模块不得再访问 ``Store`` 的私有成员。

    这条用 AST 而不是 grep：docstring 里会提到 ``store._conn`` 这类历史说明，
    grep 会误报；只看真实的 ``ast.Attribute`` 节点才准。
    """
    import ast
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "agent" / "orchestration"
    forbidden_attrs = {"_conn", "_write_tx", "_record_event"}

    offenders: list[str] = []
    for name in ("dispatcher.py", "worker.py", "supervisor.py", "redispatch.py"):
        tree = ast.parse((base / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr in forbidden_attrs:
                offenders.append(f"{name}:{node.lineno} .{node.attr}")
            elif node.attr == "_now":
                # 模块自己的 self._now 是合法的；只有 store 的时钟不许碰
                root = node.value
                root_name = getattr(root, "id", None) or getattr(root, "attr", "")
                if "store" in str(root_name):
                    offenders.append(f"{name}:{node.lineno} store._now")

    assert not offenders, (
        "以下位置仍在访问 Store 私有成员，请改用 query()/write_tx()/"
        f"record_event()/now：{offenders}"
    )
