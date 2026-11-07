"""Tests for ``agent.orchestration.schema``.

These assert the *reviewed* schema behaviour, not just that DDL parses: the state
CHECK must reject bad writes, the partial unique index must allow redispatch of a
finished task while blocking two active writers of the same file, and
``apply_schema`` must be idempotent.
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.orchestration import schema as schema_mod
from agent.orchestration.schema import (
    DDL,
    INDEXES,
    SCHEMA_SQLITE_MIN,
    SCHEMA_VERSION,
    TABLES,
    SchemaError,
    apply_schema,
    configure_connection,
    current_version,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    apply_schema(connection)
    yield connection
    connection.close()


def _insert_task(
    connection: sqlite3.Connection,
    task_id: str,
    *,
    state: str = "QUEUED",
    output_path: str | None = "out/a.md",
    idempotency_key: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO tasks (
            task_id, batch_id, role, pool, state, card_json,
            output_path, idempotency_key, created_at, updated_at
        ) VALUES (?, 'b1', 'leaf', 'solve', ?, '{}', ?, ?, 1.0, 1.0)
        """,
        (task_id, state, output_path, idempotency_key),
    )


# ------------------------------------------------------------------- layout


def test_all_tables_exist(conn: sqlite3.Connection) -> None:
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert set(TABLES) <= names, f"missing tables: {set(TABLES) - names}"


def test_all_indexes_exist(conn: sqlite3.Connection) -> None:
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    }
    assert set(INDEXES) <= names, f"missing indexes: {set(INDEXES) - names}"


def test_claim_index_uses_reviewed_order(conn: sqlite3.Connection) -> None:
    # H3: priority + bottom_level, tier must not be an ordering key.
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_tasks_claim'"
    ).fetchone()[0]
    assert "is_key DESC" in sql
    assert "priority DESC" in sql
    assert "bottom_level DESC" in sql
    assert "tier" not in sql


def test_fencing_and_control_columns_present(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    required = {
        # B1
        "lease_epoch",
        "claimed_at",
        # H5
        "cancel_requested_at",
        # M10
        "idempotency_key",
        "queueing_lock",
        "lock",
        # H3 / M15 / river
        "bottom_level",
        "trace_id",
        "span_id",
        "cursor_json",
        # H8
        "card_hash",
    }
    assert required <= cols, f"missing columns: {required - cols}"


# ----------------------------------------------------------- schema_version


def test_schema_version_recorded(conn: sqlite3.Connection) -> None:
    assert current_version(conn) == SCHEMA_VERSION
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    assert rows == [(SCHEMA_VERSION,)]


def test_apply_schema_is_idempotent(conn: sqlite3.Connection) -> None:
    apply_schema(conn)
    apply_schema(conn)
    assert current_version(conn) == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_current_version_none_on_uninitialised_db() -> None:
    raw = sqlite3.connect(":memory:")
    try:
        assert current_version(raw) is None
    finally:
        raw.close()


def test_apply_schema_refuses_newer_database(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 2.0)")
    with pytest.raises(SchemaError, match="newer"):
        apply_schema(conn)


def test_sqlite_min_version_constant_is_parseable() -> None:
    parts = tuple(int(p) for p in SCHEMA_SQLITE_MIN.split("."))
    assert parts == (3, 35)
    assert sqlite3.sqlite_version_info >= parts


# ------------------------------------------------------------ state CHECK


def test_state_check_rejects_unknown_state(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_task(conn, "bad", state="NOT_A_STATE")


def test_state_check_accepts_every_known_state(conn: sqlite3.Connection) -> None:
    for index, state in enumerate(schema_mod.TASK_STATES):
        _insert_task(conn, f"ok-{index}", state=state, output_path=f"out/{index}.md")
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == len(
        schema_mod.TASK_STATES
    )


def test_state_check_covers_contracts_enum() -> None:
    """schema 的 CHECK 必须覆盖 contracts 的枚举，且不允许降级到副本。

    contracts 不可导入时必须**失败**而不是 skip——静默回退会让 apply_schema()
    用副本建库并写 schema_version，CHECK 与真实枚举不一致且无迹可循。
    """
    from agent.orchestration.contracts import TaskState

    values = {str(getattr(state, "value", state)) for state in TaskState}
    assert values <= set(schema_mod.TASK_STATES)


def test_schema_has_no_fallback_state_literals() -> None:
    """防止后人把 fallback 常量加回来（本轮监督审计 B-1）。"""
    assert not hasattr(schema_mod, "_FALLBACK_TASK_STATES"), (
        "schema.py 又出现了重复的状态字面量；状态名必须只来自 contracts"
    )
    assert not hasattr(schema_mod, "_FALLBACK_TERMINAL_STATES"), (
        "schema.py 又出现了重复的终态字面量；终态必须只来自 contracts"
    )


def test_terminal_states_are_a_subset_and_deterministically_ordered() -> None:
    # contracts exports TERMINAL_STATES as a frozenset; schema must re-order it
    # by TASK_STATES or the emitted DDL text would vary with hash randomisation.
    assert set(schema_mod.TERMINAL_STATES) <= set(schema_mod.TASK_STATES)
    order = [schema_mod.TASK_STATES.index(state) for state in schema_mod.TERMINAL_STATES]
    assert order == sorted(order)


# -------------------------------------------------- partial unique indexes


def test_active_duplicate_output_path_conflicts(conn: sqlite3.Connection) -> None:
    _insert_task(conn, "t1", state="RUNNING", output_path="out/report.md")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_task(conn, "t2", state="QUEUED", output_path="out/report.md")


def test_terminal_state_frees_output_path(conn: sqlite3.Connection) -> None:
    # H7: redispatch/retry of a finished task must not be blocked.
    _insert_task(conn, "t1", state="SUCCEEDED", output_path="out/report.md")
    _insert_task(conn, "t2", state="QUEUED", output_path="out/report.md")
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"])
def test_each_terminal_state_frees_output_path(conn: sqlite3.Connection, terminal: str) -> None:
    _insert_task(conn, "t1", state=terminal, output_path="out/x.md")
    _insert_task(conn, "t2", state="QUEUED", output_path="out/x.md")


def test_idempotency_key_is_unique(conn: sqlite3.Connection) -> None:
    _insert_task(conn, "t1", idempotency_key="k-1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_task(conn, "t2", idempotency_key="k-1")


def test_null_idempotency_key_allows_many(conn: sqlite3.Connection) -> None:
    _insert_task(conn, "t1", output_path="out/t1.md", idempotency_key=None)
    _insert_task(conn, "t2", output_path="out/t2.md", idempotency_key=None)


# ---------------------------------------------- phase-1.5 S1-S6 (frozen)


def test_depth_column_exists_and_defaults_to_zero(conn: sqlite3.Connection) -> None:
    """S1: depth 必须是 NOT NULL DEFAULT 0，且插入不写时取 0。"""
    info = {row[1]: row for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert "depth" in info, "S1: depth 列缺失"
    _name, decl_type, notnull, default, _pk = info["depth"][1:6]
    assert "INT" in decl_type.upper(), decl_type
    assert notnull == 1, "S1: depth 必须 NOT NULL"
    assert str(default) == "0", f"S1: depth 默认值应为 0，实际 {default!r}"

    _insert_task(conn, "t-depth")
    assert conn.execute("SELECT depth FROM tasks WHERE task_id = 't-depth'").fetchone()[0] == 0


def test_batch_id_rejects_empty_string(conn: sqlite3.Connection) -> None:
    """S2: 空 batch_id 会让所有单任务共享同一批次，`list` 一次全捞。"""
    insert = """
        INSERT INTO tasks (task_id, batch_id, role, pool, state, card_json,
                           output_path, created_at, updated_at)
        VALUES (?, ?, 'leaf', 'solve', 'QUEUED', '{}', ?, 1.0, 1.0)
    """
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("t-empty-batch", "", "out/empty-batch.md"))

    # 单任务以 task_id 作 batch_id —— 合法且不冲突。
    conn.execute(insert, ("t-solo", "t-solo", "out/solo.md"))
    assert conn.execute("SELECT batch_id FROM tasks WHERE task_id = 't-solo'").fetchone()[0] == (
        "t-solo"
    )


def test_output_path_is_not_null(conn: sqlite3.Connection) -> None:
    """S3: NOT NULL 之后 NULL 无法再绕过活跃态唯一索引。"""
    insert = """
        INSERT INTO tasks (task_id, batch_id, role, pool, card_json,
                           output_path, created_at, updated_at)
        VALUES (?, 'b1', 'leaf', 'solve', '{}', NULL, 1.0, 1.0)
    """
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("t-null-1",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("t-null-2",))
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_lock_indexes_are_scoped_to_active_states(conn: sqlite3.Connection) -> None:
    """S4: 两个 lock 索引都必须只约束活跃态，且行为上可被终态任务释放。"""
    for index_name, column in (("idx_tasks_lock", "lock"), ("idx_tasks_queueing_lock", "queueing_lock")):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (index_name,)
        ).fetchone()
        assert row is not None, f"{index_name} 丢失"
        flat = " ".join(row[0].split()).lower()
        assert f"on tasks({column})" in flat, flat
        assert "state not in (" in flat, f"{index_name} 未按活跃态收窄：{flat}"
        for terminal in ("'succeeded'", "'failed'", "'cancelled'", "'interrupted'"):
            assert terminal in flat, f"{terminal} 未出现在 {index_name} 的 WHERE 子句中"

    insert = """
        INSERT INTO tasks (task_id, batch_id, role, pool, state, card_json,
                           output_path, lock, created_at, updated_at)
        VALUES (?, 'b1', 'leaf', 'solve', ?, '{}', ?, ?, 1.0, 1.0)
    """
    # 前一个持有者已终态 -> 同一 lock 值必须能被新任务复用。
    conn.execute(insert, ("t-done", "SUCCEEDED", "out/done.md", "worktree-1"))
    conn.execute(insert, ("t-next", "QUEUED", "out/next.md", "worktree-1"))
    # 但两个活跃任务仍必须互斥。
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("t-third", "RUNNING", "out/third.md", "worktree-1"))


def test_schema_version_has_primary_key(conn: sqlite3.Connection) -> None:
    """S5: version 必须是主键，重复初始化不得写多行。"""
    info = {row[1]: row for row in conn.execute("PRAGMA table_info(schema_version)").fetchall()}
    assert info["version"][5] == 1, "S5: schema_version.version 不是主键"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, 2.0),
        )


def test_role_pool_isolation_defaults(conn: sqlite3.Connection) -> None:
    """S6: role / pool 必须有默认值，与 isolation 等列保持一致。"""
    conn.execute(
        """
        INSERT INTO tasks (task_id, batch_id, card_json, output_path, created_at, updated_at)
        VALUES ('t-defaults', 't-defaults', '{}', 'out/defaults.md', 1.0, 1.0)
        """
    )
    row = conn.execute(
        "SELECT role, pool, isolation, state FROM tasks WHERE task_id = 't-defaults'"
    ).fetchone()
    assert tuple(row) == ("leaf", "solve", "process", "QUEUED"), row


# --------------------------------------------------------- other constraints


def test_deliveries_is_one_per_task(conn: sqlite3.Connection) -> None:
    row = ("d1", "t1", "sess", "", "pending", 0, None, None, None, None, 1.0)
    conn.execute(
        """
        INSERT INTO deliveries (
            delivery_id, task_id, origin_session, origin_session_id, state,
            attempts, claim, claimed_at, delivered_at, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO deliveries (
                delivery_id, task_id, origin_session, origin_session_id, state,
                attempts, claim, claimed_at, delivered_at, payload_json, created_at
            ) VALUES ('d2', 't1', 'sess', '', 'pending', 0, NULL, NULL, NULL, NULL, 1.0)
            """
        )


def test_task_commands_kind_is_constrained(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO task_commands (task_id, lease_epoch, kind, created_at) "
        "VALUES ('t1', 1, 'steer', 1.0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO task_commands (task_id, lease_epoch, kind, created_at) "
            "VALUES ('t1', 1, 'rm -rf', 1.0)"
        )


# ------------------------------------------------------------ no PRAGMA WAL


def test_ddl_never_sets_journal_mode() -> None:
    """Review §1.3: the queue DB's journal mode is the owner's decision.

    A guest connection issuing ``PRAGMA journal_mode = WAL`` takes an exclusive
    lock on every short-lived connection and collides with live writers. Guard
    against someone "helpfully" adding it back to the DDL.
    """
    assert "PRAGMA journal_mode" not in "\n".join(DDL)
    joined = "\n".join(DDL).lower()
    assert "pragma" not in joined
    assert "journal_mode" not in joined


def test_configure_connection_preserves_journal_mode(tmp_path) -> None:
    db_file = tmp_path / "orchestration.db"
    connection = sqlite3.connect(str(db_file))
    try:
        before = connection.execute("PRAGMA journal_mode").fetchone()[0]
        apply_schema(connection)
        configure_connection(connection, busy_timeout_ms=1234)
        after = connection.execute("PRAGMA journal_mode").fetchone()[0]

        assert after == before, "configure_connection must not change journal_mode"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_configure_connection_default_busy_timeout() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        configure_connection(connection)
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()
