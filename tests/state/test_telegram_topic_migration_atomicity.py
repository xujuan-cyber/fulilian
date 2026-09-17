"""``apply_telegram_topic_migration`` must be atomic (audit C1-2).

The migration used ``conn.executescript``, and Python's ``executescript``
implicitly COMMITs any pending transaction before it runs. That silently ended
the ``BEGIN IMMEDIATE`` that ``_execute_write`` had opened, so the migration
actually ran outside the transaction the caller believed it was in — the v1→v2
rebuild could be interrupted between its ``DROP TABLE`` and its ``RENAME``
(leaving no bindings table at all), and a rollback could no longer undo it.

Statement-by-statement ``conn.execute`` keeps DDL inside that transaction
(SQLite DDL is transactional), restoring all-or-nothing.
"""

import sqlite3

from fulilian_state import SessionDB


def _table_exists(db, name: str) -> bool:
    row = db._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def test_migration_rolls_back_completely(tmp_path, monkeypatch):
    """If the caller's transaction rolls back, NOTHING the migration did may
    survive. Under the old executescript-based code the implicit COMMIT made
    those CREATEs durable and this assertion failed."""
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        assert not _table_exists(db, "telegram_dm_topic_mode")

        def begin_and_rollback(fn, patience_s=None):
            with db._lock:
                db._conn.execute("BEGIN IMMEDIATE")
                try:
                    return fn(db._conn)
                finally:
                    db._conn.rollback()

        monkeypatch.setattr(db, "_execute_write", begin_and_rollback)
        db.apply_telegram_topic_migration()

        assert not _table_exists(db, "telegram_dm_topic_mode")
        assert not _table_exists(db, "telegram_dm_topic_bindings")
        assert not _table_exists(db, "telegram_dm_topic_bindings_new")
    finally:
        db.close()


def test_v1_bindings_table_is_upgraded_and_rows_preserved(tmp_path):
    """The v2 rebuild still works and keeps every binding row."""
    db_path = tmp_path / "state.db"
    db = SessionDB(db_path=db_path)
    db.create_session("s1", source="telegram")
    db.apply_telegram_topic_migration()
    db.close()

    # Downgrade the bindings table to the v1 shape (FK without CASCADE).
    raw = sqlite3.connect(str(db_path))
    try:
        raw.executescript(
            """
            CREATE TABLE bindings_v1 AS SELECT * FROM telegram_dm_topic_bindings;
            DROP TABLE telegram_dm_topic_bindings;
            CREATE TABLE telegram_dm_topic_bindings (
                chat_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                managed_mode TEXT NOT NULL DEFAULT 'auto',
                linked_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chat_id, thread_id)
            );
            INSERT INTO telegram_dm_topic_bindings SELECT * FROM bindings_v1;
            DROP TABLE bindings_v1;
            """
        )
        raw.execute(
            "INSERT INTO telegram_dm_topic_bindings "
            "(chat_id, thread_id, user_id, session_key, session_id, "
            " linked_at, updated_at) "
            "VALUES ('c1', 't1', 'u1', 'k1', 's1', 1.0, 1.0)"
        )
        raw.execute(
            "UPDATE state_meta SET value = '1' "
            "WHERE key = 'telegram_dm_topic_schema_version'"
        )
        raw.commit()
    finally:
        raw.close()

    db2 = SessionDB(db_path=db_path)
    try:
        db2.apply_telegram_topic_migration()

        fk_rows = db2._conn.execute(
            "PRAGMA foreign_key_list('telegram_dm_topic_bindings')"
        ).fetchall()
        assert any((row[6] or "") == "CASCADE" for row in fk_rows), (
            "session_id FK should have been rebuilt with ON DELETE CASCADE"
        )

        rows = db2._conn.execute(
            "SELECT chat_id, thread_id, session_id FROM telegram_dm_topic_bindings"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("c1", "t1", "s1")]

        version = db2._conn.execute(
            "SELECT value FROM state_meta "
            "WHERE key = 'telegram_dm_topic_schema_version'"
        ).fetchone()
        assert version is not None and version[0] == "2"
        assert not _table_exists(db2, "telegram_dm_topic_bindings_new")
    finally:
        db2.close()
