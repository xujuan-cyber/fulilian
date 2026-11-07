"""迁移 runner 的测试（阶段 2 收尾项）。

背景：``apply_schema`` 在 ``applied < SCHEMA_VERSION`` 时原本**静默什么都不做**，
库会停在旧版本且不报错（评审 P2-3）。``migrate()`` 补上真正的升级路径：
按版本号逐级执行注册的步骤，缺步骤直接报错，失败则回滚。
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.orchestration import schema as schema_mod
from agent.orchestration.schema import SchemaError, apply_schema, migrate


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_migrate_fresh_db_returns_current_version(conn: sqlite3.Connection) -> None:
    assert migrate(conn) == schema_mod.SCHEMA_VERSION
    assert schema_mod.current_version(conn) == schema_mod.SCHEMA_VERSION


def test_migrate_is_noop_when_up_to_date(conn: sqlite3.Connection) -> None:
    apply_schema(conn)
    assert migrate(conn) == schema_mod.SCHEMA_VERSION
    # 再跑一次仍应幂等，且不产生重复版本行
    assert migrate(conn) == schema_mod.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_migrate_applies_registered_step(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_schema(conn)
    monkeypatch.setattr(schema_mod, "SCHEMA_VERSION", 2)
    ran: list[int] = []

    def step_v2(c: sqlite3.Connection) -> None:
        ran.append(2)
        c.execute("CREATE TABLE probe_v2 (id INTEGER PRIMARY KEY)")

    monkeypatch.setitem(schema_mod.MIGRATIONS, 2, step_v2)

    assert migrate(conn) == 2
    assert ran == [2]
    assert schema_mod.current_version(conn) == 2
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='probe_v2'"
        ).fetchone()
        is not None
    )


def test_migrate_raises_when_step_missing(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_schema(conn)
    monkeypatch.setattr(schema_mod, "SCHEMA_VERSION", 2)
    monkeypatch.delitem(schema_mod.MIGRATIONS, 2, raising=False)

    with pytest.raises(SchemaError, match="缺少 v1 -> v2"):
        migrate(conn)
    # 拒绝之后库必须还停在 v1，不能半升级
    assert schema_mod.current_version(conn) == 1


def test_migrate_refuses_newer_database(conn: sqlite3.Connection) -> None:
    apply_schema(conn)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (99, 0.0)
    )
    with pytest.raises(SchemaError, match="比目标"):
        migrate(conn)


def test_migrate_rolls_back_failed_step(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_schema(conn)
    monkeypatch.setattr(schema_mod, "SCHEMA_VERSION", 2)

    def bad_step(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE probe_rollback (id INTEGER PRIMARY KEY)")
        raise RuntimeError("boom")

    monkeypatch.setitem(schema_mod.MIGRATIONS, 2, bad_step)

    with pytest.raises(RuntimeError, match="boom"):
        migrate(conn)

    # 版本没前进，且失败步骤建的表被回滚掉
    assert schema_mod.current_version(conn) == 1
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='probe_rollback'"
        ).fetchone()
        is None
    )


def test_migrate_target_argument_allows_partial_upgrade(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``target`` 可以只升到中间版本，给分批升级留口子。"""
    apply_schema(conn)
    monkeypatch.setattr(schema_mod, "SCHEMA_VERSION", 3)
    monkeypatch.setitem(schema_mod.MIGRATIONS, 2, lambda c: c.execute("SELECT 1"))
    monkeypatch.setitem(schema_mod.MIGRATIONS, 3, lambda c: c.execute("SELECT 1"))

    assert migrate(conn, target=2) == 2
    assert schema_mod.current_version(conn) == 2
    assert migrate(conn) == 3
