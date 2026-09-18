"""Hard wall-clock bounds for one-shot auxiliary calls (C3-1/C3-4/C3-14).

``ThreadPoolExecutor(max_workers=1)`` + ``future.result(timeout=...)`` does
NOT bound wall-clock: after the timeout fires, the ``with``-exit
``shutdown(wait=True)`` still JOINS the worker before returning, so a hung
callee (nous portal, plugin ``expand()``, URL fetch) blocks the caller
forever — the timeout merely converts the wait into a ``TimeoutError`` the
caller can never observe. The same shape WITHOUT a timeout argument (C3-14)
is unbounded outright.

``call_with_deadline`` runs the call on a DAEMON thread and abandons it on
deadline: the caller returns promptly, and the abandoned thread can never
block interpreter exit. Semantics for the abandonment case: best-effort
auxiliary work only — the worker keeps running with its result dropped, so
do NOT use this for writes that must land.

A per-call daemon thread (rather than a shared pool) is deliberate: the
whole point is that no code path may wait on the worker after the deadline,
and pool reuse would re-introduce exactly that join.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


def call_with_deadline(
    fn: Callable[..., Any],
    *args: Any,
    timeout_s: float,
    **kwargs: Any,
) -> Any:
    """Run ``fn(*args, **kwargs)`` under a HARD wall-clock deadline.

    Returns the callee's result. Raises ``TimeoutError`` when the deadline
    expires (worker abandoned — daemon, so it neither blocks the caller nor
    interpreter exit). Re-raises the callee's exception when it finishes
    before the deadline.
    """
    outcome: dict[str, Any] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            outcome["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — relayed below
            outcome["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(
        target=_run,
        name=f"hard-deadline:{getattr(fn, '__name__', 'call')}",
        daemon=True,
    )
    worker.start()
    if not done.wait(timeout_s):
        raise TimeoutError(
            f"{getattr(fn, '__name__', 'call')} did not finish within "
            f"{timeout_s}s — worker abandoned (daemon; cannot block exit)"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")
