"""Shared daemon-thread ThreadPoolExecutor.

Stdlib ``ThreadPoolExecutor`` workers are non-daemon AND are registered in
``concurrent.futures.thread._threads_queues``, whose atexit hook
(``_python_exit``) joins every worker unconditionally — even after
``shutdown(wait=False)``.  A single wedged worker (tool blocked on network
I/O, hung provider daemon, stuck subagent) therefore blocks interpreter
exit forever.  This is the root cause of multi-minute CLI exits on long
sessions: every abandoned concurrent-tool batch leaves workers that the
exit hook insists on joining.

``DaemonThreadPoolExecutor`` spawns daemon workers and skips the
``_threads_queues`` registration, so:

  - ``_python_exit`` never joins them, and
  - the interpreter's non-daemon thread join at shutdown skips them.

Semantics are otherwise identical (initializer/initargs, work queue,
idle-thread reuse).  Use it for any pool whose work is best-effort or
independently interruptible and must never hold the process open:
concurrent tool execution, background memory sync, catalog fan-out,
subagent timeout wrappers.  Do NOT use it for work that must complete
before exit (durable writes) — those belong on foreground threads with
explicit bounded joins.
"""

from __future__ import annotations

import inspect
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.thread import _worker

__all__ = ["DaemonThreadPoolExecutor"]

# C4-34: the private _worker() contract changed in CPython 3.14 —
#   3.8–3.13: _worker(executor_reference, work_queue, initializer, initargs)
#   3.14+:    _worker(executor_reference, ctx, work_queue)
#             with ctx = executor._create_worker_context()
# Detect the arity ONCE at import instead of sniffing version strings, so
# the mirror below keeps binding correctly (or failing loudly) on any
# interpreter, including the py3.14 Windows runtime.
try:
    _WORKER_PARAM_COUNT = len(inspect.signature(_worker).parameters)
except (TypeError, ValueError):  # pragma: no cover - exotic builds
    _WORKER_PARAM_COUNT = 4


class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor variant whose workers do not block process exit."""

    def _adjust_thread_count(self) -> None:
        # Mirrors CPython's implementation (3.8–3.13) with two changes:
        # daemon=True and no _threads_queues registration.
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (self._thread_name_prefix or self, num_threads)
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=self._daemon_worker_args(weakref_cb),
                daemon=True,
            )
            t.start()
            self._threads.add(t)

    def _daemon_worker_args(self, weakref_cb):
        """Build the _worker() args for THIS interpreter's contract (C4-34).

        The 3.8–3.13 mirror passed (ref, work_queue, initializer, initargs);
        on py3.14 that mis-binds — _worker's 2nd positional is the worker
        context and the 3rd is the queue — so daemon workers either crashed
        at startup or bound the queue into the initializer slot. See the
        arity note at module top.
        """
        ref = weakref.ref(self, weakref_cb)
        if _WORKER_PARAM_COUNT == 3:
            return (ref, self._create_worker_context(), self._work_queue)
        return (ref, self._work_queue, self._initializer, self._initargs)
