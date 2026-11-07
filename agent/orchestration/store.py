"""Orchestration queue storage -- enqueue, claim, lease, lifecycle.

Frozen contract: ``docs/design/orchestration-phase2a-store-decisions.md``
(decisions D1-D10). Signature changes need the controller's approval: phase 3's
``dispatcher.py`` calls this module directly, so anything here is public API.

This module is the *only* holder of the queue database, therefore it is the only
place that sets ``journal_mode`` (D1). It makes no scheduling decisions and
imports nothing from ``tools.*``.

Three invariants are load-bearing and must not be "simplified":

* **D2 read-before-write** -- an empty queue never opens a write transaction.
  Acceptance gate (3) -- 15 workers x 10 minutes, < 100 write transactions -- is
  met by the cheap probe in :meth:`Store.claim`, not by tuning ``busy_timeout``.
* **D3/D4 atomic increment** -- ``attempts`` and ``lease_epoch`` are incremented
  inside the claim ``UPDATE``. Reading them first would let two workers claim
  with the same ``attempts``.
* **D5 fencing** -- every write-back carries ``AND lease_epoch = ?`` and trusts
  ``rowcount``; a preceding ``SELECT`` is never a substitute (TOCTOU).

One contract gap was found and is reported to the controller rather than patched
here: ``state_machine._ALLOWED`` has **no** ``CLAIMED -> BLOCKED`` edge, while
D7 asks patrol to scan ``CLAIMED`` as well. See :meth:`Store._block_expired`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import random
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Iterator

from agent.orchestration.contracts import (
    Isolation,
    TaskCard,
    TaskRole,
    TaskState,
    TaskTier,
    validate_card,
)
from agent.orchestration.schema import (
    SCHEMA_VERSION,
    SchemaError,
    configure_connection,
    current_version,
    migrate,
)
from agent.orchestration.state_machine import transition

__all__ = [
    "ClaimedTask",
    "FencedOutError",
    "NotClaimableError",
    "SchemaMismatchError",
    "Store",
    "StoreError",
]

#: D2 step 3 -- the claim scan order, verbatim from the frozen decision.
_CLAIM_ORDER = "is_key DESC, priority DESC, bottom_level DESC, created_at ASC"

#: D2 -- probe first, write later.
_PROBE_SQL = "SELECT 1 FROM tasks WHERE state = ? AND pool = ? LIMIT 1"

#: D2 step 3 -- re-read inside the write transaction; the probe may be stale.
_PICK_SQL = (
    "SELECT task_id, lease_epoch, attempts, card_json FROM tasks "
    "WHERE state = ? AND pool = ? "
    f"ORDER BY {_CLAIM_ORDER} LIMIT 1"
)

#: D3 + D4 -- state, holder, lease, epoch and attempts change in ONE statement.
_CLAIM_UPDATE = """
UPDATE tasks SET
    state = :claimed,
    claimed_by = :worker_id,
    claimed_at = :now,
    lease_expires = :expires,
    lease_epoch = lease_epoch + 1,
    attempts = attempts + 1,
    updated_at = :now
WHERE task_id = :task_id AND state = :queued
"""


class Rows(list):
    """``Store.query()`` 的返回值：``list[sqlite3.Row]``，同时保留游标式取值。

    存在的唯一理由是让迁移只改"访问私有成员"这一件事：调用方原本写
    ``store._conn.execute(sql, p).fetchall()``，迁到 ``store.query(sql, p)``
    后不必再改 ``.fetchall()`` / ``.fetchone()`` 的写法。迁移应当是可审阅的，
    不该夹带重写七处多行调用。
    """

    def fetchall(self) -> list[sqlite3.Row]:
        return list(self)

    def fetchone(self) -> sqlite3.Row | None:
        return self[0] if self else None


class StoreError(Exception):
    """Base class for storage errors."""


class FencedOutError(StoreError):
    """The ``lease_epoch`` did not match: this worker was replaced."""


class NotClaimableError(StoreError):
    """The task's current state does not allow this action."""


class SchemaMismatchError(StoreError):
    """The database schema version does not match this code (D10)."""


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """A successful :meth:`Store.claim`. ``lease_epoch`` is the fencing token."""

    task_id: str
    lease_epoch: int
    attempts: int
    worker_id: str
    card: TaskCard


# --------------------------------------------------------------- serialisation


def _card_to_json(card: TaskCard) -> str:
    """Serialise the card snapshot. ``StrEnum``/``IntEnum`` are JSON-native."""
    return json.dumps(
        dataclasses.asdict(card), sort_keys=True, ensure_ascii=False
    )


def _card_from_json(payload: str) -> TaskCard:
    """Rebuild a :class:`TaskCard` from ``card_json``.

    ``asdict`` turns tuples into lists, so the tuple-typed fields are restored;
    the three enum fields come back as ``str``/``int`` and are re-wrapped. A
    wrong type must fail loudly -- a silently "almost right" card would hash
    differently and break the audit trail.
    """
    raw = json.loads(payload)
    for name in ("dod", "allowed_toolsets", "resources", "depends_on"):
        raw[name] = tuple(raw.get(name) or ())
    raw["role"] = TaskRole(raw["role"])
    raw["tier"] = TaskTier(raw["tier"])
    isolation = raw.get("isolation")
    raw["isolation"] = None if isolation is None else Isolation(isolation)
    return TaskCard(**raw)


def _card_hash(card_json: str) -> str:
    return hashlib.sha256(card_json.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- store


class Store:
    """SQLite-backed queue: the single holder of ``orchestration.db``."""

    def __init__(
        self,
        db_path: str,
        *,
        worker_id: str,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not worker_id:
            raise StoreError("worker_id 不能为空")
        self._db_path = db_path
        self._worker_id = worker_id
        self._now = now
        # isolation_level=None -> autocommit; every transaction is explicit so
        # an empty queue cannot accidentally open a write transaction (D2).
        self._conn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        try:
            # D1: journal_mode is a persistent property of the file and only the
            # owner sets it. schema.configure_connection() deliberately does not.
            self._conn.execute("PRAGMA journal_mode=WAL").fetchone()
            configure_connection(self._conn, busy_timeout_ms=5000)
            self._open_schema()
        except BaseException:
            self._conn.close()
            raise

    # -- lifecycle ---------------------------------------------------------

    def _open_schema(self) -> None:
        """D10: migrate-or-fail. No silent downgrade, no ``except: pass``."""
        # D10: migrate-or-fail. ``migrate()`` registers upgrade steps; when a step
        # is missing it raises instead of leaving the database half-upgraded.
        try:
            applied = migrate(self._conn)
        except SchemaError as exc:
            raise SchemaMismatchError(str(exc)) from exc
        if applied != SCHEMA_VERSION:
            raise SchemaMismatchError(
                f"迁移后版本仍为 {applied}，期望 {SCHEMA_VERSION}"
            )
        applied = current_version(self._conn)
        if applied != SCHEMA_VERSION:
            raise SchemaMismatchError(
                f"应用 schema 后版本仍为 {applied}，期望 {SCHEMA_VERSION}"
            )

    # -- 公开只读 / 公开事务接口（阶段 4.5）--------------------------------
    #
    # 引入理由：``dispatcher`` / ``worker`` / ``supervisor`` / ``redispatch``
    # 四个模块此前共 9 处直接访问 ``_conn`` / ``_now`` / ``_write_tx`` /
    # ``_record_event``。那是封装泄漏——store 一改内部结构，四个模块同时坏，
    # 且没有任何编译期信号。这里把"跨模块需要的那几个口子"显式开出来，
    # 私有成员从此只属于 store 自己。

    @property
    def now(self) -> Callable[[], float]:
        """注入的时钟。

        调用方不该自己 ``import time``：worker 的空闲超时、supervisor 的分桶、
        redispatch 的事件时间戳都必须用**同一个**时钟，否则测试里注入的假时钟
        只对 store 生效，跨模块的时间逻辑就没法确定性验证。
        """
        return self._now

    def query(self, sql: str, params: Sequence[object] = ()) -> "Rows":
        """只读查询。**只接受 ``SELECT`` 开头的语句**，其余抛 :class:`ValueError`。

        这个限制不是形式主义：``Supervisor.scan()`` 的契约是"零写操作"，而
        靠约定维持的只读迟早会被一次复制粘贴破坏。把守卫放在唯一入口上，
        误写会在开发期立刻炸掉，而不是在生产里悄悄改坏状态。

        刻意不支持 ``WITH``：SQLite 允许 ``WITH ... DELETE``，放行 CTE 就等于
        放行写操作。需要 CTE 的只读查询请改成子查询。
        """
        head = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
        if head != "SELECT":
            raise ValueError(
                f"query() 只接受 SELECT，收到 {head or '<空>'}：{sql.strip()[:60]!r}"
            )
        return Rows(self._conn.execute(sql, params).fetchall())

    @contextlib.contextmanager
    def write_tx(self) -> Iterator[sqlite3.Connection]:
        """公开的写事务：``BEGIN IMMEDIATE`` .. ``COMMIT``，异常回滚。

        与 :meth:`_write_tx` 是同一个实现，只是允许跨模块使用。拿到连接就可以
        写任意 SQL——这是 ``redispatch`` 做"豁免不递增 handoff"所必需的。
        """
        with self._write_tx() as conn:
            yield conn

    def record_event(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        kind: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        """在**调用方的事务里**写一条审计事件。

        必须传入 :meth:`write_tx` 产出的 ``conn``：事件与状态变更同事务才
        不会漂移（状态改了但事件丢了，或反之）。
        """
        self._record_event(conn, task_id, kind, payload or {})

    def close(self) -> None:
        self._conn.close()

    @contextlib.contextmanager
    def _write_tx(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` .. ``COMMIT``, rolling back on any exception."""
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        if conn.in_transaction:
            conn.execute("COMMIT")

    def _record_event(
        self, conn: sqlite3.Connection, task_id: str, kind: str, payload: dict[str, object]
    ) -> None:
        """Audit trail in ``events``. Same transaction, so it cannot drift."""
        conn.execute(
            "INSERT INTO events (task_id, kind, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                task_id,
                kind,
                json.dumps(payload, sort_keys=True, ensure_ascii=False),
                self._now(),
            ),
        )

    # -- enqueue -----------------------------------------------------------

    def enqueue(
        self,
        card: TaskCard,
        *,
        batch_id: str | None = None,
        deps: tuple[str, ...] = (),
    ) -> None:
        """Insert a ``QUEUED`` task. ``batch_id=None`` means "single task"."""
        validate_card(card)
        card_json = _card_to_json(card)
        deps_tuple = tuple(deps)
        now = self._now()
        isolation = (
            card.isolation.value if card.isolation is not None else Isolation.PROCESS.value
        )

        # bottom_level is the critical-path length used by the claim order (H3).
        # Deriving it here keeps the derived column honest; a dependency that is
        # not enqueued yet simply contributes 0.
        bottom_level = 0
        if deps_tuple:
            marks = ", ".join("?" for _ in deps_tuple)
            row = self._conn.execute(
                f"SELECT MAX(bottom_level) FROM tasks WHERE task_id IN ({marks})",
                deps_tuple,
            ).fetchone()
            bottom_level = int(row[0] or 0) + 1

        self._conn.execute(
            """
            INSERT INTO tasks (
                task_id, batch_id, parent_task_id, depth, role, pool, tier,
                is_key, priority, isolation, state, card_json, card_hash,
                output_path, depends_on, resources, attempts, handoff_count,
                bottom_level, idempotency_key, queueing_lock, lock,
                budget_seconds, budget_tokens, created_at, updated_at
            ) VALUES (
                :task_id, :batch_id, NULL, :depth, :role, :pool, :tier,
                :is_key, :priority, :isolation, :state, :card_json, :card_hash,
                :output_path, :depends_on, :resources, 0, 0,
                :bottom_level, :idempotency_key, NULL, :lock,
                :budget_seconds, :budget_tokens, :now, :now
            )
            """,
            {
                "task_id": card.task_id,
                "batch_id": card.task_id if batch_id is None else batch_id,
                "depth": card.depth,
                "role": card.role.value,
                "pool": card.pool,
                "tier": int(card.tier),
                "is_key": 1 if card.is_key else 0,
                "priority": card.priority,
                "isolation": isolation,
                "state": TaskState.QUEUED.value,
                "card_json": card_json,
                "card_hash": _card_hash(card_json),
                "output_path": card.output_path,
                "depends_on": json.dumps(deps_tuple) if deps_tuple else None,
                "resources": json.dumps(list(card.resources)) if card.resources else None,
                "bottom_level": bottom_level,
                "idempotency_key": card.idempotency_key,
                "lock": card.worktree,
                "budget_seconds": card.budget_seconds,
                "budget_tokens": card.budget_tokens,
                "now": now,
            },
        )

    # -- claim -------------------------------------------------------------

    def claim(
        self,
        pool: str,
        *,
        lease_seconds: int = 300,
        max_wait_seconds: float = 0.0,
    ) -> ClaimedTask | None:
        """Claim one ``QUEUED`` task from ``pool``, or ``None``.

        D2: the probe runs outside any transaction, so an empty queue costs one
        read and **zero** write transactions. ``max_wait_seconds=0`` returns
        immediately without sleeping.

        The wait loop uses ``time.monotonic()`` rather than the injected ``now``:
        ``now`` exists to make lease timestamps deterministic, and a frozen test
        clock would otherwise turn a bounded wait into an infinite one.
        """
        deadline = time.monotonic() + max_wait_seconds
        backoff_round = 0
        while True:
            if self._has_queued(pool):
                return self._claim_once(pool, lease_seconds)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            delay = min(0.05 * (2**backoff_round), 2.0) * random.uniform(0.5, 1.5)
            backoff_round += 1
            time.sleep(min(delay, remaining))

    def _has_queued(self, pool: str) -> bool:
        row = self._conn.execute(
            _PROBE_SQL, (TaskState.QUEUED.value, pool)
        ).fetchone()
        return row is not None

    def _claim_once(self, pool: str, lease_seconds: int) -> ClaimedTask | None:
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            # D2 step 3: re-read inside the transaction -- the probe may be stale.
            row = conn.execute(
                _PICK_SQL, (TaskState.QUEUED.value, pool)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            now = self._now()
            cursor = conn.execute(
                _CLAIM_UPDATE,
                {
                    "claimed": TaskState.CLAIMED.value,
                    "worker_id": self._worker_id,
                    "now": now,
                    "expires": now + lease_seconds,
                    "task_id": row["task_id"],
                    "queued": TaskState.QUEUED.value,
                },
            )
            if cursor.rowcount != 1:
                # Lost the race between the re-read and the UPDATE. Not an error.
                conn.execute("ROLLBACK")
                return None
            fresh = conn.execute(
                "SELECT lease_epoch, attempts FROM tasks WHERE task_id = ?",
                (row["task_id"],),
            ).fetchone()
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        return ClaimedTask(
            task_id=row["task_id"],
            lease_epoch=int(fresh["lease_epoch"]),
            attempts=int(fresh["attempts"]),
            worker_id=self._worker_id,
            card=_card_from_json(row["card_json"]),
        )

    # -- lease -------------------------------------------------------------

    def heartbeat(self, task_id: str, epoch: int, *, lease_seconds: int = 300) -> None:
        """Extend the lease. D5: the epoch is the only guard."""
        now = self._now()
        cursor = self._conn.execute(
            "UPDATE tasks SET lease_expires = ?, updated_at = ? "
            "WHERE task_id = ? AND lease_epoch = ?",
            (now + lease_seconds, now, task_id, epoch),
        )
        if cursor.rowcount != 1:
            raise FencedOutError(
                f"heartbeat 被 fence：task_id={task_id} lease_epoch={epoch}"
            )

    # -- execution lifecycle ----------------------------------------------

    def _load_for_write(
        self, conn: sqlite3.Connection, task_id: str, epoch: int
    ) -> sqlite3.Row:
        """Read the row *inside* the write transaction and check the epoch.

        The check is not a substitute for the ``AND lease_epoch = ?`` predicate
        on the following UPDATE (D5) -- it runs under ``BEGIN IMMEDIATE``, where
        no other writer can slip in, and it is what makes a stale worker get
        :class:`FencedOutError` instead of a misleading "wrong state" error.
        """
        row = conn.execute(
            "SELECT state, lease_epoch, attempts, handoff_count, card_json "
            "FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"任务不存在：{task_id}")
        if int(row["lease_epoch"]) != int(epoch):
            raise FencedOutError(
                f"写回被 fence：task_id={task_id} "
                f"lease_epoch={epoch} 实际 {int(row['lease_epoch'])}"
            )
        return row

    def start(self, task_id: str, epoch: int) -> None:
        """``CLAIMED -> RUNNING`` (D6: via ``transition``)."""
        with self._write_tx() as conn:
            row = self._load_for_write(conn, task_id, epoch)
            current = TaskState(row["state"])
            if current is not TaskState.CLAIMED:
                raise NotClaimableError(
                    f"start 需要 CLAIMED，task_id={task_id} 实际 {current}"
                )
            card = _card_from_json(row["card_json"])
            transition(
                current,
                TaskState.RUNNING,
                max_retries=card.max_retries,
                attempts=int(row["attempts"]),
                handoff_count=int(row["handoff_count"]),
                handoff_cap=card.max_handoffs,
            )
            now = self._now()
            cursor = conn.execute(
                "UPDATE tasks SET state = ?, started_at = ?, updated_at = ? "
                "WHERE task_id = ? AND lease_epoch = ?",
                (TaskState.RUNNING.value, now, now, task_id, epoch),
            )
            if cursor.rowcount != 1:
                raise FencedOutError(
                    f"start 被 fence：task_id={task_id} lease_epoch={epoch}"
                )

    def complete(
        self,
        task_id: str,
        epoch: int,
        *,
        output_path: str,
        result_json: str | None = None,
    ) -> None:
        """``RUNNING -> SUCCEEDED``. ``output_path`` goes to the audit event."""
        with self._write_tx() as conn:
            row = self._load_for_write(conn, task_id, epoch)
            current = TaskState(row["state"])
            if current is not TaskState.RUNNING:
                raise NotClaimableError(
                    f"complete 需要 RUNNING，task_id={task_id} 实际 {current}"
                )
            card = _card_from_json(row["card_json"])
            transition(
                current,
                TaskState.SUCCEEDED,
                max_retries=card.max_retries,
                attempts=int(row["attempts"]),
                handoff_count=int(row["handoff_count"]),
                handoff_cap=card.max_handoffs,
            )
            now = self._now()
            cursor = conn.execute(
                "UPDATE tasks SET state = ?, completed_at = ?, result_json = ?, "
                "updated_at = ?, claimed_by = NULL, lease_expires = NULL "
                "WHERE task_id = ? AND lease_epoch = ?",
                (
                    TaskState.SUCCEEDED.value,
                    now,
                    result_json,
                    now,
                    task_id,
                    epoch,
                ),
            )
            if cursor.rowcount != 1:
                raise FencedOutError(
                    f"complete 被 fence：task_id={task_id} lease_epoch={epoch}"
                )
            self._record_event(
                conn,
                task_id,
                "task_succeeded",
                {"output_path": output_path, "result_json": result_json},
            )

    def fail(self, task_id: str, epoch: int, *, reason: str) -> None:
        """``RUNNING -> FAILED``, then ``FAILED -> QUEUED`` if retries remain (D9).

        Both edges are separate ``transition()`` calls: jumping straight to
        ``QUEUED`` would skip the retry guard and turn ``fail`` into an infinite
        loop.
        """
        with self._write_tx() as conn:
            row = self._load_for_write(conn, task_id, epoch)
            current = TaskState(row["state"])
            if current is not TaskState.RUNNING:
                raise NotClaimableError(
                    f"fail 需要 RUNNING，task_id={task_id} 实际 {current}"
                )
            card = _card_from_json(row["card_json"])
            attempts = int(row["attempts"])
            handoff_count = int(row["handoff_count"])
            guards = {
                "max_retries": card.max_retries,
                "attempts": attempts,
                "handoff_count": handoff_count,
                "handoff_cap": card.max_handoffs,
            }
            transition(current, TaskState.FAILED, **guards)
            now = self._now()
            cursor = conn.execute(
                "UPDATE tasks SET state = ?, completed_at = ?, updated_at = ? "
                "WHERE task_id = ? AND lease_epoch = ?",
                (TaskState.FAILED.value, now, now, task_id, epoch),
            )
            if cursor.rowcount != 1:
                raise FencedOutError(
                    f"fail 被 fence：task_id={task_id} lease_epoch={epoch}"
                )
            self._record_event(
                conn,
                task_id,
                "task_failed",
                {"reason": reason, "attempts": attempts},
            )

            if attempts <= card.max_retries:
                transition(TaskState.FAILED, TaskState.QUEUED, **guards)
                cursor = conn.execute(
                    "UPDATE tasks SET state = ?, claimed_by = NULL, "
                    "lease_expires = NULL, completed_at = NULL, updated_at = ? "
                    "WHERE task_id = ? AND lease_epoch = ?",
                    (TaskState.QUEUED.value, now, task_id, epoch),
                )
                if cursor.rowcount != 1:
                    raise FencedOutError(
                        f"fail/requeue 被 fence：task_id={task_id} lease_epoch={epoch}"
                    )

    def cancel(self, task_id: str, epoch: int, *, reason: str = "cancelled") -> None:
        """``RUNNING -> CANCELLED``, with fencing (W4).

        Both ``CLAIMED`` and ``RUNNING`` may be cancelled. The ``CLAIMED`` case
        used to be impossible (the edge was missing from ``_ALLOWED``); phase 4
        added it, so a stop that lands between ``claim()`` and ``start()`` is now
        honoured instead of raising.

        Idempotency is the caller's job: a second ``cancel`` on an already
        ``CANCELLED`` task raises :class:`NotClaimableError` instead of
        pretending to have done something.
        """
        with self._write_tx() as conn:
            row = self._load_for_write(conn, task_id, epoch)
            current = TaskState(row["state"])
            if current not in (TaskState.CLAIMED, TaskState.RUNNING):
                raise NotClaimableError(
                    f"cancel 需要 CLAIMED 或 RUNNING，task_id={task_id} 实际 {current}"
                )
            card = _card_from_json(row["card_json"])
            transition(
                current,
                TaskState.CANCELLED,
                max_retries=card.max_retries,
                attempts=int(row["attempts"]),
                handoff_count=int(row["handoff_count"]),
                handoff_cap=card.max_handoffs,
            )
            now = self._now()
            cursor = conn.execute(
                # 终态不持有租约：不清 claimed_by 的话，idx_tasks_holder 会把
                # 已取消的任务算成"某 worker 手上还在跑"，而 workers.current_task_id
                # 才是持有关系的权威来源。lease_expires 同理——留着就是一条
                # 指向过去的租约，任何按 lease 扫描的查询都会把它当活任务。
                "UPDATE tasks SET state = ?, completed_at = ?, updated_at = ?, "
                "claimed_by = NULL, lease_expires = NULL "
                "WHERE task_id = ? AND lease_epoch = ?",
                (TaskState.CANCELLED.value, now, now, task_id, epoch),
            )
            if cursor.rowcount != 1:
                raise FencedOutError(
                    f"cancel 被 fence：task_id={task_id} lease_epoch={epoch}"
                )
            self._record_event(conn, task_id, "task_cancelled", {"reason": reason})

    # -- patrol / redispatch ----------------------------------------------

    def patrol(self, *, limit: int = 100) -> int:
        """Reclaim tasks whose lease expired; returns how many were blocked (D7).

        The scan is read-only and unlocked; each candidate is re-checked inside
        its own ``BEGIN IMMEDIATE`` so a heartbeat that landed in between wins.
        """
        now = self._now()
        rows = self._conn.execute(
            "SELECT task_id, state, lease_epoch, lease_expires, attempts, "
            "handoff_count, card_json FROM tasks "
            "WHERE state IN (?, ?) AND lease_expires IS NOT NULL "
            "AND lease_expires < ? ORDER BY lease_expires ASC LIMIT ?",
            (
                TaskState.CLAIMED.value,
                TaskState.RUNNING.value,
                now,
                int(limit),
            ),
        ).fetchall()
        return sum(1 for row in rows if self._block_expired(row["task_id"], now))

    def _block_expired(self, task_id: str, scan_time: float) -> bool:
        """Land one expired task in ``BLOCKED``. ``True`` if this call did it."""
        with self._write_tx() as conn:
            row = conn.execute(
                "SELECT state, lease_epoch, lease_expires, attempts, "
                "handoff_count, card_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            current = TaskState(row["state"])
            if current not in (TaskState.CLAIMED, TaskState.RUNNING):
                return False
            expires = row["lease_expires"]
            if expires is None or expires >= scan_time:
                # A heartbeat renewed the lease after the scan. Not our task.
                return False

            card = _card_from_json(row["card_json"])
            guards = {
                "max_retries": card.max_retries,
                "lease_expired": True,
                "attempts": int(row["attempts"]),
                "handoff_count": int(row["handoff_count"]),
                "handoff_cap": card.max_handoffs,
            }
            now = self._now()

            # CLAIMED 与 RUNNING 都落 BLOCKED（阶段 4 补边后统一）。
            #
            # 之前 CLAIMED 走的是 FAILED -> QUEUED 的绕路：那时表里没有
            # CLAIMED -> BLOCKED，只能借"这次尝试作废"来表达。绕路的代价是
            # 一个从未真正执行过的任务白白消耗一次重试预算（attempts 在 claim
            # 时已 +1），而且 handoff 预算完全没被计入——同一个"领取后立刻死"
            # 的事件，在两条路径上记到了两个不同的账本里。
            #
            # 补边后语义统一：租约过期且无人持有 = 故障，落 BLOCKED，由
            # redispatch 决定是否转手（并消耗 handoff 预算）。
            transition(current, TaskState.BLOCKED, **guards)
            cursor = conn.execute(
                "UPDATE tasks SET state = ?, block_reason = 'lease_expired', "
                "claimed_by = NULL, lease_expires = NULL, updated_at = ? "
                "WHERE task_id = ? AND lease_epoch = ? AND lease_expires < ?",
                (
                    TaskState.BLOCKED.value,
                    now,
                    task_id,
                    int(row["lease_epoch"]),
                    scan_time,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._record_event(
                conn, task_id, "lease_expired", {"state": current.value}
            )
            return True

    def redispatch(self, task_id: str, *, handoff_cap: int | None = None) -> None:
        """``BLOCKED -> QUEUED`` with ``handoff_count + 1`` in the same UPDATE (D8).

        ``handoff_cap=None`` means "use ``card.max_handoffs``". Exhausting the
        cap raises :class:`IllegalTransitionError` from ``transition``.
        """
        with self._write_tx() as conn:
            row = conn.execute(
                "SELECT state, handoff_count, attempts, card_json FROM tasks "
                "WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise StoreError(f"任务不存在：{task_id}")
            current = TaskState(row["state"])
            if current is not TaskState.BLOCKED:
                raise NotClaimableError(
                    f"redispatch 需要 BLOCKED，task_id={task_id} 实际 {current}"
                )
            card = _card_from_json(row["card_json"])
            cap = card.max_handoffs if handoff_cap is None else int(handoff_cap)
            transition(
                current,
                TaskState.QUEUED,
                max_retries=card.max_retries,
                attempts=int(row["attempts"]),
                handoff_count=int(row["handoff_count"]),
                handoff_cap=cap,
            )
            now = self._now()
            cursor = conn.execute(
                "UPDATE tasks SET state = ?, handoff_count = handoff_count + 1, "
                "claimed_by = NULL, lease_expires = NULL, block_reason = NULL, "
                "updated_at = ? WHERE task_id = ? AND state = ?",
                (TaskState.QUEUED.value, now, task_id, TaskState.BLOCKED.value),
            )
            if cursor.rowcount != 1:
                raise NotClaimableError(
                    f"redispatch 被并发抢先：task_id={task_id} 已不在 BLOCKED"
                )
