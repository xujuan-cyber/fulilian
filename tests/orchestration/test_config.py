"""Tests for ``agent.orchestration.config``.

Focus: the defaults are the reviewed ones (not the original plan's), unknown keys
are tolerated but wrong types are not, and the pool/max_running contradiction is
surfaced as a warning instead of a hard failure (review M1).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.orchestration.config import (
    DEFAULT_DB_NAME,
    ConfigError,
    OrchestrationConfig,
    default_db_path,
)


# ---------------------------------------------------------------- defaults


def test_default_concurrency_values() -> None:
    cfg = OrchestrationConfig()
    # review M14: 3-5 is the sweet spot, 15 is only the hard cap.
    assert cfg.batch_limit == 5
    assert cfg.batch_hard_cap == 15
    assert cfg.queue_capacity == 500
    assert cfg.max_running == 15


def test_default_pools_are_tuple_and_convert_to_map() -> None:
    cfg = OrchestrationConfig()
    assert isinstance(cfg.pools, tuple)
    assert all(isinstance(entry, tuple) for entry in cfg.pools)
    assert cfg.pool_map() == {"solve": 15, "supervision": 1, "audit": 1}


def test_default_lease_heartbeat_aging() -> None:
    cfg = OrchestrationConfig()
    assert cfg.lease_seconds == 60.0
    assert cfg.heartbeat_seconds == 5.0
    # review H3: aging term so low-priority tasks cannot starve.
    assert cfg.aging_seconds == 300.0


def test_default_caps_and_budgets() -> None:
    cfg = OrchestrationConfig()
    assert cfg.handoff_cap == 2
    assert cfg.retry_cap == 1
    assert cfg.cancel_grace_seconds == 30.0
    assert cfg.daily_token_budget == 0  # 0 == unlimited
    assert cfg.busy_timeout_ms == 5000


def test_default_db_path_is_its_own_database() -> None:
    # review §1.3: never state.db -- its journal mode belongs to SessionDB.
    cfg = OrchestrationConfig()
    assert cfg.db_path == ""  # caller supplies the path
    assert DEFAULT_DB_NAME == "orchestration.db"
    resolved = default_db_path("/tmp/somehome")
    assert resolved.endswith("/tmp/somehome/.fulilian/orchestration.db")
    assert "state.db" not in resolved


# ------------------------------------------------------------ frozen / hash


def test_config_is_frozen() -> None:
    cfg = OrchestrationConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.batch_limit = 9  # type: ignore[misc]


def test_config_is_hashable() -> None:
    # pools is a tuple, not a dict, precisely so this works (review M16).
    assert hash(OrchestrationConfig()) == hash(OrchestrationConfig())


# ------------------------------------------------------------- from_mapping


def test_from_mapping_overrides_known_keys() -> None:
    cfg = OrchestrationConfig.from_mapping({"batch_limit": 3, "lease_seconds": 30})
    assert cfg.batch_limit == 3
    assert cfg.lease_seconds == 30.0
    assert isinstance(cfg.lease_seconds, float)


def test_from_mapping_ignores_unknown_keys() -> None:
    cfg = OrchestrationConfig.from_mapping({"batch_limit": 4, "no_such_key": object()})
    assert cfg.batch_limit == 4


def test_from_mapping_rejects_wrong_type() -> None:
    with pytest.raises(ConfigError, match="batch_limit"):
        OrchestrationConfig.from_mapping({"batch_limit": "5"})


def test_from_mapping_rejects_bool_for_int() -> None:
    # bool is an int subclass; True would silently become 1.
    with pytest.raises(ConfigError):
        OrchestrationConfig.from_mapping({"max_running": True})


def test_from_mapping_rejects_non_mapping() -> None:
    with pytest.raises(ConfigError):
        OrchestrationConfig.from_mapping([("batch_limit", 3)])  # type: ignore[arg-type]


def test_from_mapping_accepts_pools_dict() -> None:
    cfg = OrchestrationConfig.from_mapping({"pools": {"solve": 4, "audit": 1}})
    assert cfg.pools == (("solve", 4), ("audit", 1))
    assert isinstance(cfg.pools, tuple)


def test_from_mapping_rejects_malformed_pools_entry() -> None:
    with pytest.raises(ConfigError, match="pools"):
        OrchestrationConfig.from_mapping({"pools": [("solve",)]})


def test_from_mapping_defaults_match_bare_constructor() -> None:
    assert OrchestrationConfig.from_mapping({}) == OrchestrationConfig()


# ---------------------------------------------------------------- validate


def test_validate_accepts_defaults() -> None:
    OrchestrationConfig().validate()


def test_validate_rejects_batch_limit_above_hard_cap() -> None:
    cfg = OrchestrationConfig(batch_limit=16, batch_hard_cap=15)
    with pytest.raises(ConfigError, match="batch_hard_cap"):
        cfg.validate()


def test_validate_rejects_zero_max_running() -> None:
    with pytest.raises(ConfigError, match="max_running"):
        OrchestrationConfig(max_running=0).validate()


def test_validate_rejects_heartbeat_at_or_past_lease() -> None:
    with pytest.raises(ConfigError, match="heartbeat_seconds"):
        OrchestrationConfig(lease_seconds=10.0, heartbeat_seconds=10.0).validate()


# ---------------------------------------------------------------- warnings


def test_warnings_flag_pool_sum_above_max_running() -> None:
    # review M1: the plan's own numbers are 15 + 1 + 1 = 17 > max_running 15.
    cfg = OrchestrationConfig()
    assert sum(cap for _, cap in cfg.pools) == 17
    notes = cfg.warnings()
    assert len(notes) == 1
    assert "17" in notes[0] and "15" in notes[0]
    # ...but it must not refuse to start.
    cfg.validate()


def test_no_warnings_when_pools_fit() -> None:
    cfg = OrchestrationConfig(
        max_running=20,
        pools=(("solve", 15), ("supervision", 1), ("audit", 1)),
    )
    assert cfg.warnings() == ()
