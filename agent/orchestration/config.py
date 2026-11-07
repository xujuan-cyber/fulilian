"""Orchestration subsystem -- single source of truth for tunables.

Background
----------
Before this module the delegation subsystem had ~10 hand-rolled
``_load_config()`` / ``_get_*`` helpers, each with its own default and its own
env-var parsing. That is how ``AGENTS.md`` drifted to "default 3" while the
code said 10. This module replaces all of them with one frozen dataclass:
every default lives here exactly once, and callers pass a config object down
instead of re-reading the environment at each layer.

Values follow ``docs/design/orchestration-plan-review-2026-10-31.md``:

* ``batch_limit = 5``   -- review M14: Anthropic's measurement is 3-5 parallel
  children; 15 is a *hard cap*, not a default.
* ``aging_seconds``     -- review H3: strict priority ordering starves tasks,
  the claim query adds an aging term so nothing waits forever.
* ``cancel_grace_seconds`` -- review H5: cancelling is asynchronous, this is the
  upper bound before the sweeper force-kills.
* ``db_path``           -- review §1.3: the queue lives in its own
  ``orchestration.db``. It must never default to ``state.db``: that file's
  journal mode is owned by ``SessionDB`` and its writers (transcript/FTS) would
  contend with claim/heartbeat writes.

Only the standard library is imported here -- ``agent.orchestration`` must stay
free of ``tools.*`` imports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Any, Mapping

__all__ = [
    "ConfigError",
    "DEFAULT_DB_NAME",
    "OrchestrationConfig",
    "default_db_path",
]


class ConfigError(ValueError):
    """Raised for malformed orchestration configuration.

    Subclasses ``ValueError`` so callers that already guard config parsing with
    ``except ValueError`` keep working.
    """


#: Filename of the queue database. Deliberately *not* ``state.db`` (review §1.3).
DEFAULT_DB_NAME = "orchestration.db"


def default_db_path(home: str | None = None) -> str:
    """Return the default queue database path: ``<home>/.fulilian/orchestration.db``."""
    base = home if home is not None else os.path.expanduser("~")
    return os.path.join(base, ".fulilian", DEFAULT_DB_NAME)


def _as_int(name: str, value: Any) -> int:
    # bool is an int subclass; accepting it here would silently turn
    # ``batch_limit=True`` into 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be int, got {type(value).__name__}")
    return value


def _as_float(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number, got {type(value).__name__}")
    return float(value)


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be str, got {type(value).__name__}")
    return value


def _as_pools(name: str, value: Any) -> tuple[tuple[str, int], ...]:
    """Normalise ``pools`` to a tuple of ``(name, cap)`` pairs.

    A ``dict`` is accepted because YAML/JSON config arrives that way; a tuple is
    what we store so that the frozen dataclass stays hashable (review M16).
    """
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ConfigError(
            f"pools must be a mapping or a sequence of pairs, got {type(value).__name__}"
        )
    out: list[tuple[str, int]] = []
    for entry in items:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ConfigError(f"pools entries must be (name, cap) pairs, got {entry!r}")
        pool_name, cap = entry
        out.append((_as_str("pools.name", pool_name), _as_int(f"pools[{pool_name!r}]", cap)))
    return tuple(out)


# Field name -> coercion callable. Kept next to the dataclass so adding a field
# without teaching ``from_mapping`` about it fails loudly (see the test suite).
_COERCE = {
    "batch_limit": _as_int,
    "batch_hard_cap": _as_int,
    "queue_capacity": _as_int,
    "max_running": _as_int,
    "pools": _as_pools,
    "lease_seconds": _as_float,
    "heartbeat_seconds": _as_float,
    "aging_seconds": _as_float,
    "handoff_cap": _as_int,
    "retry_cap": _as_int,
    "cancel_grace_seconds": _as_float,
    "daily_token_budget": _as_int,
    "db_path": _as_str,
    "busy_timeout_ms": _as_int,
}


@dataclass(frozen=True, slots=True)
class OrchestrationConfig:
    """Immutable orchestration tunables. See module docstring for provenance."""

    # Concurrency. ``batch_limit`` is the default fan-out; ``batch_hard_cap`` is
    # the ceiling a caller may never exceed (review M14).
    batch_limit: int = 5
    batch_hard_cap: int = 15
    queue_capacity: int = 500
    max_running: int = 15
    # Per-pool quotas. A tuple (not a dict) keeps the dataclass hashable.
    pools: tuple[tuple[str, int], ...] = (
        ("solve", 15),
        ("supervision", 1),
        ("audit", 1),
    )

    # Lease / liveness.
    lease_seconds: float = 60.0
    heartbeat_seconds: float = 5.0

    # Scheduling fairness (review H3: without aging, low priority starves).
    aging_seconds: float = 300.0

    # Redispatch limits.
    handoff_cap: int = 2
    retry_cap: int = 1

    # Cancellation convergence bound (review H5).
    cancel_grace_seconds: float = 30.0

    # Cost guard (review H4). 0 disables the global gate.
    daily_token_budget: int = 0

    # Storage. Empty means "caller supplies a path"; use ``default_db_path()``.
    # Never point this at ``state.db`` -- see review §1.3.
    db_path: str = ""
    busy_timeout_ms: int = 5000

    # -- constructors -----------------------------------------------------
    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OrchestrationConfig":
        """Build a config from a mapping, ignoring unknown keys.

        Unknown keys are ignored (forward compatibility with newer config
        files); a known key with the wrong type raises :class:`ConfigError`
        rather than being silently coerced.
        """
        if not isinstance(raw, Mapping):
            raise ConfigError(f"config must be a mapping, got {type(raw).__name__}")

        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in known:
                continue
            coerce = _COERCE.get(key)
            if coerce is None:  # pragma: no cover - guards future field additions
                raise ConfigError(f"no coercion registered for config field {key!r}")
            kwargs[key] = coerce(key, value)
        return cls(**kwargs)

    # -- validation -------------------------------------------------------
    def validate(self) -> None:
        """Raise :class:`ConfigError` on values that cannot work at all.

        Soft inconsistencies (notably ``sum(pools) > max_running``, review M1)
        are reported by :meth:`warnings` instead of refusing to start.
        """
        if self.batch_limit < 1:
            raise ConfigError("batch_limit must be >= 1")
        if self.batch_hard_cap < 1:
            raise ConfigError("batch_hard_cap must be >= 1")
        if self.batch_limit > self.batch_hard_cap:
            raise ConfigError(
                f"batch_limit ({self.batch_limit}) must be <= "
                f"batch_hard_cap ({self.batch_hard_cap})"
            )
        if self.max_running < 1:
            raise ConfigError("max_running must be >= 1")
        if self.queue_capacity < 1:
            raise ConfigError("queue_capacity must be >= 1")
        if self.lease_seconds <= 0:
            raise ConfigError("lease_seconds must be > 0")
        if self.heartbeat_seconds <= 0:
            raise ConfigError("heartbeat_seconds must be > 0")
        if self.heartbeat_seconds >= self.lease_seconds:
            # A heartbeat at or past the lease boundary means the task is
            # reclaimed before it can ever renew: guaranteed flapping.
            raise ConfigError(
                f"heartbeat_seconds ({self.heartbeat_seconds}) must be < "
                f"lease_seconds ({self.lease_seconds})"
            )
        if self.aging_seconds <= 0:
            raise ConfigError("aging_seconds must be > 0")
        if self.handoff_cap < 0:
            raise ConfigError("handoff_cap must be >= 0")
        if self.retry_cap < 0:
            raise ConfigError("retry_cap must be >= 0")
        if self.cancel_grace_seconds <= 0:
            raise ConfigError("cancel_grace_seconds must be > 0")
        if self.daily_token_budget < 0:
            raise ConfigError("daily_token_budget must be >= 0 (0 = unlimited)")
        if self.busy_timeout_ms < 0:
            raise ConfigError("busy_timeout_ms must be >= 0")
        if not self.pools:
            raise ConfigError("pools must not be empty")
        for pool_name, cap in self.pools:
            if not pool_name:
                raise ConfigError("pools entries must have a non-empty name")
            if cap < 0:
                raise ConfigError(f"pools[{pool_name!r}] cap must be >= 0")

    def warnings(self) -> tuple[str, ...]:
        """Return non-fatal inconsistencies worth surfacing at startup.

        Review M1: the plan ships ``max_running=15`` while its pools sum to
        ``15 + 1 + 1 = 17``. That is a contradiction, but refusing to boot over
        it would be worse than running with ``max_running`` as the real ceiling,
        so it is reported here and callers log it.
        """
        notes: list[str] = []
        pool_total = sum(cap for _, cap in self.pools)
        if pool_total > self.max_running:
            notes.append(
                f"pools sum to {pool_total} but max_running is {self.max_running}; "
                "max_running is the global ceiling, pool caps are quotas under it"
            )
        if self.batch_limit > self.max_running:
            notes.append(
                f"batch_limit ({self.batch_limit}) exceeds max_running "
                f"({self.max_running}); the batch will be throttled at dispatch"
            )
        return tuple(notes)

    # -- derived views ----------------------------------------------------
    def pool_map(self) -> dict[str, int]:
        """Return ``pools`` as a plain dict (query helpers prefer mapping access)."""
        return dict(self.pools)
