"""``_cross_process_repair_lock`` must fail CLOSED when the lock is unusable.

Without the lock file there is no cross-process serialisation of the
writable_schema surgery + VACUUM — exactly the interleaving the lock exists to
prevent (two hosts each ran the full surgery on their own private connection).
An unopenable lock path must therefore yield False (defer) rather than True
(proceed), matching the contract ``fts_rebuild_admission`` follows.
"""

from pathlib import Path

import fulilian_state


def _lock_path(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".repair.lock")


def test_repair_lock_fails_closed_when_lock_file_cannot_be_opened(tmp_path):
    db_path = tmp_path / "state.db"
    # A directory at the lock path makes open(..., "a+b") raise
    # IsADirectoryError (an OSError) with no monkeypatching.
    _lock_path(db_path).mkdir()

    with fulilian_state._cross_process_repair_lock(db_path) as holding:
        assert holding is False


def test_repair_lock_acquired_when_path_is_usable(tmp_path):
    """The guard must not regress the normal acquisition path."""
    db_path = tmp_path / "state.db"

    with fulilian_state._cross_process_repair_lock(db_path) as holding:
        assert holding is True
