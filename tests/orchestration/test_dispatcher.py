"""Tests for ``agent.orchestration.dispatcher`` (phase 3b, decisions W6/W7/W8).

Every test names the decision it pins down. The three fixed names required by
the frozen decision (§五) are ``test_choose_tier_maps_isolation_to_tier``,
``test_choose_tier_honours_explicit_request`` and ``test_sample_does_not_claim``;
the rest close the gaps those three leave (order parity with ``claim``, ``limit``,
empty pool, backoff bounds).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.orchestration import dispatcher as dispatcher_module
from agent.orchestration import store as store_module
from agent.orchestration.contracts import Isolation, TaskCard
from agent.orchestration.dispatcher import Backoff, Dispatcher, Tier
from agent.orchestration.store import Store

# ------------------------------------------------------------------- helpers


class _Clock:
    """Strictly increasing fake clock, so ``created_at`` order is deterministic."""

    def __init__(self, start: float = 1_000.0, step: float = 1.0) -> None:
        self._t = start
        self._step = step

    def __call__(self) -> float:
        self._t += self._step
        return self._t


def _card(
    task_id: str,
    *,
    pool: str = "solve",
    isolation: Isolation | None = None,
    is_key: bool = False,
    priority: int = 0,
) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal="produce a report",
        dod=("report exists",),
        output_path=f"/tmp/out/{task_id}.md",
        pool=pool,
        isolation=isolation,
        is_key=is_key,
        priority=priority,
    )


def _row(store: Store, task_id: str):
    """Read a task row raw. ``_conn`` is private, but the assertions are about
    column values, not about ``Store``'s API."""
    return store._conn.execute(
        "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()


@pytest.fixture()
def clock() -> _Clock:
    return _Clock()


@pytest.fixture()
def store(tmp_path, clock):
    queue = Store(str(tmp_path / "orchestration.db"), worker_id="w1", now=clock)
    try:
        yield queue
    finally:
        queue.close()


@pytest.fixture()
def dispatcher(store):
    return Dispatcher(store)


# --------------------------------------------------------------------- W6


@pytest.mark.parametrize(
    ("isolation", "expected"),
    [
        (Isolation.PROCESS, Tier.DAEMON),
        (Isolation.INLINE, Tier.EMBEDDED),
        (None, Tier.EMBEDDED),
    ],
)
def test_choose_tier_maps_isolation_to_tier(dispatcher, isolation, expected):
    """W6: PROCESS -> DAEMON; INLINE -> EMBEDDED (not INLINE); None -> EMBEDDED.

    The mapping is deliberately *not* identity: ``Isolation.INLINE`` never
    yields ``Tier.INLINE`` on its own, because synchronous execution blocks the
    caller.
    """
    card = _card("t1", isolation=isolation)

    assert dispatcher.choose_tier(card) is expected


def test_choose_tier_default_is_not_inline(dispatcher):
    """W6 corollary: nothing but an explicit request produces ``Tier.INLINE``."""
    for isolation in (None, Isolation.INLINE, Isolation.PROCESS):
        assert dispatcher.choose_tier(_card("t1", isolation=isolation)) is not Tier.INLINE


@pytest.mark.parametrize("requested", [Tier.INLINE, Tier.EMBEDDED, Tier.DAEMON])
@pytest.mark.parametrize("isolation", [Isolation.PROCESS, Isolation.INLINE, None])
def test_choose_tier_honours_explicit_request(dispatcher, isolation, requested):
    """W6: ``requested`` wins over everything, including the opposite isolation."""
    card = _card("t1", isolation=isolation)

    assert dispatcher.choose_tier(card, requested=requested) is requested


# --------------------------------------------------------------------- W7


def test_sample_does_not_claim(store, dispatcher):
    """W7: sampling must not claim.

    Three assertions are made on purpose. ``state == 'QUEUED'`` alone would also
    pass for an implementation that claims and then quietly puts the row back;
    ``claimed_by`` catches the holder, ``attempts`` catches the atomic increment
    inside the claim UPDATE. The whole-row comparison then catches everything
    else (``lease_epoch``, ``lease_expires``, ``updated_at``).
    """
    store.enqueue(_card("t1"))
    store.enqueue(_card("t2"))
    before = {task_id: dict(_row(store, task_id)) for task_id in ("t1", "t2")}

    sampled = dispatcher.sample("solve")

    assert sampled == ["t1", "t2"]
    for task_id in ("t1", "t2"):
        row = _row(store, task_id)
        assert row["state"] == "QUEUED"
        assert row["claimed_by"] is None
        assert row["attempts"] == 0
        assert row["lease_epoch"] == before[task_id]["lease_epoch"]
        assert row["lease_expires"] is None
        assert dict(row) == before[task_id]


def test_sample_repeatedly_does_not_claim(store, dispatcher):
    """W7: sampling is idempotent -- calling it N times changes nothing."""
    store.enqueue(_card("t1"))
    before = dict(_row(store, "t1"))

    for _ in range(5):
        assert dispatcher.sample("solve") == ["t1"]

    assert dict(_row(store, "t1")) == before


def test_sample_order_matches_claim_order(store, dispatcher):
    """W7: the sample order must be the claim order, or scheduling decisions lie.

    Both the constant and the observed order are checked: the first catches a
    silent edit to one side, the second catches a divergence that only shows up
    at runtime (e.g. a typo'd ``ORDER BY`` that still parses).
    """
    assert dispatcher_module._SAMPLE_ORDER == store_module._CLAIM_ORDER

    # A dependency chain in another pool: only used to give t_bottom a real
    # bottom_level, it must not pollute the "solve" pool.
    store.enqueue(_card("dep1", pool="setup"))
    store.enqueue(_card("dep2", pool="setup"), deps=("dep1",))
    store.enqueue(_card("t_key", is_key=True))
    store.enqueue(_card("t_prio", priority=9))
    store.enqueue(_card("t_bottom"), deps=("dep2",))
    store.enqueue(_card("t_time_a"))
    store.enqueue(_card("t_time_b"))

    expected = ["t_key", "t_prio", "t_bottom", "t_time_a", "t_time_b"]
    sampled = dispatcher.sample("solve")

    claimed: list[str] = []
    while (task := store.claim("solve")) is not None:
        claimed.append(task.task_id)

    assert sampled == expected
    assert claimed == expected


def test_sample_respects_limit(store, dispatcher):
    """W7: ``limit`` truncates the *head* of the order, never the tail."""
    for index in range(5):
        store.enqueue(_card(f"t{index}"))

    assert dispatcher.sample("solve", limit=2) == ["t0", "t1"]
    assert dispatcher.sample("solve", limit=1) == ["t0"]
    assert len(dispatcher.sample("solve", limit=99)) == 5
    # SQLite reads a negative LIMIT as "no limit"; that must not leak out.
    assert dispatcher.sample("solve", limit=0) == []
    assert dispatcher.sample("solve", limit=-1) == []


def test_sample_empty_pool_returns_empty(store, dispatcher):
    """W7: nothing queued -> ``[]``, and non-QUEUED rows are never sampled."""
    assert dispatcher.sample("solve") == []

    store.enqueue(_card("t1", pool="other"))
    assert dispatcher.sample("solve") == []
    assert dispatcher.sample("other") == ["t1"]

    store.claim("other")  # now CLAIMED: no longer sampleable
    assert dispatcher.sample("other") == []


# --------------------------------------------------------------------- W8


def test_backoff_jitter_within_bounds():
    """W8: jitter is a downward-only ``[0.5, 1.0)`` multiplier applied after
    the cap, so ``cap`` stays a **hard** upper bound."""
    backoff = Backoff(base=0.05, cap=2.0)

    for attempt in range(10):
        ceiling = min(backoff.base * 2**attempt, backoff.cap)
        assert ceiling <= backoff.cap
        for _ in range(200):
            delay = backoff.delay(attempt)
            assert 0.5 * ceiling <= delay <= ceiling
            assert delay <= backoff.cap  # the caller can bound the wait


def test_backoff_never_exceeds_cap_under_extreme_jitter():
    """W8: even the jitter's own upper edge stays within ``cap``."""
    backoff = Backoff(base=0.05, cap=2.0)

    for attempt in range(12):
        assert backoff.delay(attempt, rand=lambda: 1.0) <= backoff.cap
        assert backoff.delay(attempt, rand=lambda: 0.0) <= backoff.cap


def test_backoff_doubles_then_plateaus():
    """W8: ``base * 2**attempt`` from attempt 0, capped at ``cap``.

    ``rand() == 1.0`` is the jitter's upper edge (factor exactly 1.0), which
    reads the un-jittered base out of the formula. Real ``random()`` never
    returns 1.0 -- it is injected here only to expose the ceiling.
    """
    backoff = Backoff(base=0.05, cap=2.0)

    delays = [backoff.delay(attempt, rand=lambda: 1.0) for attempt in range(8)]

    assert delays == pytest.approx([0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0])


def test_poll_delay_delegates_to_backoff(store):
    """W8: ``poll_delay`` is the injected ``Backoff``, not a second formula."""
    backoff = Backoff(base=0.05, cap=2.0)
    dispatcher = Dispatcher(store, backoff=backoff)

    for attempt in range(6):
        ceiling = min(backoff.base * 2**attempt, backoff.cap)
        delay = dispatcher.poll_delay(attempt)
        assert 0.5 * ceiling <= delay <= ceiling

    default = Dispatcher(store)
    assert 0.025 <= default.poll_delay(0) <= 0.05


# ---------------------------------------------------------------- layering


def test_dispatcher_imports_no_tools_and_no_worker():
    """§二: this layer must not reach into ``tools.*`` nor into ``worker.py``."""
    source = Path(dispatcher_module.__file__).read_text(encoding="utf-8")
    imports = [
        line for line in source.splitlines() if line.startswith(("import ", "from "))
    ]

    assert imports, "sanity: the import scan found nothing"
    assert not [line for line in imports if "tools" in line]
    assert not [line for line in imports if "worker" in line]
