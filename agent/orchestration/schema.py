"""Orchestration queue schema (SQLite).

This is the *reviewed* schema, not the one in the original plan. The deltas are
deliberate and each one closes a hole that would otherwise surface at the phase-3
cutover (see ``docs/design/orchestration-plan-review-2026-10-31.md``):

* ``lease_epoch`` -- B1 fencing token. A lease with an expiry but no token lets a
  paused worker wake up and overwrite the result of the worker that replaced it.
  Every write-back must carry the epoch.
* ``deliveries`` as its own table -- B2. Execution state and delivery state have
  different lifecycles; merging them destroys the at-least-once delivery
  guarantee that already works today.
* ``task_commands`` -- B3. Once children run in another process there is no live
  object to steer/stop; commands go through the DB and workers poll them.
* ``cancel_requested_at`` -- H5. "Cancel requested but not yet effective" is a
  real state; record it and bound it with a grace period instead of lying.
* ``idempotency_key`` / ``queueing_lock`` / ``lock`` -- M10 (as revised by the
  implementation plan: queue-time dedupe and run-time mutex are two keys).
* ``bottom_level`` + aging in the claim index -- H3. ``tier`` is not a valid
  DAG ordering key; critical-path length is.
* ``cursor_json`` -- river-style resumable jobs; a redispatch resumes instead of
  redoing the whole task.
* ``trace_id`` / ``span_id`` -- M15, keeps parent trace linked across processes.
* partial unique index on ``output_path`` -- H7. A global unique constraint
  rejects redispatch of the same task; "one writer per file *at a time*" is the
  property actually wanted.
* ``schema_version`` -- M9, so phase 2..7 can migrate forward instead of
  silently failing.
* ``depth`` and a non-empty ``batch_id`` -- phase-1.5 S1/S2. Depth is stored
  because a handoff rewrites ``parent_task_id``, so chain length is not the
  logical depth; ``batch_id`` is required and non-empty because an empty
  string would make every single-task job share one batch.

Journal mode is intentionally *not* touched here -- see ``configure_connection``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
import time

__all__ = [
    "ACTIVE_STATES",
    "DDL",
    "INDEXES",
    "SCHEMA_SQLITE_MIN",
    "SCHEMA_VERSION",
    "SchemaError",
    "TABLES",
    "TASK_STATES",
    "TERMINAL_STATES",
    "apply_schema",
    "configure_connection",
    "current_version",
]

#: Bumped whenever :data:`DDL` changes in a way that needs a migration step.
SCHEMA_VERSION = 1

#: Minimum SQLite version. 3.35 brings ``RETURNING``, which phase 2's CAS claim
#: uses to get the claimed row (and its new ``lease_epoch``) in one statement.
SCHEMA_SQLITE_MIN = "3.35"

#: State names come from ``contracts`` -- the single source of truth.
#:
#: There is deliberately NO fallback literal here. A silent fallback would let
#: :func:`apply_schema` build a database whose CHECK constraint disagrees with
#: the real enum, write ``schema_version=1``, and report success -- the exact
#: "several sources of truth" failure this refactor exists to remove. An
#: ImportError must propagate instead of being papered over.


class SchemaError(RuntimeError):
    """Raised when the database cannot be brought to the current schema."""


def _names(states: object) -> tuple[str, ...]:
    return tuple(
        str(getattr(state, "value", state)) for state in states  # type: ignore[union-attr]
    )


def _load_contract_states() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(task_states, terminal_states)`` from contracts.

    ``contracts.TaskState`` / ``contracts.TERMINAL_STATES`` are the single
    source of truth. No fallback is provided: an ImportError propagates so the
    caller fails loudly instead of building a schema from a stale duplicate.
    """
    from agent.orchestration.contracts import TERMINAL_STATES as contract_terminal
    from agent.orchestration.contracts import TaskState

    states = _names(TaskState)
    terminal = set(_names(contract_terminal))
    # contracts exports a frozenset; order it by TASK_STATES so the emitted
    # DDL text is byte-identical across processes (no hash randomisation).
    return states, tuple(state for state in states if state in terminal)


TASK_STATES, TERMINAL_STATES = _load_contract_states()

#: States in which a task still owns its ``output_path`` (H7).
ACTIVE_STATES: tuple[str, ...] = tuple(s for s in TASK_STATES if s not in TERMINAL_STATES)


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _build_ddl() -> tuple[str, ...]:
    states = _sql_list(TASK_STATES)
    terminal = _sql_list(TERMINAL_STATES)

    return (
        # ---------------------------------------------------------------- tasks
        # Execution state only. Delivery lives in `deliveries` (review B2).
        f"""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id             TEXT PRIMARY KEY,
            -- S2: a single-task job uses its own task_id as batch_id. '' is not a
            -- batch: it would make every single-task job share one batch and a
            -- single `list` call would return all of them.
            batch_id            TEXT NOT NULL CHECK (batch_id <> ''),
            parent_task_id      TEXT,
            -- S1: logical DAG depth. Not derivable from the parent chain -- a
            -- handoff rewrites parent_task_id, so chain length != logical depth.
            depth               INTEGER NOT NULL DEFAULT 0,
            -- S6: defaults so store's insert path has fewer mandatory columns.
            role                TEXT NOT NULL DEFAULT 'leaf',
            pool                TEXT NOT NULL DEFAULT 'solve',
            -- tier is only the seed for priority; it is NOT an ordering key (H3)
            tier                INTEGER NOT NULL DEFAULT 2,
            is_key              INTEGER NOT NULL DEFAULT 0,
            priority            INTEGER NOT NULL DEFAULT 0,
            isolation           TEXT NOT NULL DEFAULT 'process',
            state               TEXT NOT NULL DEFAULT 'QUEUED'
                                CHECK (state IN ({states})),
            -- card_json is the immutable enqueue-time snapshot (audit/replay);
            -- the derived columns above are the only truth for querying (H8)
            card_json           TEXT NOT NULL,
            card_hash           TEXT,
            -- S3: the contract layer requires an absolute path; the DDL must
            -- agree or the partial unique index silently ignores NULLs.
            output_path         TEXT NOT NULL,
            depends_on          TEXT,
            resources           TEXT,
            attempts            INTEGER NOT NULL DEFAULT 0,
            handoff_count       INTEGER NOT NULL DEFAULT 0,
            route_fingerprint   TEXT,
            budget_seconds      REAL,
            budget_tokens       INTEGER,
            -- lease + fencing token (B1)
            claimed_by          TEXT,
            lease_expires       REAL,
            lease_epoch         INTEGER NOT NULL DEFAULT 0,
            claimed_at          REAL,
            cancel_requested_at REAL,
            idempotency_key     TEXT,
            queueing_lock       TEXT,
            lock                TEXT,
            trace_id            TEXT,
            span_id             TEXT,
            bottom_level        INTEGER NOT NULL DEFAULT 0,
            cursor_json         TEXT,
            created_at          REAL NOT NULL,
            updated_at          REAL NOT NULL,
            started_at          REAL,
            completed_at        REAL,
            result_json         TEXT,
            block_reason        TEXT
        )
        """,
        # Claim scan: key tasks first, then aged priority, then critical path.
        # `created_at` last keeps the order total (stable).
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_claim
            ON tasks(pool, state, is_key DESC, priority DESC, bottom_level DESC, created_at)
        """,
        "CREATE INDEX IF NOT EXISTS idx_tasks_holder ON tasks(claimed_by, state)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks(state, lease_expires)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_batch ON tasks(batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_output ON tasks(output_path)",
        # H7: "one task may write this file *at a time*". A global unique index
        # would reject redispatch/retry of a finished task.
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_output_active
            ON tasks(output_path)
         WHERE state NOT IN ({terminal})
        """,
        # M10: caller retries after a timeout must not create duplicates.
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idem
            ON tasks(idempotency_key)
         WHERE idempotency_key IS NOT NULL
        """,
        # M10 revised: queue-time dedupe (procrastinate's queueing_lock).
        # S4: scoped to non-terminal states. Without the state predicate the
        # "run-time mutex" degrades into "each lock value is usable exactly once
        # for the lifetime of the database".
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_queueing_lock
            ON tasks(queueing_lock)
         WHERE queueing_lock IS NOT NULL AND state NOT IN ({terminal})
        """,
        # M10 revised: run-time mutex (procrastinate's lock), e.g. one worktree.
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_lock
            ON tasks(lock)
         WHERE lock IS NOT NULL AND state NOT IN ({terminal})
        """,
        # ----------------------------------------------------------- deliveries
        # B2: at-least-once delivery, independent of execution state. Replaces
        # the delivery_* half of the legacy async_delegations table.
        """
        CREATE TABLE IF NOT EXISTS deliveries (
            delivery_id       TEXT PRIMARY KEY,
            task_id           TEXT NOT NULL,
            origin_session    TEXT NOT NULL,
            origin_session_id TEXT NOT NULL DEFAULT '',
            state             TEXT NOT NULL DEFAULT 'pending'
                              CHECK (state IN ('pending', 'claimed', 'delivered', 'dead')),
            attempts          INTEGER NOT NULL DEFAULT 0,
            claim             TEXT,
            claimed_at        REAL,
            delivered_at      REAL,
            payload_json      TEXT,
            created_at        REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_deliveries_pending ON deliveries(state, claimed_at)",
        # One task, one delivery.
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_deliveries_task ON deliveries(task_id)",
        # -------------------------------------------------------- task_commands
        # B3: the only cross-process control channel. SQLite has no
        # LISTEN/NOTIFY, so workers poll this during heartbeat.
        """
        CREATE TABLE IF NOT EXISTS task_commands (
            cmd_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT NOT NULL,
            lease_epoch INTEGER NOT NULL,
            kind        TEXT NOT NULL
                        CHECK (kind IN ('steer', 'stop', 'budget_update')),
            payload     TEXT,
            created_at  REAL NOT NULL,
            acked_at    REAL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_cmd_pending ON task_commands(task_id, acked_at)",
        # -------------------------------------------------------------- workers
        """
        CREATE TABLE IF NOT EXISTS workers (
            worker_id       TEXT PRIMARY KEY,
            pool            TEXT NOT NULL,
            pid             INTEGER,
            host            TEXT,
            state           TEXT NOT NULL DEFAULT 'idle'
                            CHECK (state IN ('idle', 'busy', 'draining', 'dead')),
            capability      TEXT,
            current_task_id TEXT,
            started_at      REAL NOT NULL,
            last_heartbeat  REAL NOT NULL
        )
        """,
        # Liveness is judged per worker (procrastinate), not per task.
        "CREATE INDEX IF NOT EXISTS idx_workers_heartbeat ON workers(state, last_heartbeat)",
        # --------------------------------------------------------------- events
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id    TEXT,
            kind       TEXT NOT NULL,
            payload    TEXT,
            created_at REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, created_at)",
        # M8: kind index doubles as the retention/scan path for the sweeper.
        "CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, created_at)",
        # --------------------------------------------------------- dispatch_log
        """
        CREATE TABLE IF NOT EXISTS dispatch_log (
            dispatch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT NOT NULL,
            worker_id   TEXT,
            action      TEXT NOT NULL,
            detail      TEXT,
            created_at  REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_dispatch_task ON dispatch_log(task_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_dispatch_worker ON dispatch_log(worker_id, created_at)",
        # -------------------------------------------------------- schema_version
        # M9: without this, upgrades between phases fail silently.
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            -- S5: PK, otherwise concurrent initialisation writes several rows.
            version    INTEGER NOT NULL PRIMARY KEY,
            applied_at REAL NOT NULL
        )
        """,
    )


#: Ordered DDL statements. ``apply_schema`` executes these inside one transaction.
DDL: tuple[str, ...] = _build_ddl()

#: Table names created by :data:`DDL` (introspection/tests).
TABLES: tuple[str, ...] = (
    "tasks",
    "deliveries",
    "task_commands",
    "workers",
    "events",
    "dispatch_log",
    "schema_version",
)

#: Index names created by :data:`DDL` (introspection/tests).
INDEXES: tuple[str, ...] = (
    "idx_tasks_claim",
    "idx_tasks_holder",
    "idx_tasks_lease",
    "idx_tasks_batch",
    "idx_tasks_parent",
    "idx_tasks_output",
    "idx_tasks_output_active",
    "idx_tasks_idem",
    "idx_tasks_queueing_lock",
    "idx_tasks_lock",
    "idx_deliveries_pending",
    "idx_deliveries_task",
    "idx_cmd_pending",
    "idx_workers_heartbeat",
    "idx_events_task",
    "idx_events_kind",
    "idx_dispatch_task",
    "idx_dispatch_worker",
)


def _require_sqlite_version() -> None:
    have = sqlite3.sqlite_version_info
    want = tuple(int(part) for part in SCHEMA_SQLITE_MIN.split("."))
    if have < want:
        raise SchemaError(
            f"orchestration schema needs SQLite >= {SCHEMA_SQLITE_MIN}, "
            f"runtime has {sqlite3.sqlite_version}"
        )


def current_version(conn: sqlite3.Connection) -> int | None:
    """Return the applied schema version, or ``None`` if the DB is uninitialised."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None or row[0] is None else int(row[0])


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create tables, indexes and the version row. Safe to call repeatedly.

    Only DDL runs here. Journal mode is *not* set: see
    :func:`configure_connection`.
    """
    _require_sqlite_version()

    applied = current_version(conn)
    if applied is not None and applied > SCHEMA_VERSION:
        raise SchemaError(
            f"database schema v{applied} is newer than this code (v{SCHEMA_VERSION}); "
            "upgrade the code, do not downgrade the database"
        )

    with conn:  # one transaction: either the whole schema lands or nothing does
        for statement in DDL:
            conn.execute(statement)
        if applied is None:
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, time.time()),
            )


#: Migration steps, keyed by the version they upgrade **to**.
#:
#: Each callable receives an open connection and must only issue DDL/DML that
#: brings the schema from ``N-1`` to ``N``. Steps run inside a ``SAVEPOINT`` so a
#: failing step leaves the database exactly as it was — a half-migrated schema is
#: worse than an old one.
#:
#: Empty today (only v1 exists). The registry is the extension point for every
#: later phase: register ``MIGRATIONS[2] = ...`` and bump :data:`SCHEMA_VERSION`.
MIGRATIONS: dict[int, "Callable[[sqlite3.Connection], None]"] = {}


def migrate(conn: sqlite3.Connection, *, target: int | None = None) -> int:
    """Bring ``conn`` up to ``target`` (default :data:`SCHEMA_VERSION`).

    Returns the version the database ends up at.

    Raises:
        SchemaError: the database is newer than the code, a step is missing, or a
            step failed (in which case its changes are rolled back).
    """
    _require_sqlite_version()
    goal = SCHEMA_VERSION if target is None else target

    applied = current_version(conn)
    if applied is None:
        apply_schema(conn)
        applied = current_version(conn)
        if applied is None:
            raise SchemaError("apply_schema() 没有写入 schema_version 行")

    if applied > goal:
        raise SchemaError(
            f"数据库 schema v{applied} 比目标 v{goal} 新；升级代码，不要降级数据库"
        )

    while applied < goal:
        nxt = applied + 1
        step = MIGRATIONS.get(nxt)
        if step is None:
            raise SchemaError(
                f"缺少 v{applied} -> v{nxt} 的迁移步骤；"
                f"MIGRATIONS 里没有注册 {nxt}，拒绝把库停在半升级状态"
            )
        # SAVEPOINT works both in autocommit (store) and inside an implicit
        # transaction (plain sqlite3.connect default), and gives us rollback
        # without guessing the caller's isolation level.
        conn.execute(f"SAVEPOINT migrate_v{nxt}")
        try:
            step(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (nxt, time.time()),
            )
            conn.execute(f"RELEASE migrate_v{nxt}")
        except BaseException:
            conn.execute(f"ROLLBACK TO migrate_v{nxt}")
            conn.execute(f"RELEASE migrate_v{nxt}")
            raise
        applied = nxt

    return applied


def configure_connection(conn: sqlite3.Connection, *, busy_timeout_ms: int = 5000) -> None:
    """Apply per-connection pragmas. Does **not** touch ``journal_mode``.

    Journal mode is owned by whoever owns the database file, not by a guest
    connection: ``state.db`` establishes its mode in ``SessionDB`` and
    ``fulilian_state.apply_durability_barriers()`` is documented as "without
    changing journal mode". Issuing ``PRAGMA journal_mode = WAL`` from here would
    take an exclusive lock on every short-lived connection under a DELETE-mode
    deployment and collide with live transcript/FTS writers.

    The orchestration queue has its own file (``orchestration.db``, review §1.3)
    precisely so its owner can set WAL once, deliberately, outside this helper.
    """
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
